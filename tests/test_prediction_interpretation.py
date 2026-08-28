from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields

import numpy as np
import pytest

import fura_mappo.prediction.interpretation as interpretation_module
from fura_mappo.prediction import (
    LockedTestPointEstimate,
    PairedTraceBootstrapResult,
    PredictionBootstrapSpec,
    PrimaryIDInterpretation,
    PrimaryIDLabel,
    interpret_primary_id_bootstrap,
)


def _bootstrap_result(
    delta_rmse: float,
    ci_lower: float,
    ci_upper: float,
    *,
    interior_replicates: tuple[float, ...] = (),
) -> PairedTraceBootstrapResult:
    """构造隔离解释规则所需的 synthetic、structurally typed 上游结果。"""

    point_estimate = object.__new__(LockedTestPointEstimate)
    object.__setattr__(point_estimate, "delta_rmse", delta_rmse)
    replicates = np.asarray(
        (ci_lower, *interior_replicates, ci_upper),
        dtype=np.float64,
    )
    return PairedTraceBootstrapResult(
        point_estimate=point_estimate,
        spec=PredictionBootstrapSpec(
            num_resamples=len(replicates),
            rng_seed=7,
            quantile_method="inverted_cdf",
        ),
        delta_rmse_replicates=replicates,
    )


def test_primary_id_label_has_exact_frozen_values() -> None:
    assert tuple(PrimaryIDLabel) == (
        PrimaryIDLabel.LEARNED_BETTER,
        PrimaryIDLabel.LEARNED_WORSE,
        PrimaryIDLabel.NO_CLEAR_DIFFERENCE,
    )
    assert [label.value for label in PrimaryIDLabel] == [
        "LEARNED_BETTER",
        "LEARNED_WORSE",
        "NO_CLEAR_DIFFERENCE",
    ]
    assert all(isinstance(label, str) for label in PrimaryIDLabel)


@pytest.mark.parametrize(
    ("delta_rmse", "ci_lower", "ci_upper"),
    [
        (-1.0, -2.0, -0.1),
        (-1.0e-12, -2.0e-15, -1.0e-15),
    ],
)
def test_learned_better_requires_negative_point_and_strictly_negative_ci_upper(
    delta_rmse: float,
    ci_lower: float,
    ci_upper: float,
) -> None:
    result = interpret_primary_id_bootstrap(_bootstrap_result(delta_rmse, ci_lower, ci_upper))

    assert result.label is PrimaryIDLabel.LEARNED_BETTER


@pytest.mark.parametrize(
    ("delta_rmse", "ci_lower", "ci_upper"),
    [
        (1.0, 0.1, 2.0),
        (1.0e-12, 1.0e-15, 2.0e-15),
    ],
)
def test_learned_worse_requires_positive_point_and_strictly_positive_ci_lower(
    delta_rmse: float,
    ci_lower: float,
    ci_upper: float,
) -> None:
    result = interpret_primary_id_bootstrap(_bootstrap_result(delta_rmse, ci_lower, ci_upper))

    assert result.label is PrimaryIDLabel.LEARNED_WORSE


@pytest.mark.parametrize(
    ("delta_rmse", "ci_lower", "ci_upper"),
    [
        (-1.0, -2.0, 0.1),
        (1.0, -0.1, 2.0),
        (-1.0, -2.0, 0.0),
        (1.0, 0.0, 2.0),
        (0.0, -2.0, -1.0),
        (0.0, 1.0, 2.0),
        (0.0, 0.0, 0.0),
        (-1.0, 0.1, 2.0),
        (1.0, -2.0, -0.1),
    ],
)
def test_all_boundary_crossing_zero_point_and_contradictory_cases_are_no_clear_difference(
    delta_rmse: float,
    ci_lower: float,
    ci_upper: float,
) -> None:
    result = interpret_primary_id_bootstrap(_bootstrap_result(delta_rmse, ci_lower, ci_upper))

    assert result.label is PrimaryIDLabel.NO_CLEAR_DIFFERENCE


def test_point_sign_is_mandatory_even_when_interval_is_strictly_one_sided() -> None:
    negative_interval = interpret_primary_id_bootstrap(_bootstrap_result(0.0, -2.0, -1.0))
    positive_interval = interpret_primary_id_bootstrap(_bootstrap_result(0.0, 1.0, 2.0))

    assert negative_interval.label is PrimaryIDLabel.NO_CLEAR_DIFFERENCE
    assert positive_interval.label is PrimaryIDLabel.NO_CLEAR_DIFFERENCE


def test_ci_exclusion_is_mandatory_even_when_point_sign_is_nonzero() -> None:
    negative_point = interpret_primary_id_bootstrap(_bootstrap_result(-1.0, -2.0, 0.1))
    positive_point = interpret_primary_id_bootstrap(_bootstrap_result(1.0, -0.1, 2.0))

    assert negative_point.label is PrimaryIDLabel.NO_CLEAR_DIFFERENCE
    assert positive_point.label is PrimaryIDLabel.NO_CLEAR_DIFFERENCE


def test_direct_construction_and_public_function_apply_the_same_unique_rule() -> None:
    bootstrap_result = _bootstrap_result(-0.5, -1.0, -0.01)

    direct = PrimaryIDInterpretation(bootstrap_result=bootstrap_result)
    via_function = interpret_primary_id_bootstrap(bootstrap_result)

    assert direct.label is via_function.label is PrimaryIDLabel.LEARNED_BETTER


def test_interpretation_preserves_exact_upstream_result_and_scalar_properties() -> None:
    bootstrap_result = _bootstrap_result(-0.5, -1.0, -0.25)
    interpretation = interpret_primary_id_bootstrap(bootstrap_result)

    assert interpretation.bootstrap_result is bootstrap_result
    assert interpretation.delta_rmse is bootstrap_result.point_delta_rmse
    assert interpretation.ci_lower is bootstrap_result.ci_lower
    assert interpretation.ci_upper is bootstrap_result.ci_upper


def test_label_is_derived_immutable_and_not_a_constructor_argument() -> None:
    bootstrap_result = _bootstrap_result(-0.5, -1.0, -0.25)
    interpretation = PrimaryIDInterpretation(bootstrap_result)

    assert [field.name for field in fields(PrimaryIDInterpretation)] == [
        "bootstrap_result",
        "label",
    ]
    assert tuple(inspect.signature(PrimaryIDInterpretation).parameters) == ("bootstrap_result",)
    assert not hasattr(interpretation, "__dict__")
    with pytest.raises(FrozenInstanceError):
        interpretation.label = PrimaryIDLabel.LEARNED_WORSE  # type: ignore[misc]
    with pytest.raises(TypeError):
        PrimaryIDInterpretation(
            bootstrap_result,
            label=PrimaryIDLabel.LEARNED_WORSE,  # type: ignore[call-arg]
        )


def test_repeated_interpretation_is_deterministic_and_stateless() -> None:
    bootstrap_result = _bootstrap_result(0.25, 0.01, 0.5)

    labels = [interpret_primary_id_bootstrap(bootstrap_result).label for _ in range(10)]

    assert labels == [PrimaryIDLabel.LEARNED_WORSE] * 10


def test_interpretation_does_not_inspect_or_recompute_bootstrap_replicates() -> None:
    first = _bootstrap_result(
        -0.5,
        -2.0,
        -1.0,
        interior_replicates=(-1.9, -1.2),
    )
    second = _bootstrap_result(
        -0.5,
        -2.0,
        -1.0,
        interior_replicates=(-1.8, -1.1),
    )

    assert not np.array_equal(first.delta_rmse_replicates, second.delta_rmse_replicates)
    assert (first.ci_lower, first.ci_upper) == (second.ci_lower, second.ci_upper)
    assert interpret_primary_id_bootstrap(first).label is PrimaryIDLabel.LEARNED_BETTER
    assert interpret_primary_id_bootstrap(second).label is PrimaryIDLabel.LEARNED_BETTER


def test_direct_and_function_entry_points_reject_wrong_top_level_type() -> None:
    with pytest.raises(TypeError, match="PairedTraceBootstrapResult"):
        PrimaryIDInterpretation(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PairedTraceBootstrapResult"):
        interpret_primary_id_bootstrap(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("ci_lower", float("nan"), "finite"),
        ("ci_upper", float("inf"), "finite"),
        ("ci_lower", 2.0, "ci_lower"),
    ],
)
def test_interpretation_defensively_rejects_corrupted_upstream_endpoints(
    attribute: str,
    value: float,
    message: str,
) -> None:
    bootstrap_result = _bootstrap_result(-0.5, -1.0, 1.0)
    object.__setattr__(bootstrap_result, attribute, value)

    with pytest.raises(ValueError, match=message):
        interpret_primary_id_bootstrap(bootstrap_result)


def test_interpretation_defensively_rejects_corrupted_nonfinite_point_delta() -> None:
    bootstrap_result = _bootstrap_result(-0.5, -1.0, 1.0)
    object.__setattr__(bootstrap_result.point_estimate, "delta_rmse", float("nan"))

    with pytest.raises(ValueError, match="finite"):
        interpret_primary_id_bootstrap(bootstrap_result)


def test_production_interpretation_has_no_numeric_recomputation_or_official_defaults() -> None:
    source = inspect.getsource(interpretation_module)

    assert "numpy" not in source
    assert "delta_rmse_replicates" not in source
    assert "quantile" not in source
    assert "delta_min" not in source
    assert "isclose" not in source
    assert "90260819" not in source
    assert "50000" not in source


def test_public_interpretation_surface_is_exact_and_minimal() -> None:
    assert interpretation_module.__all__ == [
        "PrimaryIDInterpretation",
        "PrimaryIDLabel",
        "interpret_primary_id_bootstrap",
    ]
    assert "_interpret_primary_id" not in interpretation_module.__all__
