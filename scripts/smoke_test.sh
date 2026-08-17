#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

printf '===== Python =====\n'
python --version

printf '\n===== Package import =====\n'
python - <<'PY'
from fura_mappo import __version__
print(f"fura_mappo version: {__version__}")
PY

printf '\n===== Ruff =====\n'
python -m ruff check .

printf '\n===== Pytest =====\n'
python -m pytest -q

printf '\n===== Runtime metadata =====\n'
python -m fura_mappo.utils.system_info --output artifacts/runtime_info.json

printf '\nWP-00 基础烟雾测试通过。\n'
