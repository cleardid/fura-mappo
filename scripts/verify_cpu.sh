#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

printf '===== 当前时间 =====\n'
date '+%Y-%m-%d %H:%M:%S %z'

printf '\n===== Git 状态 =====\n'
printf '当前 Commit：'
git rev-parse HEAD
current_branch="$(git branch --show-current)"
if [[ -n "${current_branch}" ]]; then
    printf '当前分支：%s\n' "${current_branch}"
else
    printf '当前状态：detached HEAD\n'
fi

printf '\n===== Python 环境 =====\n'
python --version
command -v python

printf '\n===== Python 依赖一致性检查 =====\n'
python -m pip check

printf '\n===== Ruff 代码检查 =====\n'
ruff check .

printf '\n===== Ruff 格式检查 =====\n'
ruff format --check .

printf '\n===== Pytest 测试 =====\n'
pytest -q

printf '\n===== CPU 验收完成 =====\n'
printf '所有 CPU 验收检查均已通过。\n'
