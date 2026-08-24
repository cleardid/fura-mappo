"""预测数据协议的不可变、PyTorch-neutral 核心模型。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from fura_mappo.demand import compute_config_hash

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_SAMPLE_ID_PATTERN = _SHA256_PATTERN
_ZONE_SCHEMA_NAME = "fura-mappo.zone-schema"
_ZONE_SCHEMA_VERSION = 1


def _contains_boolean(value: object) -> bool:
    """检查数组或嵌套序列中是否混入布尔标量。"""

    if isinstance(value, (bool, np.bool_)):
        return True
    if isinstance(value, np.ndarray):
        if np.issubdtype(value.dtype, np.bool_):
            return value.size > 0
        if value.dtype == np.dtype(object):
            return any(_contains_boolean(item) for item in value.flat)
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_boolean(item) for item in value)
    return False


def _normalize_integer(value: object, name: str, minimum: int) -> int:
    """规范化非 bool 整数并验证下界。"""

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} 必须是整数且不能是布尔值")
    normalized = int(value)
    if normalized < minimum:
        raise ValueError(f"{name} 必须大于或等于 {minimum}")
    return normalized


def _normalize_sha256(value: object, name: str) -> str:
    """验证小写完整 SHA-256。"""

    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} 必须是 64 位小写 SHA-256")
    return value


def _normalize_git_sha(value: object, name: str) -> str:
    """验证小写完整 Git Commit SHA。"""

    if not isinstance(value, str) or _GIT_SHA_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} 必须是 40 位小写 Git Commit SHA")
    return value


def _normalize_optional_sha256(value: object, name: str) -> str | None:
    """验证可选 SHA-256。"""

    if value is None:
        return None
    return _normalize_sha256(value, name)


def _normalize_count_array(value: object, name: str, ndim: int) -> np.ndarray:
    """返回 C-order、只读、非负的 ``int64`` 防御性副本。"""

    if _contains_boolean(value):
        raise TypeError(f"{name} 不能包含布尔值")
    array = np.asarray(value)
    if array.ndim != ndim:
        raise ValueError(f"{name} 必须是 {ndim} 维数组")
    if not np.issubdtype(array.dtype, np.integer):
        raise TypeError(f"{name} 必须包含整数且不能包含布尔值")
    normalized = np.array(array, dtype=np.int64, order="C", copy=True)
    if np.any(normalized < 0):
        raise ValueError(f"{name} 必须全部非负")
    normalized.setflags(write=False)
    return normalized


def _normalize_float_array(
    value: object,
    name: str,
    ndim: int,
    *,
    nonnegative: bool,
) -> np.ndarray:
    """返回 C-order、只读、有限的 ``float64`` 防御性副本。"""

    if _contains_boolean(value):
        raise TypeError(f"{name} 不能包含布尔值")
    array = np.asarray(value)
    if array.ndim != ndim:
        raise ValueError(f"{name} 必须是 {ndim} 维数组")
    if not np.issubdtype(array.dtype, np.number) or np.issubdtype(array.dtype, np.complexfloating):
        raise TypeError(f"{name} 必须包含实数")
    normalized = np.array(array, dtype=np.float64, order="C", copy=True)
    if not np.all(np.isfinite(normalized)):
        raise ValueError(f"{name} 必须全部为有限值")
    if nonnegative and np.any(normalized < 0.0):
        raise ValueError(f"{name} 必须全部非负")
    normalized.setflags(write=False)
    return normalized


def _normalize_mask(value: object, name: str, length: int) -> np.ndarray:
    """返回 shape ``[length]`` 的 C-order 只读 bool 副本。"""

    array = np.asarray(value)
    if array.ndim != 1 or array.shape != (length,):
        raise ValueError(f"{name} 形状必须为 [{length}]")
    if not np.issubdtype(array.dtype, np.bool_):
        raise TypeError(f"{name} 必须包含布尔值")
    normalized = np.array(array, dtype=np.bool_, order="C", copy=True)
    normalized.setflags(write=False)
    return normalized


@dataclass(frozen=True, slots=True, eq=False)
class ZoneSchema:
    """静态 zone 几何与规范 ``zone_id`` 顺序。

    Attributes:
        bounds: shape ``[num_zones, 4]`` 的 ``float64`` 半开矩形边界；每行是
            ``(x_min, x_max, y_min, y_max)``。
        sha256: 对 schema/version、固定 zone ordering 和 bounds 使用项目配置哈希协议
            计算的科学身份。
    """

    bounds: np.ndarray
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """规范化边界、验证矩形并计算稳定身份。"""

        bounds = _normalize_float_array(
            self.bounds,
            "bounds",
            2,
            nonnegative=False,
        )
        if bounds.shape[0] < 1 or bounds.shape[1] != 4:
            raise ValueError("bounds 形状必须为 [num_zones, 4] 且至少包含一个 zone")
        if np.any(bounds[:, 0] >= bounds[:, 1]):
            raise ValueError("bounds 必须满足 x_min < x_max")
        if np.any(bounds[:, 2] >= bounds[:, 3]):
            raise ValueError("bounds 必须满足 y_min < y_max")
        digest = compute_config_hash(
            {
                "schema": _ZONE_SCHEMA_NAME,
                "version": _ZONE_SCHEMA_VERSION,
                "zone_ordering": "zero_based_zone_id_ascending",
                "bounds": bounds,
            }
        )
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(self, "sha256", digest)

    @property
    def num_zones(self) -> int:
        """返回 zone 数量。"""

        return int(self.bounds.shape[0])

    @property
    def zone_ids(self) -> tuple[int, ...]:
        """返回规范 ``0..Z-1`` zone 顺序。"""

        return tuple(range(self.num_zones))


@dataclass(frozen=True, slots=True, eq=False)
class PredictionContext:
    """decision boundary 的纯因果需求历史。

    ``history_counts`` shape 为 ``[history_length, num_zones]``，dtype 为
    ``int64``；最后一行对应 ``absolute_step``。对象不包含 source identity、未来需求或
    模拟器 latent intensity。
    """

    absolute_step: int
    steps_remaining: int
    history_counts: np.ndarray
    history_mask: np.ndarray
    zone_schema_sha256: str
    prediction_horizon: int

    def __post_init__(self) -> None:
        """防御性规范化字段并验证 shape。"""

        absolute_step = _normalize_integer(self.absolute_step, "absolute_step", 0)
        steps_remaining = _normalize_integer(self.steps_remaining, "steps_remaining", 1)
        prediction_horizon = _normalize_integer(
            self.prediction_horizon,
            "prediction_horizon",
            1,
        )
        counts = _normalize_count_array(self.history_counts, "history_counts", 2)
        history_length, num_zones = counts.shape
        if history_length < 1 or num_zones < 1:
            raise ValueError("history_counts 形状必须为 [L, Z]，且 L、Z 均至少为 1")
        mask = _normalize_mask(self.history_mask, "history_mask", history_length)
        if not bool(mask[-1]) or np.any(mask[:-1] & ~mask[1:]):
            raise ValueError("history_mask 必须是左 padding 后连续有效，且当前行有效")
        if np.any(counts[~mask] != 0):
            raise ValueError("history padding 行必须为零")
        zone_hash = _normalize_sha256(self.zone_schema_sha256, "zone_schema_sha256")
        object.__setattr__(self, "absolute_step", absolute_step)
        object.__setattr__(self, "steps_remaining", steps_remaining)
        object.__setattr__(self, "history_counts", counts)
        object.__setattr__(self, "history_mask", mask)
        object.__setattr__(self, "zone_schema_sha256", zone_hash)
        object.__setattr__(self, "prediction_horizon", prediction_horizon)

    @property
    def history_length(self) -> int:
        """返回固定历史窗口长度。"""

        return int(self.history_counts.shape[0])

    @property
    def num_zones(self) -> int:
        """返回 zone 数量。"""

        return int(self.history_counts.shape[1])


@dataclass(frozen=True, slots=True, eq=False)
class PredictionTarget:
    """逐 lead、逐 zone 的 realized arrival count 标签。

    ``counts`` shape 为 ``[prediction_horizon, num_zones]``，dtype 为
    ``int64``；行 0 对应 anchor 后的第一个未来时间步。
    """

    counts: np.ndarray
    valid_mask: np.ndarray

    def __post_init__(self) -> None:
        """防御性规范化 count 与 episode-end mask。"""

        counts = _normalize_count_array(self.counts, "counts", 2)
        horizon, num_zones = counts.shape
        if horizon < 1 or num_zones < 1:
            raise ValueError("counts 形状必须为 [P, Z]，且 P、Z 均至少为 1")
        mask = _normalize_mask(self.valid_mask, "valid_mask", horizon)
        if np.any(~mask[:-1] & mask[1:]):
            raise ValueError("valid_mask 必须是连续有效前缀，不能包含空洞")
        if np.any(counts[~mask] != 0):
            raise ValueError("target padding 行必须为零")
        object.__setattr__(self, "counts", counts)
        object.__setattr__(self, "valid_mask", mask)

    @property
    def horizon(self) -> int:
        """返回预测 horizon。"""

        return int(self.counts.shape[0])

    @property
    def num_zones(self) -> int:
        """返回 zone 数量。"""

        return int(self.counts.shape[1])


@dataclass(frozen=True, slots=True)
class PredictionSample:
    """把 controller-safe context 与仅训练可见 target 绑定到审计 sample ID。"""

    sample_id: str
    context: PredictionContext
    target: PredictionTarget

    def __post_init__(self) -> None:
        """验证 sample identity 和 context/target shape 一致性。"""

        if (
            not isinstance(self.sample_id, str)
            or _SAMPLE_ID_PATTERN.fullmatch(self.sample_id) is None
        ):
            raise ValueError("sample_id 必须是 64 位小写 SHA-256")
        if not isinstance(self.context, PredictionContext):
            raise TypeError("context 必须是 PredictionContext")
        if not isinstance(self.target, PredictionTarget):
            raise TypeError("target 必须是 PredictionTarget")
        if self.target.horizon != self.context.prediction_horizon:
            raise ValueError("target horizon 必须等于 context.prediction_horizon")
        if self.target.num_zones != self.context.num_zones:
            raise ValueError("target 与 context 的 zone 数量必须一致")
        if not bool(self.target.valid_mask[0]):
            raise ValueError("supervised PredictionSample 必须至少包含有效 lead 1")


@dataclass(frozen=True, slots=True, eq=False)
class DemandForecast:
    """controller-visible 的 point/probabilistic demand forecast。

    所有预测均位于原始 count scale。``mean`` 与 ``variance`` shape 为 ``[P,Z]``；
    ``quantiles`` shape 为 ``[Q,P,Z]``；``scenarios`` shape 为 ``[S,P,Z]``。
    """

    absolute_step: int
    horizon: int
    zone_schema_sha256: str
    valid_mask: np.ndarray
    mean: np.ndarray
    variance: np.ndarray | None = None
    quantile_levels: np.ndarray | None = None
    quantiles: np.ndarray | None = None
    scenarios: np.ndarray | None = None

    def __post_init__(self) -> None:
        """规范化并交叉验证所有 point/probabilistic projection。"""

        absolute_step = _normalize_integer(self.absolute_step, "absolute_step", 0)
        horizon = _normalize_integer(self.horizon, "horizon", 1)
        zone_hash = _normalize_sha256(self.zone_schema_sha256, "zone_schema_sha256")
        mean = _normalize_float_array(self.mean, "mean", 2, nonnegative=True)
        if mean.shape[0] != horizon or mean.shape[1] < 1:
            raise ValueError("mean 形状必须为 [horizon, num_zones]")
        mask = _normalize_mask(self.valid_mask, "valid_mask", horizon)
        if np.any(~mask[:-1] & mask[1:]):
            raise ValueError("valid_mask 必须是连续有效前缀，不能包含空洞")
        if np.any(mean[~mask] != 0.0):
            raise ValueError("mean 在 valid_mask=False 的 horizon 行必须为零")

        variance: np.ndarray | None = None
        if self.variance is not None:
            variance = _normalize_float_array(
                self.variance,
                "variance",
                2,
                nonnegative=True,
            )
            if variance.shape != mean.shape:
                raise ValueError("variance 形状必须与 mean 完全一致")
            if np.any(variance[~mask] != 0.0):
                raise ValueError("variance 在 valid_mask=False 的 horizon 行必须为零")

        levels: np.ndarray | None = None
        quantiles: np.ndarray | None = None
        if (self.quantile_levels is None) != (self.quantiles is None):
            raise ValueError("quantile_levels 与 quantiles 必须同时提供或同时省略")
        if self.quantile_levels is not None and self.quantiles is not None:
            levels = _normalize_float_array(
                self.quantile_levels,
                "quantile_levels",
                1,
                nonnegative=False,
            )
            if levels.size < 1:
                raise ValueError("quantile_levels 必须至少包含一个分位点")
            if np.any(levels <= 0.0) or np.any(levels >= 1.0):
                raise ValueError("quantile_levels 必须严格位于 (0, 1)")
            if np.any(np.diff(levels) <= 0.0):
                raise ValueError("quantile_levels 必须严格递增")
            quantiles = _normalize_float_array(
                self.quantiles,
                "quantiles",
                3,
                nonnegative=True,
            )
            if quantiles.shape != (levels.size, *mean.shape):
                raise ValueError("quantiles 形状必须为 [Q, horizon, num_zones]")
            if np.any(np.diff(quantiles, axis=0) < 0.0):
                raise ValueError("quantiles 必须沿 quantile 轴逐点非递减")
            if np.any(quantiles[:, ~mask, :] != 0.0):
                raise ValueError("quantiles 在 valid_mask=False 的 horizon 行必须为零")

        scenarios: np.ndarray | None = None
        if self.scenarios is not None:
            scenarios = _normalize_count_array(self.scenarios, "scenarios", 3)
            if scenarios.shape[0] < 1 or scenarios.shape[1:] != mean.shape:
                raise ValueError("scenarios 形状必须为 [S, horizon, num_zones] 且 S >= 1")
            if np.any(scenarios[:, ~mask, :] != 0):
                raise ValueError("scenarios 在 valid_mask=False 的 horizon 行必须为零")

        object.__setattr__(self, "absolute_step", absolute_step)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "zone_schema_sha256", zone_hash)
        object.__setattr__(self, "valid_mask", mask)
        object.__setattr__(self, "mean", mean)
        object.__setattr__(self, "variance", variance)
        object.__setattr__(self, "quantile_levels", levels)
        object.__setattr__(self, "quantiles", quantiles)
        object.__setattr__(self, "scenarios", scenarios)

    @property
    def num_zones(self) -> int:
        """返回 zone 数量。"""

        return int(self.mean.shape[1])


@dataclass(frozen=True, slots=True)
class ForecastProvenance:
    """不向 controller 暴露的 forecast 审计 provenance。"""

    predictor_artifact_sha256: str
    prediction_config_sha256: str
    dataset_protocol_sha256: str
    split_manifest_sha256: str
    sample_id: str
    execution_git_commit: str
    normalization_sha256: str | None = None
    inference_rng_id: str | None = None

    def __post_init__(self) -> None:
        """验证显式、无任意 metadata tree 的 provenance 字段。"""

        for value, name in (
            (self.predictor_artifact_sha256, "predictor_artifact_sha256"),
            (self.prediction_config_sha256, "prediction_config_sha256"),
            (self.dataset_protocol_sha256, "dataset_protocol_sha256"),
            (self.split_manifest_sha256, "split_manifest_sha256"),
        ):
            object.__setattr__(self, name, _normalize_sha256(value, name))
        if (
            not isinstance(self.sample_id, str)
            or _SAMPLE_ID_PATTERN.fullmatch(self.sample_id) is None
        ):
            raise ValueError("sample_id 必须是 64 位小写 SHA-256")
        object.__setattr__(
            self,
            "execution_git_commit",
            _normalize_git_sha(self.execution_git_commit, "execution_git_commit"),
        )
        object.__setattr__(
            self,
            "normalization_sha256",
            _normalize_optional_sha256(self.normalization_sha256, "normalization_sha256"),
        )
        if self.inference_rng_id is not None and (
            not isinstance(self.inference_rng_id, str) or not self.inference_rng_id
        ):
            raise ValueError("inference_rng_id 必须是非空字符串或 None")


@dataclass(frozen=True, slots=True)
class ForecastRecord:
    """把 controller-visible forecast 与 controller-hidden provenance 分离。"""

    forecast: DemandForecast
    provenance: ForecastProvenance

    def __post_init__(self) -> None:
        """验证 record 只组合已验证对象。"""

        if not isinstance(self.forecast, DemandForecast):
            raise TypeError("forecast 必须是 DemandForecast")
        if not isinstance(self.provenance, ForecastProvenance):
            raise TypeError("provenance 必须是 ForecastProvenance")


__all__ = [
    "DemandForecast",
    "ForecastProvenance",
    "ForecastRecord",
    "PredictionContext",
    "PredictionSample",
    "PredictionTarget",
    "ZoneSchema",
]
