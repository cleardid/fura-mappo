from __future__ import annotations

import random

import numpy as np
import pytest

from fura_mappo.demand import DemandTrace, DriftingHotspotDemand


def _process(
    *,
    seed: int = 20260817,
    base_intensities: object = (0.3, 0.4),
    hotspot_amplitudes: object = (0.8,),
    hotspot_scales: object = (0.7,),
    initial_hotspot_positions: object = ((0.25, 0.5),),
    hotspot_velocities: object = ((0.4, 0.0),),
    zone_bounds: object = ((0.0, 1.0, 0.0, 1.0), (1.0, 3.0, 0.0, 1.0)),
    priority_range: object = (0.2, 0.8),
    service_time_range: object = (1, 4),
    deadline_offset_range: object = (2, 6),
) -> DriftingHotspotDemand:
    return DriftingHotspotDemand(
        seed=seed,
        base_intensities=base_intensities,  # type: ignore[arg-type]
        hotspot_amplitudes=hotspot_amplitudes,  # type: ignore[arg-type]
        hotspot_scales=hotspot_scales,  # type: ignore[arg-type]
        initial_hotspot_positions=initial_hotspot_positions,  # type: ignore[arg-type]
        hotspot_velocities=hotspot_velocities,  # type: ignore[arg-type]
        zone_bounds=zone_bounds,  # type: ignore[arg-type]
        priority_range=priority_range,  # type: ignore[arg-type]
        service_time_range=service_time_range,  # type: ignore[arg-type]
        deadline_offset_range=deadline_offset_range,  # type: ignore[arg-type]
    )


def _assert_traces_equal(left: DemandTrace, right: DemandTrace) -> None:
    assert left.start_step == right.start_step
    np.testing.assert_array_equal(left.counts, right.counts)
    np.testing.assert_array_equal(left.intensities, right.intensities)
    assert left.events == right.events


def _assert_numpy_states_equal(left: tuple[object, ...], right: tuple[object, ...]) -> None:
    assert left[0] == right[0]
    np.testing.assert_array_equal(left[1], right[1])
    assert left[2:] == right[2:]


def _reference_intensity(
    bounds: np.ndarray,
    base: np.ndarray,
    amplitudes: np.ndarray,
    scales: np.ndarray,
    positions: np.ndarray,
) -> np.ndarray:
    """用独立直写公式计算中心点面积近似强度。"""

    widths = bounds[:, 1] - bounds[:, 0]
    heights = bounds[:, 3] - bounds[:, 2]
    centers = np.column_stack((bounds[:, 0] + widths / 2.0, bounds[:, 2] + heights / 2.0))
    result = np.array(base, dtype=np.float64, copy=True)
    for amplitude, scale, position in zip(amplitudes, scales, positions, strict=True):
        if amplitude == 0.0:
            continue
        squared_distance = np.sum(np.square((centers - position) / scale), axis=1)
        log_weights = np.log(widths) + np.log(heights) - 0.5 * squared_distance
        weights = np.exp(log_weights - np.max(log_weights))
        weights /= weights.sum()
        result += amplitude * weights
    return result


def _reference_reflection(
    position: float,
    velocity: float,
    lower: float,
    upper: float,
) -> tuple[float, float]:
    """以逐次触壁方式独立计算测试规模内的反射。"""

    if velocity == 0.0:
        return position, velocity
    direction = 1.0 if velocity > 0.0 else -1.0
    remaining = abs(velocity)
    current = position
    while remaining > 0.0:
        boundary = upper if direction > 0.0 else lower
        available = abs(boundary - current)
        if available == 0.0:
            direction *= -1.0
            continue
        if remaining <= available:
            current += direction * remaining
            remaining = 0.0
            if current == upper:
                direction = -1.0
            elif current == lower:
                direction = 1.0
        else:
            current = boundary
            remaining -= available
            direction *= -1.0
    return current, direction * abs(velocity)


def test_same_seed_reset_generate_and_interleaving_are_reproducible() -> None:
    first = _process(seed=101)
    second = _process(seed=101)
    _assert_traces_equal(first.generate(12), second.generate(12))

    replayed = first.generate(12, seed=202)
    _assert_traces_equal(replayed, _process(seed=202).generate(12))
    assert first.base_seed == 202
    first.reset()
    _assert_traces_equal(first.generate(12), _process(seed=202).generate(12))

    interleaved = _process(seed=33)
    control = _process(seed=33)
    np.testing.assert_array_equal(interleaved.step().counts, control.step().counts)
    _process(seed=91).generate(5)
    _assert_traces_equal(interleaved.generate(5), control.generate(5))


def test_different_fixed_seeds_produce_different_trajectories() -> None:
    first = _process(seed=11).generate(40)
    second = _process(seed=29).generate(40)

    assert not np.array_equal(first.counts, second.counts) or first.events != second.events


def test_continuous_step_and_generate_state_semantics() -> None:
    process = _process(seed=71)
    control = _process(seed=71)

    first = process.generate(2)
    second = process.generate(3)
    combined = control.generate(5)

    assert first.start_step == 0
    assert second.start_step == 2
    np.testing.assert_array_equal(
        np.vstack((first.intensities, second.intensities)), combined.intensities
    )
    np.testing.assert_array_equal(np.vstack((first.counts, second.counts)), combined.counts)
    assert first.events + second.events == combined.events
    assert process.current_step == 5
    assert process.next_event_id == len(combined.events)


def test_operations_do_not_pollute_global_random_states() -> None:
    numpy_state = np.random.get_state()
    python_state = random.getstate()

    process = _process()
    process.step()
    process.generate(3)
    process.reset()
    process.reset(9)

    _assert_numpy_states_equal(numpy_state, np.random.get_state())
    assert python_state == random.getstate()


def test_output_geometry_attributes_counts_and_read_only_arrays() -> None:
    first_step = _process().step()
    assert not first_step.counts.flags.writeable
    assert not first_step.intensity.flags.writeable
    bounds = np.array([[0.0, 1.0, -1.0, 0.0], [4.0, 6.0, 2.0, 5.0]])
    trace = _process(
        base_intensities=(2.0, 3.0),
        hotspot_amplitudes=(1.0,),
        initial_hotspot_positions=((0.5, 0.0),),
        hotspot_velocities=((0.2, 0.1),),
        zone_bounds=bounds,
        priority_range=(0.25, 0.75),
        service_time_range=(2, 5),
        deadline_offset_range=(3, 8),
    ).generate(20)

    assert trace.counts.shape == (20, 2)
    assert trace.intensities.shape == (20, 2)
    assert trace.counts.dtype == np.int64
    assert trace.intensities.dtype == np.float64
    assert not trace.counts.flags.writeable
    assert not trace.intensities.flags.writeable
    assert np.all(np.isfinite(trace.intensities))
    assert np.all(trace.intensities >= 0.0)
    assert int(trace.counts.sum()) == len(trace.events)
    assert [event.event_id for event in trace.events] == list(range(len(trace.events)))
    for event in trace.events:
        x_min, x_max, y_min, y_max = bounds[event.zone_id]
        assert x_min <= event.position[0] < x_max
        assert y_min <= event.position[1] < y_max
        assert 0.25 <= event.priority <= 0.75
        assert 2 <= event.service_time <= 5
        assert 3 <= event.deadline - event.arrival_step <= 8
    for row, absolute_step in enumerate(range(20)):
        for zone_id in range(2):
            expected = sum(
                event.arrival_step == absolute_step and event.zone_id == zone_id
                for event in trace.events
            )
            assert trace.counts[row, zone_id] == expected


def test_inputs_and_returned_arrays_cannot_change_reset_replay() -> None:
    base = np.array([0.3, 0.4])
    amplitudes = np.array([0.8])
    scales = np.array([0.7])
    positions = np.array([[0.25, 0.5]])
    velocities = np.array([[0.4, 0.0]])
    bounds = np.array([[0.0, 1.0, 0.0, 1.0], [1.0, 3.0, 0.0, 1.0]])
    process = _process(
        base_intensities=base,
        hotspot_amplitudes=amplitudes,
        hotspot_scales=scales,
        initial_hotspot_positions=positions,
        hotspot_velocities=velocities,
        zone_bounds=bounds,
    )
    control = _process()
    for array in (base, amplitudes, scales, positions, velocities, bounds):
        array[...] = 99.0

    produced = process.generate(6)
    _assert_traces_equal(produced, control.generate(6))
    produced.counts.setflags(write=True)
    produced.intensities.setflags(write=True)
    produced.counts[:] = 999
    produced.intensities[:] = 999.0
    process.reset()
    control.reset()
    _assert_traces_equal(process.generate(6), control.generate(6))


def test_step_zero_uses_initial_position_area_factor_and_reference_formula() -> None:
    bounds = np.array([[0.0, 1.0, 0.0, 1.0], [1.0, 3.0, 0.0, 1.0]])
    base = np.array([0.2, 0.3])
    amplitudes = np.array([1.5])
    scales = np.array([0.8])
    positions = np.array([[0.5, 0.5]])
    step = _process(
        base_intensities=base,
        hotspot_amplitudes=amplitudes,
        hotspot_scales=scales,
        initial_hotspot_positions=positions,
        hotspot_velocities=((2.0, 0.0),),
        zone_bounds=bounds,
    ).step()
    expected = _reference_intensity(bounds, base, amplitudes, scales, positions)

    np.testing.assert_allclose(step.intensity, expected, rtol=1e-14, atol=1e-14)
    assert expected[1] - base[1] > 0.0
    assert np.isclose(step.intensity.sum(), base.sum() + amplitudes.sum(), rtol=1e-14)


def test_zero_velocity_and_extremely_narrow_legal_scale_remain_finite() -> None:
    trace = _process(
        base_intensities=(0.1, 0.2),
        hotspot_amplitudes=(0.5,),
        hotspot_scales=(1e-150,),
        initial_hotspot_positions=((0.5, 0.5),),
        hotspot_velocities=((0.0, 0.0),),
    ).generate(5)

    assert np.all(np.isfinite(trace.intensities))
    np.testing.assert_array_equal(
        trace.intensities,
        np.repeat(trace.intensities[:1], 5, axis=0),
    )
    np.testing.assert_allclose(trace.intensities.sum(axis=1), 0.8, rtol=1e-14)


@pytest.mark.parametrize(
    ("position", "velocity"),
    [
        (2.0, 3.0),
        (7.0, -3.0),
        (10.0, -3.0),
        (10.0, 3.0),
        (0.0, 3.0),
        (0.0, -3.0),
        (7.0, 3.0),
        (3.0, -3.0),
        (2.0, 37.0),
        (8.0, -37.0),
        (4.0, 0.0),
    ],
)
def test_reflection_matches_independent_reference(position: float, velocity: float) -> None:
    process = _process(
        base_intensities=(0.0,),
        hotspot_amplitudes=(0.0,),
        hotspot_scales=(1.0,),
        initial_hotspot_positions=((position, 0.5),),
        hotspot_velocities=((velocity, 0.0),),
        zone_bounds=((0.0, 10.0, 0.0, 1.0),),
    )
    expected_position, expected_velocity = _reference_reflection(position, velocity, 0.0, 10.0)

    process.step()

    assert process._hotspot_positions[0, 0] == expected_position
    assert process._hotspot_velocities[0, 0] == expected_velocity


def test_zero_amplitude_hotspot_still_moves_and_reset_restores_hidden_state() -> None:
    process = _process(
        hotspot_amplitudes=(0.0,),
        hotspot_scales=(1e-200,),
        initial_hotspot_positions=((0.25, 0.5),),
        hotspot_velocities=((0.4, 0.0),),
    )
    first = process.step()

    assert process._hotspot_positions[0, 0] == pytest.approx(0.65)
    process.generate(4)
    process.reset()
    assert process._hotspot_positions[0, 0] == 0.25
    assert process._hotspot_velocities[0, 0] == 0.4
    np.testing.assert_array_equal(process.step().intensity, first.intensity)


@pytest.mark.parametrize("boolean", [True, np.bool_(True)])
def test_mixed_boolean_arrays_are_rejected(boolean: object) -> None:
    with pytest.raises(TypeError, match="布尔"):
        _process(base_intensities=[0.3, boolean])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="布尔"):
        _process(hotspot_amplitudes=[0.8, boolean])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="布尔"):
        _process(hotspot_scales=[boolean])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="布尔"):
        _process(initial_hotspot_positions=[[0.25, boolean]])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="布尔"):
        _process(hotspot_velocities=[[boolean, 0.0]])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="布尔"):
        _process(zone_bounds=[[0.0, 1.0, 0.0, boolean], [1.0, 3.0, 0.0, 1.0]])


@pytest.mark.parametrize(
    "overrides",
    [
        {"hotspot_amplitudes": (-0.1,)},
        {"hotspot_amplitudes": ()},
        {"hotspot_scales": (0.0,)},
        {"hotspot_scales": (1.0, 2.0)},
        {"initial_hotspot_positions": ((4.0, 0.5),)},
        {"initial_hotspot_positions": ((0.5,),)},
        {"hotspot_velocities": ((np.inf, 0.0),)},
        {"hotspot_velocities": ((0.0,),)},
        {"base_intensities": (np.nan, 0.2)},
        {"base_intensities": (np.inf, 0.2)},
        {"base_intensities": (float(np.iinfo(np.int64).max), 0.2)},
        {"zone_bounds": ((0.0, 1.0, 0.0, 1.0),)},
    ],
)
def test_invalid_hotspot_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _process(**overrides)


def test_unsafe_domain_period_and_scaled_distance_are_rejected() -> None:
    with pytest.raises(ValueError, match="跨度|反射周期"):
        _process(
            base_intensities=(0.1,),
            initial_hotspot_positions=((0.0, 0.5),),
            zone_bounds=((-1e308, 1e308, 0.0, 1.0),),
        )
    with pytest.raises(ValueError, match="高斯权重"):
        _process(hotspot_scales=(1e-200,))


def test_nonfinite_hotspot_amplitude_sum_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="总和"):
        _process(
            hotspot_amplitudes=(1e308, 1e308),
            hotspot_scales=(1.0, 1.0),
            initial_hotspot_positions=((0.25, 0.5), (0.75, 0.5)),
            hotspot_velocities=((0.0, 0.0), (0.0, 0.0)),
        )


def test_long_run_poisson_means_follow_independent_moving_reference() -> None:
    seed = 314159
    num_steps = 20_000
    bounds = np.array([[0.0, 1.0, 0.0, 1.0], [1.0, 2.5, 0.0, 1.0], [2.5, 3.0, 0.0, 1.0]])
    base = np.array([0.1, 0.2, 0.2])
    amplitudes = np.array([1.0])
    scales = np.array([0.6])
    positions = np.array([[0.3, 0.4]])
    velocities = np.array([[0.37, 0.13]])
    reference = np.empty((num_steps, 3), dtype=np.float64)
    reference_position = np.array(positions, copy=True)
    reference_velocity = np.array(velocities, copy=True)
    for step in range(num_steps):
        reference[step] = _reference_intensity(bounds, base, amplitudes, scales, reference_position)
        for dimension, limits in enumerate(((0.0, 3.0), (0.0, 1.0))):
            position, velocity = _reference_reflection(
                float(reference_position[0, dimension]),
                float(reference_velocity[0, dimension]),
                *limits,
            )
            reference_position[0, dimension] = position
            reference_velocity[0, dimension] = velocity

    trace = _process(
        seed=seed,
        base_intensities=base,
        hotspot_amplitudes=amplitudes,
        hotspot_scales=scales,
        initial_hotspot_positions=positions,
        hotspot_velocities=velocities,
        zone_bounds=bounds,
        priority_range=(0.5, 0.5),
        service_time_range=(1, 1),
        deadline_offset_range=(1, 1),
    ).generate(num_steps)

    np.testing.assert_allclose(trace.intensities, reference, rtol=2e-13, atol=2e-13)
    np.testing.assert_allclose(
        trace.intensities.sum(axis=1),
        base.sum() + amplitudes.sum(),
        rtol=1e-14,
        atol=1e-14,
    )
    empirical = trace.counts.mean(axis=0)
    theoretical = reference.mean(axis=0)
    tolerance = 8.0 * np.sqrt(reference.sum(axis=0)) / num_steps
    assert np.all(np.abs(empirical - theoretical) <= tolerance), (
        f"empirical={empirical}, theoretical={theoretical}, tolerance={tolerance}"
    )
