# WP-00 运行手册：仓库初始化与服务器审计

> 历史文档：WP-00 已完成，稳定标签为 `wp00-stable`，对应 Commit `427b231f73f3194ab9420130744e9ee075998c68`。当前开发和交付流程以 `docs/CODEX_WORKFLOW.md` 为准。本手册保留用于重建基础环境或核对初始审计方法。

## 1. WP-00 范围

WP-00 只处理：

- GitHub 仓库初始化；
- 服务器软硬件审计；
- 基础 Conda 环境；
- 包导入、随机种子、测试和 CI；
- 跨会话状态文件。

不处理 PyTorch GPU 安装、需求生成器、多智能体环境、MAPPO 或训练。

## 2. 服务器只读审计

```bash
bash scripts/collect_system_info.sh
sed -n '1,260p' artifacts/system_audit/system_info.txt
```

重点检查 CPU、内存、磁盘、GPU、驱动、`nvcc`、Conda、Python 和 `tmux`。审计输出不得包含 Token、SSH 配置、IP 或不必要的主机信息。

`nvcc` 不存在不等于 PyTorch 无法使用 GPU；但 WP-01 仍明确不安装 PyTorch。

## 3. 基础环境

```bash
bash scripts/bootstrap_conda_env.sh
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate fura-mappo
python -m pip install -e ".[dev]"
```

服务器系统 Python 2.7 不得用于项目。

## 4. 基础验收

当前统一入口：

```bash
bash scripts/verify_cpu.sh
```

WP-00 原始烟雾测试入口仍可用于历史排查：

```bash
bash scripts/smoke_test.sh
```

实际稳定状态、服务器规格和最新测试结果见 `docs/PROJECT_STATE.md`。

## 5. 历史交付结果

WP-00 建立 Python 包骨架、Conda 基础环境、Ruff、Pytest、GitHub Actions、系统审计、运行时信息工具、全局种子初始化工具以及项目状态文档。OPS-01 后续建立 `AGENTS.md`、main-only 协作流程、工作包模板和 `scripts/verify_cpu.sh`。

## 6. 当前使用规则

- 不再按本历史手册初始化 Git 或创建仓库；
- 不使用 candidate 标签作为必需验收步骤；
- 不在服务器直接修改源码；
- 当前工作包遵循完整补丁审查流程；
- 最新操作顺序见 `docs/CODEX_WORKFLOW.md` 和 `docs/SESSION_HANDOFF.md`。
