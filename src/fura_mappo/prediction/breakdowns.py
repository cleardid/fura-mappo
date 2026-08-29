"""Official mandatory breakdown 的 deterministic descriptive diagnostics。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from math import isfinite, sqrt
from numbers import Integral, Real

import numpy as np

from fura_mappo.prediction.dataset import SplitLabel
from fura_mappo.prediction.governance import (
    PredictionOODKind,
    PreTestFreeze,
    TraceOODAssignment,
)
from fura_mappo.prediction.metrics import TracePointMetrics
from fura_mappo.prediction.official_metrics import (
    OfficialPredictorSplitMetrics,
    OfficialSealedPointMetrics,
)
from fura_mappo.prediction.selection import BaselineKind

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_BASELINE_ORDER = tuple(BaselineKind)
_OOD_KIND_ORDER = (
    PredictionOODKind.ID,
    PredictionOODKind.NEAR_OOD,
    PredictionOODKind.STRUCTURAL_OOD,
)
_OOD_KIND_RANK = {kind: rank for rank, kind in enumerate(_OOD_KIND_ORDER)}


class TargetValueStratum(str, Enum):
    """Target count 的精确 descriptive partition。"""

    ZERO = "ZERO"
    POSITIVE = "POSITIVE"


_STRATUM_ORDER = (TargetValueStratum.ZERO, TargetValueStratum.POSITIVE)


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """规范化 non-bool nonnegative integer。"""

    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} 必须是非 bool 整数")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} 必须大于或等于 0")
    return normalized


def _normalize_positive_integer(value: object, name: str) -> int:
    """规范化 non-bool positive integer。"""

    normalized = _normalize_nonnegative_integer(value, name)
    if normalized < 1:
        raise ValueError(f"{name} 必须大于或等于 1")
    return normalized


def _normalize_finite_metric(
    value: object,
    name: str,
    *,
    nonnegative: bool,
) -> float:
    """规范化 finite scalar metric。"""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} 必须是实数")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{name} 必须有限")
    if nonnegative and normalized < 0.0:
        raise ValueError(f"{name} 必须非负")
    return normalized


def _materialize_tuple(value: object, name: str) -> tuple[object, ...]:
    """防御性物化 finite iterable。"""

    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} 必须是有限 iterable")
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} 必须是有限 iterable") from error


def _normalize_trace_ids(value: object, name: str) -> tuple[str, ...]:
    """规范化 ordered trace identity tuple。"""

    trace_ids = _materialize_tuple(value, name)
    if any(
        not isinstance(trace_id, str) or _SAFE_ID_PATTERN.fullmatch(trace_id) is None
        for trace_id in trace_ids
    ):
        raise ValueError(f"{name} 必须全部是安全 trace IDs")
    normalized = tuple(trace_ids)  # type: ignore[arg-type]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} 不得重复 trace ID")
    return normalized


@dataclass(frozen=True, slots=True)
class TargetStratumCellMetrics:
    """一个 trace/lead/zone/stratum local cell 的 descriptive statistics。"""

    trace_id: str
    lead: int
    zone_id: int
    stratum: TargetValueStratum
    count: int
    mse: float | None
    mae: float | None
    bias: float | None

    def __post_init__(self) -> None:
        """验证 complete-row empty semantics 与 finite local metrics。"""

        if not isinstance(self.trace_id, str) or _SAFE_ID_PATTERN.fullmatch(self.trace_id) is None:
            raise ValueError("trace_id 必须是安全的非空标识符")
        lead = _normalize_positive_integer(self.lead, "lead")
        zone_id = _normalize_nonnegative_integer(self.zone_id, "zone_id")
        count = _normalize_nonnegative_integer(self.count, "count")
        if not isinstance(self.stratum, TargetValueStratum):
            raise TypeError("stratum 必须是 TargetValueStratum")
        if count == 0:
            if self.mse is not None or self.mae is not None or self.bias is not None:
                raise ValueError("count == 0 时 mse/mae/bias 必须全部为 None")
            mse = mae = bias = None
        else:
            if self.mse is None or self.mae is None or self.bias is None:
                raise ValueError("count > 0 时 mse/mae/bias 必须全部存在")
            mse = _normalize_finite_metric(self.mse, "mse", nonnegative=True)
            mae = _normalize_finite_metric(self.mae, "mae", nonnegative=True)
            bias = _normalize_finite_metric(self.bias, "bias", nonnegative=False)
        object.__setattr__(self, "lead", lead)
        object.__setattr__(self, "zone_id", zone_id)
        object.__setattr__(self, "count", count)
        object.__setattr__(self, "mse", mse)
        object.__setattr__(self, "mae", mae)
        object.__setattr__(self, "bias", bias)

    @property
    def rmse(self) -> float | None:
        """返回 local cell RMSE；empty cell 精确返回 None。"""

        return None if self.mse is None else sqrt(self.mse)


def _normalize_group_payload(
    *,
    trace_ids: object,
    trace_metrics: object,
    target_stratum_rows: object,
    name: str,
) -> tuple[
    tuple[str, ...],
    tuple[TracePointMetrics, ...],
    tuple[TargetStratumCellMetrics, ...],
]:
    """验证一个 descriptive group 的 ordered membership payload。"""

    normalized_ids = _normalize_trace_ids(trace_ids, f"{name}.trace_ids")
    metric_values = _materialize_tuple(trace_metrics, f"{name}.trace_metrics")
    if any(not isinstance(metric, TracePointMetrics) for metric in metric_values):
        raise TypeError(f"{name}.trace_metrics 必须全部是 TracePointMetrics")
    metrics = tuple(metric_values)  # type: ignore[arg-type]
    if tuple(metric.trace_id for metric in metrics) != normalized_ids:
        raise ValueError(f"{name}.trace_metrics 必须精确对应 trace_ids")
    row_values = _materialize_tuple(target_stratum_rows, f"{name}.target_stratum_rows")
    if any(not isinstance(row, TargetStratumCellMetrics) for row in row_values):
        raise TypeError(f"{name}.target_stratum_rows 类型错误")
    rows = tuple(row_values)  # type: ignore[arg-type]
    membership = set(normalized_ids)
    if any(row.trace_id not in membership for row in rows):
        raise ValueError(f"{name}.target_stratum_rows 引用了非 member trace")
    row_keys = tuple((row.trace_id, row.lead, row.zone_id, row.stratum) for row in rows)
    if len(row_keys) != len(set(row_keys)):
        raise ValueError(f"{name}.target_stratum_rows 不得重复 cell")
    trace_rank = {trace_id: rank for rank, trace_id in enumerate(normalized_ids)}
    actual_order = tuple(
        (trace_rank[row.trace_id], row.lead, row.zone_id, _STRATUM_ORDER.index(row.stratum))
        for row in rows
    )
    if actual_order != tuple(sorted(actual_order)):
        raise ValueError(f"{name}.target_stratum_rows ordering 非 canonical")
    return normalized_ids, metrics, rows


@dataclass(frozen=True, slots=True)
class ConditionTraceBreakdown:
    """一个 frozen condition 的 exact member diagnostic payload。"""

    condition_sha256: str
    trace_ids: tuple[str, ...]
    trace_metrics: tuple[TracePointMetrics, ...]
    target_stratum_rows: tuple[TargetStratumCellMetrics, ...]

    def __post_init__(self) -> None:
        """验证 condition identity 与 group payload。"""

        if (
            not isinstance(self.condition_sha256, str)
            or _SHA256_PATTERN.fullmatch(self.condition_sha256) is None
        ):
            raise ValueError("condition_sha256 必须是 64 位小写 SHA-256")
        trace_ids, trace_metrics, rows = _normalize_group_payload(
            trace_ids=self.trace_ids,
            trace_metrics=self.trace_metrics,
            target_stratum_rows=self.target_stratum_rows,
            name="condition",
        )
        if not trace_ids:
            raise ValueError("condition group 必须至少包含一条 trace")
        object.__setattr__(self, "trace_ids", trace_ids)
        object.__setattr__(self, "trace_metrics", trace_metrics)
        object.__setattr__(self, "target_stratum_rows", rows)


@dataclass(frozen=True, slots=True)
class OODKindTraceBreakdown:
    """一个 frozen coarse OOD kind 的 exact member diagnostic payload。"""

    kind: PredictionOODKind
    trace_ids: tuple[str, ...]
    trace_metrics: tuple[TracePointMetrics, ...]
    target_stratum_rows: tuple[TargetStratumCellMetrics, ...]

    def __post_init__(self) -> None:
        """验证 coarse kind 与允许为空的 group payload。"""

        if not isinstance(self.kind, PredictionOODKind):
            raise TypeError("kind 必须是 PredictionOODKind")
        trace_ids, trace_metrics, rows = _normalize_group_payload(
            trace_ids=self.trace_ids,
            trace_metrics=self.trace_metrics,
            target_stratum_rows=self.target_stratum_rows,
            name="ood_kind",
        )
        object.__setattr__(self, "trace_ids", trace_ids)
        object.__setattr__(self, "trace_metrics", trace_metrics)
        object.__setattr__(self, "target_stratum_rows", rows)


@dataclass(frozen=True, slots=True)
class OODCellTraceBreakdown:
    """一个 frozen (kind, cell_id) 的 exact member diagnostic payload。"""

    kind: PredictionOODKind
    cell_id: str
    trace_ids: tuple[str, ...]
    trace_metrics: tuple[TracePointMetrics, ...]
    target_stratum_rows: tuple[TargetStratumCellMetrics, ...]

    def __post_init__(self) -> None:
        """验证 OOD cell identity 与 nonempty group payload。"""

        if not isinstance(self.kind, PredictionOODKind):
            raise TypeError("kind 必须是 PredictionOODKind")
        if not isinstance(self.cell_id, str) or _SAFE_ID_PATTERN.fullmatch(self.cell_id) is None:
            raise ValueError("cell_id 必须是安全的非空标识符")
        trace_ids, trace_metrics, rows = _normalize_group_payload(
            trace_ids=self.trace_ids,
            trace_metrics=self.trace_metrics,
            target_stratum_rows=self.target_stratum_rows,
            name="ood_cell",
        )
        if not trace_ids:
            raise ValueError("OOD cell group 必须至少包含一条 trace")
        object.__setattr__(self, "trace_ids", trace_ids)
        object.__setattr__(self, "trace_metrics", trace_metrics)
        object.__setattr__(self, "target_stratum_rows", rows)


def _row_key(row: TargetStratumCellMetrics) -> tuple[str, int, int, TargetValueStratum]:
    """返回 complete-grid row identity。"""

    return (row.trace_id, row.lead, row.zone_id, row.stratum)


def _validate_partition_groups(
    *,
    groups: tuple[
        ConditionTraceBreakdown | OODKindTraceBreakdown | OODCellTraceBreakdown,
        ...,
    ],
    frozen_trace_ids: tuple[str, ...],
    trace_metric_by_id: dict[str, TracePointMetrics],
    all_rows: tuple[TargetStratumCellMetrics, ...],
    name: str,
) -> None:
    """验证 groups 对 frozen traces 的 exact partition 与 object binding。"""

    memberships = tuple(trace_id for group in groups for trace_id in group.trace_ids)
    if len(memberships) != len(set(memberships)) or set(memberships) != set(frozen_trace_ids):
        raise ValueError(f"{name} groups 必须精确 partition frozen traces")
    for group in groups:
        member_set = set(group.trace_ids)
        expected_ids = tuple(trace_id for trace_id in frozen_trace_ids if trace_id in member_set)
        if group.trace_ids != expected_ids:
            raise ValueError(f"{name} group 内 trace order 必须保持 frozen split order")
        expected_metrics = tuple(trace_metric_by_id[trace_id] for trace_id in expected_ids)
        if len(group.trace_metrics) != len(expected_metrics) or any(
            actual is not expected
            for actual, expected in zip(group.trace_metrics, expected_metrics, strict=True)
        ):
            raise ValueError(f"{name} group trace_metrics 必须绑定 existing exact objects")
        expected_rows = tuple(row for row in all_rows if row.trace_id in member_set)
        if len(group.target_stratum_rows) != len(expected_rows) or any(
            actual is not expected
            for actual, expected in zip(
                group.target_stratum_rows,
                expected_rows,
                strict=True,
            )
        ):
            raise ValueError(f"{name} group rows 必须绑定 exact member rows")


@dataclass(frozen=True, slots=True)
class OfficialPredictorSplitBreakdown:
    """一个 existing official split metric result 的 complete descriptive partitions。"""

    metrics: OfficialPredictorSplitMetrics
    target_strata: tuple[TargetStratumCellMetrics, ...]
    conditions: tuple[ConditionTraceBreakdown, ...]
    ood_kinds: tuple[OODKindTraceBreakdown, ...]
    ood_cells: tuple[OODCellTraceBreakdown, ...]

    def __post_init__(self) -> None:
        """验证 complete row grid、canonical groups 与 exact object partitions。"""

        if not isinstance(self.metrics, OfficialPredictorSplitMetrics):
            raise TypeError("metrics 必须是 OfficialPredictorSplitMetrics")
        row_values = _materialize_tuple(self.target_strata, "target_strata")
        if any(not isinstance(row, TargetStratumCellMetrics) for row in row_values):
            raise TypeError("target_strata 必须全部是 TargetStratumCellMetrics")
        rows = tuple(row_values)  # type: ignore[arg-type]
        forecasts = self.metrics.forecasts
        expected_keys = tuple(
            (trace_id, lead, zone_id, stratum)
            for trace_id in forecasts.trace_ids
            for lead in range(1, forecasts.prediction_horizon + 1)
            for zone_id in range(forecasts.num_zones)
            for stratum in _STRATUM_ORDER
        )
        if tuple(_row_key(row) for row in rows) != expected_keys:
            raise ValueError("target_strata 必须精确覆盖 canonical N*P*Z*2 row grid")

        condition_values = _materialize_tuple(self.conditions, "conditions")
        kind_values = _materialize_tuple(self.ood_kinds, "ood_kinds")
        cell_values = _materialize_tuple(self.ood_cells, "ood_cells")
        if any(not isinstance(group, ConditionTraceBreakdown) for group in condition_values):
            raise TypeError("conditions 类型错误")
        if any(not isinstance(group, OODKindTraceBreakdown) for group in kind_values):
            raise TypeError("ood_kinds 类型错误")
        if any(not isinstance(group, OODCellTraceBreakdown) for group in cell_values):
            raise TypeError("ood_cells 类型错误")
        conditions = tuple(condition_values)  # type: ignore[arg-type]
        ood_kinds = tuple(kind_values)  # type: ignore[arg-type]
        ood_cells = tuple(cell_values)  # type: ignore[arg-type]
        condition_ids = tuple(group.condition_sha256 for group in conditions)
        if not conditions or condition_ids != tuple(sorted(condition_ids)):
            raise ValueError("conditions 必须按 condition SHA lexical ascending")
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError("conditions 不得重复 identity")
        if tuple(group.kind for group in ood_kinds) != _OOD_KIND_ORDER:
            raise ValueError("ood_kinds 必须精确包含 canonical three coarse groups")
        cell_keys = tuple((group.kind, group.cell_id) for group in ood_cells)
        expected_cell_order = tuple(
            sorted(cell_keys, key=lambda item: (_OOD_KIND_RANK[item[0]], item[1]))
        )
        if cell_keys != expected_cell_order or len(cell_keys) != len(set(cell_keys)):
            raise ValueError("ood_cells 必须按 kind rank/cell_id canonical ordering")

        trace_metric_by_id = {
            metric.trace_id: metric for metric in self.metrics.metrics.trace_metrics
        }
        _validate_partition_groups(
            groups=conditions,
            frozen_trace_ids=forecasts.trace_ids,
            trace_metric_by_id=trace_metric_by_id,
            all_rows=rows,
            name="condition",
        )
        _validate_partition_groups(
            groups=ood_kinds,
            frozen_trace_ids=forecasts.trace_ids,
            trace_metric_by_id=trace_metric_by_id,
            all_rows=rows,
            name="ood kind",
        )
        _validate_partition_groups(
            groups=ood_cells,
            frozen_trace_ids=forecasts.trace_ids,
            trace_metric_by_id=trace_metric_by_id,
            all_rows=rows,
            name="OOD cell",
        )
        object.__setattr__(self, "target_strata", rows)
        object.__setattr__(self, "conditions", conditions)
        object.__setattr__(self, "ood_kinds", ood_kinds)
        object.__setattr__(self, "ood_cells", ood_cells)


def _compute_target_strata(
    metrics: OfficialPredictorSplitMetrics,
) -> tuple[TargetStratumCellMetrics, ...]:
    """计算每个 trace/lead/zone/stratum local descriptive cell。"""

    forecasts = metrics.forecasts
    records_by_trace = {trace_id: [] for trace_id in forecasts.trace_ids}
    for record in forecasts.records:
        trace_id = record.point_record.trace_id
        if trace_id not in records_by_trace:
            raise ValueError("forecast record trace 不属于 frozen split")
        records_by_trace[trace_id].append(record)

    rows: list[TargetStratumCellMetrics] = []
    for trace_id in forecasts.trace_ids:
        records = records_by_trace[trace_id]
        if not records:
            raise ValueError("每条 frozen trace 必须保留 records")
        for lead_index in range(forecasts.prediction_horizon):
            for zone_id in range(forecasts.num_zones):
                residuals_by_stratum: dict[TargetValueStratum, list[float]] = {
                    TargetValueStratum.ZERO: [],
                    TargetValueStratum.POSITIVE: [],
                }
                for record in records:
                    point_record = record.point_record
                    target = point_record.sample.target
                    if not bool(target.valid_mask[lead_index]):
                        continue
                    target_count = int(target.counts[lead_index, zone_id])
                    if target_count < 0:
                        raise ValueError("target count 必须非负")
                    stratum = (
                        TargetValueStratum.ZERO
                        if target_count == 0
                        else TargetValueStratum.POSITIVE
                    )
                    residual = np.float64(
                        point_record.forecast.mean[lead_index, zone_id]
                    ) - np.float64(target_count)
                    if not np.isfinite(residual):
                        raise ValueError("target-stratum residual 必须 finite")
                    residuals_by_stratum[stratum].append(float(residual))
                for stratum in _STRATUM_ORDER:
                    residual_values = residuals_by_stratum[stratum]
                    if not residual_values:
                        rows.append(
                            TargetStratumCellMetrics(
                                trace_id,
                                lead_index + 1,
                                zone_id,
                                stratum,
                                0,
                                None,
                                None,
                                None,
                            )
                        )
                        continue
                    residual_array = np.asarray(residual_values, dtype=np.float64)
                    with np.errstate(over="ignore", invalid="ignore"):
                        squared = np.square(residual_array)
                    if not np.all(np.isfinite(squared)):
                        raise ValueError("target-stratum squared residual 必须 finite")
                    rows.append(
                        TargetStratumCellMetrics(
                            trace_id,
                            lead_index + 1,
                            zone_id,
                            stratum,
                            residual_array.size,
                            np.mean(squared, dtype=np.float64),
                            np.mean(np.abs(residual_array), dtype=np.float64),
                            np.mean(residual_array, dtype=np.float64),
                        )
                    )
    return tuple(rows)


def _trace_metric_by_id(
    metrics: OfficialPredictorSplitMetrics,
) -> dict[str, TracePointMetrics]:
    """返回 existing trace metric object lookup。"""

    result = {metric.trace_id: metric for metric in metrics.metrics.trace_metrics}
    if set(result) != set(metrics.forecasts.trace_ids):
        raise ValueError("existing trace metrics 未精确覆盖 frozen traces")
    return result


def _group_rows(
    rows: tuple[TargetStratumCellMetrics, ...],
    trace_ids: tuple[str, ...],
) -> tuple[TargetStratumCellMetrics, ...]:
    """按 frozen member trace IDs filter exact row objects。"""

    membership = set(trace_ids)
    return tuple(row for row in rows if row.trace_id in membership)


def _compute_split_breakdown(
    *,
    metrics: OfficialPredictorSplitMetrics,
    condition_by_trace: dict[str, str],
    assignment_by_trace: dict[str, TraceOODAssignment],
) -> OfficialPredictorSplitBreakdown:
    """由 frozen manifest/taxonomy 构造一个 predictor/split 的 partitions。"""

    trace_ids = metrics.forecasts.trace_ids
    rows = _compute_target_strata(metrics)
    trace_metric_by_id = _trace_metric_by_id(metrics)

    conditions = tuple(
        ConditionTraceBreakdown(
            condition_sha256,
            tuple(
                trace_id
                for trace_id in trace_ids
                if condition_by_trace[trace_id] == condition_sha256
            ),
            tuple(
                trace_metric_by_id[trace_id]
                for trace_id in trace_ids
                if condition_by_trace[trace_id] == condition_sha256
            ),
            _group_rows(
                rows,
                tuple(
                    trace_id
                    for trace_id in trace_ids
                    if condition_by_trace[trace_id] == condition_sha256
                ),
            ),
        )
        for condition_sha256 in sorted({condition_by_trace[trace_id] for trace_id in trace_ids})
    )
    ood_kinds = tuple(
        OODKindTraceBreakdown(
            kind,
            tuple(trace_id for trace_id in trace_ids if assignment_by_trace[trace_id].kind is kind),
            tuple(
                trace_metric_by_id[trace_id]
                for trace_id in trace_ids
                if assignment_by_trace[trace_id].kind is kind
            ),
            _group_rows(
                rows,
                tuple(
                    trace_id for trace_id in trace_ids if assignment_by_trace[trace_id].kind is kind
                ),
            ),
        )
        for kind in _OOD_KIND_ORDER
    )
    cell_keys = sorted(
        {
            (assignment_by_trace[trace_id].kind, assignment_by_trace[trace_id].cell_id)
            for trace_id in trace_ids
        },
        key=lambda item: (_OOD_KIND_RANK[item[0]], item[1]),
    )
    ood_cells = tuple(
        OODCellTraceBreakdown(
            kind,
            cell_id,
            tuple(
                trace_id
                for trace_id in trace_ids
                if (
                    assignment_by_trace[trace_id].kind is kind
                    and assignment_by_trace[trace_id].cell_id == cell_id
                )
            ),
            tuple(
                trace_metric_by_id[trace_id]
                for trace_id in trace_ids
                if (
                    assignment_by_trace[trace_id].kind is kind
                    and assignment_by_trace[trace_id].cell_id == cell_id
                )
            ),
            _group_rows(
                rows,
                tuple(
                    trace_id
                    for trace_id in trace_ids
                    if (
                        assignment_by_trace[trace_id].kind is kind
                        and assignment_by_trace[trace_id].cell_id == cell_id
                    )
                ),
            ),
        )
        for kind, cell_id in cell_keys
    )
    return OfficialPredictorSplitBreakdown(metrics, rows, conditions, ood_kinds, ood_cells)


def _manifest_conditions(
    pretest_freeze: PreTestFreeze,
    split: SplitLabel,
    trace_ids: tuple[str, ...],
) -> dict[str, str]:
    """从 exact Layer-A manifest 派生 requested split condition identities。"""

    result = {
        entry.source.trace_id: entry.source.condition_sha256
        for entry in pretest_freeze.pretraining_freeze.split_manifest.entries
        if entry.split is split
    }
    if set(result) != set(trace_ids) or len(result) != len(trace_ids):
        raise ValueError("Layer-A manifest condition membership 与 frozen split 不一致")
    return result


def _validate_ood_assignments(
    pretest_freeze: PreTestFreeze,
) -> dict[str, TraceOODAssignment]:
    """验证 final taxonomy 对两个 frozen test splits 的 exact one-of coverage。"""

    assignments = tuple(pretest_freeze.final_ood_assignments)
    if any(not isinstance(assignment, TraceOODAssignment) for assignment in assignments):
        raise TypeError("final_ood_assignments 类型错误")
    trace_ids = tuple(assignment.trace_id for assignment in assignments)
    if len(trace_ids) != len(set(trace_ids)):
        raise ValueError("final_ood_assignments 不得重复 trace")
    expected = (*pretest_freeze.test_id_trace_ids, *pretest_freeze.test_ood_trace_ids)
    if set(trace_ids) != set(expected) or len(trace_ids) != len(expected):
        raise ValueError("final_ood_assignments 必须精确覆盖 frozen test traces")
    result = {assignment.trace_id: assignment for assignment in assignments}
    if any(
        result[trace_id].kind is not PredictionOODKind.ID
        for trace_id in pretest_freeze.test_id_trace_ids
    ):
        raise ValueError("TEST_ID trace 必须精确分类为 ID")
    if any(
        result[trace_id].kind not in (PredictionOODKind.NEAR_OOD, PredictionOODKind.STRUCTURAL_OOD)
        for trace_id in pretest_freeze.test_ood_trace_ids
    ):
        raise ValueError("TEST_OOD trace 必须分类为 NEAR_OOD 或 STRUCTURAL_OOD")
    return result


def _normalize_breakdown_group(
    value: object,
    name: str,
) -> tuple[OfficialPredictorSplitBreakdown, ...]:
    """规范化 sealed breakdown group。"""

    values = _materialize_tuple(value, name)
    if any(not isinstance(item, OfficialPredictorSplitBreakdown) for item in values):
        raise TypeError(f"{name} 类型错误")
    return tuple(values)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class OfficialSealedMandatoryBreakdowns:
    """四组 complete mandatory descriptive breakdowns，不表示 scientific success。"""

    test_id_baselines: tuple[OfficialPredictorSplitBreakdown, ...]
    test_id_learned: tuple[OfficialPredictorSplitBreakdown, ...]
    test_ood_baselines: tuple[OfficialPredictorSplitBreakdown, ...]
    test_ood_learned: tuple[OfficialPredictorSplitBreakdown, ...]

    def __post_init__(self) -> None:
        """验证 four-group split、baseline 与 per-seed canonical completeness。"""

        id_baselines = _normalize_breakdown_group(self.test_id_baselines, "test_id_baselines")
        id_learned = _normalize_breakdown_group(self.test_id_learned, "test_id_learned")
        ood_baselines = _normalize_breakdown_group(
            self.test_ood_baselines,
            "test_ood_baselines",
        )
        ood_learned = _normalize_breakdown_group(self.test_ood_learned, "test_ood_learned")
        for group, split in (
            (id_baselines, SplitLabel.TEST_ID),
            (id_learned, SplitLabel.TEST_ID),
            (ood_baselines, SplitLabel.TEST_OOD),
            (ood_learned, SplitLabel.TEST_OOD),
        ):
            if any(item.metrics.forecasts.split is not split for item in group):
                raise ValueError("sealed breakdown group split 不一致")
        if tuple(item.metrics.forecasts.baseline for item in id_baselines) != _BASELINE_ORDER:
            raise ValueError("TEST_ID baseline breakdowns 必须按 B0--B5")
        if tuple(item.metrics.forecasts.baseline for item in ood_baselines) != _BASELINE_ORDER:
            raise ValueError("TEST_OOD baseline breakdowns 必须按 B0--B5")
        if any(item.metrics.forecasts.baseline is not None for item in (*id_learned, *ood_learned)):
            raise ValueError("learned breakdowns 不得包含 baseline identity")
        id_seeds = tuple(item.metrics.forecasts.training_seed for item in id_learned)
        ood_seeds = tuple(item.metrics.forecasts.training_seed for item in ood_learned)
        if any(seed is None for seed in (*id_seeds, *ood_seeds)):
            raise ValueError("learned breakdowns 必须保留 training_seed")
        if (
            not id_seeds
            or id_seeds != tuple(sorted(id_seeds))
            or len(id_seeds) != len(set(id_seeds))
        ):
            raise ValueError("TEST_ID learned breakdowns 必须按 unique ascending seed order")
        if ood_seeds != id_seeds:
            raise ValueError("TEST_OOD learned breakdowns 必须保留同一 frozen seed order")
        object.__setattr__(self, "test_id_baselines", id_baselines)
        object.__setattr__(self, "test_id_learned", id_learned)
        object.__setattr__(self, "test_ood_baselines", ood_baselines)
        object.__setattr__(self, "test_ood_learned", ood_learned)


def compute_official_mandatory_breakdowns(
    *,
    pretest_freeze: PreTestFreeze,
    sealed_metrics: OfficialSealedPointMetrics,
) -> OfficialSealedMandatoryBreakdowns:
    """从 Slice 15 metrics 派生 complete descriptive partitions。

    本函数不是最终 official trust root：structural direct construction 的
    :class:`OfficialSealedPointMetrics` 不能单独证明 artifact/target provenance。最终 scientific
    path 必须由 Slice 17 top-level orchestrator 从 raw safe-loaded artifacts 开始，依次调用 Slice 14
    与 Slice 15 authoritative factories，并立即调用本函数，形成连续 final numerical chain；不得从
    arbitrary caller-constructed sealed metrics 直接发布 scientific result。
    """

    if not isinstance(pretest_freeze, PreTestFreeze):
        raise TypeError("pretest_freeze 必须是 PreTestFreeze")
    if not isinstance(sealed_metrics, OfficialSealedPointMetrics):
        raise TypeError("sealed_metrics 必须是 OfficialSealedPointMetrics")
    if sealed_metrics.pretraining_freeze_sha256 != pretest_freeze.pretraining_freeze_sha256:
        raise ValueError("sealed metrics Layer-A SHA 与 PreTestFreeze 不一致")
    if sealed_metrics.pretest_freeze_sha256 != pretest_freeze.sha256:
        raise ValueError("sealed metrics PreTestFreeze SHA 不一致")

    expected_seeds = pretest_freeze.pretraining_freeze.fixed_training_seeds
    groups = (
        (
            sealed_metrics.test_id_baselines,
            SplitLabel.TEST_ID,
            pretest_freeze.test_id_trace_ids,
            _BASELINE_ORDER,
            None,
        ),
        (
            sealed_metrics.test_id_learned,
            SplitLabel.TEST_ID,
            pretest_freeze.test_id_trace_ids,
            None,
            expected_seeds,
        ),
        (
            sealed_metrics.test_ood_baselines,
            SplitLabel.TEST_OOD,
            pretest_freeze.test_ood_trace_ids,
            _BASELINE_ORDER,
            None,
        ),
        (
            sealed_metrics.test_ood_learned,
            SplitLabel.TEST_OOD,
            pretest_freeze.test_ood_trace_ids,
            None,
            expected_seeds,
        ),
    )
    normalized_groups: list[tuple[OfficialPredictorSplitMetrics, ...]] = []
    for group, split, trace_ids, baselines, seeds in groups:
        group_values = _materialize_tuple(group, "sealed metric group")
        group = tuple(group_values)  # type: ignore[assignment]
        if any(not isinstance(item, OfficialPredictorSplitMetrics) for item in group):
            raise TypeError("sealed metric groups 类型错误")
        if any(item.forecasts.split is not split for item in group):
            raise ValueError("sealed metric group split 不一致")
        if any(item.forecasts.trace_ids != trace_ids for item in group):
            raise ValueError("sealed metric group frozen trace tuple 不一致")
        if any(
            item.forecasts.pretraining_freeze_sha256 != pretest_freeze.pretraining_freeze_sha256
            or item.forecasts.pretest_freeze_sha256 != pretest_freeze.sha256
            for item in group
        ):
            raise ValueError("sealed metric bundle freeze identities 不一致")
        if baselines is not None and tuple(item.forecasts.baseline for item in group) != baselines:
            raise ValueError("sealed baseline metrics 未精确保持 B0--B5")
        if seeds is not None and tuple(item.forecasts.training_seed for item in group) != seeds:
            raise ValueError("sealed learned metrics 未精确保持 frozen seeds")
        normalized_groups.append(group)  # type: ignore[arg-type]

    id_baselines, id_learned, ood_baselines, ood_learned = normalized_groups

    id_conditions = _manifest_conditions(
        pretest_freeze,
        SplitLabel.TEST_ID,
        pretest_freeze.test_id_trace_ids,
    )
    ood_conditions = _manifest_conditions(
        pretest_freeze,
        SplitLabel.TEST_OOD,
        pretest_freeze.test_ood_trace_ids,
    )
    assignment_by_trace = _validate_ood_assignments(pretest_freeze)

    return OfficialSealedMandatoryBreakdowns(
        test_id_baselines=tuple(
            _compute_split_breakdown(
                metrics=item,
                condition_by_trace=id_conditions,
                assignment_by_trace=assignment_by_trace,
            )
            for item in id_baselines
        ),
        test_id_learned=tuple(
            _compute_split_breakdown(
                metrics=item,
                condition_by_trace=id_conditions,
                assignment_by_trace=assignment_by_trace,
            )
            for item in id_learned
        ),
        test_ood_baselines=tuple(
            _compute_split_breakdown(
                metrics=item,
                condition_by_trace=ood_conditions,
                assignment_by_trace=assignment_by_trace,
            )
            for item in ood_baselines
        ),
        test_ood_learned=tuple(
            _compute_split_breakdown(
                metrics=item,
                condition_by_trace=ood_conditions,
                assignment_by_trace=assignment_by_trace,
            )
            for item in ood_learned
        ),
    )


__all__ = [
    "ConditionTraceBreakdown",
    "OODCellTraceBreakdown",
    "OODKindTraceBreakdown",
    "OfficialPredictorSplitBreakdown",
    "OfficialSealedMandatoryBreakdowns",
    "TargetStratumCellMetrics",
    "TargetValueStratum",
    "compute_official_mandatory_breakdowns",
]
