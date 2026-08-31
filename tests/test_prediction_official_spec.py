"""WP-03 ES-01 frozen official spec 与 execution-plan identity tests。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from fura_mappo.prediction import (
    EXPECTED_WP03_POINT_PRIMARY_V1_SPEC_SHA256,
    build_official_baseline_plan,
    build_official_dataset_protocols,
    build_official_rng_namespace_plan,
    build_official_training_plan,
    compute_official_model_complexity_key,
    load_official_point_experiment_spec,
    official_training_run_count,
    plan_official_learned_configs,
)

_SPEC_PATH = Path("configs/experiments/wp03_point_primary_v1.yaml")
_EXPECTED_SPEC_SHA256 = "93fd011f0dbbdbc784db1b12e18aa37c4d15121c22620649b7218d2799c84fd0"
_EXPECTED_PROTOCOL_SHA256 = {
    4: "f09c00cfbe718eb67ba77d8dac88763effc56febcfd6985910d2c879b300659c",
    8: "fd5b6e4465b7897b5018552dc9855738d34dd419738def97a28bbe420d62fcd0",
    16: "bcd60ca2e7d8aa7d18d9a64881784003fb3a6d2ab174a003aa724dfda3385ea4",
    32: "23c834e8b5faccdc58ff9963c42b13970c7a0b96fb0a9c8dd61020685f0010b0",
}
_EXPECTED_TRAINING_PLAN_SHA256 = "0d653c07705f882c8c21d36df55ff79d4278a7ba3d53d887bf706b4a6f86a807"
_EXPECTED_RNG_PLAN_SHA256 = "154f9faac053b2a298fc0d7ffd89e2b0d7bc05901b9da225eb13ed1e6bcee018"
_EXPECTED_BASELINE_PLAN_SHA256 = "bda3bea6dd31a92a0d744248300251a9652ac44f2955ee0261cee6de8011403b"


def _write_mutation(tmp_path: Path, old: str, new: str) -> Path:
    source = _SPEC_PATH.read_text(encoding="utf-8")
    assert source.count(old) == 1
    path = tmp_path / "mutated.yaml"
    path.write_text(source.replace(old, new), encoding="utf-8")
    return path


def test_exact_yaml_loads_with_stable_hash_and_recursive_immutability() -> None:
    spec = load_official_point_experiment_spec(_SPEC_PATH)

    assert EXPECTED_WP03_POINT_PRIMARY_V1_SPEC_SHA256 == _EXPECTED_SPEC_SHA256
    assert spec.sha256 == _EXPECTED_SPEC_SHA256
    assert spec.experiment_id == "wp03_point_primary_v1"
    assert spec.prediction_horizon == 2
    assert spec.history_lengths == (4, 8, 16, 32)
    assert spec.training_seeds == (610001, 610002, 610003)
    assert spec.reserved_artifact_root == "artifacts/wp03_prediction_official_v1/"
    with pytest.raises(TypeError):
        spec.config["version"] = 2  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        spec.sha256 = "0" * 64  # type: ignore[misc]

    copied = spec.to_plain_tree()
    copied["version"] = 2
    assert spec.config["version"] == 1


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("primary_prediction_horizon: 2", "primary_prediction_horizon: 3"),
        ("count: 128\n    seed_start: 410000", "count: 127\n    seed_start: 410000"),
        ("hidden_widths: [64, 128]", "hidden_widths: [32, 128]"),
    ],
)
def test_single_scientific_value_mutation_is_rejected(
    tmp_path: Path,
    old: str,
    new: str,
) -> None:
    with pytest.raises(ValueError):
        load_official_point_experiment_spec(_write_mutation(tmp_path, old, new))


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    path = _write_mutation(tmp_path, "version: 1", "version: 1\nversion: 1")
    with pytest.raises(ValueError, match="重复键"):
        load_official_point_experiment_spec(path)


def test_anchor_and_alias_are_rejected(tmp_path: Path) -> None:
    path = _write_mutation(
        tmp_path,
        "protocols:\n  prediction_horizon: 2\n  history_lengths: [4, 8, 16, 32]",
        "protocols:\n  prediction_horizon: 2\n  history_lengths: &lengths [4, 8, 16, 32]",
    )
    with pytest.raises(ValueError, match="anchor"):
        load_official_point_experiment_spec(path)

    alias_path = tmp_path / "alias.yaml"
    alias_path.write_text("schema: &schema value\nversion: *schema\n", encoding="utf-8")
    with pytest.raises(ValueError, match="anchor|alias"):
        load_official_point_experiment_spec(alias_path)


def test_bool_as_integer_and_nonfinite_float_are_rejected(tmp_path: Path) -> None:
    bool_path = _write_mutation(tmp_path, "version: 1", "version: true")
    with pytest.raises(ValueError, match="不安全|不支持|布尔值"):
        load_official_point_experiment_spec(bool_path)

    nonfinite_path = _write_mutation(
        tmp_path,
        "output_epsilon: 0.000001",
        "output_epsilon: .inf",
    )
    with pytest.raises(ValueError, match="不安全|不支持|无穷"):
        load_official_point_experiment_spec(nonfinite_path)


def test_protocols_are_exact_and_canonically_ordered() -> None:
    spec = load_official_point_experiment_spec(_SPEC_PATH)
    protocols = build_official_dataset_protocols(spec)

    assert protocols.primary_protocol.history_length == 4
    assert tuple(item.history_length for item in protocols.additional_protocols) == (8, 16, 32)
    assert tuple(item.history_length for item in protocols.all_protocols) == (4, 8, 16, 32)
    assert all(item.prediction_horizon == 2 for item in protocols.all_protocols)
    assert {
        item.history_length: item.sha256 for item in protocols.all_protocols
    } == _EXPECTED_PROTOCOL_SHA256


def test_execution_plan_hashes_and_namespace_semantics_are_stable() -> None:
    spec = load_official_point_experiment_spec(_SPEC_PATH)
    training = build_official_training_plan(spec)
    rng = build_official_rng_namespace_plan(spec)
    baseline = build_official_baseline_plan(spec)

    assert training.sha256 == _EXPECTED_TRAINING_PLAN_SHA256
    assert rng.sha256 == _EXPECTED_RNG_PLAN_SHA256
    assert baseline.sha256 == _EXPECTED_BASELINE_PLAN_SHA256
    assert training.to_plain_tree()["training"] == {
        "mode": "full_batch",
        "sample_order": "canonical_fixed",
        "shuffle": "NONE",
        "dtype": "float32",
        "amp": "DISABLED",
        "max_epochs": 300,
        "patience": 30,
        "min_improvement": 1e-5,
        "checkpoint_rule": "new_rmse_strictly_less_than_best_minus_min_improvement",
        "initial_best": "first_finite_epoch",
        "final_retrain": "NONE",
    }
    rng_tree = rng.to_plain_tree()
    demand_seeds = {
        seed
        for start, end in rng_tree["demand_generation"]["source_seed_ranges"]
        for seed in range(start, end + 1)
    }
    training_seeds = set(rng_tree["model_initialization"]["seeds"])
    bootstrap_seed = rng_tree["prediction_bootstrap"]["seed"]
    assert len(demand_seeds) == 416
    assert demand_seeds.isdisjoint(training_seeds)
    assert bootstrap_seed not in demand_seeds | training_seeds
    assert len(demand_seeds | training_seeds | {bootstrap_seed}) == 420
    assert rng_tree["cross_namespace_derivation"] == "PROHIBITED"
    baseline_tree = baseline.to_plain_tree()
    assert baseline_tree["two_stage_rule"] == {
        "step_1": "lock_each_baseline_internal_variant",
        "step_2": "compare_six_locked_variants_by_validation_primary_rmse",
    }
    assert baseline_tree["b2_internal_total_order"] == [
        "validation_primary_rmse",
        "shorter_history_length",
    ]
    assert baseline_tree["b3_internal_total_order"] == [
        "validation_primary_rmse",
        "shorter_history_length",
        "smaller_alpha",
    ]
    assert baseline_tree["bstar_tie_order"] == ["B0", "B1", "B2", "B3", "B4", "B5"]
    assert baseline_tree["execution"] == "NONE"


@pytest.mark.parametrize("history_length", [4, 8, 16, 32])
@pytest.mark.parametrize("hidden_width", [64, 128])
def test_complexity_key_is_authoritative(history_length: int, hidden_width: int) -> None:
    input_dimension = 5 * history_length + 1
    expected = input_dimension * hidden_width + hidden_width**2 + 10 * hidden_width + 8
    assert compute_official_model_complexity_key(history_length, hidden_width) == (expected,)


def test_learned_configs_have_exact_count_order_hashes_and_run_count() -> None:
    spec = load_official_point_experiment_spec(_SPEC_PATH)
    planned = plan_official_learned_configs(spec)

    assert len(planned) == 64
    assert tuple(item.canonical_order for item in planned) == tuple(range(64))
    assert len({item.config_sha256 for item in planned}) == 64
    assert official_training_run_count(spec) == 192
    assert [
        (
            item.hidden_width,
            item.learning_rate,
            item.history_length,
            item.objective.value,
            item.transform.value,
        )
        for item in planned[:5]
    ] == [
        (64, 0.0003, 4, "O0", "T0"),
        (64, 0.0003, 4, "O0", "T1"),
        (64, 0.0003, 4, "O1", "T0"),
        (64, 0.0003, 4, "O1", "T1"),
        (64, 0.0003, 8, "O0", "T0"),
    ]
    assert all(
        item.model_complexity_key
        == compute_official_model_complexity_key(item.history_length, item.hidden_width)
        for item in planned
    )


def test_static_cross_field_guards_cover_conditions_and_feasibility() -> None:
    spec = load_official_point_experiment_spec(_SPEC_PATH)
    config = spec.to_plain_tree()
    conditions = config["conditions"]
    id_condition = conditions["id"]
    for name, velocity in (("near_v020", 0.20), ("near_v030", 0.30)):
        near = conditions[name]
        differing = {key for key in id_condition if id_condition[key] != near[key]}
        assert differing == {"hotspot_velocities"}
        assert near["hotspot_velocities"] == [[velocity, 0.0]]
    assert [sum(row) for row in conditions["structural_markov"]["state_intensities"]] == [
        0.65,
        0.65,
    ]
    assert sum(id_condition["base_intensities"]) + id_condition["hotspot_amplitudes"][0] == 0.65
    assert config["feasibility"] == {
        "anchors_per_trace": 255,
        "valid_target_cells_per_trace": 2036,
        "training_run_count": 192,
    }


def test_near_ood_single_axis_and_markov_total_mutations_hit_static_guards(
    tmp_path: Path,
) -> None:
    near_path = _write_mutation(
        tmp_path,
        "near_v020:\n    type: drifting_hotspot\n"
        "    base_intensities: [0.025, 0.025, 0.025, 0.025]",
        "near_v020:\n    type: drifting_hotspot\n"
        "    base_intensities: [0.026, 0.025, 0.025, 0.025]",
    )
    with pytest.raises(ValueError, match="只改变 hotspot velocity x"):
        load_official_point_experiment_spec(near_path)

    markov_path = _write_mutation(
        tmp_path,
        "- [0.50, 0.10, 0.025, 0.025]",
        "- [0.51, 0.10, 0.025, 0.025]",
    )
    with pytest.raises(ValueError, match="Markov state total"):
        load_official_point_experiment_spec(markov_path)
