"""四类需求过程的严格内存配置工厂。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import cast

import numpy.typing as npt

from fura_mappo.demand.nonstationary import (
    BurstDemand,
    DriftingHotspotDemand,
    MarkovSwitchingDemand,
)
from fura_mappo.demand.processes import DemandProcess, StationaryPoissonDemand

_COMMON_FIELDS = frozenset(
    {
        "type",
        "seed",
        "zone_bounds",
        "priority_range",
        "service_time_range",
        "deadline_offset_range",
    }
)
_PROCESS_SCHEMAS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "stationary_poisson": _COMMON_FIELDS | {"intensities"},
        "drifting_hotspot": _COMMON_FIELDS
        | {
            "base_intensities",
            "hotspot_amplitudes",
            "hotspot_scales",
            "initial_hotspot_positions",
            "hotspot_velocities",
        },
        "markov_switching": _COMMON_FIELDS
        | {"state_intensities", "transition_matrix", "initial_state"},
        "burst": _COMMON_FIELDS
        | {
            "base_intensities",
            "burst_probability",
            "burst_duration_range",
            "burst_amplitude_range",
            "burst_zone_weights",
        },
    }
)
_SUPPORTED_TYPES = tuple(sorted(_PROCESS_SCHEMAS))


def _format_fields(fields: set[object]) -> str:
    """稳定格式化配置字段集合。"""

    return ", ".join(sorted(repr(field) for field in fields))


def _validate_schema(config: Mapping[str, object], process_type: str) -> None:
    """同时收集并报告指定过程 schema 的缺失和多余字段。"""

    required_fields = _PROCESS_SCHEMAS[process_type]
    config_fields = set(config.keys())
    missing_fields = set(required_fields) - config_fields
    extra_fields = config_fields - set(required_fields)
    problems: list[str] = []
    if missing_fields:
        problems.append(f"config 缺少必需字段: {_format_fields(missing_fields)}")
    if extra_fields:
        problems.append(f"config 包含多余字段: {_format_fields(extra_fields)}")
    if problems:
        raise ValueError("；".join(problems))


def _common_arguments(config: Mapping[str, object]) -> dict[str, object]:
    """读取共享字段而不修改调用方映射或嵌套对象。"""

    return {
        "seed": cast(int, config["seed"]),
        "zone_bounds": cast(npt.ArrayLike, config["zone_bounds"]),
        "priority_range": cast(Sequence[float], config["priority_range"]),
        "service_time_range": cast(Sequence[int], config["service_time_range"]),
        "deadline_offset_range": cast(Sequence[int], config["deadline_offset_range"]),
    }


def create_demand_process(config: Mapping[str, object]) -> DemandProcess:
    """根据严格只读 schema 创建需求过程，不修改调用方对象。

    Args:
        config: 包含规范 ``type``、共享参数及对应过程专属参数的内存映射。
            逐区域数组使用 ``[num_zones]``，区域边界使用
            ``[num_zones, 4]``，Markov 状态强度使用
            ``[num_states, num_zones]``。

    Returns:
        与规范类型名称对应的独立需求过程。

    Raises:
        TypeError: 配置或 ``type`` 的类型错误时抛出。
        ValueError: 类型未知、字段缺失或存在多余字段时抛出。
    """

    if not isinstance(config, Mapping):
        raise TypeError("config 必须是 Mapping")
    if "type" not in config:
        raise ValueError("config 缺少必需字段: 'type'")

    process_type = config["type"]
    if not isinstance(process_type, str):
        raise TypeError("config['type'] 必须是字符串")
    if process_type not in _PROCESS_SCHEMAS:
        supported = ", ".join(repr(name) for name in _SUPPORTED_TYPES)
        raise ValueError(f"未知需求过程类型 {process_type!r}；支持的类型为 {supported}")

    _validate_schema(config, process_type)
    common = _common_arguments(config)
    if process_type == "stationary_poisson":
        return StationaryPoissonDemand(
            **common,
            intensities=cast(npt.ArrayLike, config["intensities"]),
        )
    elif process_type == "drifting_hotspot":
        return DriftingHotspotDemand(
            **common,
            base_intensities=cast(npt.ArrayLike, config["base_intensities"]),
            hotspot_amplitudes=cast(npt.ArrayLike, config["hotspot_amplitudes"]),
            hotspot_scales=cast(npt.ArrayLike, config["hotspot_scales"]),
            initial_hotspot_positions=cast(npt.ArrayLike, config["initial_hotspot_positions"]),
            hotspot_velocities=cast(npt.ArrayLike, config["hotspot_velocities"]),
        )
    elif process_type == "markov_switching":
        return MarkovSwitchingDemand(
            **common,
            state_intensities=cast(npt.ArrayLike, config["state_intensities"]),
            transition_matrix=cast(npt.ArrayLike, config["transition_matrix"]),
            initial_state=cast(int, config["initial_state"]),
        )
    elif process_type == "burst":
        return BurstDemand(
            **common,
            base_intensities=cast(npt.ArrayLike, config["base_intensities"]),
            burst_probability=cast(float, config["burst_probability"]),
            burst_duration_range=cast(Sequence[int], config["burst_duration_range"]),
            burst_amplitude_range=cast(Sequence[float], config["burst_amplitude_range"]),
            burst_zone_weights=cast(npt.ArrayLike, config["burst_zone_weights"]),
        )
    raise RuntimeError("内部工厂 schema 与分发不一致")
