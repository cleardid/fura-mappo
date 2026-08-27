from __future__ import annotations

import hashlib
import math
import random
from dataclasses import FrozenInstanceError, replace

import pytest

import fura_mappo.prediction.model_selection as model_selection_module
from fura_mappo.prediction import (
    DatasetProtocolSpec,
    HistoryTransformKind,
    LearnedConfigStatus,
    LearnedConfigValidationCandidate,
    LearnedModelSelectionResult,
    PointMetricSummary,
    PointObjectiveKind,
    PredictionModelSelectionFailure,
    TracePointMetrics,
    TrainingSeedValidationResult,
    select_learned_validation_config,
)

_SCHEMA_A = "a" * 64
_SCHEMA_B = "b" * 64
_DEFAULT_SIGNATURE = (
    ("trace_a", 2, 6),
    ("trace_b", 10, 7),
)


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _metrics(
    primary_mse: float,
    *,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    signature: tuple[tuple[str, int, int], ...] = _DEFAULT_SIGNATURE,
) -> PointMetricSummary:
    mse = [[primary_mse] * num_zones for _ in range(prediction_horizon)]
    mae_value = math.sqrt(primary_mse)
    mae = [[mae_value] * num_zones for _ in range(prediction_horizon)]
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


def _success(
    training_seed: int,
    primary_mse: float = 1.0,
    *,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    signature: tuple[tuple[str, int, int], ...] = _DEFAULT_SIGNATURE,
) -> TrainingSeedValidationResult:
    return TrainingSeedValidationResult(
        training_seed=training_seed,
        checkpoint_sha256=_sha256(f"checkpoint-{training_seed}-{primary_mse}"),
        metrics=_metrics(
            primary_mse,
            prediction_horizon=prediction_horizon,
            num_zones=num_zones,
            schema=schema,
            signature=signature,
        ),
        deterministic_validation_passed=True,
        failure_reason=None,
    )


def _failure(
    training_seed: int,
    *,
    reason: str = "upstream training failed",
    checkpoint_sha256: str | None = None,
    deterministic_validation_passed: bool = False,
) -> TrainingSeedValidationResult:
    return TrainingSeedValidationResult(
        training_seed=training_seed,
        checkpoint_sha256=checkpoint_sha256,
        metrics=None,
        deterministic_validation_passed=deterministic_validation_passed,
        failure_reason=reason,
    )


def _candidate(
    canonical_order: int,
    *,
    seed_mses: tuple[float, ...] = (1.0, 1.0, 1.0),
    seeds: tuple[int, ...] = (1, 2, 3),
    failed_seeds: tuple[int, ...] = (),
    history_length: int = 8,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    signature: tuple[tuple[str, int, int], ...] = _DEFAULT_SIGNATURE,
    objective: PointObjectiveKind = PointObjectiveKind.O0,
    transform: HistoryTransformKind = HistoryTransformKind.T0,
    complexity: tuple[int, ...] = (10, 100),
    config_sha256: str | None = None,
) -> LearnedConfigValidationCandidate:
    seed_results = tuple(
        _failure(seed)
        if seed in failed_seeds
        else _success(
            seed,
            seed_mse,
            prediction_horizon=prediction_horizon,
            num_zones=num_zones,
            schema=schema,
            signature=signature,
        )
        for seed, seed_mse in zip(seeds, seed_mses, strict=True)
    )
    identity = config_sha256 or _sha256(
        repr(
            (
                canonical_order,
                seeds,
                seed_mses,
                failed_seeds,
                history_length,
                prediction_horizon,
                num_zones,
                schema,
                signature,
                objective,
                transform,
                complexity,
            )
        )
    )
    return LearnedConfigValidationCandidate(
        config_sha256=identity,
        protocol=DatasetProtocolSpec(history_length, prediction_horizon, schema),
        objective=objective,
        transform=transform,
        model_complexity_key=complexity,
        canonical_order=canonical_order,
        seed_results=seed_results,
    )


def test_public_enums_and_status_names_are_exact() -> None:
    assert [kind.value for kind in PointObjectiveKind] == ["O0", "O1"]
    assert [kind.value for kind in HistoryTransformKind] == ["T0", "T1"]
    assert [status.value for status in LearnedConfigStatus] == ["VALID", "TRAINING_FAILURE"]
    assert "PREDICTION_MODEL_SELECTION_FAILURE" not in LearnedConfigStatus.__members__


def test_successful_seed_record_is_immutable_and_complete() -> None:
    metrics = _metrics(2.0)
    result = TrainingSeedValidationResult(
        training_seed=7,
        checkpoint_sha256="c" * 64,
        metrics=metrics,
        deterministic_validation_passed=True,
        failure_reason=None,
    )

    assert result.training_seed == 7
    assert result.checkpoint_sha256 == "c" * 64
    assert result.metrics is metrics
    assert result.is_successful
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.training_seed = 8  # type: ignore[misc]


@pytest.mark.parametrize("training_seed", [True, -1, 1.5, "1"])
def test_seed_record_rejects_invalid_training_seed(training_seed: object) -> None:
    with pytest.raises((TypeError, ValueError), match="training_seed"):
        TrainingSeedValidationResult(
            training_seed=training_seed,  # type: ignore[arg-type]
            checkpoint_sha256="c" * 64,
            metrics=_metrics(1.0),
            deterministic_validation_passed=True,
            failure_reason=None,
        )


def test_successful_seed_requires_checkpoint_metrics_and_deterministic_pass() -> None:
    with pytest.raises(ValueError, match="checkpoint_sha256"):
        TrainingSeedValidationResult(1, None, _metrics(1.0), True, None)
    with pytest.raises(TypeError, match="PointMetricSummary"):
        TrainingSeedValidationResult(1, "a" * 64, None, True, None)
    with pytest.raises(ValueError, match="deterministic validation"):
        TrainingSeedValidationResult(1, "a" * 64, _metrics(1.0), False, None)


@pytest.mark.parametrize("checkpoint_sha256", [None, "d" * 64])
@pytest.mark.parametrize("deterministic_validation_passed", [False, True])
def test_failed_seed_allows_optional_checkpoint_and_either_deterministic_flag(
    checkpoint_sha256: str | None,
    deterministic_validation_passed: bool,
) -> None:
    result = _failure(
        3,
        checkpoint_sha256=checkpoint_sha256,
        deterministic_validation_passed=deterministic_validation_passed,
    )

    assert not result.is_successful
    assert result.metrics is None
    assert result.failure_reason == "upstream training failed"


@pytest.mark.parametrize("failure_reason", ["", "   "])
def test_failed_seed_rejects_empty_failure_reason(failure_reason: str) -> None:
    with pytest.raises(ValueError, match="非空字符串"):
        TrainingSeedValidationResult(1, None, None, False, failure_reason)


def test_failed_seed_rejects_metrics() -> None:
    with pytest.raises(ValueError, match="不得携带 metrics"):
        TrainingSeedValidationResult(1, None, _metrics(1.0), False, "failed")


@pytest.mark.parametrize("failure_reason", [None, "failed"])
def test_seed_record_rejects_invalid_checkpoint_sha(failure_reason: str | None) -> None:
    metrics = _metrics(1.0) if failure_reason is None else None
    with pytest.raises(ValueError, match="64 位小写 SHA-256"):
        TrainingSeedValidationResult(1, "A" * 64, metrics, failure_reason is None, failure_reason)


@pytest.mark.parametrize("flag", [0, 1, "true", None])
def test_seed_record_rejects_non_bool_deterministic_flag(flag: object) -> None:
    with pytest.raises(TypeError, match="必须是 bool"):
        TrainingSeedValidationResult(
            1,
            None,
            None,
            flag,  # type: ignore[arg-type]
            "failed",
        )


def test_candidate_canonicalizes_seed_order_and_is_immutable() -> None:
    seed_results = [_success(9), _success(2), _success(5)]
    candidate = LearnedConfigValidationCandidate(
        config_sha256="a" * 64,
        protocol=DatasetProtocolSpec(8, 2, _SCHEMA_A),
        objective=PointObjectiveKind.O0,
        transform=HistoryTransformKind.T0,
        model_complexity_key=(10, 100),
        canonical_order=4,
        seed_results=seed_results,  # type: ignore[arg-type]
    )
    seed_results.clear()

    assert candidate.fixed_training_seeds == (2, 5, 9)
    assert candidate.status is LearnedConfigStatus.VALID
    assert candidate.model_complexity_key == (10, 100)
    assert not hasattr(candidate, "__dict__")
    with pytest.raises(FrozenInstanceError):
        candidate.canonical_order = 5  # type: ignore[misc]


def test_candidate_rejects_duplicate_or_too_few_seed_results() -> None:
    common = {
        "config_sha256": "a" * 64,
        "protocol": DatasetProtocolSpec(8, 2, _SCHEMA_A),
        "objective": PointObjectiveKind.O0,
        "transform": HistoryTransformKind.T0,
        "model_complexity_key": (1,),
        "canonical_order": 0,
    }
    with pytest.raises(ValueError, match="至少包含 3"):
        LearnedConfigValidationCandidate(seed_results=(_success(1), _success(2)), **common)
    with pytest.raises(ValueError, match="全部唯一"):
        LearnedConfigValidationCandidate(
            seed_results=(_success(1), _success(1), _success(2)),
            **common,
        )


@pytest.mark.parametrize("config_sha256", ["x" * 64, "A" * 64, "a" * 63])
def test_candidate_rejects_invalid_config_sha(config_sha256: str) -> None:
    with pytest.raises(ValueError, match="64 位小写 SHA-256"):
        replace(_candidate(0), config_sha256=config_sha256)


def test_candidate_rejects_invalid_protocol_and_history_grid() -> None:
    candidate = _candidate(0)
    with pytest.raises(TypeError, match="DatasetProtocolSpec"):
        replace(candidate, protocol=object())
    with pytest.raises(ValueError, match="frozen grid"):
        replace(candidate, protocol=DatasetProtocolSpec(5, 2, _SCHEMA_A))


@pytest.mark.parametrize("complexity", [(), [], (-1,), (True,), (1, "2")])
def test_candidate_rejects_invalid_complexity_key(complexity: object) -> None:
    with pytest.raises((TypeError, ValueError), match="model_complexity_key"):
        replace(_candidate(0), model_complexity_key=complexity)


@pytest.mark.parametrize("canonical_order", [True, -1, 1.5])
def test_candidate_rejects_invalid_canonical_order(canonical_order: object) -> None:
    with pytest.raises((TypeError, ValueError), match="canonical_order"):
        replace(_candidate(0), canonical_order=canonical_order)


def test_candidate_rejects_wrong_enum_types() -> None:
    candidate = _candidate(0)
    with pytest.raises(TypeError, match="PointObjectiveKind"):
        replace(candidate, objective="O0")
    with pytest.raises(TypeError, match="HistoryTransformKind"):
        replace(candidate, transform="T0")


def test_candidate_rejects_seed_metric_protocol_mismatch() -> None:
    common = {
        "config_sha256": "a" * 64,
        "protocol": DatasetProtocolSpec(8, 2, _SCHEMA_A),
        "objective": PointObjectiveKind.O0,
        "transform": HistoryTransformKind.T0,
        "model_complexity_key": (1,),
        "canonical_order": 0,
    }
    with pytest.raises(ValueError, match="prediction_horizon"):
        LearnedConfigValidationCandidate(
            seed_results=(
                _success(1, prediction_horizon=1),
                _success(2),
                _success(3),
            ),
            **common,
        )
    with pytest.raises(ValueError, match="zone_schema_sha256"):
        LearnedConfigValidationCandidate(
            seed_results=(
                _success(1, schema=_SCHEMA_B),
                _success(2),
                _success(3),
            ),
            **common,
        )


def test_candidate_rejects_mixed_successful_seed_geometry() -> None:
    candidate = _candidate(0)
    with pytest.raises(ValueError, match="num_zones"):
        replace(
            candidate,
            seed_results=(_success(1), _success(2, num_zones=3), _success(3)),
        )
    changed_signature = (("trace_a", 3, 6), ("trace_b", 10, 7))
    with pytest.raises(ValueError, match="validation trace signature"):
        replace(
            candidate,
            seed_results=(
                _success(1),
                _success(2, signature=changed_signature),
                _success(3),
            ),
        )


def test_validation_algorithm_uses_sqrt_of_mean_seed_mse() -> None:
    candidate = _candidate(0, seed_mses=(1.0, 4.0, 9.0))

    assert candidate.validation_algorithm_mse == pytest.approx(14.0 / 3.0)
    assert candidate.validation_algorithm_rmse == pytest.approx(math.sqrt(14.0 / 3.0))
    assert candidate.validation_algorithm_rmse != pytest.approx(2.0)


def test_any_failed_seed_marks_entire_config_without_partial_average() -> None:
    candidate = _candidate(0, seed_mses=(1.0, 4.0, 9.0), failed_seeds=(2,))

    assert candidate.status is LearnedConfigStatus.TRAINING_FAILURE
    assert candidate.validation_algorithm_mse is None
    assert candidate.validation_algorithm_rmse is None
    assert [result.is_successful for result in candidate.seed_results] == [True, False, True]


def test_partial_failed_config_still_checks_available_successful_metrics() -> None:
    candidate = _candidate(0, failed_seeds=(2,))
    changed = _success(3, signature=(("trace_a", 3, 6), ("trace_b", 10, 7)))

    with pytest.raises(ValueError, match="validation trace signature"):
        replace(candidate, seed_results=(_success(1), _failure(2), changed))


def test_selection_rejects_different_fixed_training_seed_sets() -> None:
    with pytest.raises(ValueError, match="fixed training-seed set"):
        select_learned_validation_config([_candidate(0), _candidate(1, seeds=(1, 2, 4))])


def test_selection_rejects_mixed_prediction_horizon_or_schema() -> None:
    with pytest.raises(ValueError, match="prediction_horizon"):
        select_learned_validation_config([_candidate(0), _candidate(1, prediction_horizon=1)])
    with pytest.raises(ValueError, match="zone_schema_sha256"):
        select_learned_validation_config([_candidate(0), _candidate(1, schema=_SCHEMA_B)])


def test_selection_rejects_mixed_num_zones() -> None:
    with pytest.raises(ValueError, match="num_zones"):
        select_learned_validation_config([_candidate(0), _candidate(1, num_zones=3)])


@pytest.mark.parametrize(
    "changed_signature",
    [
        (("trace_a", 2, 6), ("trace_c", 10, 7)),
        (("trace_a", 3, 6), ("trace_b", 10, 7)),
        (("trace_a", 2, 8), ("trace_b", 10, 7)),
    ],
)
def test_selection_rejects_mixed_validation_trace_signature(
    changed_signature: tuple[tuple[str, int, int], ...],
) -> None:
    with pytest.raises(ValueError, match="validation trace signature"):
        select_learned_validation_config(
            [_candidate(0), _candidate(1, signature=changed_signature)]
        )


def test_selection_rejects_duplicate_config_sha_or_canonical_order() -> None:
    first = _candidate(0)
    with pytest.raises(ValueError, match="config_sha256"):
        select_learned_validation_config([first, _candidate(1, config_sha256=first.config_sha256)])
    with pytest.raises(ValueError, match="canonical_order"):
        select_learned_validation_config([first, _candidate(0, config_sha256="f" * 64)])


def test_all_training_failures_raise_phase_failure_only_after_fairness_checks() -> None:
    failures = [
        _candidate(0, failed_seeds=(1, 2, 3)),
        _candidate(1, failed_seeds=(1, 2, 3)),
    ]
    with pytest.raises(PredictionModelSelectionFailure) as captured:
        select_learned_validation_config(failures)
    assert captured.value.status == "PREDICTION_MODEL_SELECTION_FAILURE"

    with pytest.raises(ValueError, match="fixed training-seed set"):
        select_learned_validation_config(
            [failures[0], _candidate(2, seeds=(1, 2, 4), failed_seeds=(1, 2, 4))]
        )


def test_mixed_valid_and_failed_configs_rank_only_valid_and_preserve_failures() -> None:
    failed_high_order = _candidate(9, seed_mses=(0.01, 0.01, 0.01), failed_seeds=(2,))
    failed_low_order = _candidate(4, seed_mses=(0.02, 0.02, 0.02), failed_seeds=(1,))
    valid_loser = _candidate(2, seed_mses=(4.0, 4.0, 4.0))
    valid_winner = _candidate(3, seed_mses=(1.0, 1.0, 1.0))

    result = select_learned_validation_config(
        [failed_high_order, valid_loser, failed_low_order, valid_winner]
    )

    assert result.selected is valid_winner
    assert result.valid_candidates == (valid_winner, valid_loser)
    assert result.failed_candidates == (failed_low_order, failed_high_order)
    assert all(
        candidate.validation_algorithm_rmse is None for candidate in result.failed_candidates
    )


def test_strictly_lower_algorithm_rmse_wins_before_all_ties() -> None:
    lower_rmse = _candidate(
        9,
        seed_mses=(1.0, 1.0, 1.0),
        history_length=32,
        objective=PointObjectiveKind.O1,
        transform=HistoryTransformKind.T1,
        complexity=(999,),
    )
    tie_break_favorite = _candidate(
        0,
        seed_mses=(1.0 + 1.0e-12,) * 3,
        history_length=4,
        complexity=(0,),
    )

    result = select_learned_validation_config([tie_break_favorite, lower_rmse])

    assert result.selected is lower_rmse
    assert lower_rmse.validation_algorithm_rmse < tie_break_favorite.validation_algorithm_rmse


@pytest.mark.parametrize(
    ("left_complexity", "right_complexity"),
    [
        ((10, 100), (11, 0)),
        ((10, 100), (10, 101)),
    ],
)
def test_exact_rmse_tie_uses_lexicographic_complexity(
    left_complexity: tuple[int, ...],
    right_complexity: tuple[int, ...],
) -> None:
    left = _candidate(1, complexity=left_complexity)
    right = _candidate(0, complexity=right_complexity, history_length=4)

    assert select_learned_validation_config([right, left]).selected is left


def test_rmse_and_complexity_tie_uses_shorter_history() -> None:
    shorter = _candidate(5, history_length=4)
    longer = _candidate(0, history_length=16)

    assert select_learned_validation_config([longer, shorter]).selected is shorter


def test_objective_rank_o0_wins_after_prior_exact_ties() -> None:
    o0 = _candidate(5, objective=PointObjectiveKind.O0)
    o1 = _candidate(0, objective=PointObjectiveKind.O1)

    assert select_learned_validation_config([o1, o0]).selected is o0


def test_transform_rank_t0_wins_after_prior_exact_ties() -> None:
    t0 = _candidate(5, transform=HistoryTransformKind.T0)
    t1 = _candidate(0, transform=HistoryTransformKind.T1)

    assert select_learned_validation_config([t1, t0]).selected is t0


def test_canonical_order_is_final_tie_and_config_sha_cannot_decide() -> None:
    canonical_winner = _candidate(0, config_sha256="f" * 64)
    lexicographic_sha_favorite = _candidate(1, config_sha256="0" * 64)

    result = select_learned_validation_config([lexicographic_sha_favorite, canonical_winner])

    assert result.selected is canonical_winner
    assert result.selected.config_sha256 > lexicographic_sha_favorite.config_sha256


def test_caller_order_does_not_affect_selection_or_result_ordering() -> None:
    candidates = [
        _candidate(7, seed_mses=(4.0, 4.0, 4.0)),
        _candidate(2, seed_mses=(1.0, 1.0, 1.0)),
        _candidate(8, failed_seeds=(2,)),
        _candidate(3, seed_mses=(1.0, 1.0, 1.0), complexity=(5,)),
        _candidate(1, failed_seeds=(1,)),
    ]
    shuffled = candidates.copy()
    random.Random(20260827).shuffle(shuffled)
    results = (
        select_learned_validation_config(candidates),
        select_learned_validation_config(reversed(candidates)),
        select_learned_validation_config(shuffled),
    )
    reference = results[0]

    for result in results[1:]:
        assert result.selected.config_sha256 == reference.selected.config_sha256
        assert tuple(item.config_sha256 for item in result.valid_candidates) == tuple(
            item.config_sha256 for item in reference.valid_candidates
        )
        assert tuple(item.config_sha256 for item in result.failed_candidates) == tuple(
            item.config_sha256 for item in reference.failed_candidates
        )
        assert result.fixed_training_seeds == reference.fixed_training_seeds
        assert result.validation_trace_signature == reference.validation_trace_signature
        assert result.prediction_horizon == reference.prediction_horizon
        assert result.num_zones == reference.num_zones
        assert result.zone_schema_sha256 == reference.zone_schema_sha256


def _mixed_result() -> LearnedModelSelectionResult:
    return select_learned_validation_config(
        [
            _candidate(3, seed_mses=(1.0, 1.0, 1.0)),
            _candidate(4, seed_mses=(2.0, 2.0, 2.0)),
            _candidate(8, failed_seeds=(2,)),
            _candidate(6, failed_seeds=(1,)),
        ]
    )


def test_selection_result_is_immutable_detached_and_complete() -> None:
    candidates = [_candidate(0), _candidate(1, seed_mses=(2.0, 2.0, 2.0))]
    result = select_learned_validation_config(candidates)
    candidates.clear()

    assert result.selected is result.valid_candidates[0]
    assert result.fixed_training_seeds == (1, 2, 3)
    assert result.validation_trace_signature == _DEFAULT_SIGNATURE
    assert result.prediction_horizon == 2
    assert result.num_zones == 2
    assert result.zone_schema_sha256 == _SCHEMA_A
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.num_zones = 3  # type: ignore[misc]


def test_result_rejects_wrong_selected_or_candidate_ordering() -> None:
    result = _mixed_result()
    with pytest.raises(ValueError, match="selected"):
        replace(result, selected=result.valid_candidates[1])
    with pytest.raises(ValueError, match="total ordering"):
        replace(result, valid_candidates=tuple(reversed(result.valid_candidates)))
    with pytest.raises(ValueError, match="canonical_order"):
        replace(result, failed_candidates=tuple(reversed(result.failed_candidates)))


def test_result_rejects_status_in_wrong_bucket() -> None:
    result = _mixed_result()
    with pytest.raises(ValueError, match="VALID"):
        replace(
            result,
            valid_candidates=(result.failed_candidates[0], *result.valid_candidates),
        )
    with pytest.raises(ValueError, match="TRAINING_FAILURE"):
        replace(result, failed_candidates=(*result.failed_candidates, result.valid_candidates[0]))


def test_result_rejects_duplicate_config_or_order_identity() -> None:
    result = _mixed_result()
    duplicate_hash = replace(
        result.valid_candidates[1],
        config_sha256=result.valid_candidates[0].config_sha256,
    )
    with pytest.raises(ValueError, match="config_sha256"):
        replace(
            result,
            valid_candidates=(result.valid_candidates[0], duplicate_hash),
        )

    duplicate_order = replace(
        result.valid_candidates[1],
        canonical_order=result.valid_candidates[0].canonical_order,
    )
    with pytest.raises(ValueError, match="canonical_order"):
        replace(
            result,
            valid_candidates=(result.valid_candidates[0], duplicate_order),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("fixed_training_seeds", (1, 2, 4), "fixed_training_seeds"),
        ("prediction_horizon", 3, "prediction_horizon"),
        ("num_zones", 3, "num_zones"),
        ("zone_schema_sha256", _SCHEMA_B, "zone_schema_sha256"),
        (
            "validation_trace_signature",
            (("trace_a", 3, 6), ("trace_b", 10, 7)),
            "validation_trace_signature",
        ),
    ],
)
def test_result_rejects_fairness_fields_not_bound_to_candidates(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_mixed_result(), **{field: value})


def test_selection_rejects_empty_noniterable_or_wrong_candidate_types() -> None:
    with pytest.raises(ValueError, match="非空"):
        select_learned_validation_config([])
    with pytest.raises(TypeError, match="有限 iterable"):
        select_learned_validation_config(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="LearnedConfigValidationCandidate"):
        select_learned_validation_config([object()])


def test_public_model_selection_surface_is_minimal() -> None:
    assert model_selection_module.__all__ == [
        "HistoryTransformKind",
        "LearnedConfigStatus",
        "LearnedConfigValidationCandidate",
        "LearnedModelSelectionResult",
        "PointObjectiveKind",
        "PredictionModelSelectionFailure",
        "TrainingSeedValidationResult",
        "select_learned_validation_config",
    ]
    assert "_OBJECTIVE_RANK" not in model_selection_module.__all__
    assert "_TRANSFORM_RANK" not in model_selection_module.__all__
    assert "_validation_trace_signature" not in model_selection_module.__all__
    assert "_learned_sort_key" not in model_selection_module.__all__
