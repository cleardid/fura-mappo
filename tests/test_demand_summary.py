from __future__ import annotations

import json
import random

import numpy as np

from fura_mappo.demand.models import DemandEvent, DemandTrace
from fura_mappo.demand.summary import summarize_demand_trace


def _trace() -> DemandTrace:
    return DemandTrace(
        start_step=5,
        counts=[[1, 0], [2, 1], [0, 2]],
        intensities=[[0.5, 1.0], [1.0, 2.0], [1.5, 3.0]],
        events=(
            DemandEvent(0, 5, 0, (0.0, 0.0), 0.2, 1, 7),
            DemandEvent(1, 6, 0, (0.0, 0.0), 0.4, 2, 9),
            DemandEvent(2, 6, 0, (0.0, 0.0), 0.6, 3, 10),
            DemandEvent(3, 6, 1, (0.0, 0.0), 0.8, 4, 11),
            DemandEvent(4, 7, 1, (0.0, 0.0), 1.0, 5, 12),
            DemandEvent(5, 7, 1, (0.0, 0.0), 0.0, 6, 13),
        ),
    )


def test_summary_matches_hand_calculated_schema_and_population_statistics() -> None:
    summary = summarize_demand_trace(_trace())

    assert summary["schema"] == "fura-mappo.demand-summary"
    assert summary["version"] == 1
    assert (summary["start_step"], summary["num_steps"], summary["num_zones"]) == (5, 3, 2)
    assert summary["num_events"] == 6
    per_zone = summary["counts"]["per_zone"]
    assert per_zone["total"] == [3, 3]
    np.testing.assert_allclose(per_zone["mean"], [1.0, 1.0])
    np.testing.assert_allclose(per_zone["variance"], [2.0 / 3.0, 2.0 / 3.0])
    assert per_zone["min"] == [0, 0]
    assert per_zone["max"] == [2, 2]
    np.testing.assert_allclose(per_zone["zero_fraction"], [1.0 / 3.0, 1.0 / 3.0])

    per_step = summary["counts"]["per_step_total"]
    assert per_step["total"] == 6
    assert per_step["mean"] == 2.0
    assert per_step["variance"] == 2.0 / 3.0
    assert (per_step["min"], per_step["max"], per_step["zero_fraction"]) == (1, 3, 0.0)
    intensity = summary["intensity"]["per_zone"]
    np.testing.assert_allclose(intensity["mean"], [1.0, 2.0])
    assert intensity["min"] == [0.5, 1.0]
    assert intensity["max"] == [1.5, 3.0]

    assert summary["events"]["priority"]["count"] == 6
    assert summary["events"]["priority"]["mean"] == 0.5
    np.testing.assert_allclose(summary["events"]["priority"]["variance"], 0.7 / 6.0)
    assert summary["events"]["service_time"]["mean"] == 3.5
    assert summary["events"]["deadline_offset"]["min"] == 2
    assert summary["events"]["deadline_offset"]["max"] == 6
    json.dumps(summary, allow_nan=False)


def test_zero_event_summary_uses_null_property_statistics() -> None:
    trace = DemandTrace(
        start_step=0,
        counts=np.zeros((2, 2), dtype=np.int64),
        intensities=np.zeros((2, 2), dtype=np.float64),
        events=(),
    )

    summary = summarize_demand_trace(trace)

    for property_name in ("priority", "service_time", "deadline_offset"):
        stats = summary["events"][property_name]
        assert stats == {"count": 0, "mean": None, "variance": None, "min": None, "max": None}
    assert summary["counts"]["per_step_total"]["variance"] == 0.0
    json.dumps(summary, allow_nan=False)


def test_single_sample_variance_is_zero_and_input_is_unchanged() -> None:
    trace = DemandTrace(
        start_step=0,
        counts=[[1]],
        intensities=[[0.5]],
        events=(DemandEvent(0, 0, 0, (0.0, 0.0), 0.5, 2, 3),),
    )
    counts = trace.counts.copy()
    intensities = trace.intensities.copy()

    summary = summarize_demand_trace(trace)

    assert summary["counts"]["per_zone"]["variance"] == [0.0]
    assert summary["events"]["priority"]["variance"] == 0.0
    np.testing.assert_array_equal(trace.counts, counts)
    np.testing.assert_array_equal(trace.intensities, intensities)


def test_counts_totals_use_python_integers_without_int64_overflow() -> None:
    maximum = int(np.iinfo(np.int64).max)
    trace = object.__new__(DemandTrace)
    object.__setattr__(trace, "start_step", 0)
    object.__setattr__(trace, "counts", np.array([[maximum, maximum]], dtype=np.int64))
    object.__setattr__(trace, "intensities", np.zeros((1, 2)))
    object.__setattr__(trace, "events", ())

    summary = summarize_demand_trace(trace)

    assert summary["counts"]["per_step_total"]["total"] == 2 * maximum
    assert summary["counts"]["per_zone"]["total"] == [maximum, maximum]


def test_summary_does_not_pollute_global_rng() -> None:
    numpy_state = np.random.get_state()
    python_state = random.getstate()

    summarize_demand_trace(_trace())

    current = np.random.get_state()
    assert numpy_state[0] == current[0]
    np.testing.assert_array_equal(numpy_state[1], current[1])
    assert numpy_state[2:] == current[2:]
    assert python_state == random.getstate()
