"""采集不含敏感环境变量的最小运行时信息。"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any


def _package_version(name: str) -> str | None:
    """安全读取已安装软件包版本。"""

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _run_command(command: list[str]) -> str | None:
    """执行只读命令；命令不存在或执行失败时返回 ``None``。"""

    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() or None


def collect_runtime_info() -> dict[str, Any]:
    """返回可用于实验追踪的最小运行时信息。

    函数不会读取环境变量列表、网络地址、SSH 配置或凭据。
    """

    gpu_query = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=index,name,driver_version,memory.total",
            "--format=csv,noheader",
        ]
    )

    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_name": Path(sys.executable).name,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "packages": {
            "numpy": _package_version("numpy"),
            "pyyaml": _package_version("PyYAML"),
            "pytest": _package_version("pytest"),
            "ruff": _package_version("ruff"),
        },
        "git_commit": _run_command(["git", "rev-parse", "HEAD"]),
        "conda_environment": os.environ.get("CONDA_DEFAULT_ENV"),
        "gpu_query": gpu_query.splitlines() if gpu_query else [],
    }


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="采集最小运行时信息")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/runtime_info.json"),
        help="JSON 输出路径",
    )
    args = parser.parse_args()

    info = collect_runtime_info()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"运行时信息已写入：{args.output}")


if __name__ == "__main__":
    main()
