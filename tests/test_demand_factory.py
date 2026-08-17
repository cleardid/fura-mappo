from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from fura_mappo.demand import (
    BurstDemand,
    DriftingHotspotDemand,
    MarkovSwitchingDemand,
    StationaryPoissonDemand,
    create_demand_process,
)


def _config() -> dict[str, object]:
    return {
        "type": "stationary_poisson",
        "seed": 20260817,
        "intensities": np.array([0.5, 1.5]),
        "zone_bounds": [[0.0, 1.0, 0.0, 1.0], [2.0, 3.0, -1.0, 0.0]],
        "priority_range": [0.2, 0.8],
        "service_time_range": [1, 4],
        "deadline_offset_range": [2, 6],
    }


def _drifting_config() -> dict[str, object]:
    return {
        "type": "drifting_hotspot",
        "seed": 20260817,
        "base_intensities": np.array([0.3, 0.4]),
        "hotspot_amplitudes": [0.8],
        "hotspot_scales": [0.7],
        "initial_hotspot_positions": [[0.25, 0.5]],
        "hotspot_velocities": [[0.4, 0.0]],
        "zone_bounds": [[0.0, 1.0, 0.0, 1.0], [1.0, 3.0, 0.0, 1.0]],
        "priority_range": [0.2, 0.8],
        "service_time_range": [1, 4],
        "deadline_offset_range": [2, 6],
    }


def _markov_config() -> dict[str, object]:
    return {
        "type": "markov_switching",
        "seed": 20260817,
        "state_intensities": np.array([[0.3, 0.7], [1.0, 0.1]]),
        "transition_matrix": [[0.85, 0.15], [0.25, 0.75]],
        "initial_state": 0,
        "zone_bounds": [[0.0, 1.0, 0.0, 1.0], [2.0, 4.0, -1.0, 1.0]],
        "priority_range": [0.2, 0.8],
        "service_time_range": [1, 4],
        "deadline_offset_range": [2, 6],
    }


def _burst_config() -> dict[str, object]:
    return {
        "type": "burst",
        "seed": 20260817,
        "base_intensities": np.array([0.2, 0.3]),
        "burst_probability": 0.3,
        "burst_duration_range": [2, 4],
        "burst_amplitude_range": [0.5, 1.0],
        "burst_zone_weights": [1.0, 2.0],
        "zone_bounds": [[0.0, 1.0, 0.0, 1.0], [2.0, 4.0, -1.0, 1.0]],
        "priority_range": [0.2, 0.8],
        "service_time_range": [1, 4],
        "deadline_offset_range": [2, 6],
    }


_FACTORY_CASES = (
    (_config, StationaryPoissonDemand),
    (_drifting_config, DriftingHotspotDemand),
    (_markov_config, MarkovSwitchingDemand),
    (_burst_config, BurstDemand),
)


def test_factory_creates_stationary_process_from_dict_and_read_only_mapping() -> None:
    regular = create_demand_process(_config())
    read_only = create_demand_process(MappingProxyType(_config()))

    assert isinstance(regular, StationaryPoissonDemand)
    assert isinstance(read_only, StationaryPoissonDemand)
    np.testing.assert_array_equal(regular.generate(5).counts, read_only.generate(5).counts)


def test_factory_does_not_modify_config_or_nested_values() -> None:
    config = _config()
    original_keys = tuple(config.keys())
    original_intensities = np.array(config["intensities"], copy=True)
    original_bounds = [list(row) for row in config["zone_bounds"]]  # type: ignore[union-attr]
    original_priority = list(config["priority_range"])  # type: ignore[arg-type]
    original_service = list(config["service_time_range"])  # type: ignore[arg-type]
    original_deadline = list(config["deadline_offset_range"])  # type: ignore[arg-type]

    create_demand_process(config)

    assert tuple(config.keys()) == original_keys
    np.testing.assert_array_equal(config["intensities"], original_intensities)
    assert config["zone_bounds"] == original_bounds
    assert config["priority_range"] == original_priority
    assert config["service_time_range"] == original_service
    assert config["deadline_offset_range"] == original_deadline


@pytest.mark.parametrize("invalid_config", [None, [], "config", 3])
def test_factory_rejects_non_mapping(invalid_config: object) -> None:
    with pytest.raises(TypeError, match="Mapping"):
        create_demand_process(invalid_config)  # type: ignore[arg-type]


def test_factory_rejects_missing_type() -> None:
    config = _config()
    del config["type"]

    with pytest.raises(ValueError, match="type"):
        create_demand_process(config)


@pytest.mark.parametrize("invalid_type", [None, 1, True])
def test_factory_rejects_non_string_type(invalid_type: object) -> None:
    config = _config()
    config["type"] = invalid_type

    with pytest.raises(TypeError, match="字符串"):
        create_demand_process(config)


@pytest.mark.parametrize("unknown_type", ["Stationary_Poisson", "poisson", ""])
def test_factory_rejects_unknown_type_with_supported_name(unknown_type: str) -> None:
    config = _config()
    config["type"] = unknown_type

    with pytest.raises(ValueError) as error:
        create_demand_process(config)

    assert repr(unknown_type) in str(error.value)
    assert "stationary_poisson" in str(error.value)


def test_factory_lists_all_missing_fields() -> None:
    config = _config()
    del config["seed"]
    del config["zone_bounds"]

    with pytest.raises(ValueError) as error:
        create_demand_process(config)

    assert "seed" in str(error.value)
    assert "zone_bounds" in str(error.value)


def test_factory_lists_all_extra_fields() -> None:
    config = _config()
    config["alias"] = "forbidden"
    config["metadata"] = {}

    with pytest.raises(ValueError) as error:
        create_demand_process(config)

    assert "alias" in str(error.value)
    assert "metadata" in str(error.value)


@pytest.mark.parametrize(("config_factory", "expected_class"), _FACTORY_CASES)
def test_factory_creates_all_four_canonical_types(
    config_factory: object,
    expected_class: type[object],
) -> None:
    config = config_factory()  # type: ignore[operator]

    regular = create_demand_process(config)
    read_only = create_demand_process(MappingProxyType(config))

    assert isinstance(regular, expected_class)
    assert isinstance(read_only, expected_class)
    np.testing.assert_array_equal(regular.generate(5).counts, read_only.generate(5).counts)


def test_unknown_type_message_lists_all_sorted_supported_names() -> None:
    config = _config()
    config["type"] = "Drifting_Hotspot"

    with pytest.raises(ValueError) as error:
        create_demand_process(config)

    message = str(error.value)
    expected_names = ("burst", "drifting_hotspot", "markov_switching", "stationary_poisson")
    assert all(name in message for name in expected_names)
    assert [message.index(name) for name in expected_names] == sorted(
        message.index(name) for name in expected_names
    )


@pytest.mark.parametrize("config_factory", [case[0] for case in _FACTORY_CASES])
def test_schema_reports_missing_and_extra_fields_together(config_factory: object) -> None:
    config = config_factory()  # type: ignore[operator]
    del config["seed"]
    config["metadata"] = {}

    with pytest.raises(ValueError) as error:
        create_demand_process(config)

    assert "缺少" in str(error.value)
    assert "seed" in str(error.value)
    assert "多余" in str(error.value)
    assert "metadata" in str(error.value)


@pytest.mark.parametrize(
    ("config_factory", "foreign_field", "foreign_value"),
    [
        (_config, "burst_probability", 0.2),
        (_drifting_config, "transition_matrix", [[1.0]]),
        (_markov_config, "burst_zone_weights", [1.0, 1.0]),
        (_burst_config, "hotspot_scales", [1.0]),
    ],
)
def test_process_specific_fields_cannot_leak_across_schemas(
    config_factory: object,
    foreign_field: str,
    foreign_value: object,
) -> None:
    config = config_factory()  # type: ignore[operator]
    config[foreign_field] = foreign_value

    with pytest.raises(ValueError, match="多余"):
        create_demand_process(config)


@pytest.mark.parametrize("config_factory", [case[0] for case in _FACTORY_CASES])
def test_factory_preserves_top_level_and_nested_inputs_for_every_type(
    config_factory: object,
) -> None:
    config = config_factory()  # type: ignore[operator]
    keys_before = tuple(config.keys())
    arrays_before = {
        key: value.copy() for key, value in config.items() if isinstance(value, np.ndarray)
    }
    lists_before = {
        key: [list(item) if isinstance(item, list) else item for item in value]
        for key, value in config.items()
        if isinstance(value, list)
    }

    create_demand_process(config)

    assert tuple(config.keys()) == keys_before
    for key, expected in arrays_before.items():
        np.testing.assert_array_equal(config[key], expected)
    for key, expected in lists_before.items():
        assert config[key] == expected


@pytest.mark.parametrize("config_factory", [case[0] for case in _FACTORY_CASES])
def test_mutating_factory_config_after_construction_cannot_change_instance(
    config_factory: object,
) -> None:
    config = config_factory()  # type: ignore[operator]
    process = create_demand_process(config)
    control = create_demand_process(config_factory())  # type: ignore[operator]
    for value in config.values():
        if isinstance(value, np.ndarray):
            value[...] = 99.0
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, list):
                    item[:] = [99.0] * len(item)
                elif isinstance(item, (int, float)):
                    value[index] = 99.0

    produced = process.generate(5)
    expected = control.generate(5)
    np.testing.assert_array_equal(produced.counts, expected.counts)
    np.testing.assert_array_equal(produced.intensities, expected.intensities)
    assert produced.events == expected.events
