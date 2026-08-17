# 文档索引与维护规则

## 1. 权威文档

| 文档 | 作用 | 何时更新 |
|---|---|---|
| `README_zh.md` | 项目总览、当前阶段和快速入口 | 阶段变化时 |
| `docs/PROJECT_REQUIREMENTS.md` | 总体研究和工程要求 | 总目标或固定约束变化时 |
| `docs/RESEARCH_PLAN.md` | 科学问题、比较框架和研究路线 | 研究设计变化时 |
| `docs/PROJECT_STATE.md` | 当前事实、Commit、测试和待办 | 每个验收节点 |
| `docs/SESSION_HANDOFF.md` | 下一会话恢复上下文 | 每次会话结束 |
| `docs/CODEX_WORKFLOW.md` | Codex、用户、独立审查和服务器流程 | 协作流程变化时 |
| `docs/DECISIONS.md` | 已接受、修订或撤销的关键决策 | 决策形成时 |
| `docs/ANALYSIS_PLAN.md` | 统计分析原则和冻结项 | 实验协议演进时 |
| `docs/PAPER_OUTLINE.md` | 论文论证结构 | 研究问题或实验结构变化时 |
| `docs/WORK_PACKAGE_TEMPLATE.md` | 工作包定义和验收模板 | 流程或字段变化时 |

## 2. 当前工作包文档

- `docs/WP01_DEMAND_GENERATION.md`：WP-01 全局需求生成规范和 A/B/C 边界。
- `docs/WP01A_SPEC.md`：WP-01A 冻结范围、接口和测试要求。
- `docs/WP01A_RUNBOOK.md`：WP-01A 合入、Mac 验收、提交和服务器验收手册。
- `docs/WP01A_REVIEW.md`：当前补丁的独立审查记录。
- `CHANGELOG_WP01A.md`：WP-01A 候选变更摘要。

后续 WP-01B、WP-01C 应建立对应规范或变更记录，不应把所有阶段细节持续堆叠在 README 中。

## 3. 历史文档

以下文件主要保存历史事实，除勘误或补充最终验收结果外不应重写：

- `CHANGELOG_WP00.md`
- `docs/WP00_RUNBOOK.md`

`SECURITY.md` 只在安全策略变化时更新。`docs/EXPERIMENT_LEDGER.csv` 只记录实际执行的正式实验，不记录尚未运行的计划。

## 4. 状态真实性

文档必须区分以下状态：

1. 设计已确认；
2. Codex 已实现；
3. 补丁已独立审查；
4. Mac Python 3.11 验收已通过；
5. 已 Commit 并 Push；
6. A100 服务器验收已通过；
7. GitHub Actions 已通过；
8. 已形成稳定基线。

不得把本地补丁测试、独立容器复测或计划执行的命令写成服务器已验收事实。
