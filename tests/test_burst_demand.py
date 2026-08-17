from __future__ import annotations

import random

import numpy as np
import pytest

from fura_mappo.demand import BurstDemand, DemandTrace, StationaryPoissonDemand


def _process(
    *,
    seed: int = 20260817,
    base_intensities: object = (0.2, 0.3),
    burst_probability: object = 0.3,
    burst_duration_range: object = (2, 4),
    burst_amplitude_range: object = (0.5, 1.0),
    burst_zone_weights: object = (1.0, 2.0),
    zone_bounds: object = ((0.0, 1.0, 0.0, 1.0), (2.0, 4.0, -1.0, 1.0)),
    priority_range: object = (0.2, 0.8),
    service_time_range: object = (1, 4),
    deadline_offset_range: object = (2, 6),
) -> BurstDemand:
    return BurstDemand(
        seed=seed,
        base_intensities=base_intensities,  # type: ignore[arg-type]
        burst_probability=burst_probability,  # type: ignore[arg-type]
        burst_duration_range=burst_duration_range,  # type: ignore[arg-type]
        burst_amplitude_range=burst_amplitude_range,  # type: ignore[arg-type]
        burst_zone_weights=burst_zone_weights,  # type: ignore[arg-type]
        zone_bounds=zone_bounds,  # type: ignore[arg-type]
        priority_range=priority_range,  # type: ignore[arg-type]
        service_time_range=service_time_range,  # type: ignore[arg-type]
        deadline_offset_range=deadline_offset_range,  # type: ignore[arg-type]
    )


def _stationary(seed: int, intensities: object) -> StationaryPoissonDemand:
    return StationaryPoissonDemand(
        seed=seed,
        intensities=intensities,  # type: ignore[arg-type]
        zone_bounds=((0.0, 1.0, 0.0, 1.0), (2.0, 4.0, -1.0, 1.0)),
        priority_range=(0.2, 0.8),
        service_time_range=(1, 4),
        deadline_offset_range=(2, 6),
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


def test_same_seed_reset_generate_and_interleaving_are_reproducible() -> None:
    first = _process(seed=101)
    second = _process(seed=101)
    _assert_traces_equal(first.generate(15), second.generate(15))

    _assert_traces_equal(first.generate(15, seed=202), _process(seed=202).generate(15))
    assert first.base_seed == 202
    first.reset()
    _assert_traces_equal(first.generate(15), _process(seed=202).generate(15))

    interleaved = _process(seed=33)
    control = _process(seed=33)
    assert interleaved.step().events == control.step().events
    _process(seed=99).generate(5)
    _assert_traces_equal(interleaved.generate(5), control.generate(5))


def test_different_fixed_seeds_produce_different_trajectories() -> None:
    first = _process(seed=11).generate(50)
    second = _process(seed=29).generate(50)

    assert (
        not np.array_equal(first.intensities, second.intensities)
        or not np.array_equal(first.counts, second.counts)
        or first.events != second.events
    )


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


def test_zero_probability_does_not_consume_burst_rng_and_matches_stationary() -> None:
    base = (0.2, 0.3)
    burst = _process(
        seed=123,
        base_intensities=base,
        burst_probability=0.0,
        burst_duration_range=(2, 7),
        burst_amplitude_range=(0.5, 1.5),
    )
    stationary = _stationary(123, base)

    _assert_traces_equal(burst.generate(40), stationary.generate(40))


def test_certain_one_step_fixed_burst_matches_elevated_stationary_rng_path() -> None:
    base = np.array([0.2, 0.3])
    weights = np.array([1.0, 3.0])
    amplitude = 0.8
    elevated = base + amplitude * weights / weights.sum()
    burst = _process(
        seed=123,
        base_intensities=base,
        burst_probability=1.0,
        burst_duration_range=(1, 1),
        burst_amplitude_range=(amplitude, amplitude),
        burst_zone_weights=weights,
    )
    stationary = _stationary(123, elevated)

    _assert_traces_equal(burst.generate(40), stationary.generate(40))


def test_three_step_bursts_hold_amplitude_and_resample_only_at_boundaries() -> None:
    base = np.array([0.2, 0.3])
    trace = _process(
        seed=42,
        base_intensities=base,
        burst_probability=1.0,
        burst_duration_range=(3, 3),
        burst_amplitude_range=(0.5, 1.0),
        burst_zone_weights=(1.0, 1.0),
    ).generate(9)

    for start in (0, 3, 6):
        np.testing.assert_array_equal(
            trace.intensities[start : start + 3],
            np.repeat(trace.intensities[start : start + 1], 3, axis=0),
        )
    assert not np.array_equal(trace.intensities[0], trace.intensities[3])
    assert not np.array_equal(trace.intensities[3], trace.intensities[6])
    assert np.all(trace.intensities > base)


def test_start_step_lifecycle_non_overlap_and_reset_are_exact() -> None:
    process = _process(
        burst_probability=1.0,
        burst_duration_range=(2, 2),
        burst_amplitude_range=(0.6, 0.6),
    )
    base = np.array([0.2, 0.3])

    first = process.step()
    assert np.any(first.intensity > base)
    assert process._remaining_duration == 1
    assert process._active_amplitude == 0.6
    second = process.step()
    np.testing.assert_array_equal(second.intensity, first.intensity)
    assert process._remaining_duration == 0
    assert process._active_amplitude == 0.0
    third = process.step()
    assert process._remaining_duration == 1
    np.testing.assert_array_equal(third.intensity, first.intensity)

    process.reset()
    assert process._remaining_duration == 0
    assert process._active_amplitude == 0.0
    np.testing.assert_array_equal(process.step().intensity, first.intensity)


def test_large_finite_zone_weights_normalize_without_overflow() -> None:
    base = np.array([0.1, 0.2])
    step = _process(
        base_intensities=base,
        burst_probability=1.0,
        burst_duration_range=(1, 1),
        burst_amplitude_range=(0.8, 0.8),
        burst_zone_weights=(1e308, 1e308),
    ).step()

    np.testing.assert_allclose(step.intensity, base + np.array([0.4, 0.4]))
    assert np.all(np.isfinite(step.intensity))


def test_output_geometry_attributes_counts_and_read_only_arrays() -> None:
    first_step = _process().step()
    assert not first_step.counts.flags.writeable
    assert not first_step.intensity.flags.writeable
    bounds = np.array([[0.0, 1.0, -1.0, 0.0], [4.0, 6.0, 2.0, 5.0]])
    trace = _process(
        base_intensities=(2.0, 3.0),
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
    base = np.array([0.2, 0.3])
    weights = np.array([1.0, 2.0])
    bounds = np.array([[0.0, 1.0, 0.0, 1.0], [2.0, 4.0, -1.0, 1.0]])
    process = _process(
        base_intensities=base,
        burst_zone_weights=weights,
        zone_bounds=bounds,
    )
    control = _process()
    base[:] = 99.0
    weights[:] = 0.0
    bounds[:] = 99.0

    produced = process.generate(8)
    _assert_traces_equal(produced, control.generate(8))
    produced.counts.setflags(write=True)
    produced.intensities.setflags(write=True)
    produced.counts[:] = 999
    produced.intensities[:] = 999.0
    process.reset()
    control.reset()
    _assert_traces_equal(process.generate(8), control.generate(8))


@pytest.mark.parametrize("boolean", [True, np.bool_(True)])
def test_mixed_boolean_arrays_and_scalars_are_rejected(boolean: object) -> None:
    with pytest.raises(TypeError, match="布尔"):
        _process(base_intensities=[0.2, boolean])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="布尔"):
        _process(burst_probability=boolean)
    with pytest.raises(TypeError, match="布尔"):
        _process(burst_duration_range=[1, boolean])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="布尔"):
        _process(burst_amplitude_range=[0.5, boolean])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="布尔"):
        _process(burst_zone_weights=[1.0, boolean])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="布尔"):
        _process(zone_bounds=[[0.0, 1.0, 0.0, boolean], [2.0, 4.0, -1.0, 1.0]])


@pytest.mark.parametrize(
    "overrides",
    [
        {"burst_probability": -0.1},
        {"burst_probability": 1.1},
        {"burst_probability": np.nan},
        {"burst_probability": np.inf},
        {"burst_probability": "0.2"},
        {"burst_duration_range": (0, 1)},
        {"burst_duration_range": (3, 2)},
        {"burst_duration_range": (1.0, 2)},
        {"burst_amplitude_range": (-0.1, 1.0)},
        {"burst_amplitude_range": (1.0, 0.5)},
        {"burst_amplitude_range": (0.5, np.inf)},
        {"burst_zone_weights": (0.0, 0.0)},
        {"burst_zone_weights": (-1.0, 2.0)},
        {"burst_zone_weights": (1.0,)},
        {"burst_zone_weights": (1.0, np.nan)},
        {"base_intensities": (np.nan, 0.2)},
        {"base_intensities": (np.inf, 0.2)},
        {"base_intensities": (float(np.iinfo(np.int64).max), 0.2)},
    ],
)
def test_invalid_burst_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _process(**overrides)


@pytest.mark.parametrize("field_name", ["burst_duration_range", "burst_amplitude_range"])
def test_burst_ranges_reject_unordered_and_unconsumed_iterators(field_name: str) -> None:
    with pytest.raises(TypeError, match="序列"):
        _process(**{field_name: {1, 2}})

    generator = (value for value in (1, 2))
    with pytest.raises(TypeError, match="序列"):
        _process(**{field_name: generator})
    assert tuple(generator) == (1, 2)


def test_worst_case_burst_intensity_over_poisson_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="安全范围"):
        _process(
            base_intensities=(0.0, 0.0),
            burst_amplitude_range=(0.0, float(np.iinfo(np.int64).max)),
            burst_zone_weights=(1.0, 0.0),
        )


def test_long_run_activity_and_conditional_poisson_statistics() -> None:
    seed = 161803
    num_steps = 50_000
    probability = 0.2
    base = np.array([0.0, 0.35])
    weights = np.array([0.0, 1.0])
    amplitude = 0.4
    active_intensity = base + amplitude * weights
    trace = _process(
        seed=seed,
        base_intensities=base,
        burst_probability=probability,
        burst_duration_range=(1, 1),
        burst_amplitude_range=(amplitude, amplitude),
        burst_zone_weights=weights,
        priority_range=(0.5, 0.5),
        service_time_range=(1, 1),
        deadline_offset_range=(1, 1),
    ).generate(num_steps)
    active = np.all(trace.intensities == active_intensity, axis=1)
    inactive = np.all(trace.intensities == base, axis=1)
    assert np.all(active | inactive)

    empirical_probability = active.mean()
    probability_tolerance = 8.0 * np.sqrt(probability * (1.0 - probability) / num_steps)
    assert abs(empirical_probability - probability) <= probability_tolerance

    for condition, theoretical in ((inactive, base), (active, active_intensity)):
        condition_count = int(condition.sum())
        empirical = trace.counts[condition].mean(axis=0)
        tolerance = 8.0 * np.sqrt(theoretical / condition_count)
        np.testing.assert_array_equal(trace.counts[condition, 0], 0)
        assert np.all(np.abs(empirical - theoretical) <= tolerance), (
            f"empirical={empirical}, theoretical={theoretical}, tolerance={tolerance}"
        )
