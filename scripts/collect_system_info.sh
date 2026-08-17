#!/usr/bin/env bash
set -Eeuo pipefail

# 服务器只读审计脚本。
# 不读取环境变量列表、网络配置、SSH目录、Token或密钥。

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/artifacts/system_audit"
OUTPUT_FILE="${OUTPUT_DIR}/system_info.txt"
mkdir -p "${OUTPUT_DIR}"

redact_home() {
  # 将可能暴露用户名的 HOME 绝对路径替换为 ~。
  sed "s#${HOME//\#/\\#}#~#g"
}

run_optional() {
  local title="$1"
  shift
  {
    printf '\n===== %s =====\n' "${title}"
    if command -v "$1" >/dev/null 2>&1; then
      "$@" 2>&1 || true
    else
      printf '命令不可用：%s\n' "$1"
    fi
  } | redact_home
}

{
  printf 'FURA-MAPPO WP-00 SERVER AUDIT\n'
  printf '生成时间（ISO 8601）：%s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
  printf '项目目录：%s\n' "${PROJECT_ROOT}" | redact_home

  printf '\n===== OPERATING SYSTEM =====\n'
  uname -srm 2>&1 || true
  if [[ -r /etc/os-release ]]; then
    cat /etc/os-release
  fi

  printf '\n===== CPU =====\n'
  if command -v lscpu >/dev/null 2>&1; then
    lscpu
  else
    getconf _NPROCESSORS_ONLN 2>/dev/null || true
  fi

  printf '\n===== MEMORY =====\n'
  if command -v free >/dev/null 2>&1; then
    free -h
  else
    cat /proc/meminfo 2>/dev/null || true
  fi

  printf '\n===== DISK =====\n'
  df -h "${PROJECT_ROOT}" "${HOME}" /tmp 2>&1 | awk '!seen[$0]++' | redact_home

  printf '\n===== GPU SUMMARY =====\n'
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi \
      --query-gpu=index,name,driver_version,memory.total,compute_cap,pstate,temperature.gpu \
      --format=csv,noheader 2>&1 || true
  else
    printf 'nvidia-smi 不可用\n'
  fi

  printf '\n===== CUDA TOOLKIT =====\n'
  if command -v nvcc >/dev/null 2>&1; then
    nvcc --version 2>&1 || true
  else
    printf 'nvcc 不可用；这不等于 GPU 不能运行 PyTorch。\n'
  fi

  printf '\n===== CONDA =====\n'
  if command -v conda >/dev/null 2>&1; then
    conda --version 2>&1 || true
    printf 'Conda 可执行文件：%s\n' "$(command -v conda)" | redact_home
    conda env list 2>&1 | redact_home || true
  else
    printf 'conda 不可用\n'
  fi

  printf '\n===== PYTHON =====\n'
  if command -v python >/dev/null 2>&1; then
    python --version 2>&1 || true
    printf 'Python 可执行文件：%s\n' "$(command -v python)" | redact_home
  else
    printf 'python 不可用\n'
  fi

  printf '\n===== DEVELOPMENT TOOLS =====\n'
  git --version 2>&1 || true
  if command -v tmux >/dev/null 2>&1; then
    tmux -V 2>&1 || true
  else
    printf 'tmux 不可用\n'
  fi

  printf '\n===== GIT WORKTREE =====\n'
  if git -C "${PROJECT_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf 'Commit：%s\n' "$(git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || printf '尚无 Commit')"
    printf 'Branch：%s\n' "$(git -C "${PROJECT_ROOT}" branch --show-current 2>/dev/null || true)"
    printf '工作区状态：\n'
    git -C "${PROJECT_ROOT}" status --short 2>&1 | redact_home || true
  else
    printf '当前目录尚未初始化为 Git 仓库。\n'
  fi

  printf '\n===== PRIVACY CHECK =====\n'
  printf '本脚本未主动采集 IP、完整主机名、环境变量、SSH 配置或凭据。\n'
  printf '上传或提交此文件前仍须人工检查。\n'
} > "${OUTPUT_FILE}"

printf '服务器审计完成：%s\n' "${OUTPUT_FILE}"
printf '请先人工检查，再决定是否提交到私有仓库。\n'
