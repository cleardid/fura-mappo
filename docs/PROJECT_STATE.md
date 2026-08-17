# 项目状态

更新日期：2026-08-17

## 1. 项目基线

- 项目：FURA-MAPPO
- 仓库：`https://github.com/cleardid/fura-mappo`
- 分支：`main`
- 远程最新 Commit：`62675e43d17726adde3696f7fd5e5ab4208b6a2a`
- 远程最新提交说明：`chore: establish Codex collaboration workflow`
- 初始稳定标签：`wp00-stable`
- 标签 Commit：`427b231f73f3194ab9420130744e9ee075998c68`

## 2. 工作包状态

| 工作包 | 状态 | 说明 |
|---|---|---|
| WP-00 | 已完成 | 项目骨架、环境、Ruff、Pytest、CI、系统审计、随机种子和状态文档 |
| OPS-01 | 已完成 | Codex 协作规范、工作流、工作包模板和 CPU 验收脚本 |
| WP-01A | 补丁审查通过，待正式验收 | 平稳 Poisson 需求核心；尚未 Commit、Push 或服务器验收 |
| WP-01B | 未开始 | Drifting Hotspot、Markov Switching、Burst Demand |
| WP-01C | 未开始 | 配置、序列化、CLI、统计汇总和可选可视化 |

当前唯一目标是完成 WP-01A 的 Mac、Commit/Push 和服务器验收，不得开始 WP-01B。

## 3. WP-01A 候选实现

补丁：

```text
wp01a-review.patch
SHA-256: 97fe150926f746708b662126233553621595e1e234151fe40b98fa1ec4600195
```

实现文件：

```text
src/fura_mappo/utils/seeding.py
src/fura_mappo/demand/__init__.py
src/fura_mappo/demand/models.py
src/fura_mappo/demand/processes.py
src/fura_mappo/demand/factory.py
tests/test_seeding.py
tests/test_demand_models.py
tests/test_stationary_demand.py
tests/test_demand_factory.py
```

独立审查结论：无已知阻断性缺陷，可进入 Mac Python 3.11 最终验收。详细记录见 `docs/WP01A_REVIEW.md`。

## 4. 已验证结果

### OPS-01 服务器验收

- Commit：`62675e43d17726adde3696f7fd5e5ab4208b6a2a`
- Python：3.11.15
- `pip check`：通过
- Ruff：通过
- Ruff 格式检查：通过
- Pytest：6 passed
- CPU 验收：通过

### WP-01A 初始 Codex 实现结果

在前一版修复前，Mac 完整 CPU 验收报告为 150 passed。独立审查随后发现混合 bool 和一次性范围输入问题，已经在最新补丁修复，因此该 150 结果不能作为最新补丁的最终验收。

### WP-01A 最新补丁独立复测

- 专项测试：164 passed
- 重建完整基线测试：166 passed
- `git apply --check`：通过
- `git diff --check`：通过
- 额外边界和多种子检查：通过
- 环境：Python 3.13，仅作补充证据，不替代官方 Python 3.11 验收

## 5. 服务器环境

```text
CPU：80 核级
内存：502 GiB
GPU：2 × NVIDIA A100-SXM4-80GB
GPU 显存：每张 80GB
NVIDIA 驱动：590.48.01
Compute Capability：8.0
Conda：24.9.2
项目环境：fura-mappo
项目 Python：3.11.15
系统 Python：2.7.18，不得使用
nvcc：不可用
tmux：2.9a
```

WP-01 继续 CPU-only，不安装 PyTorch、不修改 CUDA 或驱动、不执行 GPU 训练。

## 6. 当前待办

1. 把本次文档包合并到 Mac 候选工作树；
2. 在 `fura-mappo-mac` 运行最新补丁专项测试和 `scripts/verify_cpu.sh`；
3. 检查完整 Diff、暂存区和未跟踪文件；
4. 用户手工 Commit：`feat: add WP-01A stationary demand core`；
5. Push 到 `origin/main`；
6. A100 服务器 `git pull --ff-only` 并执行 CPU 和 WP-01A 专项验收；
7. 记录实际 Commit、GitHub Actions 和服务器结果；
8. 只有 WP-01A 完成后才规划 WP-01B。

## 7. 已知风险

- 最新补丁尚未在受支持的 Python 3.11 Mac 环境完成最终复验；
- 当前文档记录的是候选状态，服务器通过后必须再次更新实际 Commit 和最终验收结果；
- `pyproject.toml` 允许 Python 3.10–3.12，Ruff 目标为 py310，而项目运行规范固定 Python 3.11；该差异不在 WP-01A 中顺带修改；
- WP-01A 不包含序列化和外部配置，不能误写为完整 WP-01 已完成。
