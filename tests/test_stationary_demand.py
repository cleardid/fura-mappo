from __future__ import annotations

import random

import numpy as np
import pytest

import fura_mappo.demand.processes as process_module
from fura_mappo.demand import DemandStep, DemandTrace, StationaryPoissonDemand


class _ResetProbe(StationaryPoissonDemand):
    """仅用于验证 reset 钩子顺序和失败原子性的私有测试过程。"""

    def __init__(self, seed: int) -> None:
        self._hook_ready = False
        self._hook_should_fail = False
        self._hook_calls = 0
        self._hook_order: list[str] | None = None
        super().__init__(
            seed=seed,
            intensities=(1.5,),
            zone_bounds=((0.0, 1.0, 0.0, 1.0),),
            priority_range=(0.5, 0.5),
            service_time_range=(1, 1),
            deadline_offset_range=(1, 1),
        )
        self._hook_ready = True

    def _reset_process_state(self) -> None:
        if not self._hook_ready:
            raise AssertionError("基类构造函数不得虚调用 reset 钩子")
        self._hook_calls += 1
        if self._hook_order is not None:
            self._hook_order.append("hook")
        if self._hook_should_fail:
            raise RuntimeError("预期的 reset 钩子失败")


def _process(
    *,
    seed: int = 20260817,
    intensities: object = (1.5, 2.0),
    zone_bounds: object = ((0.0, 1.0, 0.0, 1.0), (2.0, 4.0, -2.0, 0.0)),
    priority_range: object = (0.2, 0.8),
    service_time_range: object = (1, 4),
    deadline_offset_range: object = (2, 6),
) -> StationaryPoissonDemand:
    return StationaryPoissonDemand(
        seed=seed,
        intensities=intensities,  # type: ignore[arg-type]
        zone_bounds=zone_bounds,  # type: ignore[arg-type]
        priority_range=priority_range,  # type: ignore[arg-type]
        service_time_range=service_time_range,  # type: ignore[arg-type]
        deadline_offset_range=deadline_offset_range,  # type: ignore[arg-type]
    )


def _assert_steps_equal(left: DemandStep, right: DemandStep) -> None:
    assert left.step == right.step
    np.testing.assert_array_equal(left.intensity, right.intensity)
    np.testing.assert_array_equal(left.counts, right.counts)
    assert left.events == right.events


def _assert_traces_equal(left: DemandTrace, right: DemandTrace) -> None:
    assert left.start_step == right.start_step
    np.testing.assert_array_equal(left.intensities, right.intensities)
    np.testing.assert_array_equal(left.counts, right.counts)
    assert left.events == right.events


def _assert_numpy_random_states_equal(left: tuple[object, ...], right: tuple[object, ...]) -> None:
    assert left[0] == right[0]
    np.testing.assert_array_equal(left[1], right[1])
    assert left[2:] == right[2:]


def test_base_constructor_does_not_virtual_call_reset_hook() -> None:
    process = _ResetProbe(7)

    assert process._hook_calls == 0


def test_reset_creates_candidate_generator_before_calling_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _ResetProbe(7)
    order: list[str] = []
    original_factory = process_module.create_numpy_generator

    def recording_factory(seed: int) -> np.random.Generator:
        order.append("generator")
        return original_factory(seed)

    process._hook_order = order
    monkeypatch.setattr(process_module, "create_numpy_generator", recording_factory)

    process.reset(8)

    assert order == ["generator", "hook"]


def test_failed_reset_preserves_public_and_rng_state_and_can_continue() -> None:
    process = _ResetProbe(19)
    control = _ResetProbe(19)
    _assert_traces_equal(process.generate(4), control.generate(4))
    previous_rng = process._rng
    previous_public_state = (
        process.base_seed,
        process.current_step,
        process.next_event_id,
    )
    process._hook_should_fail = True

    with pytest.raises(RuntimeError, match="预期的 reset 钩子失败"):
        process.reset(999)

    assert process._rng is previous_rng
    assert (
        process.base_seed,
        process.current_step,
        process.next_event_id,
    ) == previous_public_state
    process._hook_should_fail = False
    _assert_steps_equal(process.step(), control.step())


def test_invalid_reset_seed_is_rejected_before_hook() -> None:
    process = _ResetProbe(7)

    with pytest.raises(TypeError):
        process.reset(True)

    assert process._hook_calls == 0


def test_process_is_ready_immediately_and_advances_public_state() -> None:
    process = _process()

    assert process.base_seed == 20260817
    assert process.current_step == 0
    assert process.next_event_id == 0

    first = process.step()
    second = process.step()

    assert first.step == 0
    assert second.step == 1
    assert process.current_step == 2
    all_ids = [event.event_id for step in (first, second) for event in step.events]
    assert all_ids == list(range(len(all_ids)))
    assert process.next_event_id == len(all_ids)


def test_reset_replays_current_base_seed_and_resets_ids() -> None:
    process = _process(intensities=(4.0, 3.0))
    original = process.generate(5)

    process.reset()
    replay = process.generate(5)

    _assert_traces_equal(original, replay)
    assert replay.start_step == 0
    assert replay.events[0].event_id == 0


def test_reset_with_new_seed_changes_and_saves_base_seed() -> None:
    process = _process(seed=11)
    process.generate(10)

    process.reset(np.int64(22))
    changed = process.generate(10)
    control = _process(seed=22).generate(10)

    assert process.base_seed == 22
    _assert_traces_equal(changed, control)

    process.reset()
    _assert_traces_equal(process.generate(10), _process(seed=22).generate(10))


def test_generate_continues_state_and_explicit_seed_restarts() -> None:
    process = _process(intensities=(3.0, 2.0))

    first = process.generate(2)
    second = process.generate(3)
    following = process.step()

    assert first.start_step == 0
    assert second.start_step == 2
    assert following.step == 5
    all_events = first.events + second.events + following.events
    assert [event.event_id for event in all_events] == list(range(len(all_events)))

    restarted = process.generate(2, seed=99)
    assert restarted.start_step == 0
    _assert_traces_equal(restarted, _process(seed=99, intensities=(3.0, 2.0)).generate(2))
    assert process.step().step == 2


@pytest.mark.parametrize("invalid_num_steps", [True, False, 0, -1, 1.5, "2"])
def test_generate_rejects_invalid_num_steps(invalid_num_steps: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _process().generate(invalid_num_steps)  # type: ignore[arg-type]


def test_same_seed_reproduces_and_different_seed_differs() -> None:
    first = _process(seed=101).generate(30)
    second = _process(seed=101).generate(30)
    different = _process(seed=202).generate(30)

    _assert_traces_equal(first, second)
    assert not np.array_equal(first.counts, different.counts) or first.events != different.events


def test_process_operations_do_not_change_global_random_states() -> None:
    numpy_state = np.random.get_state()
    python_state = random.getstate()

    process = _process()
    process.step()
    process.generate(3)
    process.reset()
    process.reset(44)
    process.generate(2)

    _assert_numpy_random_states_equal(numpy_state, np.random.get_state())
    assert python_state == random.getstate()


def test_instances_remain_independent_when_interleaved() -> None:
    first = _process(seed=17)
    second = _process(seed=17)
    first_control = _process(seed=17)
    second_control = _process(seed=17)

    _assert_steps_equal(first.step(), first_control.step())
    _assert_steps_equal(second.step(), second_control.step())
    first.generate(4)
    first_control.generate(4)
    _assert_steps_equal(second.step(), second_control.step())
    _assert_steps_equal(first.step(), first_control.step())


def test_input_and_output_array_mutation_cannot_change_process_state() -> None:
    intensities = np.array([1.5, 2.0])
    zone_bounds = np.array([[0.0, 1.0, 0.0, 1.0], [2.0, 4.0, -2.0, 0.0]])
    process = _process(intensities=intensities, zone_bounds=zone_bounds)
    control = _process()

    intensities[:] = 0.0
    zone_bounds[:] = 100.0
    first = process.step()
    _assert_steps_equal(first, control.step())

    first.intensity.setflags(write=True)
    first.counts.setflags(write=True)
    first.intensity[:] = 999.0
    first.counts[:] = 999

    process.reset()
    control.reset()
    _assert_steps_equal(process.step(), control.step())


def test_generated_values_obey_shapes_dtypes_ranges_and_geometry() -> None:
    bounds = np.array([[0.0, 1.0, -1.0, 0.0], [10.0, 12.0, 3.0, 7.0]])
    process = _process(
        intensities=(5.0, 6.0),
        zone_bounds=bounds,
        priority_range=(0.25, 0.75),
        service_time_range=(2, 5),
        deadline_offset_range=(3, 8),
    )
    trace = process.generate(20)

    assert trace.counts.shape == (20, 2)
    assert trace.intensities.shape == (20, 2)
    assert trace.counts.dtype == np.int64
    assert trace.intensities.dtype == np.float64
    assert np.all(trace.counts >= 0)
    assert np.all(np.isfinite(trace.intensities))
    assert np.all(trace.intensities >= 0.0)
    assert int(trace.counts.sum()) == len(trace.events)

    ids = [event.event_id for event in trace.events]
    assert ids == list(range(len(ids)))
    for event in trace.events:
        x_min, x_max, y_min, y_max = bounds[event.zone_id]
        x, y = event.position
        assert np.isfinite(x) and np.isfinite(y)
        assert x_min <= x < x_max
        assert y_min <= y < y_max
        assert 0.25 <= event.priority <= 0.75
        assert 2 <= event.service_time <= 5
        assert 3 <= event.deadline - event.arrival_step <= 8
        assert event.deadline > event.arrival_step

    for row, absolute_step in enumerate(range(trace.start_step, process.current_step)):
        step_events = [event for event in trace.events if event.arrival_step == absolute_step]
        assert int(trace.counts[row].sum()) == len(step_events)


def test_equal_attribute_ranges_produce_deterministic_values() -> None:
    trace = _process(
        intensities=(10.0,),
        zone_bounds=((0.0, 1.0, 0.0, 1.0),),
        priority_range=(0.4, 0.4),
        service_time_range=(3, 3),
        deadline_offset_range=(5, 5),
    ).generate(5)

    assert trace.events
    assert {event.priority for event in trace.events} == {0.4}
    assert {event.service_time for event in trace.events} == {3}
    assert {event.deadline - event.arrival_step for event in trace.events} == {5}


def test_non_degenerate_attribute_ranges_produce_legal_variation() -> None:
    trace = _process(
        intensities=(20.0,),
        zone_bounds=((0.0, 1.0, 0.0, 1.0),),
        priority_range=(0.1, 0.9),
        service_time_range=(1, 8),
        deadline_offset_range=(2, 10),
    ).generate(5)

    assert len({event.priority for event in trace.events}) > 1
    assert len({event.service_time for event in trace.events}) > 1
    assert len({event.deadline - event.arrival_step for event in trace.events}) > 1


def test_zero_intensity_zone_never_produces_events() -> None:
    trace = _process(
        intensities=(0.0, 2.0),
        zone_bounds=((0.0, 1.0, 0.0, 1.0), (2.0, 3.0, 2.0, 3.0)),
    ).generate(100)

    np.testing.assert_array_equal(trace.counts[:, 0], 0)
    assert all(event.zone_id == 1 for event in trace.events)


@pytest.mark.parametrize(
    "intensities",
    [
        1.0,
        [[1.0]],
        [],
        [-1.0],
        [np.nan],
        [np.inf],
        [-np.inf],
        [True],
    ],
)
def test_rejects_invalid_intensities(intensities: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _process(
            intensities=intensities,
            zone_bounds=((0.0, 1.0, 0.0, 1.0),),
        )


@pytest.mark.parametrize("boolean", [True, np.bool_(True)])
def test_rejects_boolean_mixed_into_process_numeric_arrays(boolean: object) -> None:
    with pytest.raises(TypeError, match="布尔"):
        _process(
            intensities=[1.0, boolean],  # type: ignore[list-item]
            zone_bounds=((0.0, 1.0, 0.0, 1.0), (1.0, 2.0, 0.0, 1.0)),
        )

    with pytest.raises(TypeError, match="布尔"):
        _process(
            intensities=(1.0,),
            zone_bounds=((0.0, 1.0, 0.0, boolean),),  # type: ignore[misc]
        )


@pytest.mark.parametrize(
    "zone_bounds",
    [
        [0.0, 1.0, 0.0, 1.0],
        [[[0.0, 1.0, 0.0, 1.0]]],
        ((0.0, 1.0, 0.0),),
        ((0.0, 1.0, 0.0, 1.0), (2.0, 3.0, 2.0, 3.0)),
        ((0.0, 0.0, 0.0, 1.0),),
        ((1.0, 0.0, 0.0, 1.0),),
        ((0.0, 1.0, 2.0, 2.0),),
        ((0.0, 1.0, 2.0, 1.0),),
        ((0.0, np.inf, 0.0, 1.0),),
        ((-np.inf, 1.0, 0.0, 1.0),),
        ((0.0, 1.0, np.nan, 1.0),),
    ],
)
def test_rejects_invalid_zone_bounds(zone_bounds: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _process(intensities=(1.0,), zone_bounds=zone_bounds)


@pytest.mark.parametrize(
    "priority_range",
    [
        (0.0,),
        (0.0, 0.5, 1.0),
        (-0.1, 0.5),
        (0.5, 0.4),
        (0.5, 1.1),
        (np.nan, 0.5),
        (0.0, np.inf),
        (True, 0.5),
    ],
)
def test_rejects_invalid_priority_range(priority_range: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _process(priority_range=priority_range)


@pytest.mark.parametrize(
    "field_name",
    ["service_time_range", "deadline_offset_range"],
)
@pytest.mark.parametrize(
    "invalid_range",
    [
        (1,),
        (1, 2, 3),
        (0, 1),
        (2, 1),
        (True, 2),
        (1.0, 2),
        (1, np.iinfo(np.int64).max + 1),
    ],
)
def test_rejects_invalid_integer_ranges(field_name: str, invalid_range: object) -> None:
    kwargs = {field_name: invalid_range}
    with pytest.raises((TypeError, ValueError)):
        _process(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_name",
    ["priority_range", "service_time_range", "deadline_offset_range"],
)
@pytest.mark.parametrize("invalid_range", [{1, 2}, frozenset({1, 2})])
def test_rejects_unordered_attribute_ranges(field_name: str, invalid_range: object) -> None:
    with pytest.raises(TypeError, match="序列"):
        _process(**{field_name: invalid_range})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field_name", "values"),
    [
        ("priority_range", (0.2, 0.8)),
        ("service_time_range", (1, 4)),
        ("deadline_offset_range", (2, 6)),
    ],
)
def test_rejects_generator_range_without_consuming_it(
    field_name: str, values: tuple[float, float] | tuple[int, int]
) -> None:
    range_generator = (value for value in values)

    with pytest.raises(TypeError, match="序列"):
        _process(**{field_name: range_generator})  # type: ignore[arg-type]

    assert tuple(range_generator) == values


def test_list_and_tuple_attribute_ranges_remain_supported() -> None:
    process = _process(
        priority_range=[0.2, 0.8],
        service_time_range=(1, 4),
        deadline_offset_range=[2, 6],
    )

    assert process.generate(2).start_step == 0


def test_empirical_means_match_each_poisson_intensity() -> None:
    num_steps = 20_000
    theoretical = np.array([0.2, 0.8, 2.0])
    trace = _process(
        seed=314159,
        intensities=theoretical,
        zone_bounds=(
            (0.0, 1.0, 0.0, 1.0),
            (1.0, 2.0, 0.0, 1.0),
            (2.0, 3.0, 0.0, 1.0),
        ),
        priority_range=(0.5, 0.5),
        service_time_range=(1, 1),
        deadline_offset_range=(1, 1),
    ).generate(num_steps)

    empirical = trace.counts.mean(axis=0)
    tolerance = 8.0 * np.sqrt(theoretical / num_steps)
    assert np.all(np.abs(empirical - theoretical) <= tolerance), (
        f"empirical={empirical}, theoretical={theoretical}, tolerance={tolerance}"
    )
