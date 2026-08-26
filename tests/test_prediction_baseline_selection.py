from __future__ import annotations

import random
from dataclasses import FrozenInstanceError, replace

import pytest

import fura_mappo.prediction.selection as selection_module
from fura_mappo.prediction import (
    BaselineKind,
    BaselineSelectionFailure,
    BaselineSelectionResult,
    BaselineValidationCandidate,
    DatasetProtocolSpec,
    PointMetricSummary,
    TracePointMetrics,
    select_validation_baselines,
)

_SCHEMA_A = "a" * 64
_SCHEMA_B = "b" * 64
_HISTORY_LENGTHS = (4, 8, 16, 32)
_ALPHAS = (0.25, 0.50, 0.75)
_DEFAULT_SIGNATURE = (
    ("trace_a", 2, 6),
    ("trace_b", 10, 7),
)
_FIXED_LENGTHS = {
    BaselineKind.B0: 32,
    BaselineKind.B1: 16,
    BaselineKind.B4: 8,
    BaselineKind.B5: 4,
}

VariantKey = tuple[BaselineKind, int, float | None]


def _metrics(
    primary_rmse: float,
    *,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    signature: tuple[tuple[str, int, int], ...] = _DEFAULT_SIGNATURE,
) -> PointMetricSummary:
    mse_value = primary_rmse * primary_rmse
    mse = [[mse_value] * num_zones for _ in range(prediction_horizon)]
    mae = [[primary_rmse] * num_zones for _ in range(prediction_horizon)]
    bias = [[0.0] * num_zones for _ in range(prediction_horizon)]
    trace_metrics = tuple(
        TracePointMetrics(
            trace_id=trace_id,
            trace_start_step=trace_start_step,
            trace_num_steps=trace_num_steps,
            anchor_counts_by_horizon=[
                trace_num_steps - lead for lead in range(1, prediction_horizon + 1)
            ],
            mse_by_horizon_zone=mse,
            mae_by_horizon_zone=mae,
            bias_by_horizon_zone=bias,
        )
        for trace_id, trace_start_step, trace_num_steps in signature
    )
    return PointMetricSummary(
        trace_metrics=trace_metrics,
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        zone_schema_sha256=schema,
    )


def _candidate(
    baseline: BaselineKind,
    history_length: int,
    primary_rmse: float,
    *,
    alpha: float | None = None,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    signature: tuple[tuple[str, int, int], ...] = _DEFAULT_SIGNATURE,
) -> BaselineValidationCandidate:
    return BaselineValidationCandidate(
        baseline=baseline,
        protocol=DatasetProtocolSpec(history_length, prediction_horizon, schema),
        metrics=_metrics(
            primary_rmse,
            prediction_horizon=prediction_horizon,
            num_zones=num_zones,
            schema=schema,
            signature=signature,
        ),
        alpha=alpha,
    )


def _full_grid(
    *,
    default_rmse: float = 10.0,
    overrides: dict[VariantKey, float] | None = None,
) -> list[BaselineValidationCandidate]:
    scores = overrides or {}

    def score(key: VariantKey) -> float:
        return scores.get(key, default_rmse)

    candidates = [
        _candidate(
            baseline,
            history_length,
            score((baseline, history_length, None)),
        )
        for baseline, history_length in _FIXED_LENGTHS.items()
    ]
    candidates.extend(
        _candidate(
            BaselineKind.B2,
            history_length,
            score((BaselineKind.B2, history_length, None)),
        )
        for history_length in _HISTORY_LENGTHS
    )
    candidates.extend(
        _candidate(
            BaselineKind.B3,
            history_length,
            score((BaselineKind.B3, history_length, alpha)),
            alpha=alpha,
        )
        for history_length in _HISTORY_LENGTHS
        for alpha in _ALPHAS
    )
    assert len(candidates) == 20
    return candidates


def _locked(
    result: BaselineSelectionResult,
    baseline: BaselineKind,
) -> BaselineValidationCandidate:
    return next(candidate for candidate in result.locked_variants if candidate.baseline is baseline)


def _variant(candidate: BaselineValidationCandidate) -> VariantKey:
    return (
        candidate.baseline,
        candidate.protocol.history_length,
        candidate.alpha,
    )


def test_baseline_kind_and_candidate_preserve_frozen_identity() -> None:
    assert [baseline.value for baseline in BaselineKind] == ["B0", "B1", "B2", "B3", "B4", "B5"]
    protocol = DatasetProtocolSpec(8, 2, _SCHEMA_A)
    metrics = _metrics(2.5)
    candidate = BaselineValidationCandidate(BaselineKind.B3, protocol, metrics, alpha=0.5)

    assert candidate.baseline is BaselineKind.B3
    assert candidate.alpha == 0.5
    assert candidate.primary_rmse == 2.5
    assert candidate.protocol is protocol
    assert candidate.metrics is metrics
    assert candidate.protocol.sha256 == protocol.sha256
    assert not hasattr(candidate, "__dict__")
    with pytest.raises(FrozenInstanceError):
        candidate.alpha = 0.75  # type: ignore[misc]


@pytest.mark.parametrize(
    "baseline", [BaselineKind.B0, BaselineKind.B1, BaselineKind.B4, BaselineKind.B5]
)
@pytest.mark.parametrize("history_length", _HISTORY_LENGTHS)
def test_fixed_baselines_accept_every_frozen_history_length(
    baseline: BaselineKind,
    history_length: int,
) -> None:
    candidate = _candidate(baseline, history_length, 1.0)

    assert candidate.protocol.history_length == history_length
    assert candidate.alpha is None


def test_candidate_rejects_invalid_types_and_structural_binding() -> None:
    protocol = DatasetProtocolSpec(4, 2, _SCHEMA_A)
    metrics = _metrics(1.0)
    with pytest.raises(TypeError, match="BaselineKind"):
        BaselineValidationCandidate("B0", protocol, metrics)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="DatasetProtocolSpec"):
        BaselineValidationCandidate(BaselineKind.B0, object(), metrics)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PointMetricSummary"):
        BaselineValidationCandidate(BaselineKind.B0, protocol, object())  # type: ignore[arg-type]

    with pytest.raises(BaselineSelectionFailure, match="prediction_horizon"):
        BaselineValidationCandidate(
            BaselineKind.B0,
            DatasetProtocolSpec(4, 1, _SCHEMA_A),
            metrics,
        )
    with pytest.raises(BaselineSelectionFailure, match="zone_schema_sha256"):
        BaselineValidationCandidate(
            BaselineKind.B0,
            DatasetProtocolSpec(4, 2, _SCHEMA_B),
            metrics,
        )
    with pytest.raises(BaselineSelectionFailure, match="history_length"):
        BaselineValidationCandidate(
            BaselineKind.B0,
            DatasetProtocolSpec(5, 2, _SCHEMA_A),
            metrics,
        )


@pytest.mark.parametrize("alpha", [None, 0.2, 1.0, True, "0.5"])
def test_candidate_rejects_illegal_b3_alpha(alpha: object) -> None:
    with pytest.raises(BaselineSelectionFailure) as captured:
        BaselineValidationCandidate(
            BaselineKind.B3,
            DatasetProtocolSpec(4, 2, _SCHEMA_A),
            _metrics(1.0),
            alpha=alpha,  # type: ignore[arg-type]
        )

    assert captured.value.status == "PREDICTION_BASELINE_SELECTION_FAILURE"


def test_non_b3_candidate_rejects_alpha() -> None:
    with pytest.raises(BaselineSelectionFailure, match="只有 B3"):
        _candidate(BaselineKind.B2, 4, 1.0, alpha=0.25)


@pytest.mark.parametrize(
    ("scores", "expected_length"),
    [
        ({4: 2.0, 8: 2.0, 16: 1.0, 32: 2.0}, 16),
        ({4: 1.0, 8: 1.0, 16: 1.0, 32: 1.0}, 4),
        ({4: 2.0, 8: 1.0, 16: 1.0, 32: 2.0}, 8),
    ],
)
def test_b2_exact_locking_order(
    scores: dict[int, float],
    expected_length: int,
) -> None:
    overrides = {
        (BaselineKind.B2, history_length, None): score for history_length, score in scores.items()
    }

    result = select_validation_baselines(_full_grid(default_rmse=100.0, overrides=overrides))

    assert _locked(result, BaselineKind.B2).protocol.history_length == expected_length


@pytest.mark.parametrize(
    ("lowest", "expected"),
    [
        ({(16, 0.75): 0.5}, (16, 0.75)),
        ({(8, 0.75): 1.0, (16, 0.25): 1.0}, (8, 0.75)),
        ({(8, 0.25): 1.0, (8, 0.75): 1.0}, (8, 0.25)),
        ({(history, alpha): 1.0 for history in _HISTORY_LENGTHS for alpha in _ALPHAS}, (4, 0.25)),
    ],
)
def test_b3_exact_locking_order(
    lowest: dict[tuple[int, float], float],
    expected: tuple[int, float],
) -> None:
    overrides = {
        (BaselineKind.B3, history_length, alpha): score
        for (history_length, alpha), score in lowest.items()
    }
    result = select_validation_baselines(_full_grid(default_rmse=2.0, overrides=overrides))
    locked = _locked(result, BaselineKind.B3)

    assert (locked.protocol.history_length, locked.alpha) == expected


def test_bstar_exact_tie_uses_only_baseline_rank() -> None:
    result = select_validation_baselines(_full_grid(default_rmse=1.0))

    assert result.selected_kind is BaselineKind.B0
    assert result.selected.protocol.history_length == 32
    assert _locked(result, BaselineKind.B3).protocol.history_length == 4
    assert _locked(result, BaselineKind.B3).alpha == 0.25


def test_bstar_selects_strictly_lower_b3_and_preserves_protocol_identity() -> None:
    winning_key = (BaselineKind.B3, 16, 0.75)
    candidates = _full_grid(default_rmse=1.0, overrides={winning_key: 0.5})
    original = next(candidate for candidate in candidates if _variant(candidate) == winning_key)

    result = select_validation_baselines(candidates)

    assert result.selected is original
    assert result.selected_kind is BaselineKind.B3
    assert result.selected.alpha == 0.75
    assert result.selected.protocol.history_length == 16
    assert result.selected.protocol.sha256 == original.protocol.sha256
    assert result.selected_primary_rmse == 0.5


def test_exact_nonzero_float_difference_beats_rank_and_shorter_history() -> None:
    delta = 1.0e-12
    bstar = select_validation_baselines(
        _full_grid(
            default_rmse=2.0,
            overrides={
                (BaselineKind.B0, 32, None): 1.0 + delta,
                (BaselineKind.B1, 16, None): 1.0,
            },
        )
    )
    b2 = select_validation_baselines(
        _full_grid(
            default_rmse=2.0,
            overrides={
                (BaselineKind.B2, 4, None): 1.0 + delta,
                (BaselineKind.B2, 16, None): 1.0,
            },
        )
    )

    assert (
        _locked(bstar, BaselineKind.B1).primary_rmse
        < _locked(
            bstar,
            BaselineKind.B0,
        ).primary_rmse
    )
    assert bstar.selected_kind is BaselineKind.B1
    assert _locked(b2, BaselineKind.B2).protocol.history_length == 16


@pytest.mark.parametrize(
    "missing_key",
    [
        (BaselineKind.B0, 32, None),
        (BaselineKind.B4, 8, None),
        (BaselineKind.B2, 16, None),
        (BaselineKind.B3, 16, 0.50),
    ],
)
def test_selection_rejects_missing_required_variant(missing_key: VariantKey) -> None:
    candidates = [candidate for candidate in _full_grid() if _variant(candidate) != missing_key]

    with pytest.raises(BaselineSelectionFailure) as captured:
        select_validation_baselines(candidates)

    assert captured.value.status == "PREDICTION_BASELINE_SELECTION_FAILURE"


@pytest.mark.parametrize(
    "duplicate_key",
    [
        (BaselineKind.B2, 8, None),
        (BaselineKind.B3, 8, 0.50),
    ],
)
def test_selection_rejects_duplicate_or_extra_variant(duplicate_key: VariantKey) -> None:
    candidates = _full_grid()
    duplicate = next(candidate for candidate in candidates if _variant(candidate) == duplicate_key)

    with pytest.raises(BaselineSelectionFailure, match="重复"):
        select_validation_baselines([*candidates, duplicate])


@pytest.mark.parametrize(
    "changed_signature",
    [
        (("trace_a", 2, 8), ("trace_b", 10, 7)),
        (("trace_a", 3, 6), ("trace_b", 10, 7)),
        (("trace_a", 2, 6), ("trace_c", 10, 7)),
    ],
)
def test_selection_rejects_mixed_validation_trace_signature(
    changed_signature: tuple[tuple[str, int, int], ...],
) -> None:
    candidates = _full_grid()
    original = candidates[0]
    candidates[0] = replace(
        original,
        metrics=_metrics(1.0, signature=changed_signature),
    )

    with pytest.raises(BaselineSelectionFailure, match="validation trace signature"):
        select_validation_baselines(candidates)


def test_selection_rejects_mixed_prediction_horizon() -> None:
    candidates = _full_grid()
    original = candidates[0]
    candidates[0] = _candidate(
        original.baseline,
        original.protocol.history_length,
        1.0,
        prediction_horizon=1,
    )

    with pytest.raises(BaselineSelectionFailure, match="prediction_horizon"):
        select_validation_baselines(candidates)


def test_selection_rejects_mixed_num_zones() -> None:
    candidates = _full_grid()
    original = candidates[0]
    candidates[0] = _candidate(
        original.baseline,
        original.protocol.history_length,
        1.0,
        num_zones=3,
    )

    with pytest.raises(BaselineSelectionFailure, match="num_zones"):
        select_validation_baselines(candidates)


def test_selection_rejects_mixed_zone_schema() -> None:
    candidates = _full_grid()
    original = candidates[0]
    candidates[0] = _candidate(
        original.baseline,
        original.protocol.history_length,
        1.0,
        schema=_SCHEMA_B,
    )

    with pytest.raises(BaselineSelectionFailure, match="zone_schema_sha256"):
        select_validation_baselines(candidates)


def test_caller_order_does_not_affect_any_locking_output() -> None:
    overrides = {
        (BaselineKind.B2, 8, None): 1.2,
        (BaselineKind.B3, 16, 0.50): 0.8,
        (BaselineKind.B5, 4, None): 0.9,
    }
    candidates = _full_grid(default_rmse=3.0, overrides=overrides)
    shuffled = candidates.copy()
    random.Random(20260826).shuffle(shuffled)

    results = (
        select_validation_baselines(candidates),
        select_validation_baselines(reversed(candidates)),
        select_validation_baselines(shuffled),
    )
    reference = results[0]
    for result in results[1:]:
        assert tuple(map(_variant, result.locked_variants)) == tuple(
            map(_variant, reference.locked_variants)
        )
        assert result.selected_kind is reference.selected_kind
        assert result.selected_primary_rmse == reference.selected_primary_rmse
        assert result.validation_trace_signature == reference.validation_trace_signature
        assert [candidate.baseline for candidate in result.locked_variants] == list(BaselineKind)


def test_selection_result_is_immutable_detached_and_structurally_validated() -> None:
    candidates = _full_grid(default_rmse=1.0)
    result = select_validation_baselines(candidates)
    original_locked = result.locked_variants
    candidates.reverse()
    candidates.clear()

    assert result.locked_variants == original_locked
    assert isinstance(result.locked_variants, tuple)
    assert isinstance(result.validation_trace_signature, tuple)
    assert all(isinstance(entry, tuple) for entry in result.validation_trace_signature)
    assert [candidate.baseline for candidate in result.locked_variants] == list(BaselineKind)
    assert result.prediction_horizon == 2
    assert result.num_zones == 2
    assert result.zone_schema_sha256 == _SCHEMA_A
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.selected = result.locked_variants[1]  # type: ignore[misc]
    with pytest.raises(ValueError, match="canonical order"):
        replace(result, locked_variants=tuple(reversed(result.locked_variants)))
    with pytest.raises(ValueError, match="Step-2"):
        replace(result, selected=result.locked_variants[1])


def test_selection_rejects_noniterable_and_wrong_element_types() -> None:
    with pytest.raises(TypeError, match="有限 iterable"):
        select_validation_baselines(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="BaselineValidationCandidate"):
        select_validation_baselines([object()])


def test_public_selection_surface_is_minimal() -> None:
    assert selection_module.__all__ == [
        "BaselineKind",
        "BaselineSelectionFailure",
        "BaselineSelectionResult",
        "BaselineValidationCandidate",
        "select_validation_baselines",
    ]
