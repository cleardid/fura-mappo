"""WP-03B learned-model 的 deterministic validation-only selection infrastructure。"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from numbers import Integral

from fura_mappo.prediction.dataset import DatasetProtocolSpec
from fura_mappo.prediction.metrics import PointMetricSummary

_HISTORY_LENGTHS = (4, 8, 16, 32)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MODEL_SELECTION_FAILURE_STATUS = "PREDICTION_MODEL_SELECTION_FAILURE"


class PointObjectiveKind(str, Enum):
    """冻结的 learned point-objective identity；本 Slice 不计算 objective。"""

    O0 = "O0"
    O1 = "O1"


class HistoryTransformKind(str, Enum):
    """冻结的 history-transform identity；本 Slice 不执行 transform。"""

    T0 = "T0"
    T1 = "T1"


class LearnedConfigStatus(str, Enum):
    """单个 learned config 在全部 fixed training seeds 上的 validation 状态。"""

    VALID = "VALID"
    TRAINING_FAILURE = "TRAINING_FAILURE"


_OBJECTIVE_RANK = {
    PointObjectiveKind.O0: 0,
    PointObjectiveKind.O1: 1,
}
_TRANSFORM_RANK = {
    HistoryTransformKind.T0: 0,
    HistoryTransformKind.T1: 1,
}

_ValidationTraceSignature = tuple[tuple[str, int, int], ...]


class PredictionModelSelectionFailure(ValueError):
    """表示合法 candidate batch 没有任何可进入 numerical ranking 的 config。"""

    @property
    def status(self) -> str:
        """返回与 config-level TRAINING_FAILURE 隔离的稳定 phase status。"""

        return _MODEL_SELECTION_FAILURE_STATUS


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """规范化非 bool、非负整数，不引入 NumPy dependency。"""

    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} 必须是整数且不能是布尔值")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} 必须大于或等于 0")
    return normalized


def _normalize_positive_integer(value: object, name: str) -> int:
    """规范化非 bool 正整数。"""

    normalized = _normalize_nonnegative_integer(value, name)
    if normalized < 1:
        raise ValueError(f"{name} 必须大于或等于 1")
    return normalized


def _normalize_sha256(value: object, name: str) -> str:
    """验证 64-char lowercase SHA-256 structural identity。"""

    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} 必须是 64 位小写 SHA-256")
    return value


def _normalize_optional_sha256(value: object, name: str) -> str | None:
    """验证可选 SHA-256 audit identity。"""

    if value is None:
        return None
    return _normalize_sha256(value, name)


def _validation_trace_signature(metrics: PointMetricSummary) -> _ValidationTraceSignature:
    """从 canonical trace metrics 构造独立的 structural validation signature。"""

    return tuple(
        (
            trace.trace_id,
            trace.trace_start_step,
            trace.trace_num_steps,
        )
        for trace in metrics.trace_metrics
    )


def _normalize_validation_trace_signature(value: object) -> _ValidationTraceSignature:
    """把 result signature 防御性规范化为 immutable canonical nested tuple。"""

    try:
        entries = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("validation_trace_signature 必须是有限 iterable") from error
    if not entries:
        raise ValueError("validation_trace_signature 必须至少包含一条 trace")

    normalized: list[tuple[str, int, int]] = []
    for entry in entries:
        try:
            fields = tuple(entry)
        except TypeError as error:
            raise TypeError("validation trace signature entry 必须是三元 iterable") from error
        if len(fields) != 3:
            raise ValueError("validation trace signature entry 必须包含 3 个字段")
        trace_id, trace_start_step, trace_num_steps = fields
        if not isinstance(trace_id, str) or not trace_id:
            raise ValueError("validation signature trace_id 必须是非空字符串")
        start = _normalize_nonnegative_integer(
            trace_start_step,
            "validation signature trace_start_step",
        )
        num_steps = _normalize_positive_integer(
            trace_num_steps,
            "validation signature trace_num_steps",
        )
        normalized.append((trace_id, start, num_steps))

    result = tuple(normalized)
    if result != tuple(sorted(result, key=lambda item: item[0])):
        raise ValueError("validation_trace_signature 必须按 trace_id canonical ordering")
    if len({entry[0] for entry in result}) != len(result):
        raise ValueError("validation_trace_signature 的 trace_id 必须唯一")
    return result


@dataclass(frozen=True, slots=True, eq=False)
class TrainingSeedValidationResult:
    """一个 frozen candidate config、一个 fixed training seed 的 upstream outcome。"""

    training_seed: int
    checkpoint_sha256: str | None
    metrics: PointMetricSummary | None
    deterministic_validation_passed: bool
    failure_reason: str | None

    def __post_init__(self) -> None:
        """严格区分 successful seed 与显式 failed seed，禁止 partial numeric records。"""

        training_seed = _normalize_nonnegative_integer(self.training_seed, "training_seed")
        checkpoint_sha256 = _normalize_optional_sha256(
            self.checkpoint_sha256,
            "checkpoint_sha256",
        )
        if type(self.deterministic_validation_passed) is not bool:
            raise TypeError("deterministic_validation_passed 必须是 bool")

        if self.failure_reason is None:
            if checkpoint_sha256 is None:
                raise ValueError("successful seed 必须提供 checkpoint_sha256")
            if not isinstance(self.metrics, PointMetricSummary):
                raise TypeError("successful seed metrics 必须是 PointMetricSummary")
            if not self.deterministic_validation_passed:
                raise ValueError("successful seed 必须通过 deterministic validation")
            primary_mse = self.metrics.primary_mse
            if not math.isfinite(primary_mse) or primary_mse < 0.0:
                raise ValueError("successful seed Primary MSE 必须有限且非负")
        else:
            if not isinstance(self.failure_reason, str):
                raise TypeError("failure_reason 必须是字符串或 None")
            if not self.failure_reason.strip():
                raise ValueError("failed seed failure_reason 必须是非空字符串")
            if self.metrics is not None:
                raise ValueError("failed seed 不得携带 metrics")

        object.__setattr__(self, "training_seed", training_seed)
        object.__setattr__(self, "checkpoint_sha256", checkpoint_sha256)

    @property
    def is_successful(self) -> bool:
        """返回该 seed 是否满足完整 success contract。"""

        return self.failure_reason is None


def _normalize_complexity_key(value: object) -> tuple[int, ...]:
    """验证 predeclared、architecture-neutral lexicographic complexity key。"""

    if not isinstance(value, tuple):
        raise TypeError("model_complexity_key 必须是 tuple[int, ...]")
    if not value:
        raise ValueError("model_complexity_key 必须非空")
    return tuple(
        _normalize_nonnegative_integer(component, "model_complexity_key component")
        for component in value
    )


def _normalize_seed_results(
    value: object,
) -> tuple[TrainingSeedValidationResult, ...]:
    """验证至少三个 distinct seeds，并按 training_seed canonicalize。"""

    try:
        seed_results = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("seed_results 必须是有限 iterable") from error
    if len(seed_results) < 3:
        raise ValueError("seed_results 必须至少包含 3 个 fixed training seeds")
    if any(not isinstance(result, TrainingSeedValidationResult) for result in seed_results):
        raise TypeError("seed_results 必须全部是 TrainingSeedValidationResult")
    seeds = [result.training_seed for result in seed_results]
    if len(seeds) != len(set(seeds)):
        raise ValueError("seed_results 的 training_seed 必须全部唯一")
    return tuple(sorted(seed_results, key=lambda result: result.training_seed))


def _mean_primary_mse(seed_results: tuple[TrainingSeedValidationResult, ...]) -> float:
    """对 successful fixed seeds 的 Primary MSE 等权聚合。"""

    primary_mses = [
        result.metrics.primary_mse
        for result in seed_results
        if result.metrics is not None and result.is_successful
    ]
    try:
        mean_mse = math.fsum(primary_mses) / len(seed_results)
    except OverflowError as error:
        raise ValueError("Validation Algorithm MSE 必须有限") from error
    if not math.isfinite(mean_mse) or mean_mse < 0.0:
        raise ValueError("Validation Algorithm MSE 必须有限且非负")
    return mean_mse


@dataclass(frozen=True, slots=True, eq=False)
class LearnedConfigValidationCandidate:
    """一个 frozen learned config 的 fixed-seed validation-only record。"""

    config_sha256: str
    protocol: DatasetProtocolSpec
    objective: PointObjectiveKind
    transform: HistoryTransformKind
    model_complexity_key: tuple[int, ...]
    canonical_order: int
    seed_results: tuple[TrainingSeedValidationResult, ...]

    def __post_init__(self) -> None:
        """验证 frozen config identity、seed completeness 与 candidate-local fairness。"""

        config_sha256 = _normalize_sha256(self.config_sha256, "config_sha256")
        if not isinstance(self.protocol, DatasetProtocolSpec):
            raise TypeError("protocol 必须是 DatasetProtocolSpec")
        if self.protocol.history_length not in _HISTORY_LENGTHS:
            raise ValueError("candidate history_length 不属于 frozen grid")
        if not isinstance(self.objective, PointObjectiveKind):
            raise TypeError("objective 必须是 PointObjectiveKind")
        if not isinstance(self.transform, HistoryTransformKind):
            raise TypeError("transform 必须是 HistoryTransformKind")
        complexity_key = _normalize_complexity_key(self.model_complexity_key)
        canonical_order = _normalize_nonnegative_integer(self.canonical_order, "canonical_order")
        seed_results = _normalize_seed_results(self.seed_results)

        available_metrics = tuple(
            result.metrics
            for result in seed_results
            if result.is_successful and result.metrics is not None
        )
        for metrics in available_metrics:
            if metrics.prediction_horizon != self.protocol.prediction_horizon:
                raise ValueError("seed metrics/protocol prediction_horizon 不一致")
            if metrics.zone_schema_sha256 != self.protocol.zone_schema_sha256:
                raise ValueError("seed metrics/protocol zone_schema_sha256 不一致")
        if available_metrics:
            first_metrics = available_metrics[0]
            num_zones = first_metrics.num_zones
            signature = _validation_trace_signature(first_metrics)
            for metrics in available_metrics[1:]:
                if metrics.num_zones != num_zones:
                    raise ValueError("candidate seeds 混合了 num_zones")
                if _validation_trace_signature(metrics) != signature:
                    raise ValueError("candidate seeds 的 validation trace signature 不一致")

        if all(result.is_successful for result in seed_results):
            _mean_primary_mse(seed_results)

        object.__setattr__(self, "config_sha256", config_sha256)
        object.__setattr__(self, "model_complexity_key", complexity_key)
        object.__setattr__(self, "canonical_order", canonical_order)
        object.__setattr__(self, "seed_results", seed_results)

    @property
    def status(self) -> LearnedConfigStatus:
        """只要一个 fixed seed 显式失败，整个 config 即为 TRAINING_FAILURE。"""

        if all(result.is_successful for result in self.seed_results):
            return LearnedConfigStatus.VALID
        return LearnedConfigStatus.TRAINING_FAILURE

    @property
    def fixed_training_seeds(self) -> tuple[int, ...]:
        """返回 canonical ascending fixed training-seed set。"""

        return tuple(result.training_seed for result in self.seed_results)

    @property
    def validation_algorithm_mse(self) -> float | None:
        """返回 ``mean_r(seed Primary MSE_r)``；failed config 没有数值分数。"""

        if self.status is LearnedConfigStatus.TRAINING_FAILURE:
            return None
        return _mean_primary_mse(self.seed_results)

    @property
    def validation_algorithm_rmse(self) -> float | None:
        """返回 ``sqrt(mean_r(MSE_r))``，绝不平均 per-seed RMSE。"""

        algorithm_mse = self.validation_algorithm_mse
        if algorithm_mse is None:
            return None
        return math.sqrt(algorithm_mse)


def _learned_sort_key(
    candidate: LearnedConfigValidationCandidate,
) -> tuple[float, tuple[int, ...], int, int, int, int]:
    """返回 VALID configs 的 frozen exact scientific total-order key。"""

    algorithm_rmse = candidate.validation_algorithm_rmse
    if algorithm_rmse is None:
        raise ValueError("TRAINING_FAILURE config 不得进入 numerical ranking")
    return (
        algorithm_rmse,
        candidate.model_complexity_key,
        candidate.protocol.history_length,
        _OBJECTIVE_RANK[candidate.objective],
        _TRANSFORM_RANK[candidate.transform],
        candidate.canonical_order,
    )


def _validate_unique_candidate_identity(
    candidates: tuple[LearnedConfigValidationCandidate, ...],
) -> None:
    """拒绝 duplicate config identity 与 duplicate Layer-A canonical order。"""

    config_hashes = [candidate.config_sha256 for candidate in candidates]
    if len(config_hashes) != len(set(config_hashes)):
        raise ValueError("candidate config_sha256 必须全部唯一")
    canonical_orders = [candidate.canonical_order for candidate in candidates]
    if len(canonical_orders) != len(set(canonical_orders)):
        raise ValueError("candidate canonical_order 必须全部唯一")


def _validate_batch_fairness(
    candidates: tuple[LearnedConfigValidationCandidate, ...],
) -> tuple[
    tuple[int, ...],
    int,
    int | None,
    str,
    _ValidationTraceSignature | None,
]:
    """验证 exact seeds、P/schema 及所有 available successful metrics 的 geometry。"""

    first = candidates[0]
    fixed_training_seeds = first.fixed_training_seeds
    prediction_horizon = first.protocol.prediction_horizon
    zone_schema_sha256 = first.protocol.zone_schema_sha256

    for candidate in candidates[1:]:
        if candidate.fixed_training_seeds != fixed_training_seeds:
            raise ValueError("candidates 必须共享 exact fixed training-seed set")
        if candidate.protocol.prediction_horizon != prediction_horizon:
            raise ValueError("candidates 混合了 prediction_horizon")
        if candidate.protocol.zone_schema_sha256 != zone_schema_sha256:
            raise ValueError("candidates 混合了 zone_schema_sha256")

    available_metrics = tuple(
        result.metrics
        for candidate in candidates
        for result in candidate.seed_results
        if result.is_successful and result.metrics is not None
    )
    if not available_metrics:
        return (
            fixed_training_seeds,
            prediction_horizon,
            None,
            zone_schema_sha256,
            None,
        )

    first_metrics = available_metrics[0]
    num_zones = first_metrics.num_zones
    signature = _validation_trace_signature(first_metrics)
    for metrics in available_metrics[1:]:
        if metrics.num_zones != num_zones:
            raise ValueError("successful validation metrics 混合了 num_zones")
        if _validation_trace_signature(metrics) != signature:
            raise ValueError("successful validation metrics 的 validation trace signature 不一致")
    return (
        fixed_training_seeds,
        prediction_horizon,
        num_zones,
        zone_schema_sha256,
        signature,
    )


@dataclass(frozen=True, slots=True, eq=False)
class LearnedModelSelectionResult:
    """learned configs 的 immutable、validation-only deterministic locking result。"""

    selected: LearnedConfigValidationCandidate
    valid_candidates: tuple[LearnedConfigValidationCandidate, ...]
    failed_candidates: tuple[LearnedConfigValidationCandidate, ...]
    fixed_training_seeds: tuple[int, ...]
    validation_trace_signature: _ValidationTraceSignature
    prediction_horizon: int
    num_zones: int
    zone_schema_sha256: str

    def __post_init__(self) -> None:
        """防止 caller 构造违背 status、fairness 或 frozen winner 的 result。"""

        try:
            valid_candidates = tuple(self.valid_candidates)
            failed_candidates = tuple(self.failed_candidates)
        except TypeError as error:
            raise TypeError("candidate collections 必须是有限 iterable") from error
        if not valid_candidates:
            raise ValueError("valid_candidates 必须非空")
        if any(
            not isinstance(candidate, LearnedConfigValidationCandidate)
            for candidate in (*valid_candidates, *failed_candidates)
        ):
            raise TypeError("result candidates 必须全部是 LearnedConfigValidationCandidate")
        if any(candidate.status is not LearnedConfigStatus.VALID for candidate in valid_candidates):
            raise ValueError("valid_candidates 必须全部为 VALID")
        if any(
            candidate.status is not LearnedConfigStatus.TRAINING_FAILURE
            for candidate in failed_candidates
        ):
            raise ValueError("failed_candidates 必须全部为 TRAINING_FAILURE")
        if not isinstance(self.selected, LearnedConfigValidationCandidate):
            raise TypeError("selected 必须是 LearnedConfigValidationCandidate")

        expected_valid = tuple(sorted(valid_candidates, key=_learned_sort_key))
        if valid_candidates != expected_valid:
            raise ValueError("valid_candidates 必须按 frozen learned total ordering 排列")
        expected_failed = tuple(sorted(failed_candidates, key=lambda item: item.canonical_order))
        if failed_candidates != expected_failed:
            raise ValueError("failed_candidates 必须按 canonical_order 排列")
        if self.selected is not valid_candidates[0]:
            raise ValueError("selected 必须是 valid_candidates[0] 的 exact frozen winner")

        all_candidates = (*valid_candidates, *failed_candidates)
        _validate_unique_candidate_identity(all_candidates)
        (
            expected_seeds,
            expected_horizon,
            expected_num_zones,
            expected_schema,
            expected_signature,
        ) = _validate_batch_fairness(all_candidates)
        if expected_num_zones is None or expected_signature is None:
            raise ValueError("result 必须包含 available successful validation metrics")

        try:
            fixed_training_seeds = tuple(self.fixed_training_seeds)
        except TypeError as error:
            raise TypeError("fixed_training_seeds 必须是有限 iterable") from error
        if len(fixed_training_seeds) < 3:
            raise ValueError("fixed_training_seeds 必须至少包含 3 个 seeds")
        normalized_seeds = tuple(
            _normalize_nonnegative_integer(seed, "fixed_training_seeds entry")
            for seed in fixed_training_seeds
        )
        if len(normalized_seeds) != len(set(normalized_seeds)):
            raise ValueError("fixed_training_seeds 必须全部唯一")
        normalized_seeds = tuple(sorted(normalized_seeds))
        signature = _normalize_validation_trace_signature(self.validation_trace_signature)
        prediction_horizon = _normalize_positive_integer(
            self.prediction_horizon,
            "prediction_horizon",
        )
        num_zones = _normalize_positive_integer(self.num_zones, "num_zones")
        zone_schema_sha256 = _normalize_sha256(
            self.zone_schema_sha256,
            "zone_schema_sha256",
        )

        if normalized_seeds != expected_seeds:
            raise ValueError("result fixed_training_seeds 与 candidates 不一致")
        if prediction_horizon != expected_horizon:
            raise ValueError("result prediction_horizon 与 candidates 不一致")
        if num_zones != expected_num_zones:
            raise ValueError("result num_zones 与 candidates 不一致")
        if zone_schema_sha256 != expected_schema:
            raise ValueError("result zone_schema_sha256 与 candidates 不一致")
        if signature != expected_signature:
            raise ValueError("result validation_trace_signature 与 candidates 不一致")

        object.__setattr__(self, "valid_candidates", valid_candidates)
        object.__setattr__(self, "failed_candidates", failed_candidates)
        object.__setattr__(self, "fixed_training_seeds", normalized_seeds)
        object.__setattr__(self, "validation_trace_signature", signature)
        object.__setattr__(self, "prediction_horizon", prediction_horizon)
        object.__setattr__(self, "num_zones", num_zones)
        object.__setattr__(self, "zone_schema_sha256", zone_schema_sha256)


def select_learned_validation_config(
    candidates: Iterable[LearnedConfigValidationCandidate],
) -> LearnedModelSelectionResult:
    """只使用 validation records 按 frozen exact ordering 锁定 learned config。"""

    try:
        normalized = tuple(candidates)
    except TypeError as error:
        raise TypeError(
            "candidates 必须是 LearnedConfigValidationCandidate 的有限 iterable"
        ) from error
    if not normalized:
        raise ValueError("candidates 必须非空")
    if any(not isinstance(candidate, LearnedConfigValidationCandidate) for candidate in normalized):
        raise TypeError("candidates 必须全部是 LearnedConfigValidationCandidate")

    _validate_unique_candidate_identity(normalized)
    (
        fixed_training_seeds,
        prediction_horizon,
        num_zones,
        zone_schema_sha256,
        validation_trace_signature,
    ) = _validate_batch_fairness(normalized)

    valid_candidates = tuple(
        sorted(
            (
                candidate
                for candidate in normalized
                if candidate.status is LearnedConfigStatus.VALID
            ),
            key=_learned_sort_key,
        )
    )
    if not valid_candidates:
        raise PredictionModelSelectionFailure(
            "所有 learned candidate configs 均为 TRAINING_FAILURE",
        )
    if num_zones is None or validation_trace_signature is None:
        raise ValueError("VALID config 必须提供 successful validation geometry")
    failed_candidates = tuple(
        sorted(
            (
                candidate
                for candidate in normalized
                if candidate.status is LearnedConfigStatus.TRAINING_FAILURE
            ),
            key=lambda candidate: candidate.canonical_order,
        )
    )
    return LearnedModelSelectionResult(
        selected=valid_candidates[0],
        valid_candidates=valid_candidates,
        failed_candidates=failed_candidates,
        fixed_training_seeds=fixed_training_seeds,
        validation_trace_signature=validation_trace_signature,
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        zone_schema_sha256=zone_schema_sha256,
    )


__all__ = [
    "HistoryTransformKind",
    "LearnedConfigStatus",
    "LearnedConfigValidationCandidate",
    "LearnedModelSelectionResult",
    "PointObjectiveKind",
    "PredictionModelSelectionFailure",
    "TrainingSeedValidationResult",
    "select_learned_validation_config",
]
