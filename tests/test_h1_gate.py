from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast

import numpy as np
import pytest
import yaml

import fura_mappo.experiments as experiments_package
import fura_mappo.experiments.h1_gate as h1_module
from fura_mappo.demand import (
    DemandEvent,
    DemandTrace,
    DemandTraceArtifact,
    load_demand_trace,
    save_demand_trace,
)
from fura_mappo.envs import (
    EpisodeMetrics,
    MoveAction,
    ResourceServiceConfig,
)
from fura_mappo.experiments import (
    H1GateSpec,
    H1Verdict,
    compute_artifact_inventory_hash,
    compute_h1_spec_hash,
    compute_paired_results_hash,
    load_h1_gate_spec,
    primary_seeds,
    read_artifact_inventory,
    run_paired_trace,
    run_primary_artifact,
)
from fura_mappo.experiments.h1_gate import (
    ArtifactInventory,
    ArtifactInventoryEntry,
    ArtifactPlanEntry,
    FormalProvenance,
    H1GateSummary,
    H1ProtocolError,
    PairedTraceResult,
    build_primary_artifact_inventory,
    build_primary_demand_config,
    build_primary_environment_config,
    build_provenance_bound_artifact_entry,
    compute_environment_config_hash,
    evaluate_primary_gate,
    plan_primary_artifacts,
    read_h1_summary,
    read_paired_jsonl,
    read_primary_verdict,
    require_locked_primary_verdict,
    validate_canonical_mechanism,
    validate_formal_provenance,
    validate_h0_invariant,
    validate_primary_paired_results,
    write_artifact_inventory,
    write_canonical_json,
    write_h1_summary,
    write_paired_jsonl,
    write_primary_verdict,
)

_SPEC_PATH = Path("configs/experiments/wp02d_h1.yaml")
_TEST_SPEC_SHA256 = "1" * 64
_TEST_CONFIG_SHA256 = "2" * 64
_TEST_CONTENT_SHA256 = "3" * 64


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _spec_tree() -> dict[str, object]:
    loaded = yaml.safe_load(_SPEC_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _event(
    event_id: int,
    *,
    arrival: int,
    position: tuple[float, float],
    service: int = 1,
    deadline: int,
) -> DemandEvent:
    return DemandEvent(
        event_id=event_id,
        arrival_step=arrival,
        zone_id=0,
        position=position,
        priority=0.5,
        service_time=service,
        deadline=deadline,
    )


def _trace(events: tuple[DemandEvent, ...] = (), *, num_steps: int = 4) -> DemandTrace:
    counts = np.zeros((num_steps, 1), dtype=np.int64)
    for event in events:
        counts[event.arrival_step, 0] += 1
    return DemandTrace(
        start_step=0,
        counts=counts,
        intensities=np.zeros((num_steps, 1), dtype=np.float64),
        events=events,
    )


def _metrics(arrived: int, completed: int) -> EpisodeMetrics:
    expired = arrived - completed
    return EpisodeMetrics(
        arrived=arrived,
        completed=completed,
        expired=expired,
        truncated=0,
        arrived_priority_sum=0.5 * arrived,
        completed_priority_sum=0.5 * completed,
        expired_priority_sum=0.5 * expired,
        truncated_priority_sum=0.0,
        demanded_service_work=arrived,
        service_slots=completed,
        movement_slots=0,
        idle_slots=0,
        movement_distance=0.0,
        completed_service_work=completed,
        expired_service_work=0,
        truncated_service_work=0,
        expired_remaining_work=expired,
        truncated_remaining_work=0,
        service_start_wait_sum=0,
        service_start_count=completed,
        completed_response_sum=completed,
        completed_response_count=completed,
        duplicate_assignment_conflicts=0,
        zero_distance_moves=0,
        per_zone_arrived=(arrived,),
        per_zone_completed=(completed,),
        per_zone_expired=(expired,),
        per_zone_truncated=(0,),
        completion_rate=None if arrived == 0 else completed / arrived,
        expiration_rate=None if arrived == 0 else expired / arrived,
        truncation_rate=None if arrived == 0 else 0.0,
        mean_service_start_wait=None if completed == 0 else 0.0,
        mean_completed_response=None if completed == 0 else 1.0,
    )


def _result(seed: int, difference: float, *, horizon: int = 2) -> PairedTraceResult:
    arrived = 100
    reactive_completed = 50
    oracle_completed = reactive_completed + round(difference * arrived)
    return PairedTraceResult(
        seed=seed,
        trace_id=f"trace_{seed}",
        horizon=horizon,
        experiment_spec_sha256=_TEST_SPEC_SHA256,
        artifact_config_sha256=_TEST_CONFIG_SHA256,
        artifact_content_sha256=_TEST_CONTENT_SHA256,
        environment_config_sha256="4" * 64,
        reactive_metrics=_metrics(arrived, reactive_completed),
        oracle_metrics=_metrics(arrived, oracle_completed),
        primary_difference=(oracle_completed - reactive_completed) / arrived,
        reference_nonempty_view_steps=1,
        reference_feasible_future_pair_steps=1,
        reference_oracle_would_differ_steps=1,
        reference_oracle_would_preposition_steps=1,
        actionable_steps=2,
        has_reference_feasible_future_pair=True,
        has_reference_oracle_action_difference=True,
        realized_oracle_prearrival_move_steps=1,
        oracle_actionable_steps=2,
    )


def _run_tiny(
    trace: DemandTrace,
    config: ResourceServiceConfig,
    horizon: int,
    *,
    seed: int,
    trace_id: str,
) -> PairedTraceResult:
    """使用显式测试 provenance 调用非正式低层 runner。"""

    return run_paired_trace(
        trace,
        config,
        horizon,
        seed=seed,
        trace_id=trace_id,
        experiment_spec_sha256=_TEST_SPEC_SHA256,
        artifact_config_sha256=_TEST_CONFIG_SHA256,
        artifact_content_sha256=_TEST_CONTENT_SHA256,
    )


def _seed_hash(label: str, seed: int) -> str:
    return hashlib.sha256(f"{label}:{seed}".encode("ascii")).hexdigest()


def _formal_inventory(spec: H1GateSpec) -> ArtifactInventory:
    entries = tuple(
        ArtifactInventoryEntry(
            seed=seed,
            relative_path=f"trace_{seed}.npz",
            process_type="drifting_hotspot",
            config_sha256=h1_module.compute_config_hash(build_primary_demand_config(spec, seed)),
            content_sha256=_seed_hash("content", seed),
            start_step=0,
            num_steps=256,
            num_events=0,
        )
        for seed in primary_seeds(spec)
    )
    return ArtifactInventory(
        experiment_spec_sha256=spec.sha256,
        wp02c_stable_sha=spec.wp02c_stable_sha,
        planned_seed_count=256,
        entries=entries,
    )


def _formal_results(
    spec: H1GateSpec,
    inventory: ArtifactInventory,
    difference: float = 0.03,
) -> tuple[PairedTraceResult, ...]:
    environment_sha256 = compute_environment_config_hash(build_primary_environment_config(spec))
    return tuple(
        replace(
            _result(entry.seed, difference),
            trace_id=entry.relative_path,
            experiment_spec_sha256=spec.sha256,
            artifact_config_sha256=entry.config_sha256,
            artifact_content_sha256=entry.content_sha256,
            environment_config_sha256=environment_sha256,
        )
        for entry in inventory.entries
    )


def _write_result_rows(path: Path, rows: list[dict[str, object]]) -> Path:
    payload = b"\n".join(h1_module._canonical_json_bytes(row) for row in rows) + b"\n"
    path.write_bytes(payload)
    return path


def _formal_result_rows(
    spec: H1GateSpec,
    inventory: ArtifactInventory,
) -> list[dict[str, object]]:
    return [h1_module.paired_result_to_dict(result) for result in _formal_results(spec, inventory)]


def _formal_provenance(spec: H1GateSpec) -> FormalProvenance:
    return FormalProvenance(
        actual_head="a" * 40,
        origin_main="a" * 40,
        wp02c_stable_sha=spec.wp02c_stable_sha,
        wp02d_accepted_implementation_sha="b" * 40,
        experiment_spec_sha256=spec.sha256,
        git_dirty=False,
    )


def _formal_summary() -> H1GateSummary:
    """构造不运行 formal bootstrap 的结构合法 verdict 测试替身。"""

    small = h1_module._scientific_summary(
        tuple(_result(seed, 0.03) for seed in range(4)),
        delta_min=0.02,
        resamples=100,
        bootstrap_seed=13,
        n_planned=4,
    )
    return replace(
        small,
        n_planned=256,
        n_valid=256,
        bootstrap_resamples=50_000,
        bootstrap_seed=90_260_819,
    )


def _formal_verdict_context(
    spec: H1GateSpec,
) -> tuple[ArtifactInventory, tuple[PairedTraceResult, ...], str, str, FormalProvenance]:
    inventory = _formal_inventory(spec)
    results = _formal_results(spec, inventory)
    return (
        inventory,
        results,
        compute_artifact_inventory_hash(inventory),
        compute_paired_results_hash(results),
        _formal_provenance(spec),
    )


def test_public_exports_are_minimal_and_available() -> None:
    assert experiments_package.__all__ == [
        "H1GateSpec",
        "H1GateSummary",
        "H1Verdict",
        "PairedTraceResult",
        "compute_artifact_inventory_hash",
        "compute_h1_spec_hash",
        "compute_paired_results_hash",
        "evaluate_primary_gate",
        "load_h1_gate_spec",
        "primary_seeds",
        "read_artifact_inventory",
        "run_paired_trace",
        "run_primary_artifact",
    ]


def test_load_frozen_spec_and_hash_is_stable() -> None:
    first = load_h1_gate_spec(_SPEC_PATH)
    second = load_h1_gate_spec(_SPEC_PATH)

    assert isinstance(first, H1GateSpec)
    assert first.primary_horizon == 2
    assert first.num_steps == 256
    assert first.sha256 == second.sha256 == compute_h1_spec_hash(first)
    assert len(first.sha256) == 64
    primary = first.config["primary"]
    assert primary["demand"]["priority_range"] == (0.5, 0.5)  # type: ignore[index]
    assert first.config["sensitivity"] == {
        "horizons": (0, 1, 2, 3, 4),
        "priority_range": (0.25, 0.75),
    }


def test_spec_defensively_copies_programmatic_mapping() -> None:
    tree = _spec_tree()
    original = json.loads(json.dumps(tree))

    spec = H1GateSpec(tree)

    assert tree == original
    tree["primary"]["demand"]["base_intensities"][0] = 9.0  # type: ignore[index]
    primary = spec.config["primary"]
    assert primary["demand"]["base_intensities"][0] == 0.025  # type: ignore[index]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda tree: tree.update(version=2), "version"),
        (lambda tree: tree.update(extra=1), "字段"),
        (lambda tree: tree.pop("gate"), "字段"),
        (lambda tree: tree["primary"].update(horizon=3), "horizon"),  # type: ignore[union-attr]
        (
            lambda tree: tree["primary"]["demand"].update(priority_range=[0.25, 0.75]),  # type: ignore[index,union-attr]
            "priority_range",
        ),
        (lambda tree: tree["seed_protocol"].update(count=255), "count"),  # type: ignore[union-attr]
        (lambda tree: tree["bootstrap"].update(resamples=100), "resamples"),  # type: ignore[union-attr]
        (lambda tree: tree["gate"].update(delta_min=0.01), "delta_min"),  # type: ignore[union-attr]
    ],
)
def test_loader_rejects_any_frozen_override(
    tmp_path: Path,
    mutator: object,
    message: str,
) -> None:
    tree = _spec_tree()
    mutator(tree)  # type: ignore[operator]
    path = _write(tmp_path / "spec.yaml", yaml.safe_dump(tree, sort_keys=False))

    with pytest.raises(ValueError, match=message):
        load_h1_gate_spec(path)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("schema: x\nschema: y\n", "重复键"),
        ("schema: &x value\nvalue: *x\n", "anchor|alias"),
        ("base: &x {value: 1}\nmerged: {<<: *x}\n", "anchor|merge"),
        ("value: !!python/object/apply:os.system ['false']\n", "标签|安全"),
        ("- not-a-mapping\n", "顶层"),
    ],
)
def test_loader_rejects_unsafe_yaml(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_h1_gate_spec(_write(tmp_path / "unsafe.yaml", text))


@pytest.mark.parametrize("replacement", ["version: true", "version: .nan", "version: .inf"])
def test_loader_rejects_bool_and_nonfinite(tmp_path: Path, replacement: str) -> None:
    text = _SPEC_PATH.read_text(encoding="utf-8").replace("version: 1", replacement, 1)
    with pytest.raises(ValueError):
        load_h1_gate_spec(_write(tmp_path / "invalid.yaml", text))


def test_loader_preserves_path_and_io_contract(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        load_h1_gate_spec(b"spec.yaml")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=".yaml"):
        load_h1_gate_spec(tmp_path / "spec.yml")
    with pytest.raises(FileNotFoundError):
        load_h1_gate_spec(tmp_path / "missing.yaml")


def test_loader_rejects_oversized_yaml_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "large.yaml"
    path.write_bytes(b"x" * (h1_module._MAX_SPEC_BYTES + 1))

    with pytest.raises(ValueError, match="大小上限|不能超过"):
        load_h1_gate_spec(path)


def test_seed_protocol_is_exact_without_generating_traces() -> None:
    seeds = primary_seeds(load_h1_gate_spec(_SPEC_PATH))

    assert isinstance(seeds, tuple)
    assert len(seeds) == len(set(seeds)) == 256
    assert seeds[0] == 20_260_819
    assert seeds[-1] == 20_261_074
    assert seeds == tuple(range(20_260_819, 20_261_075))


def test_primary_demand_and_environment_configs_are_exact() -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    demand = build_primary_demand_config(spec, 17)
    environment = build_primary_environment_config(spec)

    assert demand["schema"] == "fura-mappo.demand-generation"
    assert demand["version"] == 1
    assert demand["demand"]["seed"] == 17  # type: ignore[index]
    assert demand["demand"]["priority_range"] == [0.5, 0.5]  # type: ignore[index]
    assert demand["generation"] == {"num_steps": 256}
    assert environment.initial_resource_positions == ((0.5, 0.5), (3.5, 0.5))
    assert environment.movement_speed == 0.75
    with pytest.raises(TypeError, match="布尔"):
        build_primary_demand_config(spec, True)


def test_artifact_plan_is_deterministic_and_relative() -> None:
    plan = plan_primary_artifacts(load_h1_gate_spec(_SPEC_PATH))

    assert len(plan) == 256
    assert plan[0].relative_path == "trace_20260819.npz"
    assert plan[-1].relative_path == "trace_20261074.npz"
    assert all(not Path(item.relative_path).is_absolute() for item in plan)
    with pytest.raises(H1ProtocolError, match="相对"):
        ArtifactInventoryEntry(
            seed=1,
            relative_path="/private/trace_1.npz",
            process_type="drifting_hotspot",
            config_sha256="a" * 64,
            content_sha256="b" * 64,
            start_step=0,
            num_steps=1,
            num_events=0,
        )


def test_primary_inventory_checks_each_seed_config_hash_without_generating_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)

    def fake_build(_: H1GateSpec, seed: int) -> dict[str, object]:
        return {"seed": seed}

    def fake_hash(config: object) -> str:
        seed = config["seed"]  # type: ignore[index]
        return hashlib.sha256(str(seed).encode("ascii")).hexdigest()

    monkeypatch.setattr(h1_module, "build_primary_demand_config", fake_build)
    monkeypatch.setattr(h1_module, "compute_config_hash", fake_hash)
    entries = tuple(
        ArtifactInventoryEntry(
            seed=seed,
            relative_path=f"trace_{seed}.npz",
            process_type="drifting_hotspot",
            config_sha256=fake_hash({"seed": seed}),
            content_sha256="a" * 64,
            start_step=0,
            num_steps=256,
            num_events=0,
        )
        for seed in primary_seeds(spec)
    )

    inventory = build_primary_artifact_inventory(spec, entries)
    assert inventory.entries == entries
    with pytest.raises(H1ProtocolError, match="config_sha256"):
        build_primary_artifact_inventory(
            spec,
            (replace(entries[0], config_sha256="b" * 64), *entries[1:]),
        )


def test_tiny_synthetic_artifact_entry_round_trip_and_mismatch(tmp_path: Path) -> None:
    config = {
        "schema": "fura-mappo.demand-generation",
        "version": 1,
        "demand": {
            "type": "stationary_poisson",
            "seed": 17,
            "intensities": [0.0],
            "zone_bounds": [[0.0, 1.0, 0.0, 1.0]],
            "priority_range": [0.5, 0.5],
            "service_time_range": [1, 1],
            "deadline_offset_range": [1, 1],
        },
        "generation": {"num_steps": 3},
    }
    path = tmp_path / "trace_17.npz"
    save_demand_trace(path, _trace(num_steps=3), resolved_config=config)
    artifact = load_demand_trace(path)
    manifest = artifact.manifest
    entry = ArtifactInventoryEntry(
        seed=17,
        relative_path=path.name,
        process_type="stationary_poisson",
        config_sha256=manifest["config_sha256"],  # type: ignore[arg-type]
        content_sha256=manifest["content_sha256"],  # type: ignore[arg-type]
        start_step=0,
        num_steps=3,
        num_events=0,
    )

    h1_module._validate_artifact_entry(path, entry, 3)
    with pytest.raises(H1ProtocolError, match="content_sha256"):
        h1_module._validate_artifact_entry(
            path,
            replace(entry, content_sha256="0" * 64),
            3,
        )
    with pytest.raises(FileNotFoundError):
        h1_module._validate_artifact_entry(tmp_path / "missing.npz", entry, 3)
    corrupt = tmp_path / "corrupt.npz"
    corrupt.write_bytes(b"not-an-npz")
    with pytest.raises(ValueError):
        h1_module._validate_artifact_entry(corrupt, entry, 3)


def test_inventory_rejects_duplicate_paths_and_wrong_seed_order() -> None:
    entries = (
        ArtifactInventoryEntry(1, "trace_1.npz", "drifting_hotspot", "0" * 64, "1" * 64, 0, 3, 0),
        ArtifactInventoryEntry(2, "trace_1.npz", "drifting_hotspot", "2" * 64, "3" * 64, 0, 3, 0),
    )
    inventory = ArtifactInventory("4" * 64, "5" * 40, 2, entries)

    with pytest.raises(H1ProtocolError, match="重复 artifact path"):
        h1_module._validate_inventory_entries(
            inventory,
            expected_seeds=(1, 2),
            expected_num_steps=3,
        )
    with pytest.raises(H1ProtocolError, match="seed 集或顺序"):
        h1_module._validate_inventory_entries(
            replace(inventory, entries=tuple(reversed(entries))),
            expected_seeds=(1, 2),
            expected_num_steps=3,
        )


def test_read_inventory_is_strict_and_runs_full_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)
    path = write_artifact_inventory(tmp_path / "inventory.json", inventory)
    validated: list[tuple[H1GateSpec, ArtifactInventory, Path]] = []

    def fake_validate(
        received_spec: H1GateSpec,
        received_inventory: ArtifactInventory,
        artifact_root: Path,
    ) -> None:
        validated.append((received_spec, received_inventory, artifact_root))

    monkeypatch.setattr(h1_module, "validate_primary_artifact_inventory", fake_validate)

    loaded = read_artifact_inventory(path, spec, tmp_path / "artifacts")

    assert loaded == inventory
    assert validated == [(spec, inventory, tmp_path / "artifacts")]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"schema":"a","schema":"b"}', "重复键"),
        ('{"value":NaN}', "不允许常量"),
        ('{"schema":"x"}', "字段集合"),
    ],
)
def test_read_inventory_rejects_invalid_strict_json(
    tmp_path: Path,
    payload: str,
    message: str,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    path = _write(tmp_path / "inventory.json", payload)

    with pytest.raises(H1ProtocolError, match=message):
        read_artifact_inventory(path, spec, tmp_path)


def test_read_inventory_rejects_symlink_file(tmp_path: Path) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    actual = _write(tmp_path / "actual.json", "{}")
    link = tmp_path / "inventory.json"
    link.symlink_to(actual)

    with pytest.raises(H1ProtocolError, match="符号链接"):
        read_artifact_inventory(link, spec, tmp_path)


def test_formal_artifact_wrapper_binds_frozen_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    trace = _trace(num_steps=2)
    entry = ArtifactInventoryEntry(
        seed=17,
        relative_path="trace_17.npz",
        process_type="drifting_hotspot",
        config_sha256=_TEST_CONFIG_SHA256,
        content_sha256=_TEST_CONTENT_SHA256,
        start_step=0,
        num_steps=2,
        num_events=0,
    )
    artifact = DemandTraceArtifact(
        trace=trace,
        manifest={
            "config_sha256": entry.config_sha256,
            "content_sha256": entry.content_sha256,
        },
    )
    loaded_paths: list[Path] = []

    monkeypatch.setattr(
        h1_module,
        "_validate_primary_inventory_entry_identity",
        lambda received_spec, received_entry: None,
    )

    def fake_load(
        path: Path,
        received_entry: ArtifactInventoryEntry,
        expected_num_steps: int,
    ) -> DemandTraceArtifact:
        loaded_paths.append(path)
        assert received_entry is entry
        assert expected_num_steps == spec.num_steps
        return artifact

    monkeypatch.setattr(h1_module, "_load_validated_artifact_entry", fake_load)

    result = run_primary_artifact(spec, entry, tmp_path)

    assert loaded_paths == [tmp_path / entry.relative_path]
    assert result.seed == entry.seed
    assert result.trace_id == entry.relative_path
    assert result.horizon == spec.primary_horizon
    assert result.experiment_spec_sha256 == spec.sha256
    assert result.artifact_config_sha256 == entry.config_sha256
    assert result.artifact_content_sha256 == entry.content_sha256
    assert result.environment_config_sha256 == compute_environment_config_hash(
        build_primary_environment_config(spec)
    )


def test_paired_runner_same_state_diagnostics_and_primary_difference() -> None:
    trace = _trace(
        (_event(0, arrival=2, position=(2.0, 0.0), deadline=3),),
        num_steps=4,
    )
    config = ResourceServiceConfig(((0.0, 0.0),), 1.0)

    result = _run_tiny(trace, config, 2, seed=17, trace_id="tiny")

    assert result.reactive_metrics.completed == 0
    assert result.oracle_metrics.completed == 1
    assert result.primary_difference == 1.0
    assert result.reference_nonempty_view_steps == 2
    assert result.reference_feasible_future_pair_steps == 1
    assert result.reference_oracle_would_differ_steps == 1
    assert result.reference_oracle_would_preposition_steps == 1
    assert result.actionable_steps == 4
    assert result.realized_oracle_prearrival_move_steps == 2
    assert result.oracle_actionable_steps == 4


def test_paired_runner_is_deterministic_and_zero_arrival_is_zero() -> None:
    trace = _trace(num_steps=2)
    config = ResourceServiceConfig(((0.0, 0.0),), 1.0)

    first = _run_tiny(trace, config, 2, seed=18, trace_id="zero")
    second = _run_tiny(trace, config, 2, seed=18, trace_id="zero")

    assert first == second
    assert first.reactive_metrics.arrived == first.oracle_metrics.arrived == 0
    assert first.primary_difference == 0.0


def test_paired_runner_passes_same_trace_object_to_both_environments_and_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _trace(num_steps=2)
    reset_sources: list[DemandTrace] = []
    environment_ids: list[int] = []
    builder_sources: list[DemandTrace] = []
    original_reset = h1_module.ResourceServiceEnvironment.reset
    original_builder = h1_module.build_true_future_view

    def checked_reset(
        environment: object,
        source: DemandTrace,
    ) -> object:
        reset_sources.append(source)
        environment_ids.append(id(environment))
        return original_reset(environment, source)  # type: ignore[arg-type]

    def checked_builder(source: DemandTrace, snapshot: object, horizon: int) -> object:
        builder_sources.append(source)
        return original_builder(source, snapshot, horizon)  # type: ignore[arg-type]

    monkeypatch.setattr(h1_module.ResourceServiceEnvironment, "reset", checked_reset)
    monkeypatch.setattr(h1_module, "build_true_future_view", checked_builder)

    _run_tiny(
        trace,
        ResourceServiceConfig(((0.0, 0.0),), 1.0),
        2,
        seed=20,
        trace_id="identity",
    )

    assert reset_sources == [trace, trace]
    assert len(set(environment_ids)) == 2
    assert builder_sources and all(source is trace for source in builder_sources)


def test_counterfactual_oracle_actions_never_advance_reactive_environment() -> None:
    trace = _trace(
        (_event(0, arrival=2, position=(2.0, 0.0), deadline=3),),
        num_steps=4,
    )
    result = _run_tiny(
        trace,
        ResourceServiceConfig(((0.0, 0.0),), 1.0),
        2,
        seed=19,
        trace_id="counterfactual-only",
    )

    assert result.reference_oracle_would_preposition_steps == 1
    assert result.reactive_metrics.completed == 0


def test_h0_invariant_and_canonical_mechanism() -> None:
    trace = _trace(
        (_event(0, arrival=1, position=(0.0, 0.0), deadline=2),),
        num_steps=2,
    )
    validate_h0_invariant(trace, ResourceServiceConfig(((0.0, 0.0),), 1.0))
    validate_canonical_mechanism()


def test_h0_mismatch_raises_protocol_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    trace = _trace(num_steps=1)

    monkeypatch.setattr(
        h1_module.RollingTrueFutureOracle,
        "act",
        lambda self, snapshot, view: (MoveAction((0.0, 0.0)),),
    )
    with pytest.raises(H1ProtocolError, match="action sequence"):
        validate_h0_invariant(trace, ResourceServiceConfig(((0.0, 0.0),), 1.0))


def test_bootstrap_is_deterministic_and_uses_linear_quantiles() -> None:
    values = np.asarray([-0.1, 0.0, 0.1, 0.2], dtype=np.float64)

    first = h1_module._bootstrap_mean_interval(values, resamples=200, seed=7, chunk_size=17)
    second = h1_module._bootstrap_mean_interval(values, resamples=200, seed=7, chunk_size=17)
    generator = np.random.Generator(np.random.PCG64(7))
    indices = generator.integers(0, values.size, size=(200, values.size))
    expected = np.quantile(
        np.mean(values[indices], axis=1),
        [0.05, 0.95, 0.025, 0.975],
        method="linear",
    )

    assert first == second
    assert first == (expected[0], expected[1], (expected[2], expected[3]))
    assert first[2][0] <= first[0] <= first[1] <= first[2][1]


def test_bootstrap_and_paired_runner_do_not_pollute_global_rng_state() -> None:
    python_state = random.getstate()
    numpy_state = np.random.get_state()

    h1_module._bootstrap_mean_interval(
        np.asarray([0.0, 0.1], dtype=np.float64),
        resamples=20,
        seed=7,
    )
    _run_tiny(
        _trace(num_steps=2),
        ResourceServiceConfig(((0.0, 0.0),), 1.0),
        0,
        seed=21,
        trace_id="rng-isolation",
    )

    assert random.getstate() == python_state
    current_numpy_state = np.random.get_state()
    assert current_numpy_state[0] == numpy_state[0]
    np.testing.assert_array_equal(current_numpy_state[1], numpy_state[1])
    assert current_numpy_state[2:] == numpy_state[2:]


@pytest.mark.parametrize(
    ("difference", "expected"),
    [(0.03, H1Verdict.PASS), (0.0, H1Verdict.FAIL)],
)
def test_gate_rule_pass_and_fail(difference: float, expected: H1Verdict) -> None:
    results = tuple(_result(seed, difference) for seed in range(8))
    summary = h1_module._scientific_summary(
        results,
        delta_min=0.02,
        resamples=200,
        bootstrap_seed=11,
        n_planned=8,
    )

    assert summary.verdict is expected


def test_gate_rule_inconclusive() -> None:
    results = tuple(
        _result(seed, difference)
        for seed, difference in enumerate((-0.2, -0.2, -0.2, -0.2, 0.25, 0.25, 0.25, 0.25))
    )
    summary = h1_module._scientific_summary(
        results,
        delta_min=0.02,
        resamples=500,
        bootstrap_seed=12,
        n_planned=8,
    )

    assert summary.verdict is H1Verdict.INCONCLUSIVE


def test_formal_evaluator_rejects_incomplete_or_wrong_horizon_records() -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)

    incomplete = evaluate_primary_gate((_result(1, 0.03),), spec, inventory)
    assert incomplete.verdict is H1Verdict.PROTOCOL_FAIL
    assert incomplete.point_estimate is None

    wrong_horizon = tuple(replace(result, horizon=1) for result in _formal_results(spec, inventory))
    summary = evaluate_primary_gate(wrong_horizon, spec, inventory)
    assert summary.verdict is H1Verdict.PROTOCOL_FAIL
    assert summary.point_estimate is None


def test_formal_evaluator_locks_bootstrap_and_rejects_derived_metric_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)
    results = _formal_results(spec, inventory)
    call: dict[str, int] = {}

    def fake_bootstrap(
        values: np.ndarray,
        *,
        resamples: int,
        seed: int,
        chunk_size: int = 1024,
    ) -> tuple[float, float, tuple[float, float]]:
        del values, chunk_size
        call.update(resamples=resamples, seed=seed)
        return 0.01, 0.04, (0.0, 0.05)

    monkeypatch.setattr(h1_module, "_bootstrap_mean_interval", fake_bootstrap)
    summary = evaluate_primary_gate(results, spec, inventory)

    assert summary.verdict is H1Verdict.PASS
    assert call == {"resamples": 50_000, "seed": 90_260_819}
    mismatched = (replace(results[0], primary_difference=0.5), *results[1:])
    failed = evaluate_primary_gate(mismatched, spec, inventory)
    assert failed.verdict is H1Verdict.PROTOCOL_FAIL
    assert any("primary difference" in error for error in failed.protocol_errors)


def test_formal_evaluator_rejects_every_provenance_mismatch() -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)
    results = _formal_results(spec, inventory)
    first_entry, second_entry = inventory.entries[:2]
    swapped = (
        replace(
            results[0],
            trace_id=second_entry.relative_path,
            artifact_config_sha256=second_entry.config_sha256,
            artifact_content_sha256=second_entry.content_sha256,
        ),
        replace(
            results[1],
            trace_id=first_entry.relative_path,
            artifact_config_sha256=first_entry.config_sha256,
            artifact_content_sha256=first_entry.content_sha256,
        ),
        *results[2:],
    )
    variants = (
        swapped,
        (replace(results[0], artifact_content_sha256="a" * 64), *results[1:]),
        (replace(results[0], artifact_config_sha256="b" * 64), *results[1:]),
        (replace(results[0], experiment_spec_sha256="c" * 64), *results[1:]),
        (replace(results[0], environment_config_sha256="d" * 64), *results[1:]),
        tuple(_result(seed, 0.03) for seed in primary_seeds(spec)),
    )

    for variant in variants:
        summary = evaluate_primary_gate(variant, spec, inventory)
        assert summary.verdict is H1Verdict.PROTOCOL_FAIL
        assert summary.point_estimate is None


def test_inventory_and_results_hashes_are_canonical_and_input_sensitive() -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)
    results = _formal_results(spec, inventory)

    inventory_hash = compute_artifact_inventory_hash(inventory)
    results_hash = compute_paired_results_hash(results)

    assert inventory_hash == compute_artifact_inventory_hash(inventory)
    assert results_hash == compute_paired_results_hash(results)
    changed_inventory = replace(
        inventory,
        entries=(
            replace(inventory.entries[0], content_sha256="a" * 64),
            *inventory.entries[1:],
        ),
    )
    changed_results = (
        replace(results[0], artifact_content_sha256="a" * 64),
        *results[1:],
    )
    assert compute_artifact_inventory_hash(changed_inventory) != inventory_hash
    assert compute_paired_results_hash(changed_results) != results_hash
    with pytest.raises(H1ProtocolError, match="formal seed 顺序"):
        compute_paired_results_hash(tuple(reversed(results)))


def test_canonical_json_jsonl_no_overwrite_and_no_nan(tmp_path: Path) -> None:
    json_path = write_canonical_json(tmp_path / "value.json", {"b": 2, "a": 1})
    assert json_path.read_bytes() == b'{"a":1,"b":2}\n'
    with pytest.raises(FileExistsError):
        write_canonical_json(json_path, {"a": 1})
    with pytest.raises(ValueError):
        write_canonical_json(tmp_path / "nan.json", {"value": math.nan})

    result = _result(1, 0.03)
    jsonl = write_paired_jsonl(tmp_path / "results.jsonl", (result,))
    loaded = json.loads(jsonl.read_text(encoding="utf-8"))
    assert loaded["schema"] == "fura-mappo.wp02d-paired-trace"
    assert loaded["seed"] == 1

    entries = tuple(
        ArtifactInventoryEntry(
            seed=seed,
            relative_path=f"trace_{seed}.npz",
            process_type="drifting_hotspot",
            config_sha256=f"{seed}" * 64,
            content_sha256=f"{seed + 2}" * 64,
            start_step=0,
            num_steps=3,
            num_events=0,
        )
        for seed in (0, 1)
    )
    inventory = ArtifactInventory("a" * 64, "b" * 40, 2, entries)
    inventory_path = write_artifact_inventory(tmp_path / "inventory.json", inventory)
    assert json.loads(inventory_path.read_text(encoding="utf-8"))["planned_seed_count"] == 2

    summary_path = write_h1_summary(tmp_path / "summary.json", _formal_summary())
    assert json.loads(summary_path.read_text(encoding="utf-8"))["verdict"] == "PASS"


def test_read_paired_jsonl_canonical_round_trip_and_hash(tmp_path: Path) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)
    results = _formal_results(spec, inventory)
    path = write_paired_jsonl(tmp_path / "results.jsonl", results)

    loaded = read_paired_jsonl(path, spec, inventory)

    assert loaded == results
    assert len(loaded) == 256
    assert compute_paired_results_hash(loaded) == compute_paired_results_hash(results)
    validate_primary_paired_results(loaded, spec, inventory)
    with pytest.raises(TypeError, match="bytes"):
        read_paired_jsonl(bytes(path), spec, inventory)  # type: ignore[arg-type]


def test_read_paired_jsonl_rejects_strict_json_and_canonical_violations(
    tmp_path: Path,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)
    rows = _formal_result_rows(spec, inventory)
    canonical = _write_result_rows(tmp_path / "canonical.jsonl", rows).read_bytes()
    first, remainder = canonical.split(b"\n", 1)

    duplicate = first.replace(
        b'"seed":20260819',
        b'"seed":20260819,"seed":20260819',
        1,
    )
    (tmp_path / "duplicate.jsonl").write_bytes(duplicate + b"\n" + remainder)
    with pytest.raises(H1ProtocolError, match="重复键"):
        read_paired_jsonl(tmp_path / "duplicate.jsonl", spec, inventory)

    for name, constant in (("nan", math.nan), ("infinity", math.inf)):
        changed = _formal_result_rows(spec, inventory)
        changed[0]["primary_difference"] = constant
        payload = "\n".join(
            json.dumps(row, allow_nan=True, sort_keys=True, separators=(",", ":"))
            for row in changed
        )
        (tmp_path / f"{name}.jsonl").write_text(payload + "\n", encoding="utf-8")
        with pytest.raises(H1ProtocolError, match="不允许常量"):
            read_paired_jsonl(tmp_path / f"{name}.jsonl", spec, inventory)

    (tmp_path / "blank.jsonl").write_bytes(first + b"\n\n" + remainder)
    with pytest.raises(H1ProtocolError, match="blank"):
        read_paired_jsonl(tmp_path / "blank.jsonl", spec, inventory)

    (tmp_path / "utf8.jsonl").write_bytes(b"\xff\n" + remainder)
    with pytest.raises(H1ProtocolError, match="UTF-8"):
        read_paired_jsonl(tmp_path / "utf8.jsonl", spec, inventory)

    (tmp_path / "noncanonical.jsonl").write_bytes(b" " + first + b"\n" + remainder)
    with pytest.raises(H1ProtocolError, match="canonical"):
        read_paired_jsonl(tmp_path / "noncanonical.jsonl", spec, inventory)

    overflow = first.replace(b'"primary_difference":0.03', b'"primary_difference":1e999', 1)
    assert overflow != first
    (tmp_path / "overflow.jsonl").write_bytes(overflow + b"\n" + remainder)
    with pytest.raises(H1ProtocolError, match="无法 canonical 编码"):
        read_paired_jsonl(tmp_path / "overflow.jsonl", spec, inventory)

    surrogate = first.replace(
        b'"trace_id":"trace_20260819.npz"',
        b'"trace_id":"\\ud800"',
        1,
    )
    assert surrogate != first
    (tmp_path / "surrogate.jsonl").write_bytes(surrogate + b"\n" + remainder)
    with pytest.raises(H1ProtocolError, match="无法 canonical 编码"):
        read_paired_jsonl(tmp_path / "surrogate.jsonl", spec, inventory)


def test_read_paired_jsonl_rejects_schema_scalar_and_nested_metric_errors(
    tmp_path: Path,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)

    cases: list[tuple[str, Callable[[list[dict[str, object]]], None], str]] = []

    def wrong_schema(rows: list[dict[str, object]]) -> None:
        rows[0]["schema"] = "wrong"

    def wrong_version(rows: list[dict[str, object]]) -> None:
        rows[0]["version"] = 2

    def unknown_field(rows: list[dict[str, object]]) -> None:
        rows[0]["unknown"] = 1

    def missing_field(rows: list[dict[str, object]]) -> None:
        rows[0].pop("trace_id")

    def bool_seed(rows: list[dict[str, object]]) -> None:
        rows[0]["seed"] = True

    def nested_missing(rows: list[dict[str, object]]) -> None:
        metrics = cast(dict[str, object], rows[0]["reactive_metrics"])
        metrics.pop("arrived")

    cases.extend(
        [
            ("schema", wrong_schema, "schema/version"),
            ("version", wrong_version, "schema/version"),
            ("unknown", unknown_field, "字段集合"),
            ("missing", missing_field, "字段集合"),
            ("bool", bool_seed, "布尔|不能是布尔"),
            ("nested", nested_missing, "reactive_metrics 字段集合"),
        ]
    )
    for name, mutate, message in cases:
        rows = _formal_result_rows(spec, inventory)
        mutate(rows)
        path = _write_result_rows(tmp_path / f"{name}.jsonl", rows)
        with pytest.raises(H1ProtocolError, match=message):
            read_paired_jsonl(path, spec, inventory)


def test_read_paired_jsonl_rejects_formal_identity_and_protocol_mismatches(
    tmp_path: Path,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)

    def assert_rejected(name: str, rows: list[dict[str, object]], message: str) -> None:
        path = _write_result_rows(tmp_path / f"{name}.jsonl", rows)
        with pytest.raises(H1ProtocolError, match=message):
            read_paired_jsonl(path, spec, inventory)

    rows = _formal_result_rows(spec, inventory)
    rows[0], rows[1] = rows[1], rows[0]
    assert_rejected("order", rows, "seed 集或顺序")

    rows = _formal_result_rows(spec, inventory)
    rows[1] = dict(rows[0])
    assert_rejected("duplicate", rows, "seed 集或顺序|重复")

    assert_rejected("missing", _formal_result_rows(spec, inventory)[:-1], "行数")

    mutations = (
        ("horizon", "horizon", 1, "horizon"),
        ("spec", "experiment_spec_sha256", "a" * 64, "spec hash"),
        ("config", "artifact_config_sha256", "a" * 64, "config hash"),
        ("content", "artifact_content_sha256", "a" * 64, "content hash"),
        ("environment", "environment_config_sha256", "a" * 64, "environment"),
        ("difference", "primary_difference", 0.5, "primary difference"),
        ("protocol", "protocol_failure", "broken", "protocol failure"),
    )
    for name, field_name, replacement, message in mutations:
        rows = _formal_result_rows(spec, inventory)
        rows[0][field_name] = replacement
        assert_rejected(name, rows, message)

    rows = _formal_result_rows(spec, inventory)
    rows[0]["oracle_metrics"] = asdict(_metrics(99, 53))
    assert_rejected("arrived", rows, "arrived denominator")


def test_read_paired_jsonl_rejects_symlink_and_oversized_file(tmp_path: Path) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory = _formal_inventory(spec)
    actual = write_paired_jsonl(
        tmp_path / "actual.jsonl",
        _formal_results(spec, inventory),
    )
    link = tmp_path / "link.jsonl"
    link.symlink_to(actual)
    with pytest.raises(H1ProtocolError, match="符号链接"):
        read_paired_jsonl(link, spec, inventory)

    oversized = tmp_path / "oversized.jsonl"
    oversized.write_bytes(b"x" * (h1_module._MAX_PROTOCOL_JSON_BYTES + 1))
    with pytest.raises(H1ProtocolError, match="大小上限"):
        read_paired_jsonl(oversized, spec, inventory)


def test_read_h1_summary_round_trip_all_verdicts(tmp_path: Path) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    passed = _formal_summary()
    failed = replace(
        passed,
        verdict=H1Verdict.FAIL,
        point_estimate=0.0,
        one_sided_lcb=-0.1,
        one_sided_ucb=0.01,
        two_sided_interval=(-0.15, 0.015),
    )
    inconclusive = replace(
        passed,
        verdict=H1Verdict.INCONCLUSIVE,
        point_estimate=0.01,
        one_sided_lcb=-0.01,
        one_sided_ucb=0.03,
        two_sided_interval=(-0.02, 0.04),
    )
    protocol_fail = h1_module._protocol_fail_summary(spec, ("broken",))

    for summary in (passed, failed, inconclusive, protocol_fail):
        path = write_h1_summary(tmp_path / f"{summary.verdict.value}.json", summary)
        assert read_h1_summary(path) == summary


def test_read_h1_summary_rejects_strict_json_and_schema_errors(tmp_path: Path) -> None:
    summary = _formal_summary()
    payload = h1_module.summary_to_dict(summary)

    unknown = dict(payload, unknown=1)
    for name, changed, message in (
        ("unknown", unknown, "字段集合"),
        ("missing", {key: value for key, value in payload.items() if key != "verdict"}, "字段集合"),
        ("bool", dict(payload, n_valid=True), "布尔"),
    ):
        path = tmp_path / f"{name}.json"
        path.write_bytes(h1_module._canonical_json_bytes(changed) + b"\n")
        with pytest.raises(H1ProtocolError, match=message):
            read_h1_summary(path)

    duplicate = h1_module._canonical_json_bytes(payload).replace(
        b'"version":1',
        b'"version":1,"version":1',
    )
    (tmp_path / "duplicate-summary.json").write_bytes(duplicate + b"\n")
    with pytest.raises(H1ProtocolError, match="重复键"):
        read_h1_summary(tmp_path / "duplicate-summary.json")

    nonfinite = dict(payload, point_estimate=math.nan)
    (tmp_path / "nonfinite-summary.json").write_text(
        json.dumps(nonfinite, allow_nan=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(H1ProtocolError, match="不允许常量"):
        read_h1_summary(tmp_path / "nonfinite-summary.json")

    (tmp_path / "noncanonical-summary.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(H1ProtocolError, match="canonical"):
        read_h1_summary(tmp_path / "noncanonical-summary.json")

    canonical = h1_module._canonical_json_bytes(payload) + b"\n"
    overflow = canonical.replace(b'"point_estimate":0.03', b'"point_estimate":1e999', 1)
    assert overflow != canonical
    (tmp_path / "overflow-summary.json").write_bytes(overflow)
    with pytest.raises(H1ProtocolError, match="无法 canonical 编码"):
        read_h1_summary(tmp_path / "overflow-summary.json")


def test_provenance_bound_artifact_entry_uses_loaded_manifest_not_caller_hashes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    plan = ArtifactPlanEntry(primary_seeds(spec)[0], f"trace_{primary_seeds(spec)[0]}.npz")
    provenance = _formal_provenance(spec)
    resolved_config = build_primary_demand_config(spec, plan.seed)
    trace = _trace(num_steps=256)
    manifest = {
        "seed": plan.seed,
        "process_type": "drifting_hotspot",
        "resolved_config": resolved_config,
        "config_sha256": h1_module.compute_config_hash(resolved_config),
        "content_sha256": "c" * 64,
        "start_step": 0,
        "num_steps": 256,
        "num_events": 0,
        "git_commit": provenance.actual_head,
        "git_dirty": False,
    }
    artifact = DemandTraceArtifact(trace, manifest)
    monkeypatch.setattr(h1_module, "load_demand_trace", lambda path: artifact)

    entry = build_provenance_bound_artifact_entry(
        spec,
        plan,
        tmp_path / plan.relative_path,
        provenance,
    )
    assert entry.config_sha256 == manifest["config_sha256"]
    assert entry.content_sha256 == manifest["content_sha256"]

    bad_manifest = dict(manifest, git_commit="d" * 40)
    monkeypatch.setattr(
        h1_module,
        "load_demand_trace",
        lambda path: DemandTraceArtifact(trace, bad_manifest),
    )
    with pytest.raises(H1ProtocolError, match="execution HEAD"):
        build_provenance_bound_artifact_entry(
            spec,
            plan,
            tmp_path / plan.relative_path,
            provenance,
        )


def test_protocol_json_parent_fsync_and_exception_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []
    with monkeypatch.context() as scoped:
        scoped.setattr(h1_module.os, "open", lambda path, flags: 91)
        scoped.setattr(
            h1_module.os,
            "fsync",
            lambda descriptor: calls.append(("fsync", descriptor)),
        )
        scoped.setattr(
            h1_module.os,
            "close",
            lambda descriptor: calls.append(("close", descriptor)),
        )
        h1_module._fsync_protocol_parent(tmp_path)
    assert calls == [("fsync", 91), ("close", 91)]

    def fail_parent(parent: Path) -> None:
        assert not tuple(parent.glob(".published.json.*.tmp"))
        raise OSError("directory fsync failed")

    monkeypatch.setattr(h1_module, "_fsync_protocol_parent", fail_parent)
    target = tmp_path / "published.json"
    with pytest.raises(OSError, match="fsync"):
        write_canonical_json(target, {"value": 1})
    assert target.is_file()
    assert not tuple(tmp_path.glob(".published.json.*.tmp"))


def test_output_rejects_symlink_target(tmp_path: Path) -> None:
    actual = tmp_path / "actual.json"
    actual.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(actual)

    with pytest.raises(FileExistsError):
        write_canonical_json(link, {"value": 1})


def test_primary_verdict_write_read_hash_and_sensitivity_guard(tmp_path: Path) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    _, _, inventory_hash, results_hash, provenance = _formal_verdict_context(spec)
    summary = _formal_summary()
    path = write_primary_verdict(
        tmp_path / "verdict.json",
        summary,
        spec.sha256,
        inventory_hash,
        results_hash,
        provenance,
    )

    loaded = read_primary_verdict(
        path,
        expected_spec_sha256=spec.sha256,
        expected_artifact_inventory_sha256=inventory_hash,
        expected_paired_results_sha256=results_hash,
        expected_formal_provenance=provenance,
    )
    assert loaded["summary"]["verdict"] == "PASS"  # type: ignore[index]
    require_locked_primary_verdict(
        path,
        spec,
        expected_artifact_inventory_sha256=inventory_hash,
        expected_paired_results_sha256=results_hash,
        expected_formal_provenance=provenance,
    )
    with pytest.raises(FileExistsError):
        write_primary_verdict(
            path,
            summary,
            spec.sha256,
            inventory_hash,
            results_hash,
            provenance,
        )


def test_verdict_tamper_and_protocol_fail_do_not_unlock_sensitivity(tmp_path: Path) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    _, _, inventory_hash, results_hash, provenance = _formal_verdict_context(spec)
    failed = h1_module._protocol_fail_summary(spec, ("broken",))
    failed_path = write_primary_verdict(
        tmp_path / "failed.json",
        failed,
        spec.sha256,
        inventory_hash,
        results_hash,
        provenance,
    )
    loaded_failed = read_primary_verdict(
        failed_path,
        expected_spec_sha256=spec.sha256,
        expected_artifact_inventory_sha256=inventory_hash,
        expected_paired_results_sha256=results_hash,
        expected_formal_provenance=provenance,
    )
    assert loaded_failed["summary"]["verdict"] == "PROTOCOL_FAIL"  # type: ignore[index]
    with pytest.raises(H1ProtocolError, match="PROTOCOL_FAIL"):
        require_locked_primary_verdict(
            failed_path,
            spec,
            expected_artifact_inventory_sha256=inventory_hash,
            expected_paired_results_sha256=results_hash,
            expected_formal_provenance=provenance,
        )

    summary = _formal_summary()
    path = write_primary_verdict(
        tmp_path / "valid.json",
        summary,
        spec.sha256,
        inventory_hash,
        results_hash,
        provenance,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summary"]["point_estimate"] = 9.0
    path.write_bytes(h1_module._canonical_json_bytes(payload) + b"\n")
    with pytest.raises(H1ProtocolError, match="hash"):
        read_primary_verdict(
            path,
            expected_spec_sha256=spec.sha256,
            expected_artifact_inventory_sha256=inventory_hash,
            expected_paired_results_sha256=results_hash,
            expected_formal_provenance=provenance,
        )


def test_primary_verdict_canonical_round_trip_all_verdicts(tmp_path: Path) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    _, _, inventory_hash, results_hash, provenance = _formal_verdict_context(spec)
    passed = _formal_summary()
    failed = replace(
        passed,
        verdict=H1Verdict.FAIL,
        point_estimate=0.0,
        one_sided_lcb=-0.1,
        one_sided_ucb=0.01,
        two_sided_interval=(-0.15, 0.015),
    )
    inconclusive = replace(
        passed,
        verdict=H1Verdict.INCONCLUSIVE,
        point_estimate=0.01,
        one_sided_lcb=-0.01,
        one_sided_ucb=0.03,
        two_sided_interval=(-0.02, 0.04),
    )
    protocol_fail = h1_module._protocol_fail_summary(spec, ("broken",))

    for summary in (passed, failed, inconclusive, protocol_fail):
        path = write_primary_verdict(
            tmp_path / f"{summary.verdict.value}.json",
            summary,
            spec.sha256,
            inventory_hash,
            results_hash,
            provenance,
        )
        loaded = read_primary_verdict(
            path,
            expected_spec_sha256=spec.sha256,
            expected_artifact_inventory_sha256=inventory_hash,
            expected_paired_results_sha256=results_hash,
            expected_formal_provenance=provenance,
        )
        assert loaded["summary"]["verdict"] == summary.verdict.value  # type: ignore[index]


def test_primary_verdict_rejects_noncanonical_file_and_embedded_scalar_type_drift(
    tmp_path: Path,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    _, _, inventory_hash, results_hash, provenance = _formal_verdict_context(spec)
    path = write_primary_verdict(
        tmp_path / "verdict.json",
        _formal_summary(),
        spec.sha256,
        inventory_hash,
        results_hash,
        provenance,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(H1ProtocolError, match="canonical"):
        read_primary_verdict(
            path,
            expected_spec_sha256=spec.sha256,
            expected_artifact_inventory_sha256=inventory_hash,
            expected_paired_results_sha256=results_hash,
            expected_formal_provenance=provenance,
        )

    canonical_path = write_primary_verdict(
        tmp_path / "scalar-type.json",
        _formal_summary(),
        spec.sha256,
        inventory_hash,
        results_hash,
        provenance,
    )
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    completed = payload["summary"]["secondary"]["completed"]
    assert isinstance(completed["reactive_mean"], float)
    completed["reactive_mean"] = int(completed["reactive_mean"])
    without_hash = dict(payload)
    without_hash.pop("payload_sha256")
    payload["payload_sha256"] = hashlib.sha256(
        h1_module._canonical_json_bytes(without_hash)
    ).hexdigest()
    canonical_path.write_bytes(h1_module._canonical_json_bytes(payload) + b"\n")
    with pytest.raises(H1ProtocolError, match="writer canonical"):
        read_primary_verdict(
            canonical_path,
            expected_spec_sha256=spec.sha256,
            expected_artifact_inventory_sha256=inventory_hash,
            expected_paired_results_sha256=results_hash,
            expected_formal_provenance=provenance,
        )


def test_verdict_rejects_different_inventory_or_results_even_with_valid_payload_hash(
    tmp_path: Path,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    inventory, results, inventory_hash, results_hash, provenance = _formal_verdict_context(spec)
    path = write_primary_verdict(
        tmp_path / "verdict.json",
        _formal_summary(),
        spec.sha256,
        inventory_hash,
        results_hash,
        provenance,
    )
    inventory_b = replace(
        inventory,
        entries=(
            replace(inventory.entries[0], content_sha256="a" * 64),
            *inventory.entries[1:],
        ),
    )
    results_b = (
        replace(results[0], artifact_content_sha256="a" * 64),
        *results[1:],
    )

    with pytest.raises(H1ProtocolError, match="inventory hash"):
        require_locked_primary_verdict(
            path,
            spec,
            expected_artifact_inventory_sha256=compute_artifact_inventory_hash(inventory_b),
            expected_paired_results_sha256=results_hash,
            expected_formal_provenance=provenance,
        )
    with pytest.raises(H1ProtocolError, match="paired results hash"):
        require_locked_primary_verdict(
            path,
            spec,
            expected_artifact_inventory_sha256=inventory_hash,
            expected_paired_results_sha256=compute_paired_results_hash(results_b),
            expected_formal_provenance=provenance,
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["paired_results_sha256"] = compute_paired_results_hash(results_b)
    without_hash = dict(payload)
    without_hash.pop("payload_sha256")
    payload["payload_sha256"] = hashlib.sha256(
        h1_module._canonical_json_bytes(without_hash)
    ).hexdigest()
    path.write_bytes(h1_module._canonical_json_bytes(payload) + b"\n")
    with pytest.raises(H1ProtocolError, match="paired results hash"):
        require_locked_primary_verdict(
            path,
            spec,
            expected_artifact_inventory_sha256=inventory_hash,
            expected_paired_results_sha256=results_hash,
            expected_formal_provenance=provenance,
        )


def test_hash_consistent_but_incomplete_verdict_cannot_unlock_sensitivity(
    tmp_path: Path,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    _, _, inventory_hash, results_hash, provenance = _formal_verdict_context(spec)
    path = write_primary_verdict(
        tmp_path / "incomplete.json",
        _formal_summary(),
        spec.sha256,
        inventory_hash,
        results_hash,
        provenance,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summary"] = {"verdict": "PASS"}
    without_hash = dict(payload)
    without_hash.pop("payload_sha256")
    payload["payload_sha256"] = hashlib.sha256(
        h1_module._canonical_json_bytes(without_hash)
    ).hexdigest()
    path.write_bytes(h1_module._canonical_json_bytes(payload) + b"\n")

    with pytest.raises(H1ProtocolError, match="summary 字段集合"):
        require_locked_primary_verdict(
            path,
            spec,
            expected_artifact_inventory_sha256=inventory_hash,
            expected_paired_results_sha256=results_hash,
            expected_formal_provenance=provenance,
        )


def _fake_git_runner(
    *,
    status: str = "",
    head: str = "b" * 40,
    origin: str = "b" * 40,
    changed: str = "docs/PROJECT_STATE.md\n",
    stable_ancestor_returncode: int = 0,
    accepted_ancestor_returncode: int = 0,
) -> object:
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = command[1:]
        if arguments[:2] == ["status", "--porcelain=v1"]:
            output, returncode = status, 0
        elif arguments[:2] == ["rev-parse", "HEAD"]:
            output, returncode = head, 0
        elif arguments[:2] == ["rev-parse", "origin/main"]:
            output, returncode = origin, 0
        elif arguments[:2] == ["merge-base", "--is-ancestor"]:
            output = ""
            returncode = (
                stable_ancestor_returncode
                if arguments[2] == "9159c841af4f605d6e32cca4b37940f0116a19cf"
                else accepted_ancestor_returncode
            )
        elif arguments[:2] == ["diff", "--name-only"]:
            output, returncode = changed, 0
        else:
            raise AssertionError(f"unexpected git command: {command!r}")
        return subprocess.CompletedProcess(command, returncode, stdout=output, stderr="")

    return run


def test_provenance_accepts_clean_docs_only_descendant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = load_h1_gate_spec(_SPEC_PATH)
    accepted = "a" * 40
    monkeypatch.setattr(h1_module.subprocess, "run", _fake_git_runner())

    result = validate_formal_provenance(
        Path.cwd(),
        spec,
        wp02d_accepted_implementation_sha=accepted,
    )

    assert result.actual_head == "b" * 40
    assert result.git_dirty is False
    assert result.experiment_spec_sha256 == spec.sha256


@pytest.mark.parametrize(
    ("runner", "message"),
    [
        (_fake_git_runner(status="?? untracked\n"), "干净"),
        (_fake_git_runner(origin="c" * 40), "HEAD == origin/main"),
        (_fake_git_runner(stable_ancestor_returncode=1), "WP-02C stable SHA"),
        (_fake_git_runner(accepted_ancestor_returncode=1), "WP-02D accepted SHA"),
        (_fake_git_runner(changed="src/fura_mappo/experiments/h1_gate.py\n"), "仅允许"),
    ],
)
def test_provenance_rejects_dirty_mismatch_or_code_descendant(
    monkeypatch: pytest.MonkeyPatch,
    runner: object,
    message: str,
) -> None:
    monkeypatch.setattr(h1_module.subprocess, "run", runner)

    with pytest.raises(H1ProtocolError, match=message):
        validate_formal_provenance(
            Path.cwd(),
            load_h1_gate_spec(_SPEC_PATH),
            wp02d_accepted_implementation_sha="a" * 40,
        )
