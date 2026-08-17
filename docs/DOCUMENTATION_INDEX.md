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

当前工作包是 WP-01C，当前仅进行只读设计分析。设计确认后再冻结配置、序列化、CLI、统计汇总和可视化接口，不能把候选格式写成已接受协议。

必须先读取：

- `docs/WP01_DEMAND_GENERATION.md`：WP-01 全局规范和 A/B/C 边界；
- `docs/WP01A_SPEC.md`：WP-01A 已冻结公共接口；
- `docs/WP01B_SPEC.md`：四类需求过程已冻结科学和配置语义；
- `docs/PROJECT_STATE.md`：已验证基线和当前待办；
- `docs/SESSION_HANDOFF.md`：WP-01C 只读分析入口；
- `configs/README.md`：配置目录当前边界；
- `docs/DECISIONS.md`：不可违反的项目决策。

## 3. 已完成工作包文档


### WP-01B

- `docs/WP01B_SPEC.md`：已冻结接口、过程定义和测试要求；
- `docs/WP01B_RUNBOOK.md`：已完成的实现、审查、发布和服务器验收流程；
- `docs/WP01B_REVIEW.md`：独立审查及最终验收记录；
- `CHANGELOG_WP01B.md`：WP-01B 已完成变更摘要。

### WP-01A 与历史基础

- `docs/WP01A_SPEC.md`：已冻结的 WP-01A 范围、接口和测试要求；
- `docs/WP01A_RUNBOOK.md`：已完成的实现、审查和验收流程；
- `docs/WP01A_REVIEW.md`：独立审查及最终验收记录；
- `CHANGELOG_WP01A.md`：WP-01A 已完成变更摘要；
- `CHANGELOG_WP00.md`、`docs/WP00_RUNBOOK.md`：WP-00 历史记录。

已完成工作包文档除勘误或追加最终证据外不重写历史范围。

## 4. 专用维护规则

- `SECURITY.md` 只在安全策略变化时更新；
- Desktop/Downloads 中的一键脚本是操作辅助，不是项目事实来源；事实仍以 Git、测试和仓库文档为准；
- `configs/README.md` 只描述配置目录边界，WP-01C 前不新增持久化需求配置；
- `docs/EXPERIMENT_LEDGER.csv` 只记录实际执行的正式实验，不记录计划；
- README 只保留概览，不堆叠完整工作包设计；
- 具体工作包应拥有独立规范、运行手册、审查记录或变更记录。

## 5. 状态真实性

文档必须区分：

1. 设计已确认；
2. Codex 已实现；
3. 补丁已独立审查；
4. Mac Python 3.11 验收已通过；
5. 已 Commit 并 Push；
6. A100 服务器验收已通过；
7. GitHub Actions 已通过；
8. 已形成稳定实现基线。

不得把本地补丁测试、独立容器复测或计划命令写成服务器已验收事实。无法获得逐行日志时，只记录实际确认的通过/失败结论，不补造测试数量。
