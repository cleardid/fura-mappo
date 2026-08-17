from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from fura_mappo.demand import StationaryPoissonDemand, create_demand_process


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
