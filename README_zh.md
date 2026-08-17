# FURA-MAPPO

面向非平稳时空需求的预测式多智能体资源预置研究项目。

当前代码包为 **WP-00：仓库初始化与服务器审计**。这一阶段只完成工程基础设施和硬件/软件环境核验，暂不安装 PyTorch，也不实现仿真环境或强化学习算法。

## 本阶段目标

1. 确认服务器的操作系统、CPU、内存、磁盘、GPU、驱动、CUDA、Conda 和 Python 状态。
2. 建立可测试、可追踪、可跨会话交接的 GitHub 仓库。
3. 验证基础 Python 包、随机种子工具、单元测试和 GitHub Actions。
4. 为 WP-01（需求生成器）冻结开发环境和接口约束。

## 快速开始

### 1. 在本地解压并上传到 GitHub

建议创建私有仓库 `fura-mappo`。将本目录中的所有文件放入仓库根目录后提交。

```bash
git init
git add .
git commit -m "chore: initialize WP-00 project skeleton"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

### 2. 在服务器克隆仓库

```bash
cd ~
git clone <你的仓库地址>
cd fura-mappo
```

### 3. 先执行无安装审计

```bash
bash scripts/collect_system_info.sh
```

输出文件位于：

```text
artifacts/system_audit/system_info.txt
```

脚本不会主动采集 SSH 私钥、Token、环境变量、IP 地址或完整主机名，并会尝试将 `$HOME` 路径替换为 `~`。提交前仍应人工检查输出内容。

### 4. 创建基础 Conda 环境

本阶段环境不安装 PyTorch。GPU版 PyTorch 必须等服务器审计完成后，根据驱动和 CUDA 兼容性单独确定。

```bash
conda env create -f environment.yml
conda activate fura-mappo
python -m pip install -e ".[dev]"
```

若环境已经存在：

```bash
conda env update -f environment.yml --prune
conda activate fura-mappo
python -m pip install -e ".[dev]"
```

### 5. 执行验收

```bash
bash scripts/smoke_test.sh
```

或分别执行：

```bash
python -m pytest -q
python -m ruff check .
python -m fura_mappo.utils.system_info --output artifacts/runtime_info.json
```

## WP-00 完成标准

- [ ] GitHub 仓库已创建并完成首次提交。
- [ ] GitHub Actions 的 `CPU checks` 通过。
- [ ] 服务器完成 `collect_system_info.sh`。
- [ ] 本地/服务器 `pytest` 和 `ruff` 均通过。
- [ ] `docs/PROJECT_STATE.md` 已填写服务器审计摘要。
- [ ] `docs/SESSION_HANDOFF.md` 已记录当前 Commit、测试结果和下一步。
- [ ] 未将密钥、Token、IP、用户名路径或大型日志提交到仓库。

详细操作见 `docs/WP00_RUNBOOK.md`。

## 开发与验收流程

项目采用 main-only 交付：Codex 修改 Mac 本地 `main` → Mac 本地测试 → 用户本地 Commit → candidate 标签上传 GitHub → A100 服务器验收 → 用户推送 `main` → GitHub Actions → 稳定标签。

完整协作规则与失败处理见 `docs/CODEX_WORKFLOW.md`。
