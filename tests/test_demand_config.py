from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from fura_mappo.demand.config import compute_config_hash, load_demand_config
from fura_mappo.demand.factory import create_demand_process

_EXAMPLE_NAMES = (
    "stationary_poisson",
    "drifting_hotspot",
    "markov_switching",
    "burst",
)


def _valid_yaml() -> str:
    return """\
schema: fura-mappo.demand-generation
version: 1
demand:
  type: stationary_poisson
  seed: 17
  intensities: [0.2, 0.4]
  zone_bounds:
    - [0.0, 1.0, 0.0, 1.0]
    - [1.0, 2.0, 0.0, 1.0]
  priority_range: [0.2, 0.8]
  service_time_range: [1, 2]
  deadline_offset_range: [2, 3]
generation:
  num_steps: 3
"""


def _write_yaml(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("name", _EXAMPLE_NAMES)
def test_examples_load_create_and_generate_small_trace(name: str) -> None:
    path = Path("configs/demand") / f"{name}.yaml"

    config = load_demand_config(path)
    process = create_demand_process(config["demand"])  # type: ignore[arg-type]
    trace = process.generate(config["generation"]["num_steps"])  # type: ignore[index]

    assert config["demand"]["type"] == name  # type: ignore[index]
    assert trace.counts.shape == (5, 2)


def test_loader_returns_independent_plain_tree(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path / "config.yaml", _valid_yaml())

    first = load_demand_config(path)
    second = load_demand_config(path)
    first["demand"]["intensities"][0] = 99.0  # type: ignore[index]

    assert second["demand"]["intensities"] == [0.2, 0.4]  # type: ignore[index]
    assert path.read_text(encoding="utf-8") == _valid_yaml()


@pytest.mark.parametrize("path_value", [b"config.yaml", bytearray(b"config.yaml")])
def test_loader_rejects_bytes_paths(path_value: object) -> None:
    with pytest.raises(TypeError):
        load_demand_config(path_value)  # type: ignore[arg-type]


def test_loader_requires_exact_lowercase_yaml_suffix(tmp_path: Path) -> None:
    for name in ("config.yml", "config.YAML", "config.yaml.txt"):
        with pytest.raises(ValueError, match=".yaml"):
            load_demand_config(tmp_path / name)


def test_loader_preserves_io_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_demand_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- top-level-sequence\n", "顶层必须是 Mapping"),
        (
            """\
schema: fura-mappo.demand-generation
version: 1
demand: stationary_poisson
generation: {num_steps: 3}
""",
            "demand 必须是 Mapping",
        ),
        (
            """\
schema: fura-mappo.demand-generation
version: 1
demand: {}
generation: scalar
""",
            "generation 必须是 Mapping",
        ),
        (
            """\
schema: fura-mappo.demand-generation
version: "1"
demand: {}
generation: {num_steps: 3}
""",
            "version 必须是整数",
        ),
    ],
)
def test_yaml_content_type_errors_are_public_value_errors(
    tmp_path: Path, text: str, message: str
) -> None:
    path = _write_yaml(tmp_path / "content-error.yaml", text)

    with pytest.raises(ValueError, match=message):
        load_demand_config(path)


def test_loader_rejects_oversize_and_non_utf8_files(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="1048576"):
        load_demand_config(oversized)

    invalid_utf8 = tmp_path / "invalid.yaml"
    invalid_utf8.write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="UTF-8"):
        load_demand_config(invalid_utf8)


@pytest.mark.parametrize(
    ("fragment", "message"),
    [
        ("schema: [", "语法"),
        ("value: !!python/object/apply:os.system ['false']", "标签"),
        ("schema: &base fura-mappo.demand-generation", "anchor"),
        ("schema: *base", "alias"),
        ("<<: {schema: fura-mappo.demand-generation}", "merge"),
        ("created: 2026-08-18", "标签"),
        ("payload: !!binary YQ==", "标签"),
        ("items: !!set {a: null}", "标签"),
    ],
)
def test_loader_rejects_unsafe_yaml_before_construction(
    tmp_path: Path, fragment: str, message: str
) -> None:
    path = _write_yaml(tmp_path / "unsafe.yaml", fragment + "\n")

    with pytest.raises(ValueError, match=message):
        load_demand_config(path)


def test_loader_rejects_duplicate_and_non_string_mapping_keys(tmp_path: Path) -> None:
    duplicate = _write_yaml(
        tmp_path / "duplicate.yaml",
        _valid_yaml().replace("version: 1", "version: 1\nversion: 1"),
    )
    with pytest.raises(ValueError, match="重复键"):
        load_demand_config(duplicate)

    non_string = _write_yaml(tmp_path / "key.yaml", "1: value\n")
    with pytest.raises(ValueError, match="字符串"):
        load_demand_config(non_string)


def test_loader_enforces_node_and_depth_limits(tmp_path: Path) -> None:
    deep = "value: " + "[" * 65 + "0" + "]" * 65 + "\n"
    with pytest.raises(ValueError, match="深度"):
        load_demand_config(_write_yaml(tmp_path / "deep.yaml", deep))

    many = "values:\n" + "  - 0\n" * 10_001
    with pytest.raises(ValueError, match="节点数"):
        load_demand_config(_write_yaml(tmp_path / "many.yaml", many))


@pytest.mark.parametrize(
    "replacement",
    [
        "version: true",
        "version: null",
        "version: .nan",
        "version: .inf",
    ],
)
def test_loader_rejects_disallowed_scalar_types(tmp_path: Path, replacement: str) -> None:
    text = _valid_yaml().replace("version: 1", replacement)

    with pytest.raises(ValueError):
        load_demand_config(_write_yaml(tmp_path / "scalar.yaml", text))


def test_loader_reports_top_and_generation_schema_errors(tmp_path: Path) -> None:
    text = _valid_yaml().replace("schema:", "metadata: x\nschema:")
    text = text.replace("version: 1\n", "")
    with pytest.raises(ValueError) as error:
        load_demand_config(_write_yaml(tmp_path / "top.yaml", text))
    assert "version" in str(error.value) and "metadata" in str(error.value)

    generation = _valid_yaml().replace("  num_steps: 3", "  steps: 3\n  output: ignored")
    with pytest.raises(ValueError) as error:
        load_demand_config(_write_yaml(tmp_path / "generation.yaml", generation))
    assert "num_steps" in str(error.value) and "output" in str(error.value)


@pytest.mark.parametrize("value", ["true", "0", "-1", "1.5", "null"])
def test_loader_rejects_invalid_num_steps(tmp_path: Path, value: str) -> None:
    text = _valid_yaml().replace("num_steps: 3", f"num_steps: {value}")
    with pytest.raises(ValueError, match="num_steps|标签|布尔"):
        load_demand_config(_write_yaml(tmp_path / "steps.yaml", text))


def test_loader_delegates_scientific_validation_to_factory(tmp_path: Path) -> None:
    text = _valid_yaml().replace("intensities: [0.2, 0.4]", "intensities: [-1.0, 0.4]")
    with pytest.raises(ValueError, match="非负"):
        load_demand_config(_write_yaml(tmp_path / "science.yaml", text))


def test_hash_is_order_stable_and_sequence_numpy_scalar_equivalent() -> None:
    first = {"b": [np.int64(1), np.float32(0.5)], "a": ("x",)}
    second = {"a": np.array(["x"]), "b": np.array([1.0, 0.5])}

    assert compute_config_hash(first) != compute_config_hash(second)
    assert compute_config_hash({"a": [1, 0.5]}) == compute_config_hash(
        {"a": (np.int64(1), np.float64(0.5))}
    )
    assert compute_config_hash({"a": 1, "b": 2}) == compute_config_hash({"b": 2, "a": 1})


def test_hash_preserves_type_boundaries_and_normalizes_negative_zero() -> None:
    assert compute_config_hash({"x": 1}) != compute_config_hash({"x": 1.0})
    assert compute_config_hash({"x": 0.5}) != compute_config_hash({"x": "0x1.000p-1"})
    assert compute_config_hash({"x": -0.0}) == compute_config_hash({"x": 0.0})
    assert compute_config_hash({"x": "é"}) != compute_config_hash({"x": "e\u0301"})


def test_hash_changes_for_seed_or_steps_and_does_not_modify_input() -> None:
    config = {"demand": {"seed": 1, "values": [1.0]}, "generation": {"num_steps": 3}}
    original_values = list(config["demand"]["values"])  # type: ignore[arg-type]
    original = compute_config_hash(config)
    changed_seed = {"demand": {"seed": 2, "values": [1.0]}, "generation": {"num_steps": 3}}
    changed_steps = {"demand": {"seed": 1, "values": [1.0]}, "generation": {"num_steps": 4}}

    assert original != compute_config_hash(changed_seed)
    assert original != compute_config_hash(changed_steps)
    assert config["demand"]["values"] == original_values  # type: ignore[index]


@pytest.mark.parametrize("value", [True, np.bool_(False), np.nan, np.inf, None, {1, 2}])
def test_hash_rejects_unsupported_or_nonfinite_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        compute_config_hash({"value": value})


def test_hash_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(TypeError):
        compute_config_hash({1: "value"})  # type: ignore[dict-item]


def test_yaml_loaded_and_direct_mapping_generate_identical_trajectories() -> None:
    loaded = load_demand_config(Path("configs/demand/markov_switching.yaml"))
    direct = {
        key: value
        for key, value in loaded["demand"].items()  # type: ignore[union-attr]
    }

    loaded_trace = create_demand_process(loaded["demand"]).generate(5)  # type: ignore[arg-type]
    direct_trace = create_demand_process(direct).generate(5)

    np.testing.assert_array_equal(loaded_trace.counts, direct_trace.counts)
    np.testing.assert_array_equal(loaded_trace.intensities, direct_trace.intensities)
    assert loaded_trace.events == direct_trace.events


def test_load_and_hash_do_not_pollute_global_random_states(tmp_path: Path) -> None:
    numpy_state = np.random.get_state()
    python_state = random.getstate()

    config = load_demand_config(_write_yaml(tmp_path / "config.yaml", _valid_yaml()))
    compute_config_hash(config)

    current = np.random.get_state()
    assert numpy_state[0] == current[0]
    np.testing.assert_array_equal(numpy_state[1], current[1])
    assert numpy_state[2:] == current[2:]
    assert python_state == random.getstate()
