"""需求轨迹生成与汇总命令行接口。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fura_mappo.demand.config import (
    _validate_demand_config,
    compute_config_hash,
    load_demand_config,
)
from fura_mappo.demand.factory import create_demand_process
from fura_mappo.demand.serialization import (
    _collect_git_state,
    _fsync_parent,
    load_demand_trace,
    save_demand_trace,
)
from fura_mappo.demand.summary import summarize_demand_trace


@dataclass(frozen=True, slots=True)
class _CliFailure(Exception):
    """携带固定退出码和不含路径的用户消息。"""

    code: int
    message: str


def _strict_json_text(value: object) -> str:
    """编码单行严格 JSON。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _print_json(value: object) -> None:
    """向 stdout 写入单个严格 JSON 对象。"""

    print(_strict_json_text(value))


def _display_path(path: Path) -> str:
    """返回不泄露工作目录之外绝对路径的用户显示路径。"""

    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return path.name


def _file_sha256(path: Path) -> str:
    """流式计算已发布文件 SHA-256。"""

    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _resolved_config(
    loaded: Mapping[str, object],
    seed: int | None,
    num_steps: int | None,
) -> dict[str, object]:
    """在深复制上应用两个显式 CLI 覆盖并重新验证。"""

    resolved = copy.deepcopy(dict(loaded))
    if seed is not None:
        demand = resolved.get("demand")
        if not isinstance(demand, dict):
            raise TypeError("demand 必须是 Mapping")
        demand["seed"] = seed
    if num_steps is not None:
        generation = resolved.get("generation")
        if not isinstance(generation, dict):
            raise TypeError("generation 必须是 Mapping")
        generation["num_steps"] = num_steps
    return _validate_demand_config(resolved)


def _load_and_resolve(args: argparse.Namespace) -> dict[str, object]:
    """加载配置并把配置/覆盖错误统一映射到退出码 3。"""

    try:
        loaded = load_demand_config(args.config)
        return _resolved_config(loaded, args.seed, args.num_steps)
    except (TypeError, ValueError) as error:
        raise _CliFailure(3, f"配置或覆盖无效：{error}") from error
    except OSError as error:
        raise _CliFailure(6, "无法读取配置文件") from error


def _run_generate(args: argparse.Namespace) -> int:
    """执行 generate 子命令。"""

    config = _load_and_resolve(args)
    commit, dirty = _collect_git_state()
    if commit is None or dirty is None:
        print("警告：Git 状态不可用，artifact 将记录 null", file=sys.stderr)
    if dirty is True and not args.allow_dirty:
        raise _CliFailure(7, "Git 工作树不干净；如确需生成请显式使用 --allow-dirty")

    demand = config["demand"]
    generation = config["generation"]
    if not isinstance(demand, dict) or not isinstance(generation, dict):
        raise _CliFailure(3, "配置子结构无效")
    process = create_demand_process(demand)
    num_steps = generation["num_steps"]
    if not isinstance(num_steps, int) or isinstance(num_steps, bool):
        raise _CliFailure(3, "generation.num_steps 无效")
    trace = process.generate(num_steps)
    config_hash = compute_config_hash(config)

    if args.output is None:
        process_type = demand["type"]
        seed = demand["seed"]
        output = Path("artifacts/demand") / (
            f"{process_type}-s{seed}-n{num_steps}-{config_hash[:12]}.npz"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
    else:
        output = args.output

    try:
        save_demand_trace(output, trace, resolved_config=config, overwrite=args.force)
        artifact = load_demand_trace(output)
        file_hash = _file_sha256(output)
    except FileExistsError as error:
        raise _CliFailure(5, "输出目标已存在；如需替换请显式使用 --force") from error
    except (OSError, PermissionError) as error:
        raise _CliFailure(6, "写入 artifact 时发生文件系统或权限错误") from error
    except (TypeError, ValueError) as error:
        raise _CliFailure(6, f"artifact 输出路径或内容无效：{error}") from error

    _print_json(
        {
            "status": "ok",
            "output": _display_path(output),
            "config_sha256": config_hash,
            "content_sha256": artifact.manifest["content_sha256"],
            "file_sha256": file_hash,
        }
    )
    return 0


def _validate_json_target(path: Path, overwrite: bool) -> None:
    """验证 summary JSON 目标和覆盖策略。"""

    if path.suffix != ".json":
        raise ValueError("summary 输出后缀必须精确为 .json")
    if not path.parent.exists() or not path.parent.is_dir():
        raise FileNotFoundError("summary 输出目录不存在或不是目录")
    if path.is_symlink():
        raise ValueError("summary 输出目标不能是符号链接")
    if os.path.lexists(path) and not overwrite:
        raise FileExistsError("summary 输出目标已存在")


def _atomic_write_json(path: Path, value: object, overwrite: bool) -> None:
    """在目标同目录原子写入严格 JSON，并清理失败临时文件。"""

    _validate_json_target(path, overwrite)
    payload = (_strict_json_text(value) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        with temporary.open("r", encoding="utf-8") as stream:
            json.load(stream)
        if overwrite:
            if path.is_symlink():
                raise ValueError("summary 输出目标不能是符号链接")
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        _fsync_parent(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _run_summarize(args: argparse.Namespace) -> int:
    """执行 summarize 子命令。"""

    try:
        artifact = load_demand_trace(args.input)
    except (TypeError, ValueError) as error:
        raise _CliFailure(4, "输入 artifact 损坏或版本不兼容") from error
    except OSError as error:
        raise _CliFailure(6, "无法读取输入 artifact") from error
    summary = summarize_demand_trace(artifact.trace)
    if args.output is None:
        _print_json(summary)
        return 0

    try:
        _atomic_write_json(args.output, summary, args.force)
    except FileExistsError as error:
        raise _CliFailure(5, "summary 输出已存在；如需替换请显式使用 --force") from error
    except (OSError, PermissionError) as error:
        raise _CliFailure(6, "写入 summary 时发生文件系统或权限错误") from error
    except (TypeError, ValueError) as error:
        raise _CliFailure(6, f"summary 输出路径无效：{error}") from error
    _print_json({"status": "ok", "output": _display_path(args.output)})
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """构造无交互、仅含两个子命令的参数解析器。"""

    parser = argparse.ArgumentParser(prog="fura-demand", description="生成和汇总外生需求轨迹")
    parser.add_argument("--debug", action="store_true", help="发生错误时显示 traceback")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="从严格 YAML 配置生成 NPZ 轨迹")
    generate.add_argument("--config", required=True, type=Path, help="小写 .yaml 配置")
    generate.add_argument("--seed", type=int, help="覆盖 demand.seed")
    generate.add_argument("--num-steps", type=int, help="覆盖 generation.num_steps")
    generate.add_argument("--output", type=Path, help="小写 .npz 输出")
    generate.add_argument("--force", action="store_true", help="替换已有普通文件")
    generate.add_argument(
        "--allow-dirty", action="store_true", help="允许在 dirty Git 工作树生成 artifact"
    )

    summarize = subparsers.add_parser("summarize", help="汇总已验证的 NPZ 轨迹")
    summarize.add_argument("--input", required=True, type=Path, help="小写 .npz artifact")
    summarize.add_argument("--output", type=Path, help="小写 .json 输出")
    summarize.add_argument("--force", action="store_true", help="替换已有普通文件")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """运行 CLI 并返回固定退出码；不捕获 ``KeyboardInterrupt``。"""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            return _run_generate(args)
        if args.command == "summarize":
            return _run_summarize(args)
        raise RuntimeError("argparse 返回了未知子命令")
    except _CliFailure as error:
        if args.debug:
            traceback.print_exc()
        else:
            print(f"错误：{error.message}", file=sys.stderr)
        return error.code
    except Exception:
        if args.debug:
            traceback.print_exc()
        else:
            print("错误：发生未预期内部错误；使用 --debug 获取诊断信息", file=sys.stderr)
        return 1


__all__: list[str] = ["main"]
