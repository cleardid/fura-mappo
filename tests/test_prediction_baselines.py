from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from fractions import Fraction

import numpy as np
import pytest

import fura_mappo.prediction.baselines as baselines_module
from fura_mappo.prediction import (
    DemandForecast,
    EWMADemandPredictor,
    MaskedMeanDemandPredictor,
    PersistenceDemandPredictor,
    PredictionContext,
    ZeroDemandPredictor,
    validate_forecast_for_context,
)

_ZONE_SCHEMA_SHA256 = "a" * 64


def _context(
    history_counts: object,
    history_mask: object,
    *,
    absolute_step: int = 8,
    steps_remaining: int = 5,
    prediction_horizon: int = 3,
) -> PredictionContext:
    return PredictionContext(
        absolute_step=absolute_step,
        steps_remaining=steps_remaining,
        history_counts=history_counts,
        history_mask=history_mask,
        zone_schema_sha256=_ZONE_SCHEMA_SHA256,
        prediction_horizon=prediction_horizon,
    )


def _predictors() -> tuple[object, ...]:
    return (
        ZeroDemandPredictor(),
        PersistenceDemandPredictor(),
        MaskedMeanDemandPredictor(),
        EWMADemandPredictor(0.5),
    )


def test_b0_returns_exact_float64_zeros_for_generic_horizon() -> None:
    context = _context(
        [[0, 0], [3, 5]],
        [False, True],
        prediction_horizon=5,
        steps_remaining=8,
    )

    forecast = ZeroDemandPredictor().predict(context)

    np.testing.assert_array_equal(forecast.mean, np.zeros((5, 2)))
    np.testing.assert_array_equal(forecast.valid_mask, np.ones(5, dtype=np.bool_))
    assert forecast.mean.dtype == np.float64


def test_padding_and_real_zero_have_distinct_b1_b2_b3_semantics() -> None:
    context = _context(
        [[0, 0], [0, 0], [4, 0], [0, 8]],
        [False, False, True, True],
    )

    persistence = PersistenceDemandPredictor().predict(context)
    masked_mean = MaskedMeanDemandPredictor().predict(context)
    ewma = EWMADemandPredictor(0.5).predict(context)

    np.testing.assert_array_equal(persistence.mean, [[0.0, 8.0]] * 3)
    np.testing.assert_array_equal(masked_mean.mean, [[2.0, 4.0]] * 3)
    np.testing.assert_array_equal(ewma.mean, [[2.0, 4.0]] * 3)


def test_b2_uses_float64_mean_without_rounding() -> None:
    context = _context([[0], [1], [2]], [False, True, True])

    forecast = MaskedMeanDemandPredictor().predict(context)

    np.testing.assert_array_equal(forecast.mean, [[1.5], [1.5], [1.5]])
    assert forecast.mean.dtype == np.float64


def test_b3_exact_hand_calculation_single_zone() -> None:
    context = _context([[2], [6], [10]], [True, True, True])

    forecast = EWMADemandPredictor(0.5).predict(context)

    np.testing.assert_array_equal(forecast.mean, [[7.0], [7.0], [7.0]])


def test_b3_exact_hand_calculation_multi_zone() -> None:
    context = _context(
        [[0, 0], [2, 4], [6, 0], [10, 8]],
        [False, True, True, True],
    )

    forecast = EWMADemandPredictor(0.5).predict(context)

    np.testing.assert_array_equal(forecast.mean, [[7.0, 5.0]] * 3)


@pytest.mark.parametrize(
    "alpha",
    [0.25, 0.50, 0.75, np.float32(0.25), np.float64(0.50), Fraction(3, 4)],
)
def test_b3_accepts_only_exact_official_alpha_values(alpha: object) -> None:
    predictor = EWMADemandPredictor(alpha)  # type: ignore[arg-type]

    assert predictor.alpha == float(alpha)  # type: ignore[arg-type]
    assert isinstance(predictor.alpha, float)


@pytest.mark.parametrize(
    "alpha",
    [0.0, 0.2, 1.0, -0.25, True, False, np.bool_(True), np.nan, np.inf, "0.5"],
)
def test_b3_rejects_nonofficial_or_nonreal_alpha(alpha: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        EWMADemandPredictor(alpha)  # type: ignore[arg-type]


def test_all_predictors_zero_every_row_at_terminal_boundary() -> None:
    context = _context(
        [[4, 2], [8, 6]],
        [True, True],
        steps_remaining=1,
        prediction_horizon=4,
    )

    for predictor in _predictors():
        forecast = predictor.predict(context)  # type: ignore[attr-defined]
        np.testing.assert_array_equal(forecast.valid_mask, [False] * 4)
        np.testing.assert_array_equal(forecast.mean, np.zeros((4, 2)))


def test_all_predictors_keep_partial_terminal_suffix_exactly_zero() -> None:
    context = _context(
        [[2, 4], [6, 8]],
        [True, True],
        steps_remaining=3,
        prediction_horizon=4,
    )

    for predictor in _predictors():
        forecast = predictor.predict(context)  # type: ignore[attr-defined]
        np.testing.assert_array_equal(forecast.valid_mask, [True, True, False, False])
        np.testing.assert_array_equal(forecast.mean[2:], np.zeros((2, 2)))


def test_all_predictors_satisfy_output_and_readonly_contract() -> None:
    context = _context(
        [[0, 0], [2, 4], [0, 6]],
        [False, True, True],
        steps_remaining=3,
        prediction_horizon=4,
    )

    for predictor in _predictors():
        forecast = predictor.predict(context)  # type: ignore[attr-defined]
        assert isinstance(forecast, DemandForecast)
        assert forecast.absolute_step == context.absolute_step
        assert forecast.horizon == context.prediction_horizon
        assert forecast.zone_schema_sha256 == context.zone_schema_sha256
        assert forecast.mean.dtype == np.float64
        assert forecast.mean.shape == (4, 2)
        assert np.isfinite(forecast.mean).all()
        assert (forecast.mean >= 0.0).all()
        assert not forecast.mean.flags.writeable
        assert not forecast.valid_mask.flags.writeable
        validate_forecast_for_context(context, forecast)


def test_each_predictor_invokes_shared_forecast_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context([[1], [3]], [True, True])
    calls: list[tuple[PredictionContext, DemandForecast]] = []
    original = baselines_module.validate_forecast_for_context

    def _record(context_: PredictionContext, forecast: DemandForecast) -> None:
        calls.append((context_, forecast))
        original(context_, forecast)

    monkeypatch.setattr(baselines_module, "validate_forecast_for_context", _record)

    for predictor in _predictors():
        predictor.predict(context)  # type: ignore[attr-defined]

    assert len(calls) == 4
    assert all(item[0] is context for item in calls)


def test_predictors_are_stateless_across_call_order_and_episodes() -> None:
    context_a = _context([[0, 0], [2, 4], [6, 0]], [False, True, True])
    context_b = _context(
        [[100, 200], [300, 400]],
        [True, True],
        absolute_step=40,
        steps_remaining=2,
    )

    for predictor in _predictors():
        first_a = predictor.predict(context_a)  # type: ignore[attr-defined]
        predictor.predict(context_b)  # type: ignore[attr-defined]
        second_a = predictor.predict(context_a)  # type: ignore[attr-defined]
        np.testing.assert_array_equal(first_a.mean, second_a.mean)
        np.testing.assert_array_equal(first_a.valid_mask, second_a.valid_mask)
        assert first_a.absolute_step == second_a.absolute_step
        assert first_a.horizon == second_a.horizon
        assert first_a.zone_schema_sha256 == second_a.zone_schema_sha256


def test_predictor_instances_are_immutable_and_slot_only() -> None:
    ewma = EWMADemandPredictor(0.5)

    assert not hasattr(ZeroDemandPredictor(), "__dict__")
    assert not hasattr(PersistenceDemandPredictor(), "__dict__")
    assert not hasattr(MaskedMeanDemandPredictor(), "__dict__")
    assert not hasattr(ewma, "__dict__")
    with pytest.raises(FrozenInstanceError):
        ewma.alpha = 0.75  # type: ignore[misc]


def test_public_predictor_boundary_accepts_only_prediction_context() -> None:
    for predictor_type in (
        ZeroDemandPredictor,
        PersistenceDemandPredictor,
        MaskedMeanDemandPredictor,
        EWMADemandPredictor,
    ):
        assert tuple(inspect.signature(predictor_type.predict).parameters) == (
            "self",
            "context",
        )

    context_a = _context([[0, 2], [4, 0]], [True, True])
    context_b = _context([[0, 2], [4, 0]], [True, True])
    for predictor in _predictors():
        forecast_a = predictor.predict(context_a)  # type: ignore[attr-defined]
        forecast_b = predictor.predict(context_b)  # type: ignore[attr-defined]
        np.testing.assert_array_equal(forecast_a.mean, forecast_b.mean)


@pytest.mark.parametrize("value", [None, object(), [[1]], np.array([[1]])])
def test_predictors_reject_non_context_inputs(value: object) -> None:
    for predictor in _predictors():
        with pytest.raises(TypeError, match="PredictionContext"):
            predictor.predict(value)  # type: ignore[arg-type,attr-defined]
