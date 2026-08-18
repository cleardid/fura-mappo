"""需求轨迹的严格 JSON 统计汇总。"""

from __future__ import annotations

import math
from collections.abc import Iterable

from fura_mappo.demand.models import DemandTrace


def _online_statistics(values: Iterable[float | int]) -> dict[str, float | int | None]:
    """用 Welford 算法计算总体统计量。"""

    count = 0
    mean = 0.0
    squared_difference_sum = 0.0
    minimum: float | int | None = None
    maximum: float | int | None = None
    for raw_value in values:
        value = float(raw_value)
        count += 1
        delta = value - mean
        mean += delta / count
        squared_difference_sum += delta * (value - mean)
        if minimum is None or raw_value < minimum:
            minimum = raw_value
        if maximum is None or raw_value > maximum:
            maximum = raw_value
    if count == 0:
        return {
            "count": 0,
            "mean": None,
            "variance": None,
            "min": None,
            "max": None,
        }
    variance = squared_difference_sum / count
    if not math.isfinite(mean) or not math.isfinite(variance):
        raise ValueError("轨迹统计结果必须为有限值")
    return {
        "count": count,
        "mean": mean,
        "variance": max(0.0, variance),
        "min": minimum,
        "max": maximum,
    }


def summarize_demand_trace(trace: DemandTrace) -> dict[str, object]:
    """返回需求轨迹的 v1 严格 JSON 汇总。

    Args:
        trace: 计数和强度形状均为 ``[num_steps, num_zones]`` 的轨迹。

    Returns:
        仅含普通 JSON 类型、使用 ``ddof=0`` 总体方差的汇总树。
    """

    if not isinstance(trace, DemandTrace):
        raise TypeError("trace 必须是 DemandTrace")
    num_steps, num_zones = trace.counts.shape

    per_zone_total: list[int] = []
    per_zone_mean: list[float] = []
    per_zone_variance: list[float] = []
    per_zone_minimum: list[int] = []
    per_zone_maximum: list[int] = []
    per_zone_zero_fraction: list[float] = []
    intensity_mean: list[float] = []
    intensity_minimum: list[float] = []
    intensity_maximum: list[float] = []
    for zone in range(num_zones):
        count_values = [int(value) for value in trace.counts[:, zone]]
        count_stats = _online_statistics(count_values)
        total = sum(count_values)
        per_zone_total.append(total)
        per_zone_mean.append(float(count_stats["mean"]))
        per_zone_variance.append(float(count_stats["variance"]))
        per_zone_minimum.append(int(count_stats["min"]))
        per_zone_maximum.append(int(count_stats["max"]))
        per_zone_zero_fraction.append(sum(value == 0 for value in count_values) / num_steps)

        intensity_values = [float(value) for value in trace.intensities[:, zone]]
        intensity_stats = _online_statistics(intensity_values)
        intensity_mean.append(float(intensity_stats["mean"]))
        intensity_minimum.append(float(intensity_stats["min"]))
        intensity_maximum.append(float(intensity_stats["max"]))

    step_totals = [sum(int(value) for value in row) for row in trace.counts]
    step_stats = _online_statistics(step_totals)
    per_step_total = {
        "total": sum(step_totals),
        "mean": float(step_stats["mean"]),
        "variance": float(step_stats["variance"]),
        "min": int(step_stats["min"]),
        "max": int(step_stats["max"]),
        "zero_fraction": sum(value == 0 for value in step_totals) / num_steps,
    }

    def event_statistics(values: Iterable[float | int]) -> dict[str, object]:
        stats = _online_statistics(values)
        return {
            "count": stats["count"],
            "mean": stats["mean"],
            "variance": stats["variance"],
            "min": stats["min"],
            "max": stats["max"],
        }

    result: dict[str, object] = {
        "schema": "fura-mappo.demand-summary",
        "version": 1,
        "start_step": trace.start_step,
        "num_steps": num_steps,
        "num_zones": num_zones,
        "num_events": len(trace.events),
        "counts": {
            "per_zone": {
                "total": per_zone_total,
                "mean": per_zone_mean,
                "variance": per_zone_variance,
                "min": per_zone_minimum,
                "max": per_zone_maximum,
                "zero_fraction": per_zone_zero_fraction,
            },
            "per_step_total": per_step_total,
        },
        "intensity": {
            "per_zone": {
                "mean": intensity_mean,
                "min": intensity_minimum,
                "max": intensity_maximum,
            }
        },
        "events": {
            "priority": event_statistics(event.priority for event in trace.events),
            "service_time": event_statistics(event.service_time for event in trace.events),
            "deadline_offset": event_statistics(
                event.deadline - event.arrival_step for event in trace.events
            ),
        },
    }
    return result


__all__ = ["summarize_demand_trace"]
