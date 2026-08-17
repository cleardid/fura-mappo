# 项目状态

更新日期：2026-08-17

## 1. 已验证基线

- 项目：FURA-MAPPO
- 仓库：`https://github.com/cleardid/fura-mappo`
- 分支：`main`
- WP-01A 实现 Commit：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`
- 实现提交说明：`feat: add WP-01A stationary demand core`
- WP-01A 稳定标签：`wp01a-stable`
- 标签目标：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`
- 初始稳定标签：`wp00-stable`
- 初始标签 Commit：`427b231f73f3194ab9420130744e9ee075998c68`

本文件所在的文档收尾 Commit 不硬编码自身 SHA；当前仓库 Commit 应以 `git rev-parse HEAD` 为准。科研实现稳定基线固定为上述 WP-01A Commit。

## 2. 工作包状态

| 工作包 | 状态 | 说明 |
|---|---|---|
| WP-00 | 已完成 | 项目骨架、环境、Ruff、Pytest、CI、系统审计、随机种子和状态文档 |
| OPS-01 | 已完成 | Codex 协作规范、工作流、工作包模板和 CPU 验收脚本 |
| WP-01A | 已完成 | 核心数据结构、统一状态接口、平稳 Poisson、工厂和统计验证 |
| WP-01B | 准备开始 | 先进行只读设计分析；仅包含 Drifting Hotspot、Markov Switching、Burst Demand |
| WP-01C | 未开始 | 配置、序列化、CLI、统计汇总和可选可视化 |

当前唯一目标是 WP-01B 只读设计分析。设计确认前不得修改源码或提前实现 WP-01C。

## 3. WP-01A 已冻结接口

```text
DemandEvent
DemandStep
DemandTrace
DemandProcess
StationaryPoissonDemand
create_demand_process
create_numpy_generator
```

核心语义：

- 每个需求过程实例独占 `numpy.random.Generator`；
- `reset(None)` 重放当前基准 seed；
- `reset(seed)` 切换并保存新基准 seed；
- `step()` 仅在完整 `DemandStep` 构造成功后推进状态；
- `generate(n)` 从当前状态继续；
- `generate(n, seed=s)` 从 step 0 重启并更新基准 seed；
- event ID 连续递增；
- 输出数组防御性复制并设置只读；
- 需求过程不读取智能体、动作、奖励或任务完成状态。

WP-01B 必须复用这些接口和语义。任何变更都需要先形成决策记录并重新审查兼容性。

## 4. WP-01A 验收证据

### 独立补丁审查

- 补丁 SHA-256：`97fe150926f746708b662126233553621595e1e234151fe40b98fa1ec4600195`；
- 专项测试：`164 passed`；
- 补入远程基线测试后的隔离完整测试：`166 passed`；
- `git apply --check`：通过；
- `git diff --check`：通过；
- 额外边界、多种子和状态隔离检查：通过；
- 早期混合 bool、set/generator 范围问题已修复。

隔离审查使用 Python 3.13，只作为补充证据，不替代正式 Python 3.11 验收。

### GitHub

- `main` 实现 Commit：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`；
- GitHub Actions 工作流：`CPU checks`；
- Run：#3；
- 结论：成功。

### A100 服务器

- 用户确认 `git pull --ff-only` 后的 CPU 与 WP-01A 专项测试全部通过；
- 项目 Python：3.11.15；
- 服务器不直接修改源码；
- 原始日志、大型输出和敏感环境信息不提交仓库。

本次会话未收到逐行服务器日志，因此这里只记录已确认的通过结论，不虚构具体测试数量或终端输出。

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

## 6. 下一步

1. 冻结本次文档收尾 Commit，并保持工作树干净；
2. A100 同步文档收尾 Commit，确认 `git status --short` 无输出；
3. 启动 WP-01B 阶段 1：Codex 只读设计分析；
4. 审查三类过程的参数化、隐状态、工厂扩展、统计测试和 ID/OOD 边界；
5. 设计确认后才生成 WP-01B 实现任务。

## 7. 当前风险

- WP-01B 参数化、隐状态暴露和 OOD 边界尚未冻结；
- `pyproject.toml` 允许 Python 3.10–3.12、Ruff 目标为 py310，而项目运行规范固定 Python 3.11；该差异不在 WP-01 中顺带修改；
- WP-01B 不得为了方便提前加入 YAML、序列化、CLI 或绘图；
- WP-01A 的稳定接口在后续扩展中必须保持兼容。
