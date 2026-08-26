"""WP-03B deterministic validation-only baseline selection。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from numbers import Integral, Real

from fura_mappo.prediction.dataset import DatasetProtocolSpec
from fura_mappo.prediction.metrics import PointMetricSummary

_HISTORY_LENGTHS = (4, 8, 16, 32)
_B3_ALPHAS = (0.25, 0.50, 0.75)
_SELECTION_FAILURE_STATUS = "PREDICTION_BASELINE_SELECTION_FAILURE"


class BaselineKind(str, Enum):
    """冻结的 B0--B5 baseline identity。"""

    B0 = "B0"
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"
    B4 = "B4"
    B5 = "B5"


_BASELINE_ORDER = (
    BaselineKind.B0,
    BaselineKind.B1,
    BaselineKind.B2,
    BaselineKind.B3,
    BaselineKind.B4,
    BaselineKind.B5,
)
_BASELINE_RANK = {baseline: rank for rank, baseline in enumerate(_BASELINE_ORDER)}
_FIXED_BASELINES = (
    BaselineKind.B0,
    BaselineKind.B1,
    BaselineKind.B4,
    BaselineKind.B5,
)

ValidationTraceSignature = tuple[tuple[str, int, int], ...]


class BaselineSelectionFailure(ValueError):
    """表示完整 deterministic baseline hierarchy 无法锁定。"""

    @property
    def status(self) -> str:
        """返回与其他 scientific failure namespace 隔离的稳定状态。"""

        return _SELECTION_FAILURE_STATUS


def _selection_failure(message: str) -> BaselineSelectionFailure:
    """构造稳定 namespace 的 hard selection failure。"""

    return BaselineSelectionFailure(message)


def _normalize_positive_integer(value: object, name: str) -> int:
    """规范化非 bool 正整数，不引入 NumPy dependency。"""

    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} 必须是整数且不能是布尔值")
    normalized = int(value)
    if normalized < 1:
        raise ValueError(f"{name} 必须大于或等于 1")
    return normalized


def _validation_trace_signature(metrics: PointMetricSummary) -> ValidationTraceSignature:
    """从 canonical trace metrics 构造 structural validation signature。"""

    return tuple(
        (
            trace.trace_id,
            trace.trace_start_step,
            trace.trace_num_steps,
        )
        for trace in metrics.trace_metrics
    )


def _normalize_validation_trace_signature(value: object) -> ValidationTraceSignature:
    """把 signature 防御性规范化为 immutable nested tuple。"""

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
        if isinstance(trace_start_step, bool) or not isinstance(trace_start_step, Integral):
            raise TypeError("validation signature trace_start_step 必须是非 bool 整数")
        if isinstance(trace_num_steps, bool) or not isinstance(trace_num_steps, Integral):
            raise TypeError("validation signature trace_num_steps 必须是非 bool 整数")
        start = int(trace_start_step)
        num_steps = int(trace_num_steps)
        if start < 0 or num_steps < 1:
            raise ValueError("validation signature trace geometry 超出合法范围")
        normalized.append((trace_id, start, num_steps))
    result = tuple(normalized)
    if result != tuple(sorted(result, key=lambda item: item[0])):
        raise ValueError("validation_trace_signature 必须按 trace_id canonical ordering")
    if len({entry[0] for entry in result}) != len(result):
        raise ValueError("validation_trace_signature 的 trace_id 必须唯一")
    return result


@dataclass(frozen=True, slots=True, eq=False)
class BaselineValidationCandidate:
    """一个 validation-only baseline variant 的 structural/audit record。"""

    baseline: BaselineKind
    protocol: DatasetProtocolSpec
    metrics: PointMetricSummary
    alpha: float | None = None

    def __post_init__(self) -> None:
        """验证 frozen grid identity 与 protocol/metrics structural binding。"""

        if not isinstance(self.baseline, BaselineKind):
            raise TypeError("baseline 必须是 BaselineKind")
        if not isinstance(self.protocol, DatasetProtocolSpec):
            raise TypeError("protocol 必须是 DatasetProtocolSpec")
        if not isinstance(self.metrics, PointMetricSummary):
            raise TypeError("metrics 必须是 PointMetricSummary")
        if self.metrics.prediction_horizon != self.protocol.prediction_horizon:
            raise _selection_failure("candidate metrics/protocol prediction_horizon 不一致")
        if self.metrics.zone_schema_sha256 != self.protocol.zone_schema_sha256:
            raise _selection_failure("candidate metrics/protocol zone_schema_sha256 不一致")
        if self.protocol.history_length not in _HISTORY_LENGTHS:
            raise _selection_failure("candidate history_length 不属于 frozen grid")

        normalized_alpha: float | None = None
        if self.baseline is BaselineKind.B3:
            if isinstance(self.alpha, bool) or not isinstance(self.alpha, Real):
                raise _selection_failure("B3 alpha 必须是 frozen grid 中的实数")
            normalized_alpha = float(self.alpha)
            if normalized_alpha not in _B3_ALPHAS:
                raise _selection_failure("B3 alpha 不属于 frozen grid")
        elif self.alpha is not None:
            raise _selection_failure("只有 B3 candidate 可以提供 alpha")

        object.__setattr__(self, "alpha", normalized_alpha)

    @property
    def primary_rmse(self) -> float:
        """直接返回 Slice 3 metrics 的唯一 authoritative Primary RMSE。"""

        return self.metrics.primary_rmse


def _candidate_sort_key(
    candidate: BaselineValidationCandidate,
) -> tuple[int, int, float]:
    """返回只用于 canonical input normalization 的 deterministic key。"""

    alpha = candidate.alpha if candidate.alpha is not None else -1.0
    return (
        _BASELINE_RANK[candidate.baseline],
        candidate.protocol.history_length,
        alpha,
    )


def _validate_complete_grid(
    candidates: tuple[BaselineValidationCandidate, ...],
) -> dict[BaselineKind, tuple[BaselineValidationCandidate, ...]]:
    """验证精确 20-candidate B0--B5 hierarchy，不做 deduplication。"""

    grouped: dict[BaselineKind, list[BaselineValidationCandidate]] = {
        baseline: [] for baseline in _BASELINE_ORDER
    }
    for candidate in candidates:
        grouped[candidate.baseline].append(candidate)

    for baseline in _FIXED_BASELINES:
        if len(grouped[baseline]) != 1:
            raise _selection_failure(f"{baseline.value} 必须精确包含 1 个 candidate")

    b2_candidates = grouped[BaselineKind.B2]
    b2_lengths = [candidate.protocol.history_length for candidate in b2_candidates]
    if len(b2_lengths) != len(set(b2_lengths)):
        raise _selection_failure("B2 candidate history_length variant 重复")
    if set(b2_lengths) != set(_HISTORY_LENGTHS):
        raise _selection_failure("B2 必须精确覆盖 frozen history_length grid")

    b3_candidates = grouped[BaselineKind.B3]
    b3_variants = [
        (candidate.protocol.history_length, candidate.alpha) for candidate in b3_candidates
    ]
    if len(b3_variants) != len(set(b3_variants)):
        raise _selection_failure("B3 (history_length, alpha) variant 重复")
    expected_b3_variants = {
        (history_length, alpha) for history_length in _HISTORY_LENGTHS for alpha in _B3_ALPHAS
    }
    if set(b3_variants) != expected_b3_variants:
        raise _selection_failure("B3 必须精确覆盖 frozen Cartesian grid")
    if len(candidates) != 20:
        raise _selection_failure("完整 baseline selection 必须精确包含 20 个 candidates")

    return {
        baseline: tuple(sorted(grouped[baseline], key=_candidate_sort_key))
        for baseline in _BASELINE_ORDER
    }


def _validate_batch_fairness(
    candidates: tuple[BaselineValidationCandidate, ...],
) -> tuple[int, int, str, ValidationTraceSignature]:
    """验证所有 candidates 的 P/Z/schema 与 validation trace geometry 完全一致。"""

    first_metrics = candidates[0].metrics
    prediction_horizon = first_metrics.prediction_horizon
    num_zones = first_metrics.num_zones
    zone_hash = first_metrics.zone_schema_sha256
    signature = _validation_trace_signature(first_metrics)

    for candidate in candidates[1:]:
        metrics = candidate.metrics
        if metrics.prediction_horizon != prediction_horizon:
            raise _selection_failure("candidates 混合了 prediction_horizon")
        if metrics.num_zones != num_zones:
            raise _selection_failure("candidates 混合了 num_zones")
        if metrics.zone_schema_sha256 != zone_hash:
            raise _selection_failure("candidates 混合了 zone_schema_sha256")
        if _validation_trace_signature(metrics) != signature:
            raise _selection_failure("candidates 的 validation trace signature 不一致")
    return prediction_horizon, num_zones, zone_hash, signature


@dataclass(frozen=True, slots=True, eq=False)
class BaselineSelectionResult:
    """完整 B0--B5 hierarchy 的 immutable validation-only locking result。"""

    locked_variants: tuple[BaselineValidationCandidate, ...]
    selected: BaselineValidationCandidate
    validation_trace_signature: ValidationTraceSignature
    prediction_horizon: int
    num_zones: int
    zone_schema_sha256: str

    def __post_init__(self) -> None:
        """验证 canonical six-variant result、fairness binding 与 Step-2 winner。"""

        try:
            locked_variants = tuple(self.locked_variants)
        except TypeError as error:
            raise TypeError("locked_variants 必须是有限 iterable") from error
        if len(locked_variants) != len(_BASELINE_ORDER):
            raise ValueError("locked_variants 必须精确包含 6 个 candidates")
        if any(
            not isinstance(candidate, BaselineValidationCandidate) for candidate in locked_variants
        ):
            raise TypeError("locked_variants 必须全部是 BaselineValidationCandidate")
        if tuple(candidate.baseline for candidate in locked_variants) != _BASELINE_ORDER:
            raise ValueError("locked_variants 必须按 B0--B5 canonical order 完整排列")
        if not isinstance(self.selected, BaselineValidationCandidate):
            raise TypeError("selected 必须是 BaselineValidationCandidate")
        if not any(self.selected is candidate for candidate in locked_variants):
            raise ValueError("selected 必须属于 locked_variants")

        signature = _normalize_validation_trace_signature(self.validation_trace_signature)
        prediction_horizon = _normalize_positive_integer(
            self.prediction_horizon,
            "prediction_horizon",
        )
        num_zones = _normalize_positive_integer(self.num_zones, "num_zones")
        if not isinstance(self.zone_schema_sha256, str):
            raise TypeError("zone_schema_sha256 必须是字符串")

        for candidate in locked_variants:
            metrics = candidate.metrics
            if metrics.prediction_horizon != prediction_horizon:
                raise ValueError("locked candidate prediction_horizon 与 result 不一致")
            if metrics.num_zones != num_zones:
                raise ValueError("locked candidate num_zones 与 result 不一致")
            if metrics.zone_schema_sha256 != self.zone_schema_sha256:
                raise ValueError("locked candidate zone_schema_sha256 与 result 不一致")
            if _validation_trace_signature(metrics) != signature:
                raise ValueError("locked candidate validation signature 与 result 不一致")

        expected_selected = min(
            locked_variants,
            key=lambda candidate: (
                candidate.primary_rmse,
                _BASELINE_RANK[candidate.baseline],
            ),
        )
        if self.selected is not expected_selected:
            raise ValueError("selected 不是 locked_variants 的 exact Step-2 B*")

        object.__setattr__(self, "locked_variants", locked_variants)
        object.__setattr__(self, "validation_trace_signature", signature)
        object.__setattr__(self, "prediction_horizon", prediction_horizon)
        object.__setattr__(self, "num_zones", num_zones)

    @property
    def selected_kind(self) -> BaselineKind:
        """返回最终 locked B* identity。"""

        return self.selected.baseline

    @property
    def selected_primary_rmse(self) -> float:
        """返回最终 B* 的 validation Primary RMSE。"""

        return self.selected.primary_rmse


def select_validation_baselines(
    candidates: Iterable[BaselineValidationCandidate],
) -> BaselineSelectionResult:
    """只使用 validation metrics 执行 frozen B2、B3 与两阶段 B* locking。"""

    try:
        normalized = tuple(candidates)
    except TypeError as error:
        raise TypeError("candidates 必须是 BaselineValidationCandidate 的有限 iterable") from error
    if any(not isinstance(candidate, BaselineValidationCandidate) for candidate in normalized):
        raise TypeError("candidates 必须全部是 BaselineValidationCandidate")

    ordered = tuple(sorted(normalized, key=_candidate_sort_key))
    grouped = _validate_complete_grid(ordered)
    prediction_horizon, num_zones, zone_hash, signature = _validate_batch_fairness(ordered)

    locked_b2 = min(
        grouped[BaselineKind.B2],
        key=lambda candidate: (
            candidate.primary_rmse,
            candidate.protocol.history_length,
        ),
    )
    locked_b3 = min(
        grouped[BaselineKind.B3],
        key=lambda candidate: (
            candidate.primary_rmse,
            candidate.protocol.history_length,
            candidate.alpha,
        ),
    )
    locked_variants = (
        grouped[BaselineKind.B0][0],
        grouped[BaselineKind.B1][0],
        locked_b2,
        locked_b3,
        grouped[BaselineKind.B4][0],
        grouped[BaselineKind.B5][0],
    )
    selected = min(
        locked_variants,
        key=lambda candidate: (
            candidate.primary_rmse,
            _BASELINE_RANK[candidate.baseline],
        ),
    )
    return BaselineSelectionResult(
        locked_variants=locked_variants,
        selected=selected,
        validation_trace_signature=signature,
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        zone_schema_sha256=zone_hash,
    )


__all__ = [
    "BaselineKind",
    "BaselineSelectionFailure",
    "BaselineSelectionResult",
    "BaselineValidationCandidate",
    "select_validation_baselines",
]
