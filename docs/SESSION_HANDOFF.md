# 会话交接

更新日期：2026-08-17

## 1. 当前任务

WP-01B：三类非平稳外生需求过程。

当前阶段仅为 **只读设计分析**。设计审查通过前不得修改源码、创建补丁、Commit 或 Push。

## 2. 稳定基线

```text
仓库：https://github.com/cleardid/fura-mappo
分支：main
WP-01A 实现 Commit：b7b48bb394bd4613652b4d1ff4158cb8503f52a5
稳定标签：wp01a-stable
标签目标：b7b48bb394bd4613652b4d1ff4158cb8503f52a5
前序稳定标签：wp00-stable
```

文档收尾 Commit 以仓库当前 `HEAD` 为准，不在文档中自引用 SHA。

## 3. WP-01A 完成结论

- 核心数据模型、状态接口、平稳 Poisson 和工厂已实现；
- 独立补丁审查无阻断问题；
- 最终实现已推送到 `main`；
- GitHub Actions `CPU checks` run #3 成功；
- A100 CPU 与专项验收由用户确认全部通过；
- WP-01A 已正式关闭；
- WP-01A 接口和状态语义在 WP-01B 中视为冻结。

## 4. WP-01B 唯一范围

只设计和实现：

- Drifting Hotspot；
- Markov Switching；
- Burst Demand。

必须继续满足：

- 外生性；
- 实例独立 `numpy.random.Generator`；
- 复用 `DemandEvent`、`DemandStep`、`DemandTrace`；
- 复用 `DemandProcess.reset/step/generate` 语义；
- 每步 counts 与 events 完全一致；
- 工厂不修改调用方配置；
- 固定 seed 的可复现统计测试；
- CPU-only。

不得实现：

- YAML、NPZ、CSV、JSON；
- CLI、统计汇总或绘图；
- PettingZoo、智能体、服务、奖励；
- 预测模型、MAPPO、PyTorch 或 GPU；
- 并行化和性能框架。

## 5. WP-01B 只读分析必须读取

```text
AGENTS.md
pyproject.toml
docs/PROJECT_REQUIREMENTS.md
docs/PROJECT_STATE.md
docs/DECISIONS.md
docs/SESSION_HANDOFF.md
docs/CODEX_WORKFLOW.md
docs/WP01_DEMAND_GENERATION.md
docs/WP01A_SPEC.md
src/fura_mappo/demand/
src/fura_mappo/utils/seeding.py
tests/test_demand_models.py
tests/test_stationary_demand.py
tests/test_demand_factory.py
tests/test_seeding.py
```

## 6. WP-01B 只读分析必须报告

1. 当前 Commit、分支和工作树；
2. WP-01A 公共接口与可复用内部扩展点；
3. 三类过程各自的最小科学定义；
4. 参数、数组形状、值域和必需校验；
5. 隐状态如何随 `reset`、`step`、`generate` 演化；
6. 是否需要新增基类钩子，以及如何避免破坏 WP-01A；
7. 工厂类型名称和严格配置字段；
8. ID/OOD 参数边界建议；
9. 固定 seed、统计容差和低偶发失败测试；
10. 推荐文件范围；
11. 过度设计、性能和兼容性风险；
12. 需要 ChatGPT 决策的问题。

不得在只读阶段写实现代码或修改文件。

## 7. 固定协作流程

```text
Codex 只读分析
→ ChatGPT 设计审查
→ Codex 聚焦实现和 Mac 测试
→ Codex 在 Downloads/Desktop 生成完整 patch
→ 用户上传
→ ChatGPT 独立应用、审查和复测
→ 用户手工 Commit/Push
→ A100 同步验收
→ 状态收尾
```

## 8. 下一会话开场模板

```text
项目：FURA-MAPPO
仓库：https://github.com/cleardid/fura-mappo
当前分支：main
当前 Commit：<git rev-parse HEAD>
稳定标签：wp01a-stable

请先读取：
- AGENTS.md
- docs/PROJECT_STATE.md
- docs/DECISIONS.md
- docs/SESSION_HANDOFF.md
- docs/WP01_DEMAND_GENERATION.md
- docs/WP01A_SPEC.md
- src/fura_mappo/demand/
- tests/

本会话目标：仅完成 WP-01B 只读设计分析，不修改文件。
```
