# FURA-MAPPO

面向非平稳时空需求的预测引导、不确定性感知多智能体资源预置研究项目。

## 当前状态

- `WP-00`：仓库骨架、Conda 环境、Ruff、Pytest、GitHub Actions、系统审计和随机种子工具，已完成。
- `OPS-01`：Codex 协作规范、工作流、工作包模板和 CPU 验收脚本，已完成。
- `WP-01A`：外生需求核心与平稳 Poisson 过程，已完成。
- WP-01A 实现 Commit：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`。
- GitHub Actions `CPU checks` 第 3 次运行：通过。
- A100 CPU 与 WP-01A 专项验收：用户确认全部通过。
- 稳定里程碑标签：`wp01a-stable` → `b7b48bb394bd4613652b4d1ff4158cb8503f52a5`。
- 当前唯一开发目标：`WP-01B`。先进行只读设计分析，设计审查前不得修改源码。

## 研究目标

项目独立于指定原文，研究以下核心问题：

> 在非平稳时空需求下，未来需求预测及预测不确定性是否能够提高多智能体主动资源预置的服务质量、资源效率和分布外稳健性？

研究必须先验证真实未来信息的价值：比较反应式资源分配与 Oracle 未来需求配置。只有 Oracle 能产生稳定收益时，才继续研究预测模型和 MAPPO。最终系统计划支持：

- 反应式资源分配；
- Oracle 未来需求配置；
- 概率需求预测数据生成；
- 预测引导、风险或不确定性感知的 MAPPO 资源预置；
- 分布内与分布外评估；
- 预测误差、校准度和控制收益之间的价值相图分析。

研究要求、科学问题和阶段路线分别见：

- `docs/PROJECT_REQUIREMENTS.md`
- `docs/RESEARCH_PLAN.md`
- `docs/ANALYSIS_PLAN.md`

## WP-01 拆分

### WP-01A：已完成

- `DemandEvent`、`DemandStep`、`DemandTrace`；
- `DemandProcess` 的 `reset`、`step`、`generate` 状态语义；
- 独立 `numpy.random.Generator`；
- `StationaryPoissonDemand`；
- 最小需求过程工厂；
- 严格输入校验和统计测试。

WP-01A 的数据模型、随机性隔离和公共状态语义已冻结，WP-01B 原则上不得修改。

### WP-01B：当前阶段

只增加：

- Drifting Hotspot；
- Markov Switching；
- Burst Demand。

当前先执行只读设计分析，明确参数化、隐状态、工厂扩展、统计测试和 ID/OOD 边界。不得提前加入 WP-01C 功能。

### WP-01C：未开始

- 配置与工厂完善；
- 轨迹序列化；
- 命令行工具；
- 统计汇总；
- 可选可视化。

## 环境

### Mac

- Codex 桌面版在本地仓库主工作目录工作；
- 分支为 `main`，不创建额外 worktree；
- Conda 环境：`fura-mappo-mac`；
- 仅运行快速 CPU 测试。

### A100 服务器

- CPU：80 核级；
- 内存：502 GiB；
- GPU：2 × NVIDIA A100-SXM4-80GB；
- 驱动：590.48.01；
- Compute Capability：8.0；
- Conda：24.9.2；
- 项目环境：`fura-mappo`；
- Python：3.11.15；
- 系统 Python 2.7.18，不得使用；
- `nvcc` 当前不可用；
- `tmux`：2.9a。

WP-01 期间不安装 PyTorch、不修改 CUDA 或驱动、不执行 GPU 训练。

## 固定协作流程

```text
ChatGPT 制定研究设计和 Codex 任务
→ Codex 在 Mac 本地 main 修改并测试
→ Codex 在 Downloads 或 Desktop 生成完整补丁
→ 用户上传补丁
→ ChatGPT 独立应用、审查并复测
→ 有问题时 Codex 聚焦修复并重新上传
→ 审查通过后用户手工 Commit 和 Push main
→ A100 服务器 git pull --ff-only 并验收
→ 通过后更新状态和交接文档
```

不使用功能分支、额外 worktree、必需 PR 或必需 candidate 标签。Codex 不得 Commit、Push 或 Tag。完整规则见 `docs/CODEX_WORKFLOW.md`。

## 文档入口

- 文档索引：`docs/DOCUMENTATION_INDEX.md`
- 当前状态：`docs/PROJECT_STATE.md`
- 会话交接及 WP-01B 入口：`docs/SESSION_HANDOFF.md`
- 项目决策：`docs/DECISIONS.md`
- WP-01 总体需求规范：`docs/WP01_DEMAND_GENERATION.md`
- WP-01A 冻结规范：`docs/WP01A_SPEC.md`
- WP-01A 完成审查：`docs/WP01A_REVIEW.md`
