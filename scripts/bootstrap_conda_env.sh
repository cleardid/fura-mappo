#!/usr/bin/env bash
set -Eeuo pipefail

# 本脚本只创建 WP-00 的基础 CPU 开发环境，不安装 PyTorch。
# GPU版 PyTorch 将在服务器驱动与 CUDA 状态核验后单独安装。

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

if ! command -v conda >/dev/null 2>&1; then
  printf '错误：当前 shell 中找不到 conda。\n' >&2
  printf '请先执行 conda init，或 source 对应的 conda.sh。\n' >&2
  exit 1
fi

if conda env list | awk '{print $1}' | grep -qx 'fura-mappo'; then
  printf '检测到已有环境 fura-mappo，执行更新。\n'
  conda env update -n fura-mappo -f environment.yml --prune
else
  printf '创建环境 fura-mappo。\n'
  conda env create -f environment.yml
fi

printf '\n环境准备完成。请执行：\n'
printf '  conda activate fura-mappo\n'
printf '  python -m pip install -e ".[dev]"\n'
printf '  bash scripts/smoke_test.sh\n'
