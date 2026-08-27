"""WP-03B paired whole-test-trace bootstrap confidence-interval core。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Integral

import numpy as np

from fura_mappo.prediction.comparison import LockedTestPointEstimate
from fura_mappo.prediction.metrics import PointMetricSummary

_CI_PROBABILITIES = (0.025, 0.975)
_TraceSignature = tuple[tuple[str, int, int], ...]


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """规范化非 bool、非负整数。"""

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


def _validate_quantile_method(value: object) -> str:
    """使用当前 NumPy runtime hard-check quantile method，不做 fallback。"""

    if not isinstance(value, str):
        raise TypeError("quantile_method 必须是字符串")
    if not value.strip():
        raise ValueError("quantile_method 必须是非空字符串")
    try:
        np.quantile(
            np.asarray([0.0, 1.0], dtype=np.float64),
            _CI_PROBABILITIES,
            method=value,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("quantile_method 不受当前 NumPy runtime 支持") from error
    return value


@dataclass(frozen=True, slots=True)
class PredictionBootstrapSpec:
    """显式 prediction-bootstrap RNG/replicate/quantile identity；无 scientific defaults。"""

    num_resamples: int
    rng_seed: int
    quantile_method: str

    def __post_init__(self) -> None:
        """验证 caller 显式提供的 bootstrap 参数。"""

        num_resamples = _normalize_positive_integer(self.num_resamples, "num_resamples")
        rng_seed = _normalize_nonnegative_integer(self.rng_seed, "rng_seed")
        quantile_method = _validate_quantile_method(self.quantile_method)
        object.__setattr__(self, "num_resamples", num_resamples)
        object.__setattr__(self, "rng_seed", rng_seed)
        object.__setattr__(self, "quantile_method", quantile_method)


def _trace_signature(metrics: PointMetricSummary) -> _TraceSignature:
    """返回 canonical whole-trace structural signature。"""

    return tuple(
        (
            trace.trace_id,
            trace.trace_start_step,
            trace.trace_num_steps,
        )
        for trace in metrics.trace_metrics
    )


def _extract_trace_mse(
    point_estimate: LockedTestPointEstimate,
) -> tuple[np.ndarray, np.ndarray]:
    """防御性抽取 per-trace Primary MSE，不读取 windows、anchors、targets 或 forecasts。"""

    signature = point_estimate.test_trace_signature
    num_traces = len(signature)
    if num_traces < 1:
        raise ValueError("test trace signature 必须至少包含一条完整 trace")

    expected_seeds = point_estimate.learned_selection.fixed_training_seeds
    actual_seeds = tuple(result.training_seed for result in point_estimate.learned_seed_results)
    if actual_seeds != expected_seeds:
        raise ValueError("learned test results 与 fixed training-seed set 不一致")

    learned_rows: list[list[float]] = []
    for result in point_estimate.learned_seed_results:
        metrics = result.metrics
        if len(metrics.trace_metrics) != num_traces or _trace_signature(metrics) != signature:
            raise ValueError("learned test metrics 的 whole-trace alignment 不一致")
        learned_rows.append([trace.primary_mse for trace in metrics.trace_metrics])

    baseline_metrics = point_estimate.baseline_metrics
    if (
        len(baseline_metrics.trace_metrics) != num_traces
        or _trace_signature(baseline_metrics) != signature
    ):
        raise ValueError("baseline test metrics 的 whole-trace alignment 不一致")

    learned_trace_mse = np.array(learned_rows, dtype=np.float64, order="C", copy=True)
    baseline_trace_mse = np.array(
        [trace.primary_mse for trace in baseline_metrics.trace_metrics],
        dtype=np.float64,
        order="C",
        copy=True,
    )
    expected_shape = (len(expected_seeds), num_traces)
    if learned_trace_mse.shape != expected_shape:
        raise ValueError("learned_trace_mse shape 必须为 [R,N]")
    if baseline_trace_mse.shape != (num_traces,):
        raise ValueError("baseline_trace_mse shape 必须为 [N]")
    if not np.all(np.isfinite(learned_trace_mse)) or np.any(learned_trace_mse < 0.0):
        raise ValueError("learned per-trace Primary MSE 必须有限且非负")
    if not np.all(np.isfinite(baseline_trace_mse)) or np.any(baseline_trace_mse < 0.0):
        raise ValueError("baseline per-trace Primary MSE 必须有限且非负")
    return learned_trace_mse, baseline_trace_mse


def _normalize_replicates(value: object, expected_length: int) -> np.ndarray:
    """返回一维、C-contiguous、只读 ``float64[B]`` defensive copy。"""

    try:
        array = np.asarray(value)
    except (TypeError, ValueError) as error:
        raise TypeError("delta_rmse_replicates 必须是数值 array-like") from error
    if array.ndim != 1:
        raise ValueError("delta_rmse_replicates 必须是一维数组")
    if not (
        np.issubdtype(array.dtype, np.integer) or np.issubdtype(array.dtype, np.floating)
    ) or np.issubdtype(array.dtype, np.bool_):
        raise TypeError("delta_rmse_replicates 必须包含非 bool 实数")
    normalized = np.array(array, dtype=np.float64, order="C", copy=True)
    if normalized.shape != (expected_length,):
        raise ValueError("delta_rmse_replicates 长度必须等于 spec.num_resamples")
    if not np.all(np.isfinite(normalized)):
        raise ValueError("delta_rmse_replicates 必须全部有限")
    normalized.setflags(write=False)
    return normalized


def _percentile_interval(replicates: np.ndarray, method: str) -> tuple[float, float]:
    """通过唯一 authoritative path 计算固定 two-sided 95% percentile CI。"""

    lower, upper = np.quantile(
        replicates,
        _CI_PROBABILITIES,
        method=method,
    )
    ci_lower = float(lower)
    ci_upper = float(upper)
    if not math.isfinite(ci_lower) or not math.isfinite(ci_upper):
        raise ValueError("bootstrap CI endpoints 必须有限")
    if ci_lower > ci_upper:
        raise ValueError("bootstrap CI endpoints 顺序错误")
    return ci_lower, ci_upper


@dataclass(frozen=True, slots=True, eq=False)
class PairedTraceBootstrapResult:
    """structurally valid 的 paired trace-bootstrap replicates 与固定 95% percentile CI。

    直接构造仅证明结构和 quantile 自洽；只有 ``bootstrap_locked_test_delta_rmse`` 执行本 Slice
    的 explicit-PCG64 computation path。official provenance 仍需 future orchestration 绑定。
    """

    point_estimate: LockedTestPointEstimate
    spec: PredictionBootstrapSpec
    delta_rmse_replicates: np.ndarray
    ci_lower: float = field(init=False)
    ci_upper: float = field(init=False)

    def __post_init__(self) -> None:
        """防御性复制 replicates，并从它们唯一重算 percentile CI。"""

        if not isinstance(self.point_estimate, LockedTestPointEstimate):
            raise TypeError("point_estimate 必须是 LockedTestPointEstimate")
        if not isinstance(self.spec, PredictionBootstrapSpec):
            raise TypeError("spec 必须是 PredictionBootstrapSpec")
        replicates = _normalize_replicates(
            self.delta_rmse_replicates,
            self.spec.num_resamples,
        )
        ci_lower, ci_upper = _percentile_interval(
            replicates,
            self.spec.quantile_method,
        )
        object.__setattr__(self, "delta_rmse_replicates", replicates)
        object.__setattr__(self, "ci_lower", ci_lower)
        object.__setattr__(self, "ci_upper", ci_upper)

    @property
    def point_delta_rmse(self) -> float:
        """返回 Slice 6 locked point estimate，不产生 scientific label。"""

        return self.point_estimate.delta_rmse


def bootstrap_locked_test_delta_rmse(
    point_estimate: LockedTestPointEstimate,
    spec: PredictionBootstrapSpec,
) -> PairedTraceBootstrapResult:
    """以独立 explicit PCG64 对完整 test traces 做 paired percentile bootstrap。"""

    if not isinstance(point_estimate, LockedTestPointEstimate):
        raise TypeError("point_estimate 必须是 LockedTestPointEstimate")
    if not isinstance(spec, PredictionBootstrapSpec):
        raise TypeError("spec 必须是 PredictionBootstrapSpec")
    learned_trace_mse, baseline_trace_mse = _extract_trace_mse(point_estimate)
    num_traces = baseline_trace_mse.size

    generator = np.random.Generator(np.random.PCG64(spec.rng_seed))
    sampled_indices = generator.integers(
        0,
        num_traces,
        size=(spec.num_resamples, num_traces),
        dtype=np.int64,
    )
    with np.errstate(over="ignore", invalid="ignore"):
        per_seed_mse = np.mean(
            learned_trace_mse[:, sampled_indices],
            axis=2,
            dtype=np.float64,
        )
        algorithm_mse = np.mean(per_seed_mse, axis=0, dtype=np.float64)
        algorithm_rmse = np.sqrt(algorithm_mse)
        baseline_mse = np.mean(
            baseline_trace_mse[sampled_indices],
            axis=1,
            dtype=np.float64,
        )
        baseline_rmse = np.sqrt(baseline_mse)
        delta_rmse_replicates = algorithm_rmse - baseline_rmse
    if not np.all(np.isfinite(delta_rmse_replicates)):
        raise ValueError("bootstrap Delta_RMSE replicates 必须全部有限")

    return PairedTraceBootstrapResult(
        point_estimate=point_estimate,
        spec=spec,
        delta_rmse_replicates=delta_rmse_replicates,
    )


__all__ = [
    "PairedTraceBootstrapResult",
    "PredictionBootstrapSpec",
    "bootstrap_locked_test_delta_rmse",
]
