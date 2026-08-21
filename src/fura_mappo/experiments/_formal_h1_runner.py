"""WP-02D3 Formal H1 的私有、可恢复、no-overwrite 执行协调器。"""

from __future__ import annotations

import argparse
import errno
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import fura_mappo
import fura_mappo.baselines as baselines_package
import fura_mappo.demand as demand_package
import fura_mappo.envs as envs_package
import fura_mappo.experiments.h1_gate as h1_gate_module
from fura_mappo.demand import create_demand_process, save_demand_trace
from fura_mappo.experiments.h1_gate import (
    ArtifactInventory,
    ArtifactInventoryEntry,
    ArtifactPlanEntry,
    FormalProvenance,
    H1GateSpec,
    H1GateSummary,
    H1ProtocolError,
    H1Verdict,
    PairedTraceResult,
    _load_validated_artifact_entry,
    build_primary_artifact_inventory,
    build_primary_demand_config,
    build_primary_environment_config,
    build_provenance_bound_artifact_entry,
    compute_artifact_inventory_hash,
    compute_paired_results_hash,
    evaluate_primary_gate,
    load_h1_gate_spec,
    plan_primary_artifacts,
    read_artifact_inventory,
    read_h1_summary,
    read_paired_jsonl,
    read_primary_verdict,
    require_locked_primary_verdict,
    run_primary_artifact,
    summary_to_dict,
    validate_canonical_mechanism,
    validate_formal_provenance,
    validate_h0_invariant,
    validate_primary_paired_results,
    write_artifact_inventory,
    write_h1_summary,
    write_paired_jsonl,
    write_primary_verdict,
)

_SPEC_RELATIVE = Path("configs/experiments/wp02d_h1.yaml")
_ARTIFACTS_RELATIVE = Path("artifacts")
_RUN_ROOT_RELATIVE = _ARTIFACTS_RELATIVE / "wp02d_h1_formal_v1"
_TRACES_NAME = "traces"
_INVENTORY_NAME = "artifact_inventory.json"
_PAIRED_NAME = "primary_paired_results.jsonl"
_AGGREGATE_NAME = "primary_aggregate.json"
_VERDICT_NAME = "primary_verdict.json"
_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class FormalH1Paths:
    """冻结的 repo-local Formal H1 路径集合。"""

    repository: Path
    spec: Path
    run_root: Path
    traces: Path
    inventory: Path
    paired_results: Path
    aggregate: Path
    verdict: Path


def _git(repository: Path, *arguments: str) -> str:
    """执行短时、无网络、只读 Git 查询。"""

    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise H1ProtocolError(f"Git runner gate 失败: git {' '.join(arguments)}")
    return result.stdout.strip()


def _validate_accepted_sha(value: object) -> str:
    """要求调用方提供未来已审查的完整 D3 accepted implementation SHA。"""

    if not isinstance(value, str) or _GIT_SHA_PATTERN.fullmatch(value) is None:
        raise H1ProtocolError("--accepted-implementation-sha 必须是 40 位小写 Commit SHA")
    return value


def _require_real_repository_root() -> Path:
    """要求 cwd 本身就是无 symlink 的 Git top-level。"""

    cwd = Path.cwd().absolute()
    if cwd.is_symlink() or cwd.resolve(strict=True) != cwd:
        raise H1ProtocolError("cwd 必须是真实、非 symlink repository top-level")
    top_level_raw = _git(cwd, "rev-parse", "--show-toplevel")
    top_level = Path(top_level_raw)
    if not top_level.is_absolute() or top_level.absolute() != cwd:
        raise H1ProtocolError("cwd 必须精确为 repository top-level")
    if _git(cwd, "branch", "--show-current") != "main":
        raise H1ProtocolError("Formal H1 runner 要求 branch 精确为 main")
    return cwd


def _resolved_module_file(module: object, name: str) -> Path:
    """返回 imported module 的真实文件路径，拒绝 namespace/缺失文件。"""

    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str) or not raw:
        raise H1ProtocolError(f"loaded code module {name} 缺少有效 __file__")
    try:
        return Path(raw).resolve(strict=True)
    except OSError as error:
        raise H1ProtocolError(f"loaded code module {name} 文件不可解析") from error


def _require_module_within_package(module: object, name: str, package_root: Path) -> None:
    """要求 imported module 的真实文件严格位于当前 repository package tree。"""

    resolved = _resolved_module_file(module, name)
    try:
        resolved.relative_to(package_root)
    except ValueError as error:
        raise H1ProtocolError(
            f"loaded code module {name} 不来自当前 repository: {resolved}"
        ) from error


def _require_loaded_code_from_repository(repository: Path) -> None:
    """把实际执行的 src-layout package/module 路径绑定到已验证 repository。"""

    try:
        expected_package_root = (repository / "src" / "fura_mappo").resolve(strict=True)
    except OSError as error:
        raise H1ProtocolError("当前 repository 缺少真实 src/fura_mappo package root") from error
    expected_init = expected_package_root / "__init__.py"
    if _resolved_module_file(fura_mappo, "fura_mappo") != expected_init:
        raise H1ProtocolError("loaded fura_mappo.__file__ 不来自当前 repository")

    raw_package_paths = getattr(fura_mappo, "__path__", None)
    if raw_package_paths is None:
        raise H1ProtocolError("loaded fura_mappo 缺少 package __path__")
    try:
        package_paths = tuple(Path(path).resolve(strict=True) for path in raw_package_paths)
    except (OSError, TypeError) as error:
        raise H1ProtocolError("loaded fura_mappo.__path__ 不可解析") from error
    if package_paths != (expected_package_root,):
        raise H1ProtocolError("loaded fura_mappo.__path__ 不唯一指向当前 repository")

    expected_runner = expected_package_root / "experiments" / "_formal_h1_runner.py"
    if _resolved_module_file(sys.modules[__name__], __name__) != expected_runner:
        raise H1ProtocolError("loaded formal H1 runner 不来自当前 repository")
    expected_h1_gate = expected_package_root / "experiments" / "h1_gate.py"
    if _resolved_module_file(h1_gate_module, h1_gate_module.__name__) != expected_h1_gate:
        raise H1ProtocolError("loaded h1_gate 不来自当前 repository")

    for module in (demand_package, envs_package, baselines_package):
        _require_module_within_package(module, module.__name__, expected_package_root)
    prefixes = ("fura_mappo.demand", "fura_mappo.envs", "fura_mappo.baselines")
    for module_name in sorted(sys.modules):
        if not any(
            module_name == prefix or module_name.startswith(prefix + ".") for prefix in prefixes
        ):
            continue
        module = sys.modules[module_name]
        if module is None:
            raise H1ProtocolError(f"loaded code module {module_name} 缺失")
        _require_module_within_package(module, module_name, expected_package_root)


def _require_confined_path(repository: Path, target: Path) -> None:
    """拒绝逃逸 repository 或从 root 起任何已存在的 symlink component。"""

    if not repository.is_absolute() or not target.is_absolute():
        raise H1ProtocolError("formal path 必须是绝对路径")
    try:
        relative = target.relative_to(repository)
    except ValueError as error:
        raise H1ProtocolError("formal path 必须位于真实 repository root 内") from error
    current = repository
    if current.is_symlink():
        raise H1ProtocolError("repository root 不能是符号链接")
    for component in relative.parts:
        if component in {"", ".", ".."}:
            raise H1ProtocolError("formal path 包含非规范 component")
        current = current / component
        if current.is_symlink():
            raise H1ProtocolError(f"formal path 不能经过符号链接: {current}")
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(repository)
    except ValueError as error:
        raise H1ProtocolError("resolved formal path 逃逸 repository root") from error


def _fixed_paths(repository: Path) -> FormalH1Paths:
    """返回唯一冻结路径并检查每条 path chain。"""

    run_root = repository / _RUN_ROOT_RELATIVE
    traces = run_root / _TRACES_NAME
    paths = FormalH1Paths(
        repository=repository,
        spec=repository / _SPEC_RELATIVE,
        run_root=run_root,
        traces=traces,
        inventory=run_root / _INVENTORY_NAME,
        paired_results=run_root / _PAIRED_NAME,
        aggregate=run_root / _AGGREGATE_NAME,
        verdict=run_root / _VERDICT_NAME,
    )
    for target in (
        repository / _ARTIFACTS_RELATIVE,
        paths.run_root,
        paths.traces,
        paths.inventory,
        paths.paired_results,
        paths.aggregate,
        paths.verdict,
    ):
        _require_confined_path(repository, target)
    return paths


def _regular_file_or_absent(path: Path, name: str) -> None:
    """拒绝 output symlink、目录与其他特殊文件。"""

    if path.is_symlink():
        raise H1ProtocolError(f"{name} 不能是符号链接")
    if os.path.lexists(path) and not path.is_file():
        raise H1ProtocolError(f"{name} 必须是普通文件")


def _fsync_directory(path: Path) -> None:
    """同步目录项，仅忽略平台明确不支持目录 fsync 的错误。"""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            unsupported = {errno.EINVAL, errno.ENOTSUP}
            if hasattr(errno, "EOPNOTSUPP"):
                unsupported.add(errno.EOPNOTSUPP)
            if error.errno not in unsupported:
                raise
    finally:
        os.close(descriptor)


def _prepare_run_root(paths: FormalH1Paths, plan: tuple[ArtifactPlanEntry, ...]) -> None:
    """创建允许创建的目录，并拒绝 unknown/不可能的 resume 状态。"""

    artifacts = paths.repository / _ARTIFACTS_RELATIVE
    if artifacts.is_symlink() or not artifacts.is_dir():
        raise H1ProtocolError("repository artifacts/ 必须是已存在的普通目录")
    if paths.run_root.is_symlink():
        raise H1ProtocolError("formal run root 不能是符号链接")
    if not paths.run_root.exists():
        paths.run_root.mkdir()
        _fsync_directory(artifacts)
    elif not paths.run_root.is_dir():
        raise H1ProtocolError("formal run root 必须是普通目录")

    allowed_root_names = {
        _TRACES_NAME,
        _INVENTORY_NAME,
        _PAIRED_NAME,
        _AGGREGATE_NAME,
        _VERDICT_NAME,
    }
    unknown_root = sorted(
        child.name for child in paths.run_root.iterdir() if child.name not in allowed_root_names
    )
    if unknown_root:
        raise H1ProtocolError("formal run root 包含 unknown files: " + ", ".join(unknown_root))

    if paths.traces.is_symlink():
        raise H1ProtocolError("formal traces dir 不能是符号链接")
    if not paths.traces.exists():
        paths.traces.mkdir()
        _fsync_directory(paths.run_root)
    elif not paths.traces.is_dir():
        raise H1ProtocolError("formal traces 必须是普通目录")

    for path, name in (
        (paths.inventory, "artifact inventory"),
        (paths.paired_results, "paired results"),
        (paths.aggregate, "aggregate"),
        (paths.verdict, "verdict"),
    ):
        _regular_file_or_absent(path, name)

    planned_names = {entry.relative_path for entry in plan}
    trace_children = tuple(paths.traces.iterdir())
    unknown_traces = sorted(
        child.name for child in trace_children if child.name not in planned_names
    )
    if unknown_traces:
        raise H1ProtocolError("formal traces dir 包含 unknown files: " + ", ".join(unknown_traces))
    for child in trace_children:
        if child.is_symlink() or not child.is_file():
            raise H1ProtocolError(f"formal trace 必须是普通文件: {child.name}")

    if paths.inventory.exists():
        missing = sorted(planned_names - {child.name for child in trace_children})
        if missing:
            raise H1ProtocolError("inventory 已存在但 formal traces 不完整")
    elif any(path.exists() for path in (paths.paired_results, paths.aggregate, paths.verdict)):
        raise H1ProtocolError("inventory 不存在时不得存在下游 formal output")
    if not paths.paired_results.exists() and any(
        path.exists() for path in (paths.aggregate, paths.verdict)
    ):
        raise H1ProtocolError("paired results 不存在时不得存在 aggregate/verdict")
    if not paths.aggregate.exists() and paths.verdict.exists():
        raise H1ProtocolError("aggregate 不存在时不得存在 verdict")


def _validate_initial_provenance(
    repository: Path,
    spec: H1GateSpec,
    accepted_sha: str,
) -> FormalProvenance:
    """验证 main 和 accepted-code hard gate，保存初始 provenance。"""

    if _git(repository, "branch", "--show-current") != "main":
        raise H1ProtocolError("Formal H1 runner 要求 branch 精确为 main")
    return validate_formal_provenance(
        repository,
        spec,
        wp02d_accepted_implementation_sha=accepted_sha,
    )


def _revalidate_provenance(
    repository: Path,
    spec: H1GateSpec,
    accepted_sha: str,
    initial: FormalProvenance,
) -> FormalProvenance:
    """在 publication boundary 重新验证并要求逐值等于初始快照。"""

    current = _validate_initial_provenance(repository, spec, accepted_sha)
    if current != initial:
        raise H1ProtocolError("formal provenance 在执行期间发生变化")
    return current


def _provenance_bound_entry(
    spec: H1GateSpec,
    plan_entry: ArtifactPlanEntry,
    trace_path: Path,
    provenance: FormalProvenance,
) -> ArtifactInventoryEntry:
    """统一验证 existing/new artifact；任何调用方 hashes 均不受信任。"""

    return build_provenance_bound_artifact_entry(
        spec,
        plan_entry,
        trace_path,
        provenance,
    )


def _load_or_create_inventory(
    paths: FormalH1Paths,
    spec: H1GateSpec,
    plan: tuple[ArtifactPlanEntry, ...],
    accepted_sha: str,
    initial: FormalProvenance,
    emit: Callable[[str], None],
) -> ArtifactInventory:
    """实现 trace/inventory 的 no-overwrite、restart-safe 状态机。"""

    if paths.inventory.exists():
        inventory = read_artifact_inventory(paths.inventory, spec, paths.traces)
        for plan_entry, recorded_entry in zip(plan, inventory.entries, strict=True):
            validated = _provenance_bound_entry(
                spec,
                plan_entry,
                paths.traces / plan_entry.relative_path,
                initial,
            )
            if validated != recorded_entry:
                raise H1ProtocolError(
                    "existing inventory entry 与 provenance-bound artifact 不一致"
                )
        _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
        emit(f"stage=inventory status=reused count={len(inventory.entries)}")
        return inventory

    entries: list[ArtifactInventoryEntry] = []
    for index, plan_entry in enumerate(plan, start=1):
        trace_path = paths.traces / plan_entry.relative_path
        if trace_path.exists():
            entry = _provenance_bound_entry(spec, plan_entry, trace_path, initial)
        else:
            _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
            resolved_config = build_primary_demand_config(spec, plan_entry.seed)
            demand_config = resolved_config.get("demand")
            if not isinstance(demand_config, Mapping):
                raise H1ProtocolError("resolved demand config 缺少 demand mapping")
            process = create_demand_process(demand_config)
            trace = process.generate(spec.num_steps)
            _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
            save_demand_trace(
                trace_path,
                trace,
                resolved_config=resolved_config,
                overwrite=False,
            )
            _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
            entry = _provenance_bound_entry(spec, plan_entry, trace_path, initial)
            _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
        entries.append(entry)
        emit(f"stage=traces status=validated count={index}/{len(plan)}")

    _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
    inventory = build_primary_artifact_inventory(spec, entries)
    _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
    write_artifact_inventory(paths.inventory, inventory)
    _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
    read_back = read_artifact_inventory(paths.inventory, spec, paths.traces)
    if read_back != inventory:
        raise H1ProtocolError("artifact inventory strict readback 不一致")
    _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
    emit(f"stage=inventory status=published count={len(inventory.entries)}")
    return inventory


def _run_h0_and_mechanism(
    paths: FormalH1Paths,
    spec: H1GateSpec,
    inventory: ArtifactInventory,
    emit: Callable[[str], None],
) -> None:
    """每次 primary invocation 都重跑完整 H=0 batch 与 canonical preflight。"""

    config = build_primary_environment_config(spec)
    for index, entry in enumerate(inventory.entries, start=1):
        artifact = _load_validated_artifact_entry(
            paths.traces / entry.relative_path,
            entry,
            spec.num_steps,
        )
        validate_h0_invariant(artifact.trace, config)
        emit(f"stage=h0 status=validated count={index}/{len(inventory.entries)}")
    validate_canonical_mechanism()
    emit("stage=canonical-mechanism status=validated")


def _load_or_run_primary_results(
    paths: FormalH1Paths,
    spec: H1GateSpec,
    inventory: ArtifactInventory,
    accepted_sha: str,
    initial: FormalProvenance,
    emit: Callable[[str], None],
) -> tuple[PairedTraceResult, ...]:
    """严格复用完整 JSONL，或在内存完成整个 H=2 batch 后一次发布。"""

    if paths.paired_results.exists():
        results = read_paired_jsonl(paths.paired_results, spec, inventory)
        emit(f"stage=primary-h2 status=reused count={len(results)}")
        return results

    completed = []
    for index, entry in enumerate(inventory.entries, start=1):
        completed.append(run_primary_artifact(spec, entry, paths.traces))
        emit(f"stage=primary-h2 status=completed count={index}/{len(inventory.entries)}")
    results = tuple(completed)
    validate_primary_paired_results(results, spec, inventory)
    expected_hash = compute_paired_results_hash(results)
    _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
    write_paired_jsonl(paths.paired_results, results)
    _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
    read_back = read_paired_jsonl(paths.paired_results, spec, inventory)
    if read_back != results or compute_paired_results_hash(read_back) != expected_hash:
        raise H1ProtocolError("paired results strict readback/digest 不一致")
    emit(f"stage=paired-results status=published sha256={expected_hash}")
    return read_back


def _load_or_write_aggregate(
    paths: FormalH1Paths,
    spec: H1GateSpec,
    inventory: ArtifactInventory,
    results: Sequence[PairedTraceResult],
    accepted_sha: str,
    initial: FormalProvenance,
    emit: Callable[[str], None],
) -> H1GateSummary:
    """总是从 strict results 重算 summary，再与磁盘 aggregate 逐值比较。"""

    recomputed = evaluate_primary_gate(results, spec, inventory)
    if paths.aggregate.exists():
        disk_summary = read_h1_summary(paths.aggregate)
        status = "reused"
    else:
        _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
        write_h1_summary(paths.aggregate, recomputed)
        _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
        disk_summary = read_h1_summary(paths.aggregate)
        status = "published"
    if disk_summary != recomputed:
        raise H1ProtocolError("disk aggregate 与 recomputed summary 不一致")
    emit(f"stage=aggregate status={status}")
    return recomputed


def _plain_tree(value: object) -> object:
    """把 read-only mappings/tuples 转回可比较普通树。"""

    if isinstance(value, Mapping):
        return {key: _plain_tree(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_tree(item) for item in value]
    if isinstance(value, list):
        return [_plain_tree(item) for item in value]
    return value


def _load_or_write_verdict(
    paths: FormalH1Paths,
    spec: H1GateSpec,
    inventory_hash: str,
    results_hash: str,
    summary: H1GateSummary,
    accepted_sha: str,
    initial: FormalProvenance,
    emit: Callable[[str], None],
) -> H1GateSummary:
    """no-overwrite 发布或严格复用 terminal verdict，并验证 sensitivity lock 语义。"""

    current = _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
    if paths.verdict.exists():
        status = "reused"
    else:
        write_primary_verdict(
            paths.verdict,
            summary,
            spec.sha256,
            inventory_hash,
            results_hash,
            current,
        )
        _revalidate_provenance(paths.repository, spec, accepted_sha, initial)
        status = "published"
    loaded = read_primary_verdict(
        paths.verdict,
        expected_spec_sha256=spec.sha256,
        expected_artifact_inventory_sha256=inventory_hash,
        expected_paired_results_sha256=results_hash,
        expected_formal_provenance=initial,
    )
    if _plain_tree(loaded["summary"]) != _plain_tree(summary_to_dict(summary)):
        raise H1ProtocolError("verdict embedded summary 与 recomputed summary 不一致")
    if summary.verdict is not H1Verdict.PROTOCOL_FAIL:
        require_locked_primary_verdict(
            paths.verdict,
            spec,
            expected_artifact_inventory_sha256=inventory_hash,
            expected_paired_results_sha256=results_hash,
            expected_formal_provenance=initial,
        )
    emit(f"stage=verdict status={status}")
    return summary


def run_formal_h1(
    accepted_implementation_sha: str,
    *,
    emit: Callable[[str], None] = print,
) -> H1GateSummary:
    """从固定 cwd/repo paths 运行唯一 Formal H1 状态机。"""

    accepted_sha = _validate_accepted_sha(accepted_implementation_sha)
    repository = _require_real_repository_root()
    _require_loaded_code_from_repository(repository)
    paths = _fixed_paths(repository)
    spec = load_h1_gate_spec(paths.spec)
    initial = _validate_initial_provenance(repository, spec, accepted_sha)
    plan = plan_primary_artifacts(spec)
    _prepare_run_root(paths, plan)
    _revalidate_provenance(repository, spec, accepted_sha, initial)
    emit(f"stage=provenance status=validated head={initial.actual_head}")
    emit(f"stage=spec status=validated sha256={spec.sha256}")

    inventory = _load_or_create_inventory(paths, spec, plan, accepted_sha, initial, emit)
    inventory_hash = compute_artifact_inventory_hash(inventory)
    emit(f"stage=inventory status=locked sha256={inventory_hash}")
    _run_h0_and_mechanism(paths, spec, inventory, emit)

    results = _load_or_run_primary_results(
        paths,
        spec,
        inventory,
        accepted_sha,
        initial,
        emit,
    )
    results_hash = compute_paired_results_hash(results)
    emit(f"stage=paired-results status=locked sha256={results_hash}")
    summary = _load_or_write_aggregate(
        paths,
        spec,
        inventory,
        results,
        accepted_sha,
        initial,
        emit,
    )
    terminal = _load_or_write_verdict(
        paths,
        spec,
        inventory_hash,
        results_hash,
        summary,
        accepted_sha,
        initial,
        emit,
    )
    emit(f"formal_verdict={terminal.verdict.value}")
    if terminal.verdict is not H1Verdict.PROTOCOL_FAIL:
        emit(f"point_estimate={terminal.point_estimate}")
        emit(f"one_sided_lcb={terminal.one_sided_lcb}")
        emit(f"one_sided_ucb={terminal.one_sided_ucb}")
    return terminal


def _build_parser() -> argparse.ArgumentParser:
    """构造只有 accepted implementation SHA 可变的 CLI。"""

    parser = argparse.ArgumentParser(description="Run the frozen WP-02D Formal H1 workflow")
    parser.add_argument("--accepted-implementation-sha", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口；PROTOCOL_FAIL 是已持久化但非科学推断的非零 terminal outcome。"""

    args = _build_parser().parse_args(argv)
    try:
        summary = run_formal_h1(args.accepted_implementation_sha)
    except H1ProtocolError as error:
        print("formal_verdict=PROTOCOL_FAIL", file=sys.stderr)
        print(f"formal_h1_protocol_error={error}", file=sys.stderr)
        return 2
    except (OSError, TypeError, ValueError) as error:
        print(f"formal_h1_error={error}", file=sys.stderr)
        return 1
    return 2 if summary.verdict is H1Verdict.PROTOCOL_FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
