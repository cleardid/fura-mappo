# FURA-MAPPO Codex 协作规范

本文件适用于仓库根目录及全部子目录。具体工作包中的约束如更严格，以工作包为准。

## 当前阶段

- 研究目标：非平稳时空需求下，研究未来需求预测及不确定性对多智能体主动资源预置的价值。
- `WP-01` 外生需求生成系统已完成。
- WP-01 稳定实现：`29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`，标签 `wp01c-stable`。
- WP-02A/B/C/D1/D2/D3 已完成并接受；Formal H1 science 尚未执行。
- `WP-03 IMPLEMENTATION CLOSED`；accepted implementation：
  `55dd9ef5f951d9328266b8e331ba5ae68854b414`。
- WP-03 Slice 1–17 engineering implementation 已接受，但没有真实 WP-03 scientific result。
- Formal H1 scientific gate 尚未执行；Formal primary traces 为 `0/256`，artifact root absent。
- `55dd9ef5...` 只是已接受的 WP-03 implementation/code-content reference；它不是将传给 Formal H1
  provenance gate 的 final refrozen execution SHA，也不是 Formal H1 execution authorization。
- 当前下一阶段：`Formal H1 execution-provenance refreeze and non-executing readiness audit`。
- WP-03B official predictors/baselines 必须是 deterministic、stateless、跨调用无 persistent state，
  且只能读取 WP-03A 冻结的有限 causal `PredictionContext` 与 immutable fitted artifact。
- Official predictor science、WP-03 official experiment、`FIRST OFFICIAL TEST EXECUTION`、真实
  `SPENT` transition、uncertainty 实验、MAPPO、PyTorch/GPU scientific workload 与 ID/OOD 主实验
  继续锁定。
- 未取得用户 explicit authorization 前不得执行 Formal H1；不得机械运行旧 Formal H1 command 或
  正式 seeds。

## 开发环境

- 正式 Python：3.11。
- Mac Conda：`fura-mappo-mac`。
- A100 Conda：`fura-mappo`。
- A100 系统 Python 2.7 不得使用。
- GPU/大型实验只由用户在服务器明确启动。

## 科学与代码规范

- 英文标识符；中文 Docstring 和关键算法说明。
- 公共接口必须有类型标注。
- NumPy 数组必须说明 shape，必要时注明 dtype。
- 随机过程使用实例独立 `numpy.random.Generator`。
- 不污染 NumPy 全局 RNG。
- 不使用可变默认参数、隐藏全局状态或 `assert` 校验用户输入。
- WP-01 已冻结的需求数据模型、四类过程、状态机、YAML/config hash、artifact v1、summary v1 和 CLI 协议在后续工作包中视为兼容性边界。
- 环境只能消费外生需求，不能反向影响需求过程。
- 在 Oracle 价值门槛验证前，不冻结最终 MAPPO reward 权重。

## Git 与审查

- 单人 `main-only`；不创建功能分支、额外 worktree 或必需 PR。
- Codex 不得 Commit、Push、Tag、Merge、Rebase、Reset、Clean、Stash 或 force push。
- 候选实现必须生成完整 patch 和报告到 Downloads/Desktop。
- 用户上传 patch，ChatGPT 独立审查；通过后才发布。
- 用户确认的一键脚本可以执行核对、测试、标签、Commit、Push 和服务器同步。
- 已推送错误只用追加修复 Commit 或 `git revert`。
