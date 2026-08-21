from __future__ import annotations

import errno
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import fura_mappo.experiments as experiments_package
import fura_mappo.experiments._formal_h1_runner as runner
from fura_mappo.demand.processes import DemandProcess
from fura_mappo.experiments.h1_gate import (
    ArtifactInventory,
    ArtifactInventoryEntry,
    ArtifactPlanEntry,
    FormalProvenance,
    H1GateSummary,
    H1ProtocolError,
    H1Verdict,
    load_h1_gate_spec,
    summary_to_dict,
)

_SPEC_PATH = Path("configs/experiments/wp02d_h1.yaml")
_FORMAL_SEEDS = frozenset(range(20_260_819, 20_261_075))


@pytest.fixture(autouse=True)
def _forbid_real_formal_seed_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """任何 runner test 若把正式 seed 送入真实 generate，立即失败。"""

    original = DemandProcess.generate

    def guarded_generate(
        self: DemandProcess,
        num_steps: int,
        seed: int | None = None,
    ) -> object:
        effective_seed = self.base_seed if seed is None else seed
        if effective_seed in _FORMAL_SEEDS:
            pytest.fail("runner tests 禁止真实 DemandProcess.generate 接收正式 seed")
        return original(self, num_steps, seed)

    monkeypatch.setattr(DemandProcess, "generate", guarded_generate)


def _spec():
    return load_h1_gate_spec(_SPEC_PATH)


def _provenance(spec=None) -> FormalProvenance:
    selected = _spec() if spec is None else spec
    return FormalProvenance(
        actual_head="a" * 40,
        origin_main="a" * 40,
        wp02c_stable_sha=selected.wp02c_stable_sha,
        wp02d_accepted_implementation_sha="b" * 40,
        experiment_spec_sha256=selected.sha256,
        git_dirty=False,
    )


def _entry(seed: int) -> ArtifactInventoryEntry:
    return ArtifactInventoryEntry(
        seed=seed,
        relative_path=f"trace_{seed}.npz",
        process_type="drifting_hotspot",
        config_sha256=hashlib.sha256(f"config:{seed}".encode()).hexdigest(),
        content_sha256=hashlib.sha256(f"content:{seed}".encode()).hexdigest(),
        start_step=0,
        num_steps=256,
        num_events=0,
    )


def _inventory(spec=None, seeds: tuple[int, ...] = (101, 102)) -> ArtifactInventory:
    selected = _spec() if spec is None else spec
    return ArtifactInventory(
        experiment_spec_sha256=selected.sha256,
        wp02c_stable_sha=selected.wp02c_stable_sha,
        planned_seed_count=len(seeds),
        entries=tuple(_entry(seed) for seed in seeds),
    )


def _plan(seeds: tuple[int, ...] = (101, 102)) -> tuple[ArtifactPlanEntry, ...]:
    return tuple(ArtifactPlanEntry(seed, f"trace_{seed}.npz") for seed in seeds)


def _summary(verdict: H1Verdict = H1Verdict.PASS) -> H1GateSummary:
    if verdict is H1Verdict.PROTOCOL_FAIL:
        return H1GateSummary(
            verdict=verdict,
            n_planned=256,
            n_valid=0,
            point_estimate=None,
            one_sided_lcb=None,
            one_sided_ucb=None,
            two_sided_interval=None,
            delta_min=0.02,
            bootstrap_resamples=50_000,
            bootstrap_seed=90_260_819,
            secondary={},
            diagnostics={},
            protocol_errors=("broken",),
        )
    return H1GateSummary(
        verdict=verdict,
        n_planned=256,
        n_valid=256,
        point_estimate=0.03,
        one_sided_lcb=0.01,
        one_sided_ucb=0.04,
        two_sided_interval=(0.0, 0.05),
        delta_min=0.02,
        bootstrap_resamples=50_000,
        bootstrap_seed=90_260_819,
        secondary={},
        diagnostics={},
    )


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "artifacts").mkdir()
    return root


def _prepared_paths(
    tmp_path: Path,
    plan: tuple[ArtifactPlanEntry, ...] | None = None,
) -> tuple[runner.FormalH1Paths, tuple[ArtifactPlanEntry, ...]]:
    selected_plan = _plan() if plan is None else plan
    paths = runner._fixed_paths(_repository(tmp_path))
    runner._prepare_run_root(paths, selected_plan)
    return paths, selected_plan


def test_accepted_sha_parameter_format() -> None:
    assert runner._validate_accepted_sha("a" * 40) == "a" * 40
    for invalid in ("cfab8c1", "A" * 40, "g" * 40, b"a" * 40, True):
        with pytest.raises(H1ProtocolError, match="40 位小写"):
            runner._validate_accepted_sha(invalid)


def test_repository_root_and_branch_are_exact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    monkeypatch.chdir(root)

    def valid_git(repository: Path, *arguments: str) -> str:
        if arguments == ("rev-parse", "--show-toplevel"):
            return str(root)
        if arguments == ("branch", "--show-current"):
            return "main"
        raise AssertionError(arguments)

    monkeypatch.setattr(runner, "_git", valid_git)
    assert runner._require_real_repository_root() == root

    monkeypatch.setattr(
        runner,
        "_git",
        lambda repository, *arguments: (
            "feature" if arguments == ("branch", "--show-current") else str(root)
        ),
    )
    with pytest.raises(H1ProtocolError, match="branch"):
        runner._require_real_repository_root()

    other = root / "nested"
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setattr(runner, "_git", lambda repository, *arguments: str(root))
    with pytest.raises(H1ProtocolError, match="top-level"):
        runner._require_real_repository_root()


def test_loaded_code_from_current_repository_passes() -> None:
    runner._require_loaded_code_from_repository(Path.cwd().resolve(strict=True))


def test_loaded_runner_from_other_checkout_hard_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    other_runner = tmp_path / "other" / "src" / "fura_mappo" / "experiments" / "runner.py"
    other_runner.parent.mkdir(parents=True)
    other_runner.write_text("# other checkout\n", encoding="utf-8")
    monkeypatch.setattr(runner, "__file__", str(other_runner))
    with pytest.raises(H1ProtocolError, match="runner 不来自"):
        runner._require_loaded_code_from_repository(Path.cwd().resolve(strict=True))


def test_loaded_top_level_package_path_from_other_checkout_hard_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    other_package = tmp_path / "other" / "src" / "fura_mappo"
    other_package.mkdir(parents=True)
    monkeypatch.setattr(runner.fura_mappo, "__path__", [str(other_package)])
    with pytest.raises(H1ProtocolError, match="__path__"):
        runner._require_loaded_code_from_repository(Path.cwd().resolve(strict=True))


@pytest.mark.parametrize(
    "module_attribute",
    ["h1_gate_module", "demand_package", "envs_package", "baselines_package"],
)
def test_loaded_dependency_module_from_other_checkout_hard_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module_attribute: str,
) -> None:
    other_module = tmp_path / "other" / f"{module_attribute}.py"
    other_module.parent.mkdir(parents=True, exist_ok=True)
    other_module.write_text("# other checkout\n", encoding="utf-8")
    module = getattr(runner, module_attribute)
    monkeypatch.setattr(module, "__file__", str(other_module))
    with pytest.raises(H1ProtocolError, match="不来自当前 repository"):
        runner._require_loaded_code_from_repository(Path.cwd().resolve(strict=True))


def test_code_path_mismatch_prevents_run_root_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Path.cwd().resolve(strict=True)
    monkeypatch.setattr(runner, "_require_real_repository_root", lambda: repository)
    monkeypatch.setattr(
        runner,
        "_require_loaded_code_from_repository",
        lambda root: (_ for _ in ()).throw(H1ProtocolError("loaded code mismatch")),
    )
    monkeypatch.setattr(
        runner,
        "_prepare_run_root",
        lambda *args: pytest.fail("code-path mismatch 后不得创建 formal run root"),
    )
    with pytest.raises(H1ProtocolError, match="loaded code mismatch"):
        runner.run_formal_h1("b" * 40, emit=lambda message: None)


@pytest.mark.parametrize(
    ("message", "error_text"),
    [
        ("dirty repo", "working tree/index/untracked 全部干净"),
        ("HEAD/origin mismatch", "actual HEAD == origin/main"),
        ("accepted SHA scope violation", "accepted SHA 后仅允许"),
    ],
)
def test_provenance_failures_are_hard_gates(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    error_text: str,
) -> None:
    spec = _spec()
    monkeypatch.setattr(runner, "_git", lambda repository, *arguments: "main")

    def fail(*args: object, **kwargs: object) -> FormalProvenance:
        raise H1ProtocolError(error_text)

    monkeypatch.setattr(runner, "validate_formal_provenance", fail)
    with pytest.raises(H1ProtocolError, match=error_text):
        runner._validate_initial_provenance(Path.cwd(), spec, "b" * 40)
    assert message


def test_provenance_revalidation_requires_exact_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec()
    initial = _provenance(spec)
    changed = replace(initial, actual_head="c" * 40, origin_main="c" * 40)
    monkeypatch.setattr(runner, "_validate_initial_provenance", lambda *args: changed)
    with pytest.raises(H1ProtocolError, match="发生变化"):
        runner._revalidate_provenance(Path.cwd(), spec, "b" * 40, initial)


def test_first_run_empty_root_creates_only_frozen_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    paths = runner._fixed_paths(root)
    fsynced: list[Path] = []

    def record_directory_fsync(path: Path) -> None:
        if path == root / "artifacts":
            assert paths.run_root.is_dir()
            assert not paths.traces.exists()
        elif path == paths.run_root:
            assert paths.traces.is_dir()
        else:
            raise AssertionError(path)
        fsynced.append(path)

    monkeypatch.setattr(runner, "_fsync_directory", record_directory_fsync)
    runner._prepare_run_root(paths, _plan())
    assert paths.run_root.is_dir()
    assert paths.traces.is_dir()
    assert set(paths.run_root.iterdir()) == {paths.traces}
    assert fsynced == [root / "artifacts", paths.run_root]


def test_resume_existing_directories_does_not_repeat_directory_fsync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths, plan = _prepared_paths(tmp_path)
    monkeypatch.setattr(
        runner,
        "_fsync_directory",
        lambda path: pytest.fail(f"resume 不应重复 fsync 已存在目录: {path}"),
    )

    runner._prepare_run_root(paths, plan)


@pytest.mark.parametrize(
    "unsupported_errno",
    sorted(
        {
            errno.EINVAL,
            errno.ENOTSUP,
            *([errno.EOPNOTSUPP] if hasattr(errno, "EOPNOTSUPP") else []),
        }
    ),
)
def test_directory_fsync_ignores_platform_unsupported_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    unsupported_errno: int,
) -> None:
    root = _repository(tmp_path)
    paths = runner._fixed_paths(root)
    monkeypatch.setattr(
        runner.os,
        "fsync",
        lambda descriptor: (_ for _ in ()).throw(
            OSError(unsupported_errno, "directory fsync unsupported")
        ),
    )

    runner._prepare_run_root(paths, _plan())

    assert paths.run_root.is_dir()
    assert paths.traces.is_dir()


def test_unexpected_directory_fsync_error_stops_before_trace_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    root = _repository(tmp_path)
    paths = runner._fixed_paths(root)

    monkeypatch.setattr(runner, "_require_real_repository_root", lambda: root)
    monkeypatch.setattr(runner, "_require_loaded_code_from_repository", lambda repository: None)
    monkeypatch.setattr(runner, "_fixed_paths", lambda repository: paths)
    monkeypatch.setattr(runner, "load_h1_gate_spec", lambda path: spec)
    monkeypatch.setattr(runner, "_validate_initial_provenance", lambda *args: provenance)
    monkeypatch.setattr(runner, "plan_primary_artifacts", lambda selected: _plan())
    monkeypatch.setattr(
        runner.os,
        "fsync",
        lambda descriptor: (_ for _ in ()).throw(OSError(errno.EIO, "directory fsync")),
    )
    monkeypatch.setattr(
        runner,
        "_load_or_create_inventory",
        lambda *args: pytest.fail("directory fsync 失败后不得进入 trace generation"),
    )

    with pytest.raises(OSError, match="directory fsync"):
        runner.run_formal_h1("b" * 40, emit=lambda message: None)

    assert paths.run_root.is_dir()
    assert not paths.traces.exists()


@pytest.mark.parametrize("target", ["run_root", "traces", "inventory"])
def test_formal_path_symlinks_are_rejected(tmp_path: Path, target: str) -> None:
    root = _repository(tmp_path)
    run_root = root / runner._RUN_ROOT_RELATIVE
    real = root / "real"
    real.mkdir()
    if target == "run_root":
        run_root.symlink_to(real, target_is_directory=True)
    else:
        run_root.mkdir()
        link = run_root / (runner._TRACES_NAME if target == "traces" else runner._INVENTORY_NAME)
        link.symlink_to(real, target_is_directory=target == "traces")
    with pytest.raises(H1ProtocolError, match="符号链接"):
        runner._fixed_paths(root)


def test_unknown_run_root_and_trace_files_are_rejected(tmp_path: Path) -> None:
    paths, plan = _prepared_paths(tmp_path)
    (paths.run_root / "unknown.txt").write_text("x", encoding="utf-8")
    with pytest.raises(H1ProtocolError, match="unknown files"):
        runner._prepare_run_root(paths, plan)
    (paths.run_root / "unknown.txt").unlink()
    (paths.traces / "trace_999.npz").write_bytes(b"x")
    with pytest.raises(H1ProtocolError, match="unknown files"):
        runner._prepare_run_root(paths, plan)


def test_inventory_existing_with_missing_trace_hard_fails(tmp_path: Path) -> None:
    paths, plan = _prepared_paths(tmp_path)
    paths.inventory.write_text("{}\n", encoding="utf-8")
    (paths.traces / plan[0].relative_path).write_bytes(b"x")
    with pytest.raises(H1ProtocolError, match="traces 不完整"):
        runner._prepare_run_root(paths, plan)


def test_partial_valid_trace_resume_generates_only_missing_with_initial_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    paths, plan = _prepared_paths(tmp_path)
    (paths.traces / plan[0].relative_path).write_bytes(b"existing")
    generated: list[int] = []
    seen_provenance: list[FormalProvenance] = []

    class FakeProcess:
        def __init__(self, seed: int) -> None:
            self.seed = seed

        def generate(self, num_steps: int) -> object:
            generated.append(self.seed)
            assert num_steps == 256
            return object()

    monkeypatch.setattr(runner, "_revalidate_provenance", lambda *args: provenance)
    monkeypatch.setattr(
        runner,
        "build_primary_demand_config",
        lambda selected_spec, seed: {"demand": {"seed": seed}},
    )
    monkeypatch.setattr(
        runner,
        "create_demand_process",
        lambda demand: FakeProcess(demand["seed"]),
    )
    monkeypatch.setattr(
        runner,
        "save_demand_trace",
        lambda path, trace, *, resolved_config, overwrite: path.write_bytes(b"new") or path,
    )

    def validate_entry(
        selected_spec: object,
        plan_entry: ArtifactPlanEntry,
        path: Path,
        formal_provenance: FormalProvenance,
    ) -> ArtifactInventoryEntry:
        assert path.is_file()
        seen_provenance.append(formal_provenance)
        return _entry(plan_entry.seed)

    expected = _inventory(spec)
    monkeypatch.setattr(runner, "_provenance_bound_entry", validate_entry)
    monkeypatch.setattr(runner, "build_primary_artifact_inventory", lambda spec, entries: expected)
    monkeypatch.setattr(
        runner,
        "write_artifact_inventory",
        lambda path, inventory: path.write_text("inventory", encoding="utf-8") or path,
    )
    monkeypatch.setattr(runner, "read_artifact_inventory", lambda *args: expected)

    loaded = runner._load_or_create_inventory(
        paths,
        spec,
        plan,
        "b" * 40,
        provenance,
        lambda message: None,
    )

    assert loaded == expected
    assert generated == [102]
    assert seen_provenance == [provenance, provenance]


def test_partial_invalid_trace_hard_fails_without_generation_or_deletion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    paths, plan = _prepared_paths(tmp_path)
    invalid = paths.traces / plan[0].relative_path
    invalid.write_bytes(b"invalid")
    monkeypatch.setattr(
        runner,
        "_provenance_bound_entry",
        lambda *args: (_ for _ in ()).throw(H1ProtocolError("invalid NPZ")),
    )
    monkeypatch.setattr(
        runner,
        "create_demand_process",
        lambda config: pytest.fail("invalid existing trace 不得触发 generation"),
    )
    with pytest.raises(H1ProtocolError, match="invalid NPZ"):
        runner._load_or_create_inventory(
            paths,
            spec,
            plan,
            "b" * 40,
            provenance,
            lambda message: None,
        )
    assert invalid.read_bytes() == b"invalid"


def test_existing_inventory_never_generates_and_revalidates_every_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    paths, plan = _prepared_paths(tmp_path)
    inventory = _inventory(spec)
    paths.inventory.write_text("inventory", encoding="utf-8")
    for plan_entry in plan:
        (paths.traces / plan_entry.relative_path).write_bytes(b"trace")
    monkeypatch.setattr(runner, "read_artifact_inventory", lambda *args: inventory)
    seen: list[int] = []

    def validate(*args: object) -> ArtifactInventoryEntry:
        plan_entry = args[1]
        assert isinstance(plan_entry, ArtifactPlanEntry)
        seen.append(plan_entry.seed)
        return _entry(plan_entry.seed)

    monkeypatch.setattr(runner, "_provenance_bound_entry", validate)
    monkeypatch.setattr(runner, "_revalidate_provenance", lambda *args: provenance)
    monkeypatch.setattr(
        runner,
        "create_demand_process",
        lambda config: pytest.fail("inventory resume 不得 generation"),
    )

    assert (
        runner._load_or_create_inventory(
            paths,
            spec,
            plan,
            "b" * 40,
            provenance,
            lambda message: None,
        )
        == inventory
    )
    assert seen == [101, 102]


def test_provenance_change_before_generation_stops_without_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    paths, plan = _prepared_paths(tmp_path, _plan((101,)))
    monkeypatch.setattr(
        runner,
        "_revalidate_provenance",
        lambda *args: (_ for _ in ()).throw(H1ProtocolError("provenance changed")),
    )
    monkeypatch.setattr(
        runner,
        "create_demand_process",
        lambda config: pytest.fail("provenance failure 后不得 generation"),
    )
    with pytest.raises(H1ProtocolError, match="changed"):
        runner._load_or_create_inventory(
            paths,
            spec,
            plan,
            "b" * 40,
            provenance,
            lambda message: None,
        )
    assert not tuple(paths.traces.iterdir())


def test_h0_runs_all_entries_before_canonical_and_failure_stops(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    inventory = _inventory(spec)
    paths, _ = _prepared_paths(tmp_path)
    order: list[object] = []
    monkeypatch.setattr(
        runner,
        "_load_validated_artifact_entry",
        lambda path, entry, steps: SimpleNamespace(trace=entry.seed),
    )
    monkeypatch.setattr(runner, "validate_h0_invariant", lambda trace, config: order.append(trace))
    monkeypatch.setattr(runner, "validate_canonical_mechanism", lambda: order.append("canonical"))
    runner._run_h0_and_mechanism(paths, spec, inventory, lambda message: None)
    assert order == [101, 102, "canonical"]

    order.clear()

    def fail_first(trace: object, config: object) -> None:
        order.append(trace)
        raise H1ProtocolError("H0 failed")

    monkeypatch.setattr(runner, "validate_h0_invariant", fail_first)
    with pytest.raises(H1ProtocolError, match="H0 failed"):
        runner._run_h0_and_mechanism(paths, spec, inventory, lambda message: None)
    assert order == [101]


def test_canonical_mechanism_failure_is_hard_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    inventory = _inventory(spec, (101,))
    paths, _ = _prepared_paths(tmp_path, _plan((101,)))
    monkeypatch.setattr(
        runner,
        "_load_validated_artifact_entry",
        lambda *args: SimpleNamespace(trace=object()),
    )
    monkeypatch.setattr(runner, "validate_h0_invariant", lambda *args: None)
    monkeypatch.setattr(
        runner,
        "validate_canonical_mechanism",
        lambda: (_ for _ in ()).throw(H1ProtocolError("mechanism failed")),
    )
    with pytest.raises(H1ProtocolError, match="mechanism failed"):
        runner._run_h0_and_mechanism(paths, spec, inventory, lambda message: None)


def test_h2_crash_before_jsonl_is_rerunnable_without_partial_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    inventory = _inventory(spec)
    paths, _ = _prepared_paths(tmp_path)
    calls = 0

    def crashing_run(*args: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("H2 crash")
        return object()

    monkeypatch.setattr(runner, "run_primary_artifact", crashing_run)
    monkeypatch.setattr(
        runner,
        "write_paired_jsonl",
        lambda *args: pytest.fail("crashed batch 不得发布 JSONL"),
    )
    with pytest.raises(RuntimeError, match="H2 crash"):
        runner._load_or_run_primary_results(
            paths,
            spec,
            inventory,
            "b" * 40,
            provenance,
            lambda message: None,
        )
    assert not paths.paired_results.exists()

    expected = (object(), object())
    iterator = iter(expected)
    monkeypatch.setattr(runner, "run_primary_artifact", lambda *args: next(iterator))
    monkeypatch.setattr(runner, "validate_primary_paired_results", lambda *args: None)
    monkeypatch.setattr(runner, "compute_paired_results_hash", lambda results: "f" * 64)
    monkeypatch.setattr(runner, "_revalidate_provenance", lambda *args: provenance)
    monkeypatch.setattr(
        runner,
        "write_paired_jsonl",
        lambda path, results: path.write_text("complete", encoding="utf-8") or path,
    )
    monkeypatch.setattr(runner, "read_paired_jsonl", lambda *args: expected)
    assert (
        runner._load_or_run_primary_results(
            paths,
            spec,
            inventory,
            "b" * 40,
            provenance,
            lambda message: None,
        )
        == expected
    )


def test_existing_jsonl_is_strictly_reused_or_hard_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    inventory = _inventory(spec)
    paths, _ = _prepared_paths(tmp_path)
    paths.paired_results.write_text("checkpoint", encoding="utf-8")
    expected = (object(), object())
    monkeypatch.setattr(runner, "read_paired_jsonl", lambda *args: expected)
    monkeypatch.setattr(
        runner,
        "run_primary_artifact",
        lambda *args: pytest.fail("existing JSONL 不得重跑 H2"),
    )
    assert (
        runner._load_or_run_primary_results(
            paths,
            spec,
            inventory,
            "b" * 40,
            provenance,
            lambda message: None,
        )
        == expected
    )

    monkeypatch.setattr(
        runner,
        "read_paired_jsonl",
        lambda *args: (_ for _ in ()).throw(H1ProtocolError("invalid JSONL")),
    )
    with pytest.raises(H1ProtocolError, match="invalid JSONL"):
        runner._load_or_run_primary_results(
            paths,
            spec,
            inventory,
            "b" * 40,
            provenance,
            lambda message: None,
        )


def test_existing_aggregate_is_recomputed_and_exactly_compared(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    inventory = _inventory(spec)
    paths, _ = _prepared_paths(tmp_path)
    paths.aggregate.write_text("checkpoint", encoding="utf-8")
    expected = _summary()
    monkeypatch.setattr(runner, "evaluate_primary_gate", lambda *args: expected)
    monkeypatch.setattr(runner, "read_h1_summary", lambda path: expected)
    monkeypatch.setattr(
        runner,
        "write_h1_summary",
        lambda *args: pytest.fail("existing aggregate 不得 overwrite"),
    )
    assert (
        runner._load_or_write_aggregate(
            paths,
            spec,
            inventory,
            (),
            "b" * 40,
            provenance,
            lambda message: None,
        )
        == expected
    )

    mismatch = replace(expected, point_estimate=0.04)
    monkeypatch.setattr(runner, "read_h1_summary", lambda path: mismatch)
    with pytest.raises(H1ProtocolError, match="recomputed"):
        runner._load_or_write_aggregate(
            paths,
            spec,
            inventory,
            (),
            "b" * 40,
            provenance,
            lambda message: None,
        )


@pytest.mark.parametrize("verdict", [H1Verdict.PASS, H1Verdict.PROTOCOL_FAIL])
def test_existing_verdict_never_overwrites_and_protocol_fail_never_unlocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    verdict: H1Verdict,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    paths, _ = _prepared_paths(tmp_path)
    paths.verdict.write_text("checkpoint", encoding="utf-8")
    summary = _summary(verdict)
    locked: list[bool] = []
    monkeypatch.setattr(runner, "_revalidate_provenance", lambda *args: provenance)
    monkeypatch.setattr(
        runner,
        "write_primary_verdict",
        lambda *args: pytest.fail("existing verdict 不得 overwrite"),
    )
    monkeypatch.setattr(
        runner,
        "read_primary_verdict",
        lambda *args, **kwargs: {"summary": summary_to_dict(summary)},
    )
    monkeypatch.setattr(
        runner,
        "require_locked_primary_verdict",
        lambda *args, **kwargs: locked.append(True),
    )
    assert (
        runner._load_or_write_verdict(
            paths,
            spec,
            "c" * 64,
            "d" * 64,
            summary,
            "b" * 40,
            provenance,
            lambda message: None,
        )
        == summary
    )
    assert locked == ([True] if verdict is H1Verdict.PASS else [])


def test_h0_failure_prevents_h2_in_top_level_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    paths, plan = _prepared_paths(tmp_path)
    inventory = _inventory(spec)
    monkeypatch.setattr(runner, "_require_real_repository_root", lambda: paths.repository)
    monkeypatch.setattr(runner, "_require_loaded_code_from_repository", lambda repository: None)
    monkeypatch.setattr(runner, "_fixed_paths", lambda repository: paths)
    monkeypatch.setattr(runner, "load_h1_gate_spec", lambda path: spec)
    monkeypatch.setattr(runner, "_validate_initial_provenance", lambda *args: provenance)
    monkeypatch.setattr(runner, "plan_primary_artifacts", lambda spec: plan)
    monkeypatch.setattr(runner, "_prepare_run_root", lambda *args: None)
    monkeypatch.setattr(runner, "_revalidate_provenance", lambda *args: provenance)
    monkeypatch.setattr(runner, "_load_or_create_inventory", lambda *args: inventory)
    monkeypatch.setattr(runner, "compute_artifact_inventory_hash", lambda value: "c" * 64)
    monkeypatch.setattr(
        runner,
        "_run_h0_and_mechanism",
        lambda *args: (_ for _ in ()).throw(H1ProtocolError("H0 failed")),
    )
    monkeypatch.setattr(
        runner,
        "_load_or_run_primary_results",
        lambda *args: pytest.fail("H0 failure 后不得进入 H2"),
    )
    with pytest.raises(H1ProtocolError, match="H0 failed"):
        runner.run_formal_h1("b" * 40, emit=lambda message: None)


def test_stage_output_hides_statistics_until_strict_verdict_readback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    paths, plan = _prepared_paths(tmp_path)
    inventory = _inventory(spec)
    summary = _summary()
    messages: list[str] = []
    monkeypatch.setattr(runner, "_require_real_repository_root", lambda: paths.repository)
    monkeypatch.setattr(runner, "_require_loaded_code_from_repository", lambda repository: None)
    monkeypatch.setattr(runner, "_fixed_paths", lambda repository: paths)
    monkeypatch.setattr(runner, "load_h1_gate_spec", lambda path: spec)
    monkeypatch.setattr(runner, "_validate_initial_provenance", lambda *args: provenance)
    monkeypatch.setattr(runner, "plan_primary_artifacts", lambda spec: plan)
    monkeypatch.setattr(runner, "_prepare_run_root", lambda *args: None)
    monkeypatch.setattr(runner, "_revalidate_provenance", lambda *args: provenance)
    monkeypatch.setattr(runner, "_load_or_create_inventory", lambda *args: inventory)
    monkeypatch.setattr(runner, "compute_artifact_inventory_hash", lambda value: "c" * 64)
    monkeypatch.setattr(runner, "_run_h0_and_mechanism", lambda *args: None)
    monkeypatch.setattr(runner, "_load_or_run_primary_results", lambda *args: (object(),))
    monkeypatch.setattr(runner, "compute_paired_results_hash", lambda value: "d" * 64)
    monkeypatch.setattr(runner, "_load_or_write_aggregate", lambda *args: summary)

    def strict_verdict(*args: object) -> H1GateSummary:
        emit = args[-1]
        assert callable(emit)
        emit("stage=verdict status=published")
        return summary

    monkeypatch.setattr(runner, "_load_or_write_verdict", strict_verdict)
    assert runner.run_formal_h1("b" * 40, emit=messages.append) == summary
    verdict_index = messages.index("stage=verdict status=published")
    before_verdict = "\n".join(messages[: verdict_index + 1])
    assert "point_estimate" not in before_verdict
    assert "one_sided_lcb" not in before_verdict
    assert "formal_verdict=" not in before_verdict
    assert messages[verdict_index + 1 :] == [
        "formal_verdict=PASS",
        "point_estimate=0.03",
        "one_sided_lcb=0.01",
        "one_sided_ucb=0.04",
    ]


def test_private_runner_does_not_change_package_exports_or_bounded_verifier() -> None:
    assert "_formal_h1_runner" not in experiments_package.__all__
    assert (
        hashlib.sha256(Path("src/fura_mappo/experiments/__init__.py").read_bytes()).hexdigest()
        == "9882e80e0169173bc996cb7872fdecf9cdfd166a22e7b7f3f2c472b74c69e6a3"
    )
    assert (
        hashlib.sha256(
            Path("src/fura_mappo/experiments/_bounded_verifier.py").read_bytes()
        ).hexdigest()
        == "7cf35386d839b7711f9f295bdcd330be5f4f2bb6c9dbe7241f84a8b168496a7c"
    )


@pytest.mark.parametrize(
    ("stage", "error_text"),
    [
        ("h0", "H0 protocol failure"),
        ("canonical", "canonical mechanism protocol failure"),
        ("jsonl", "strict JSONL protocol failure"),
    ],
)
def test_real_runner_protocol_stage_failure_maps_to_cli_protocol_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    stage: str,
    error_text: str,
) -> None:
    spec = _spec()
    provenance = _provenance(spec)
    paths, plan = _prepared_paths(tmp_path)
    inventory = _inventory(spec)
    monkeypatch.setattr(runner, "_require_real_repository_root", lambda: paths.repository)
    monkeypatch.setattr(runner, "_require_loaded_code_from_repository", lambda repository: None)
    monkeypatch.setattr(runner, "_fixed_paths", lambda repository: paths)
    monkeypatch.setattr(runner, "load_h1_gate_spec", lambda path: spec)
    monkeypatch.setattr(runner, "_validate_initial_provenance", lambda *args: provenance)
    monkeypatch.setattr(runner, "plan_primary_artifacts", lambda spec: plan)
    monkeypatch.setattr(runner, "_prepare_run_root", lambda *args: None)
    monkeypatch.setattr(runner, "_revalidate_provenance", lambda *args: provenance)
    monkeypatch.setattr(runner, "_load_or_create_inventory", lambda *args: inventory)
    monkeypatch.setattr(runner, "compute_artifact_inventory_hash", lambda value: "c" * 64)
    monkeypatch.setattr(
        runner,
        "_load_or_write_aggregate",
        lambda *args: pytest.fail("protocol failure 后不得计算/写 aggregate"),
    )
    monkeypatch.setattr(
        runner,
        "_load_or_write_verdict",
        lambda *args: pytest.fail("pre-results protocol failure 不得写 fake verdict"),
    )
    monkeypatch.setattr(
        runner,
        "require_locked_primary_verdict",
        lambda *args, **kwargs: pytest.fail("PROTOCOL_FAIL 不得解锁 sensitivity"),
    )

    if stage in {"h0", "canonical"}:
        monkeypatch.setattr(
            runner,
            "_run_h0_and_mechanism",
            lambda *args: (_ for _ in ()).throw(H1ProtocolError(error_text)),
        )
        monkeypatch.setattr(
            runner,
            "_load_or_run_primary_results",
            lambda *args: pytest.fail("H0/mechanism failure 后不得进入 H2"),
        )
    else:
        monkeypatch.setattr(runner, "_run_h0_and_mechanism", lambda *args: None)
        paths.paired_results.write_text("invalid checkpoint", encoding="utf-8")
        monkeypatch.setattr(
            runner,
            "read_paired_jsonl",
            lambda *args: (_ for _ in ()).throw(H1ProtocolError(error_text)),
        )

    assert runner.main(["--accepted-implementation-sha", "b" * 40]) == 2
    captured = capsys.readouterr()
    assert "formal_verdict=PROTOCOL_FAIL" in captured.err
    assert f"formal_h1_protocol_error={error_text}" in captured.err
    assert "formal_h1_error=" not in captured.err
    assert not paths.verdict.exists()


def test_ordinary_runtime_io_error_is_not_protocol_fail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        runner,
        "_require_real_repository_root",
        lambda: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    assert runner.main(["--accepted-implementation-sha", "b" * 40]) == 1
    captured = capsys.readouterr()
    assert "formal_h1_error=disk unavailable" in captured.err
    assert "formal_verdict=PROTOCOL_FAIL" not in captured.err


def test_protocol_fail_cli_status_is_nonzero_without_sensitivity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "run_formal_h1",
        lambda accepted_sha: _summary(H1Verdict.PROTOCOL_FAIL),
    )
    assert runner.main(["--accepted-implementation-sha", "b" * 40]) == 2
