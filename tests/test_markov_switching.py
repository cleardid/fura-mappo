from __future__ import annotations

import random

import numpy as np
import pytest

from fura_mappo.demand import (
    DemandTrace,
    MarkovSwitchingDemand,
    StationaryPoissonDemand,
)


def _process(
    *,
    seed: int = 20260817,
    state_intensities: object = ((0.3, 0.7), (1.0, 0.1)),
    transition_matrix: object = ((0.85, 0.15), (0.25, 0.75)),
    initial_state: object = 0,
    zone_bounds: object = ((0.0, 1.0, 0.0, 1.0), (2.0, 4.0, -1.0, 1.0)),
    priority_range: object = (0.2, 0.8),
    service_time_range: object = (1, 4),
    deadline_offset_range: object = (2, 6),
) -> MarkovSwitchingDemand:
    return MarkovSwitchingDemand(
        seed=seed,
        state_intensities=state_intensities,  # type: ignore[arg-type]
        transition_matrix=transition_matrix,  # type: ignore[arg-type]
        initial_state=initial_state,  # type: ignore[arg-type]
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


def _infer_states(trace: DemandTrace, rows: np.ndarray) -> np.ndarray:
    """通过互异强度行反推每个发射时间步的 Markov 状态。"""

    matches = np.all(trace.intensities[:, None, :] == rows[None, :, :], axis=2)
    assert np.all(matches.sum(axis=1) == 1)
    return np.argmax(matches, axis=1)


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


def test_single_state_deterministic_transition_matches_stationary_rng_path() -> None:
    intensities = (0.3, 0.7)
    markov = _process(
        seed=123,
        state_intensities=(intensities,),
        transition_matrix=((1,),),
        initial_state=0,
    )
    stationary = _stationary(123, intensities)

    _assert_traces_equal(markov.generate(40), stationary.generate(40))


def test_current_state_emits_before_deterministic_transition_and_reset_restores_it() -> None:
    rows = np.array([[0.1, 0.0], [0.0, 0.2]])
    process = _process(
        state_intensities=rows,
        transition_matrix=((0, 1), (1, 0)),
        initial_state=1,
    )

    trace = process.generate(5)
    np.testing.assert_array_equal(trace.intensities, rows[[1, 0, 1, 0, 1]])
    process.reset()
    np.testing.assert_array_equal(process.step().intensity, rows[1])


def test_absorbing_state_and_zero_intensity_are_exact() -> None:
    rows = np.array([[0.4, 0.1], [0.0, 0.0]])
    trace = _process(
        state_intensities=rows,
        transition_matrix=((0, 1), (0, 1)),
        initial_state=0,
    ).generate(8)

    np.testing.assert_array_equal(trace.intensities[0], rows[0])
    np.testing.assert_array_equal(trace.intensities[1:], np.repeat(rows[1:2], 7, axis=0))
    np.testing.assert_array_equal(trace.counts[1:], 0)


def test_float32_row_rounding_is_accepted_but_explicit_tolerances_are_enforced() -> None:
    accepted = np.array([[0.1, 0.9], [0.2, 0.8]], dtype=np.float32)
    assert _process(transition_matrix=accepted).step().step == 0

    too_far_float32 = np.array([[0.1, 0.900002], [0.2, 0.8]], dtype=np.float32)
    with pytest.raises(ValueError, match="容差"):
        _process(transition_matrix=too_far_float32)

    with pytest.raises(ValueError, match="容差"):
        _process(transition_matrix=((0.1, 0.90000001), (0.2, 0.8)))


def test_output_geometry_attributes_counts_and_read_only_arrays() -> None:
    first_step = _process().step()
    assert not first_step.counts.flags.writeable
    assert not first_step.intensity.flags.writeable
    bounds = np.array([[0.0, 1.0, -1.0, 0.0], [4.0, 6.0, 2.0, 5.0]])
    trace = _process(
        state_intensities=((2.0, 3.0), (1.0, 4.0)),
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
    intensities = np.array([[0.3, 0.7], [1.0, 0.1]])
    transition = np.array([[0.85, 0.15], [0.25, 0.75]])
    bounds = np.array([[0.0, 1.0, 0.0, 1.0], [2.0, 4.0, -1.0, 1.0]])
    process = _process(
        state_intensities=intensities,
        transition_matrix=transition,
        zone_bounds=bounds,
    )
    control = _process()
    intensities[:] = 99.0
    transition[:] = 0.5
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
def test_mixed_boolean_arrays_and_initial_state_are_rejected(boolean: object) -> None:
    with pytest.raises(TypeError, match="布尔"):
        _process(state_intensities=[[0.3, boolean], [1.0, 0.1]])
    with pytest.raises(TypeError, match="布尔"):
        _process(transition_matrix=[[0.85, boolean], [0.25, 0.75]])
    with pytest.raises(TypeError, match="布尔"):
        _process(zone_bounds=[[0.0, 1.0, 0.0, boolean], [2.0, 4.0, -1.0, 1.0]])
    with pytest.raises(TypeError, match="布尔"):
        _process(initial_state=boolean)


@pytest.mark.parametrize(
    "overrides",
    [
        {"state_intensities": ((0.1,),)},
        {"state_intensities": ((-0.1, 0.2), (0.1, 0.2))},
        {"state_intensities": ((np.nan, 0.2), (0.1, 0.2))},
        {"state_intensities": ((np.inf, 0.2), (0.1, 0.2))},
        {
            "state_intensities": (
                (float(np.iinfo(np.int64).max), 0.2),
                (0.1, 0.2),
            )
        },
        {"transition_matrix": (0.5, 0.5)},
        {"transition_matrix": ((1.0,),)},
        {"transition_matrix": ((0.9, -0.1), (0.2, 0.8))},
        {"transition_matrix": ((np.nan, 0.0), (0.2, 0.8))},
        {"transition_matrix": ((np.inf, 0.0), (0.2, 0.8))},
        {"transition_matrix": ((1.0 + 0.0j, 0.0), (0.2, 0.8))},
        {"transition_matrix": np.array([[0.8, 0.2], [0.2, 0.8]], dtype=object)},
        {"transition_matrix": ((1, 1), (0, 1))},
        {"initial_state": -1},
        {"initial_state": 2},
        {"initial_state": 0.0},
    ],
)
def test_invalid_markov_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _process(**overrides)


def test_transition_matrix_input_is_not_normalized_in_place() -> None:
    matrix = np.array([[0.1, 0.9], [0.2, 0.8]], dtype=np.float32)
    original = matrix.copy()

    _process(transition_matrix=matrix)

    np.testing.assert_array_equal(matrix, original)
    assert matrix.dtype == np.float32


def test_long_run_state_transition_and_conditional_poisson_statistics() -> None:
    seed = 271828
    num_steps = 50_000
    burn_in = 1_000
    transition = np.array([[0.9, 0.1], [0.2, 0.8]])
    rows = np.array([[0.4, 0.1], [0.1, 0.8]])
    trace = _process(
        seed=seed,
        state_intensities=rows,
        transition_matrix=transition,
        initial_state=0,
        priority_range=(0.5, 0.5),
        service_time_range=(1, 1),
        deadline_offset_range=(1, 1),
    ).generate(num_steps)
    states = _infer_states(trace, rows)
    sampled_states = states[burn_in:]
    sample_size = sampled_states.size
    stationary = np.array([2.0 / 3.0, 1.0 / 3.0])
    rho = 0.7

    occupancy = np.bincount(sampled_states, minlength=2) / sample_size
    occupancy_tolerance = 8.0 * np.sqrt(
        stationary * (1.0 - stationary) * (1.0 + rho) / (1.0 - rho) / sample_size
    )
    assert np.all(np.abs(occupancy - stationary) <= occupancy_tolerance), (
        f"occupancy={occupancy}, expected={stationary}, tolerance={occupancy_tolerance}"
    )

    source_states = states[burn_in:-1]
    target_states = states[burn_in + 1 :]
    for state in range(2):
        source_mask = source_states == state
        source_count = int(source_mask.sum())
        empirical_switch = np.mean(target_states[source_mask] != state)
        theoretical_switch = transition[state, 1 - state]
        transition_tolerance = 8.0 * np.sqrt(
            theoretical_switch * (1.0 - theoretical_switch) / source_count
        )
        assert abs(empirical_switch - theoretical_switch) <= transition_tolerance

        condition_mask = sampled_states == state
        condition_count = int(condition_mask.sum())
        empirical_means = trace.counts[burn_in:][condition_mask].mean(axis=0)
        poisson_tolerance = 8.0 * np.sqrt(rows[state] / condition_count)
        assert np.all(np.abs(empirical_means - rows[state]) <= poisson_tolerance), (
            f"state={state}, empirical={empirical_means}, expected={rows[state]}, "
            f"tolerance={poisson_tolerance}"
        )
