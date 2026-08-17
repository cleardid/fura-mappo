"""需求过程的最小配置工厂。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

import numpy.typing as npt

from fura_mappo.demand.processes import DemandProcess, StationaryPoissonDemand

_PROCESS_TYPE = "stationary_poisson"
_REQUIRED_FIELDS = frozenset(
    {
        "type",
        "seed",
        "intensities",
        "zone_bounds",
        "priority_range",
        "service_time_range",
        "deadline_offset_range",
    }
)


def _format_fields(fields: set[object]) -> str:
    """稳定格式化配置字段集合。"""

    return ", ".join(sorted(repr(field) for field in fields))


def create_demand_process(config: Mapping[str, object]) -> DemandProcess:
    """根据只读配置创建需求过程，不修改调用方对象。

    Args:
        config: 包含 ``type`` 及过程完整参数的映射。数组分别具有
            ``intensities[num_zones]`` 和 ``zone_bounds[num_zones, 4]`` 形状。

    Returns:
        与配置类型对应的独立需求过程。

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
    if process_type != _PROCESS_TYPE:
        raise ValueError(f"未知需求过程类型 {process_type!r}；支持的类型为 {_PROCESS_TYPE!r}")

    config_fields = set(config.keys())
    missing_fields = set(_REQUIRED_FIELDS) - config_fields
    if missing_fields:
        raise ValueError(f"config 缺少必需字段: {_format_fields(missing_fields)}")
    extra_fields = config_fields - set(_REQUIRED_FIELDS)
    if extra_fields:
        raise ValueError(f"config 包含多余字段: {_format_fields(extra_fields)}")

    return StationaryPoissonDemand(
        seed=cast(int, config["seed"]),
        intensities=cast(npt.ArrayLike, config["intensities"]),
        zone_bounds=cast(npt.ArrayLike, config["zone_bounds"]),
        priority_range=cast(Sequence[float], config["priority_range"]),
        service_time_range=cast(Sequence[int], config["service_time_range"]),
        deadline_offset_range=cast(Sequence[int], config["deadline_offset_range"]),
    )
