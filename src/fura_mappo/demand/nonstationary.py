"""三类非平稳外生 Poisson 需求过程。"""

from __future__ import annotations

import math
from collections.abc import Sequence
from numbers import Real

import numpy as np
import numpy.typing as npt

from fura_mappo.demand.models import DemandStep, _contains_boolean
from fura_mappo.demand.processes import (
    _POISSON_LIMIT,
    _normalize_common_ranges,
    _normalize_integer_range,
    _normalize_intensity_vector,
    _normalize_numeric_array,
    _normalize_real_range,
    _normalize_zone_bounds,
    _PoissonDemandProcess,
)


def _set_read_only(*arrays: np.ndarray) -> None:
    """把防御性副本统一设为只读。"""

    for array in arrays:
        array.setflags(write=False)


def _validate_poisson_upper_bound(values: np.ndarray, name: str) -> None:
    """拒绝非有限或超过 NumPy Poisson 安全范围的保守上界。"""

    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} 的保守强度上界必须为有限值")
    if np.any(values > _POISSON_LIMIT):
        raise ValueError(f"{name} 的保守强度上界超出 NumPy Poisson 采样的安全范围")


def _reflect_coordinate(
    position: float,
    velocity: float,
    lower: float,
    upper: float,
) -> tuple[float, float]:
    """以周期折叠推进一个反射坐标，支持单步跨越任意多次边界。"""

    if velocity == 0.0:
        return position, velocity

    width = upper - lower
    period = 2.0 * width
    offset = position - lower
    phase = offset if velocity > 0.0 else period - offset
    phase_mod = math.fmod(phase, period)
    speed = abs(velocity)
    speed_mod = math.fmod(speed, period)

    # 分支加法避免两个小于 period 的正数相加溢出。
    distance_to_period = period - phase_mod
    if speed_mod >= distance_to_period:
        phase_next = speed_mod - distance_to_period
    else:
        phase_next = phase_mod + speed_mod

    if phase_next < width:
        reflected_position = lower + phase_next
        reflected_velocity = speed
    else:
        reflected_position = lower + (period - phase_next)
        reflected_velocity = -speed

    reflected_position = min(upper, max(lower, reflected_position))
    return reflected_position, reflected_velocity


class DriftingHotspotDemand(_PoissonDemandProcess):
    """以确定性反射热点调制逐区域强度的非平稳需求过程。"""

    def __init__(
        self,
        *,
        seed: int,
        base_intensities: npt.ArrayLike,
        hotspot_amplitudes: npt.ArrayLike,
        hotspot_scales: npt.ArrayLike,
        initial_hotspot_positions: npt.ArrayLike,
        hotspot_velocities: npt.ArrayLike,
        zone_bounds: npt.ArrayLike,
        priority_range: Sequence[float],
        service_time_range: Sequence[int],
        deadline_offset_range: Sequence[int],
    ) -> None:
        """验证配置并创建确定性漂移热点过程。

        Args:
            seed: 非负整数随机种子。
            base_intensities: 基础逐区域强度，形状 ``[num_zones]``，dtype
                规范化为 ``float64``。
            hotspot_amplitudes: 各热点每步增加的总到达率，形状
                ``[num_hotspots]``，dtype 规范化为 ``float64``。
            hotspot_scales: 各向同性高斯尺度，形状 ``[num_hotspots]``，dtype
                规范化为 ``float64``。
            initial_hotspot_positions: 初始二维位置，形状
                ``[num_hotspots, 2]``，dtype 规范化为 ``float64``。
            hotspot_velocities: 每步二维速度，形状 ``[num_hotspots, 2]``，dtype
                规范化为 ``float64``。
            zone_bounds: 半开矩形区域，形状 ``[num_zones, 4]``，dtype
                规范化为 ``float64``。
            priority_range: 连续均匀优先级的闭区间配置。
            service_time_range: 离散均匀服务时长的闭区间配置。
            deadline_offset_range: 离散均匀截止偏移的闭区间配置。
        """

        normalized_base = _normalize_intensity_vector(base_intensities, "base_intensities")
        normalized_amplitudes = _normalize_numeric_array(
            hotspot_amplitudes, "hotspot_amplitudes", 1
        )
        if normalized_amplitudes.size < 1:
            raise ValueError("hotspot_amplitudes 必须至少包含一个热点")
        if np.any(normalized_amplitudes < 0.0):
            raise ValueError("hotspot_amplitudes 必须全部非负")

        num_hotspots = normalized_amplitudes.size
        normalized_scales = _normalize_numeric_array(hotspot_scales, "hotspot_scales", 1)
        if normalized_scales.shape != (num_hotspots,):
            raise ValueError("hotspot_scales 必须与热点数量一致")
        if np.any(normalized_scales <= 0.0):
            raise ValueError("hotspot_scales 必须全部严格大于零")

        normalized_positions = _normalize_numeric_array(
            initial_hotspot_positions, "initial_hotspot_positions", 2
        )
        normalized_velocities = _normalize_numeric_array(
            hotspot_velocities, "hotspot_velocities", 2
        )
        expected_hotspot_shape = (num_hotspots, 2)
        if normalized_positions.shape != expected_hotspot_shape:
            raise ValueError("initial_hotspot_positions 形状必须为 [num_hotspots, 2]")
        if normalized_velocities.shape != expected_hotspot_shape:
            raise ValueError("hotspot_velocities 形状必须为 [num_hotspots, 2]")

        normalized_bounds = _normalize_zone_bounds(
            zone_bounds,
            normalized_base.size,
            "base_intensities",
        )
        normalized_priority, normalized_service, normalized_deadline = _normalize_common_ranges(
            priority_range,
            service_time_range,
            deadline_offset_range,
        )

        widths = normalized_bounds[:, 1] - normalized_bounds[:, 0]
        heights = normalized_bounds[:, 3] - normalized_bounds[:, 2]
        centers = np.column_stack(
            (
                normalized_bounds[:, 0] + 0.5 * widths,
                normalized_bounds[:, 2] + 0.5 * heights,
            )
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            log_areas = np.log(widths) + np.log(heights)
        if not np.all(np.isfinite(centers)) or not np.all(np.isfinite(log_areas)):
            raise ValueError("zone_bounds 无法安全计算区域中心或对数面积")

        domain_lower = np.array(
            [np.min(normalized_bounds[:, 0]), np.min(normalized_bounds[:, 2])],
            dtype=np.float64,
        )
        domain_upper = np.array(
            [np.max(normalized_bounds[:, 1]), np.max(normalized_bounds[:, 3])],
            dtype=np.float64,
        )
        with np.errstate(over="ignore", invalid="ignore"):
            domain_spans = domain_upper - domain_lower
            reflection_periods = 2.0 * domain_spans
        if (
            not np.all(np.isfinite(domain_spans))
            or np.any(domain_spans <= 0.0)
            or not np.all(np.isfinite(reflection_periods))
            or np.any(reflection_periods <= 0.0)
        ):
            raise ValueError("zone_bounds 的外包矩形跨度和反射周期必须安全且为正")
        if np.any(normalized_positions < domain_lower) or np.any(
            normalized_positions > domain_upper
        ):
            raise ValueError("initial_hotspot_positions 必须位于外包矩形闭边界内")

        try:
            amplitude_sum = math.fsum(float(value) for value in normalized_amplitudes)
        except OverflowError as error:
            raise ValueError("hotspot_amplitudes 总和必须为有限值") from error
        if not math.isfinite(amplitude_sum):
            raise ValueError("hotspot_amplitudes 总和必须为有限值")
        with np.errstate(over="ignore", invalid="ignore"):
            conservative_bound = normalized_base + amplitude_sum
        _validate_poisson_upper_bound(conservative_bound, "DriftingHotspotDemand")

        # 热点可遍历整个外包矩形；预先验证最坏距离的缩放平方和与 log weight。
        for hotspot_index, scale in enumerate(normalized_scales):
            if normalized_amplitudes[hotspot_index] == 0.0:
                continue
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                max_dx = np.maximum(
                    np.abs(domain_lower[0] - centers[:, 0]),
                    np.abs(domain_upper[0] - centers[:, 0]),
                )
                max_dy = np.maximum(
                    np.abs(domain_lower[1] - centers[:, 1]),
                    np.abs(domain_upper[1] - centers[:, 1]),
                )
                worst_energy = 0.5 * (np.square(max_dx / scale) + np.square(max_dy / scale))
                worst_log_weight = log_areas - worst_energy
            if not np.all(np.isfinite(worst_energy)) or not np.all(np.isfinite(worst_log_weight)):
                raise ValueError("hotspot_scales 与外包矩形组合无法安全计算 float64 高斯权重")

        _set_read_only(
            normalized_base,
            normalized_amplitudes,
            normalized_scales,
            normalized_positions,
            normalized_velocities,
            centers,
            log_areas,
            domain_lower,
            domain_upper,
            reflection_periods,
        )
        self._base_intensities = normalized_base
        self._hotspot_amplitudes = normalized_amplitudes
        self._hotspot_scales = normalized_scales
        self._initial_hotspot_positions = normalized_positions
        self._initial_hotspot_velocities = normalized_velocities
        self._zone_centers = centers
        self._zone_log_areas = log_areas
        self._domain_lower = domain_lower
        self._domain_upper = domain_upper
        self._reflection_periods = reflection_periods

        super().__init__(
            seed=seed,
            num_zones=normalized_base.size,
            zone_bounds=normalized_bounds,
            priority_range=normalized_priority,
            service_time_range=normalized_service,
            deadline_offset_range=normalized_deadline,
            zone_reference_name="base_intensities",
        )
        self._reset_process_state()

    def _reset_process_state(self) -> None:
        """原子地恢复显式配置的初始热点位置和速度。"""

        positions = np.array(self._initial_hotspot_positions, copy=True)
        velocities = np.array(self._initial_hotspot_velocities, copy=True)
        self._hotspot_positions, self._hotspot_velocities = positions, velocities

    def _calculate_intensities(self) -> np.ndarray:
        """由当前热点位置计算 ``float64[num_zones]`` 强度。"""

        intensities = np.array(self._base_intensities, copy=True)
        for hotspot_index, amplitude in enumerate(self._hotspot_amplitudes):
            if amplitude == 0.0:
                continue
            scale = self._hotspot_scales[hotspot_index]
            displacement = self._zone_centers - self._hotspot_positions[hotspot_index]
            with np.errstate(over="ignore", invalid="ignore"):
                scaled_distance = displacement / scale
                log_weights = self._zone_log_areas - 0.5 * np.sum(
                    np.square(scaled_distance), axis=1
                )
            if not np.all(np.isfinite(log_weights)):
                raise ValueError("当前热点状态无法安全计算有限高斯 log weight")

            shifted_weights = np.exp(log_weights - np.max(log_weights))
            weight_sum = math.fsum(float(value) for value in shifted_weights)
            if not math.isfinite(weight_sum) or weight_sum <= 0.0:
                raise ValueError("当前热点状态无法形成有效的区域归一化权重")
            normalized_weights = shifted_weights / weight_sum
            correction_index = int(np.argmax(normalized_weights))
            normalized_weights[correction_index] += 1.0 - math.fsum(
                float(value) for value in normalized_weights
            )
            intensities += float(amplitude) * normalized_weights
        return intensities

    def _advance_hotspots(self) -> tuple[np.ndarray, np.ndarray]:
        """计算但不提交下一步热点位置和速度。"""

        positions = np.empty_like(self._hotspot_positions)
        velocities = np.empty_like(self._hotspot_velocities)
        for hotspot_index in range(self._hotspot_positions.shape[0]):
            for dimension in range(2):
                position, velocity = _reflect_coordinate(
                    float(self._hotspot_positions[hotspot_index, dimension]),
                    float(self._hotspot_velocities[hotspot_index, dimension]),
                    float(self._domain_lower[dimension]),
                    float(self._domain_upper[dimension]),
                )
                positions[hotspot_index, dimension] = position
                velocities[hotspot_index, dimension] = velocity
        return positions, velocities

    def _sample_step(self, step: int, first_event_id: int) -> DemandStep:
        """按当前热点发射，完整 Step 成功后再提交反射移动。"""

        intensities = self._calculate_intensities()
        result = self._build_demand_step(step, first_event_id, intensities)
        positions, velocities = self._advance_hotspots()
        self._hotspot_positions, self._hotspot_velocities = positions, velocities
        return result


def _normalize_state_intensities(value: object) -> np.ndarray:
    """验证 ``float64[num_states, num_zones]`` 状态强度矩阵。"""

    normalized = _normalize_numeric_array(value, "state_intensities", 2)
    if normalized.shape[0] < 1 or normalized.shape[1] < 1:
        raise ValueError("state_intensities 必须至少包含一个状态和一个区域")
    if np.any(normalized < 0.0):
        raise ValueError("state_intensities 必须全部非负")
    if np.any(normalized > _POISSON_LIMIT):
        raise ValueError("state_intensities 超出 NumPy Poisson 采样的安全范围")
    return normalized


def _normalize_transition_matrix(value: object, num_states: int) -> np.ndarray:
    """按源浮点 dtype 的明确容差验证并微量归一化转移矩阵。"""

    if _contains_boolean(value):
        raise TypeError("transition_matrix 不能包含布尔值")
    source = np.asarray(value)
    if source.ndim != 2:
        raise ValueError("transition_matrix 必须是二维方阵")
    if source.shape != (num_states, num_states):
        raise ValueError("transition_matrix 形状必须为 [num_states, num_states]")
    if not (np.issubdtype(source.dtype, np.integer) or np.issubdtype(source.dtype, np.floating)):
        raise TypeError("transition_matrix 必须包含实数")

    normalized = np.array(source, dtype=np.float64, copy=True)
    if not np.all(np.isfinite(normalized)):
        raise ValueError("transition_matrix 必须全部为有限值")
    if np.any(normalized < 0.0):
        raise ValueError("transition_matrix 必须全部非负")

    if np.issubdtype(source.dtype, np.integer):
        for row in normalized:
            if np.count_nonzero(row == 1.0) != 1 or np.count_nonzero(row) != 1:
                raise ValueError("整数 transition_matrix 每行必须是精确 one-hot")
    else:
        source_epsilon = float(np.finfo(source.dtype).eps)
        tolerance = max(1e-12, min(1e-6, 8.0 * num_states * source_epsilon))
        for row in normalized:
            row_sum = math.fsum(float(item) for item in row)
            if not math.isfinite(row_sum) or abs(row_sum - 1.0) > tolerance:
                raise ValueError(f"transition_matrix 每行和必须在绝对容差 {tolerance:g} 内等于 1")

    for row_index in range(num_states):
        row_sum = math.fsum(float(item) for item in normalized[row_index])
        normalized[row_index] /= row_sum
    return normalized


class MarkovSwitchingDemand(_PoissonDemandProcess):
    """由有限状态 Markov 链切换逐区域强度的需求过程。"""

    def __init__(
        self,
        *,
        seed: int,
        state_intensities: npt.ArrayLike,
        transition_matrix: npt.ArrayLike,
        initial_state: int,
        zone_bounds: npt.ArrayLike,
        priority_range: Sequence[float],
        service_time_range: Sequence[int],
        deadline_offset_range: Sequence[int],
    ) -> None:
        """验证配置并创建有限状态 Markov 切换过程。

        Args:
            seed: 非负整数随机种子。
            state_intensities: 状态逐区域强度，形状
                ``[num_states, num_zones]``，dtype 规范化为 ``float64``。
            transition_matrix: 行随机转移矩阵，形状
                ``[num_states, num_states]``，dtype 规范化为 ``float64``。
            initial_state: reset 后首个发射时间步使用的显式状态编号。
            zone_bounds: 半开矩形区域，形状 ``[num_zones, 4]``，dtype
                规范化为 ``float64``。
            priority_range: 连续均匀优先级的闭区间配置。
            service_time_range: 离散均匀服务时长的闭区间配置。
            deadline_offset_range: 离散均匀截止偏移的闭区间配置。
        """

        normalized_intensities = _normalize_state_intensities(state_intensities)
        num_states, num_zones = normalized_intensities.shape
        normalized_transition = _normalize_transition_matrix(transition_matrix, num_states)
        if isinstance(initial_state, (bool, np.bool_)) or not isinstance(
            initial_state, (int, np.integer)
        ):
            raise TypeError("initial_state 必须是整数且不能是布尔值")
        normalized_initial_state = int(initial_state)
        if not 0 <= normalized_initial_state < num_states:
            raise ValueError("initial_state 必须位于 [0, num_states) 范围内")

        normalized_bounds = _normalize_zone_bounds(
            zone_bounds,
            num_zones,
            "state_intensities",
        )
        normalized_priority, normalized_service, normalized_deadline = _normalize_common_ranges(
            priority_range,
            service_time_range,
            deadline_offset_range,
        )

        _set_read_only(normalized_intensities, normalized_transition)
        self._state_intensities = normalized_intensities
        self._transition_matrix = normalized_transition
        self._initial_state = normalized_initial_state
        super().__init__(
            seed=seed,
            num_zones=num_zones,
            zone_bounds=normalized_bounds,
            priority_range=normalized_priority,
            service_time_range=normalized_service,
            deadline_offset_range=normalized_deadline,
            zone_reference_name="state_intensities",
        )
        self._reset_process_state()

    def _reset_process_state(self) -> None:
        """恢复显式初始状态。"""

        current_state = self._initial_state
        self._current_state = current_state

    def _sample_step(self, step: int, first_event_id: int) -> DemandStep:
        """按当前状态发射，完整 Step 成功后再采样并提交转移。"""

        current_state = self._current_state
        result = self._build_demand_step(
            step,
            first_event_id,
            self._state_intensities[current_state],
        )
        probabilities = self._transition_matrix[current_state]
        positive_states = np.flatnonzero(probabilities > 0.0)
        if positive_states.size == 1:
            next_state = int(positive_states[0])
        else:
            next_state = int(self._rng.choice(self._state_intensities.shape[0], p=probabilities))
        self._current_state = next_state
        return result


class BurstDemand(_PoissonDemandProcess):
    """以非重叠加法 burst 调制显式空间模式的需求过程。"""

    def __init__(
        self,
        *,
        seed: int,
        base_intensities: npt.ArrayLike,
        burst_probability: float,
        burst_duration_range: Sequence[int],
        burst_amplitude_range: Sequence[float],
        burst_zone_weights: npt.ArrayLike,
        zone_bounds: npt.ArrayLike,
        priority_range: Sequence[float],
        service_time_range: Sequence[int],
        deadline_offset_range: Sequence[int],
    ) -> None:
        """验证配置并创建非重叠加法 burst 过程。

        Args:
            seed: 非负整数随机种子。
            base_intensities: 基础逐区域强度，形状 ``[num_zones]``，dtype
                规范化为 ``float64``。
            burst_probability: 空闲时间步启动 burst 的 Bernoulli 概率。
            burst_duration_range: burst 持续时间的闭整数范围。
            burst_amplitude_range: 每个活动步增加总到达率的闭实数范围。
            burst_zone_weights: 增量空间权重，形状 ``[num_zones]``，dtype
                规范化并归一化为 ``float64``。
            zone_bounds: 半开矩形区域，形状 ``[num_zones, 4]``，dtype
                规范化为 ``float64``。
            priority_range: 连续均匀优先级的闭区间配置。
            service_time_range: 离散均匀服务时长的闭区间配置。
            deadline_offset_range: 离散均匀截止偏移的闭区间配置。
        """

        normalized_base = _normalize_intensity_vector(base_intensities, "base_intensities")
        if isinstance(burst_probability, (bool, np.bool_)) or not isinstance(
            burst_probability, Real
        ):
            raise TypeError("burst_probability 必须是实数且不能是布尔值")
        normalized_probability = float(burst_probability)
        if not math.isfinite(normalized_probability):
            raise ValueError("burst_probability 必须是有限值")
        if not 0.0 <= normalized_probability <= 1.0:
            raise ValueError("burst_probability 必须位于 [0, 1]")

        normalized_duration = _normalize_integer_range(burst_duration_range, "burst_duration_range")
        if not 1 <= normalized_duration[0] <= normalized_duration[1]:
            raise ValueError("burst_duration_range 必须满足 1 <= low <= high")
        if normalized_duration[1] > int(np.iinfo(np.int64).max):
            raise ValueError("burst_duration_range 上界不能超过 int64 最大值")

        normalized_amplitude = _normalize_real_range(burst_amplitude_range, "burst_amplitude_range")
        if not 0.0 <= normalized_amplitude[0] <= normalized_amplitude[1]:
            raise ValueError("burst_amplitude_range 必须满足 0 <= low <= high")

        normalized_weights = _normalize_numeric_array(burst_zone_weights, "burst_zone_weights", 1)
        if normalized_weights.shape != normalized_base.shape:
            raise ValueError("burst_zone_weights 必须与 base_intensities 区域数一致")
        if np.any(normalized_weights < 0.0):
            raise ValueError("burst_zone_weights 必须全部非负")
        max_weight = float(np.max(normalized_weights))
        if max_weight <= 0.0:
            raise ValueError("burst_zone_weights 必须至少有一个严格正值")
        scaled_weights = normalized_weights / max_weight
        scaled_sum = math.fsum(float(value) for value in scaled_weights)
        normalized_weights = scaled_weights / scaled_sum
        correction_index = int(np.argmax(normalized_weights))
        normalized_weights[correction_index] += 1.0 - math.fsum(
            float(value) for value in normalized_weights
        )
        if not np.all(np.isfinite(normalized_weights)) or np.any(normalized_weights < 0.0):
            raise ValueError("burst_zone_weights 无法安全归一化")

        normalized_bounds = _normalize_zone_bounds(
            zone_bounds,
            normalized_base.size,
            "base_intensities",
        )
        normalized_priority, normalized_service, normalized_deadline = _normalize_common_ranges(
            priority_range,
            service_time_range,
            deadline_offset_range,
        )
        with np.errstate(over="ignore", invalid="ignore"):
            conservative_bound = normalized_base + normalized_amplitude[1] * normalized_weights
        _validate_poisson_upper_bound(conservative_bound, "BurstDemand")

        _set_read_only(normalized_base, normalized_weights)
        self._base_intensities = normalized_base
        self._burst_probability = normalized_probability
        self._burst_duration_range = normalized_duration
        self._burst_amplitude_range = normalized_amplitude
        self._burst_zone_weights = normalized_weights
        super().__init__(
            seed=seed,
            num_zones=normalized_base.size,
            zone_bounds=normalized_bounds,
            priority_range=normalized_priority,
            service_time_range=normalized_service,
            deadline_offset_range=normalized_deadline,
            zone_reference_name="base_intensities",
        )
        self._reset_process_state()

    def _reset_process_state(self) -> None:
        """原子地清除活动 burst。"""

        remaining_duration = 0
        active_amplitude = 0.0
        self._remaining_duration, self._active_amplitude = (
            remaining_duration,
            active_amplitude,
        )

    def _sample_burst_amplitude(self) -> float:
        """采样 burst 幅度；退化范围不消费 Generator。"""

        low, high = self._burst_amplitude_range
        if low == high:
            return low
        return float(self._rng.uniform(low, high))

    def _sample_step(self, step: int, first_event_id: int) -> DemandStep:
        """在局部候选 burst 状态上发射，成功后递减并提交生命周期。"""

        remaining_duration = self._remaining_duration
        active_amplitude = self._active_amplitude
        if remaining_duration == 0:
            if self._burst_probability == 0.0:
                starts_burst = False
            elif self._burst_probability == 1.0:
                starts_burst = True
            else:
                starts_burst = bool(self._rng.random() < self._burst_probability)

            if starts_burst:
                remaining_duration = int(
                    self._sample_integer_range(self._burst_duration_range, 1)[0]
                )
                active_amplitude = self._sample_burst_amplitude()

        intensities = np.array(self._base_intensities, copy=True)
        if remaining_duration > 0:
            intensities += active_amplitude * self._burst_zone_weights
        result = self._build_demand_step(step, first_event_id, intensities)

        if remaining_duration > 0:
            remaining_duration -= 1
            if remaining_duration == 0:
                active_amplitude = 0.0
        self._remaining_duration, self._active_amplitude = (
            remaining_duration,
            active_amplitude,
        )
        return result
