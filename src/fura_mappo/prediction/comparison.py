"""WP-03B locked learned-vs-B* deterministic test point comparison。"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from numbers import Integral

from fura_mappo.prediction.metrics import PointMetricSummary
from fura_mappo.prediction.model_selection import LearnedModelSelectionResult
from fura_mappo.prediction.selection import BaselineSelectionResult

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_TestTraceSignature = tuple[tuple[str, int, int], ...]


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """规范化非 bool、非负整数，不引入 NumPy dependency。"""

    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} 必须是整数且不能是布尔值")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} 必须大于或等于 0")
    return normalized


def _normalize_sha256(value: object, name: str) -> str:
    """验证 64-char lowercase SHA-256 identity。"""

    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} 必须是 64 位小写 SHA-256")
    return value


def _test_trace_signature(metrics: PointMetricSummary) -> _TestTraceSignature:
    """构造 structural signature；它不证明 split、source 或 spent-test provenance。"""

    return tuple(
        (
            trace.trace_id,
            trace.trace_start_step,
            trace.trace_num_steps,
        )
        for trace in metrics.trace_metrics
    )


@dataclass(frozen=True, slots=True, eq=False)
class TrainingSeedTestResult:
    """一个已锁定 learned checkpoint 的外部完整 test metric record。"""

    training_seed: int
    checkpoint_sha256: str
    metrics: PointMetricSummary

    def __post_init__(self) -> None:
        """验证 seed/checkpoint identity 与可进入聚合的有限 Primary MSE。"""

        training_seed = _normalize_nonnegative_integer(self.training_seed, "training_seed")
        checkpoint_sha256 = _normalize_sha256(
            self.checkpoint_sha256,
            "checkpoint_sha256",
        )
        if not isinstance(self.metrics, PointMetricSummary):
            raise TypeError("metrics 必须是 PointMetricSummary")
        primary_mse = self.metrics.primary_mse
        if not math.isfinite(primary_mse) or primary_mse < 0.0:
            raise ValueError("test Primary MSE 必须有限且非负")

        object.__setattr__(self, "training_seed", training_seed)
        object.__setattr__(self, "checkpoint_sha256", checkpoint_sha256)


def _normalize_test_seed_results(
    value: object,
) -> tuple[TrainingSeedTestResult, ...]:
    """验证 successful test records，并按 training_seed canonicalize。"""

    try:
        seed_results = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("learned_seed_results 必须是有限 iterable") from error
    if not seed_results:
        raise ValueError("learned_seed_results 必须非空")
    if any(not isinstance(result, TrainingSeedTestResult) for result in seed_results):
        raise TypeError("learned_seed_results 必须全部是 TrainingSeedTestResult")
    seeds = [result.training_seed for result in seed_results]
    if len(seeds) != len(set(seeds)):
        raise ValueError("learned_seed_results 的 training_seed 必须全部唯一")
    return tuple(sorted(seed_results, key=lambda result: result.training_seed))


def _validate_selection_compatibility(
    learned_selection: LearnedModelSelectionResult,
    baseline_selection: BaselineSelectionResult,
) -> tuple[int, int, str]:
    """在读取 test metrics 前验证两个 validation locking result 的 Layer-B geometry。"""

    if learned_selection.prediction_horizon != baseline_selection.prediction_horizon:
        raise ValueError("learned/baseline selections 的 prediction_horizon 不一致")
    if learned_selection.num_zones != baseline_selection.num_zones:
        raise ValueError("learned/baseline selections 的 num_zones 不一致")
    if learned_selection.zone_schema_sha256 != baseline_selection.zone_schema_sha256:
        raise ValueError("learned/baseline selections 的 zone_schema_sha256 不一致")
    if (
        learned_selection.validation_trace_signature
        != baseline_selection.validation_trace_signature
    ):
        raise ValueError("learned/baseline selections 的 validation trace signature 不一致")

    prediction_horizon = learned_selection.prediction_horizon
    num_zones = learned_selection.num_zones
    zone_schema_sha256 = learned_selection.zone_schema_sha256
    learned_protocol = learned_selection.selected.protocol
    baseline_protocol = baseline_selection.selected.protocol
    if learned_protocol.prediction_horizon != prediction_horizon:
        raise ValueError("selected learned protocol prediction_horizon 与 selection 不一致")
    if learned_protocol.zone_schema_sha256 != zone_schema_sha256:
        raise ValueError("selected learned protocol zone_schema_sha256 与 selection 不一致")
    if baseline_protocol.prediction_horizon != prediction_horizon:
        raise ValueError("selected B* protocol prediction_horizon 与 comparison 不一致")
    if baseline_protocol.zone_schema_sha256 != zone_schema_sha256:
        raise ValueError("selected B* protocol zone_schema_sha256 与 comparison 不一致")
    return prediction_horizon, num_zones, zone_schema_sha256


def _locked_checkpoint_by_seed(
    learned_selection: LearnedModelSelectionResult,
) -> dict[int, str]:
    """读取 selected learned config 的 fixed-seed checkpoint identities，不做 re-selection。"""

    locked: dict[int, str] = {}
    for result in learned_selection.selected.seed_results:
        if result.checkpoint_sha256 is None:
            raise ValueError("selected learned config 的 checkpoint identity 不完整")
        locked[result.training_seed] = result.checkpoint_sha256
    return locked


def _mean_test_mse(seed_results: tuple[TrainingSeedTestResult, ...]) -> float:
    """对全部 fixed seeds 的 Test MSE_r 等权求均值。"""

    try:
        test_algorithm_mse = math.fsum(result.metrics.primary_mse for result in seed_results) / len(
            seed_results
        )
    except OverflowError as error:
        raise ValueError("Test Algorithm MSE 必须有限") from error
    if not math.isfinite(test_algorithm_mse) or test_algorithm_mse < 0.0:
        raise ValueError("Test Algorithm MSE 必须有限且非负")
    return test_algorithm_mse


@dataclass(frozen=True, slots=True, eq=False)
class LockedTestPointEstimate:
    """已锁定 learned config 与已锁定 B* 的纯数学 deterministic point estimate。

    ``test_trace_signature`` 只确认双方 structural trace geometry 完全相同；它不能证明 test split、
    source identity、未污染性、未提前暴露或 spent-test governance。authoritative provenance 绑定属于
    future official orchestration。本对象不选择 config/baseline，也不产生 scientific label。
    """

    learned_selection: LearnedModelSelectionResult
    baseline_selection: BaselineSelectionResult
    learned_seed_results: tuple[TrainingSeedTestResult, ...]
    baseline_metrics: PointMetricSummary
    test_trace_signature: _TestTraceSignature = field(init=False)
    prediction_horizon: int = field(init=False)
    num_zones: int = field(init=False)
    zone_schema_sha256: str = field(init=False)
    test_algorithm_mse: float = field(init=False)
    test_algorithm_rmse: float = field(init=False)
    baseline_mse: float = field(init=False)
    baseline_rmse: float = field(init=False)
    delta_rmse: float = field(init=False)

    def __post_init__(self) -> None:
        """重验 locked identities、公平性与唯一 authoritative arithmetic path。"""

        if not isinstance(self.learned_selection, LearnedModelSelectionResult):
            raise TypeError("learned_selection 必须是 LearnedModelSelectionResult")
        if not isinstance(self.baseline_selection, BaselineSelectionResult):
            raise TypeError("baseline_selection 必须是 BaselineSelectionResult")
        if not isinstance(self.baseline_metrics, PointMetricSummary):
            raise TypeError("baseline_metrics 必须是 PointMetricSummary")

        prediction_horizon, num_zones, zone_schema_sha256 = _validate_selection_compatibility(
            self.learned_selection,
            self.baseline_selection,
        )
        seed_results = _normalize_test_seed_results(self.learned_seed_results)
        actual_seeds = tuple(result.training_seed for result in seed_results)
        if actual_seeds != self.learned_selection.fixed_training_seeds:
            raise ValueError("learned_seed_results 必须精确覆盖 locked fixed training-seed set")

        checkpoint_by_seed = _locked_checkpoint_by_seed(self.learned_selection)
        for result in seed_results:
            expected_checkpoint = checkpoint_by_seed.get(result.training_seed)
            if result.checkpoint_sha256 != expected_checkpoint:
                raise ValueError(
                    "test result checkpoint_sha256 与 locked checkpoint identity 不一致"
                )

        first_metrics = seed_results[0].metrics
        test_signature = _test_trace_signature(first_metrics)
        for result in seed_results:
            metrics = result.metrics
            if metrics.prediction_horizon != prediction_horizon:
                raise ValueError("learned test metrics prediction_horizon 不一致")
            if metrics.num_zones != num_zones:
                raise ValueError("learned test metrics num_zones 不一致")
            if metrics.zone_schema_sha256 != zone_schema_sha256:
                raise ValueError("learned test metrics zone_schema_sha256 不一致")
            if _test_trace_signature(metrics) != test_signature:
                raise ValueError("learned test metrics 的 test trace signature 不一致")

        baseline_protocol = self.baseline_selection.selected.protocol
        if self.baseline_metrics.prediction_horizon != baseline_protocol.prediction_horizon:
            raise ValueError("baseline_metrics prediction_horizon 与 locked B* protocol 不一致")
        if self.baseline_metrics.zone_schema_sha256 != baseline_protocol.zone_schema_sha256:
            raise ValueError("baseline_metrics zone_schema_sha256 与 locked B* protocol 不一致")
        if self.baseline_metrics.prediction_horizon != prediction_horizon:
            raise ValueError("baseline_metrics prediction_horizon 与 learned test metrics 不一致")
        if self.baseline_metrics.num_zones != num_zones:
            raise ValueError("baseline_metrics num_zones 与 learned test metrics 不一致")
        if self.baseline_metrics.zone_schema_sha256 != zone_schema_sha256:
            raise ValueError("baseline_metrics zone_schema_sha256 与 learned test metrics 不一致")
        if _test_trace_signature(self.baseline_metrics) != test_signature:
            raise ValueError("baseline_metrics 与 learned metrics 的 test trace signature 不一致")

        test_algorithm_mse = _mean_test_mse(seed_results)
        test_algorithm_rmse = math.sqrt(test_algorithm_mse)
        baseline_mse = self.baseline_metrics.primary_mse
        baseline_rmse = self.baseline_metrics.primary_rmse
        if not math.isfinite(baseline_mse) or baseline_mse < 0.0:
            raise ValueError("B* MSE 必须有限且非负")
        if not math.isfinite(baseline_rmse) or baseline_rmse < 0.0:
            raise ValueError("B* RMSE 必须有限且非负")
        delta_rmse = test_algorithm_rmse - baseline_rmse
        if not math.isfinite(delta_rmse):
            raise ValueError("Delta_RMSE 必须有限")

        object.__setattr__(self, "learned_seed_results", seed_results)
        object.__setattr__(self, "test_trace_signature", test_signature)
        object.__setattr__(self, "prediction_horizon", prediction_horizon)
        object.__setattr__(self, "num_zones", num_zones)
        object.__setattr__(self, "zone_schema_sha256", zone_schema_sha256)
        object.__setattr__(self, "test_algorithm_mse", test_algorithm_mse)
        object.__setattr__(self, "test_algorithm_rmse", test_algorithm_rmse)
        object.__setattr__(self, "baseline_mse", baseline_mse)
        object.__setattr__(self, "baseline_rmse", baseline_rmse)
        object.__setattr__(self, "delta_rmse", delta_rmse)


def compute_locked_test_point_estimate(
    learned_selection: LearnedModelSelectionResult,
    baseline_selection: BaselineSelectionResult,
    learned_seed_results: Iterable[TrainingSeedTestResult],
    baseline_metrics: PointMetricSummary,
) -> LockedTestPointEstimate:
    """聚合外部 synthetic/official-agnostic metrics，不加载数据、执行 predictor 或改变状态。"""

    return LockedTestPointEstimate(
        learned_selection=learned_selection,
        baseline_selection=baseline_selection,
        learned_seed_results=learned_seed_results,  # type: ignore[arg-type]
        baseline_metrics=baseline_metrics,
    )


__all__ = [
    "LockedTestPointEstimate",
    "TrainingSeedTestResult",
    "compute_locked_test_point_estimate",
]
