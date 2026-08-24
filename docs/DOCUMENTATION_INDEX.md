# 文档索引与维护规则

## 权威文档

- `README_zh.md`：项目总览
- `docs/PROJECT_REQUIREMENTS.md`：总体要求
- `docs/RESEARCH_PLAN.md`：科学路线
- `docs/PROJECT_STATE.md`：当前事实
- `docs/SESSION_HANDOFF.md`：会话交接
- `docs/CODEX_WORKFLOW.md`：协作流程
- `docs/DECISIONS.md`：关键决策
- `docs/ANALYSIS_PLAN.md`：统计原则
- `docs/PREDICTION_PROTOCOL.md`：WP-03A prediction interface/dataset 冻结协议

## 当前工作包

WP-02D overall 进行中且 Formal H1 尚未运行。WP-02D1 protocol/statistics baseline、WP-02D2
`bounded task-target root-information exhaustive diagnostic verifier` 与 WP-02D3
`Formal H1 execution orchestration / persistence hardening` 均已完成并接受。服务器不可用期间当前
工作包为 WP-03A Prediction Interface & Dataset Protocol implementation/review；只允许基础设施、
CPU tests 与 tiny smoke，不解锁 official prediction science 或 MAPPO。Formal primary traces 为
`0 / 256`。服务器恢复后必须同步 latest accepted main、重新冻结 Formal H1 execution provenance、
完成 readiness preflight 并取得用户明确授权。

当前是 candidate v4：v3 独立复审的 signed-zero intrinsic-hash MAJOR 与 D-039 stale wording MINOR
已定向修复；realized positions/priority 的 `+0.0`/`-0.0` 现在具有相同 hash，真实非零差异保持可辨，
仍待新的完整 patch 独立复审。

优先读取：

- `docs/PROJECT_STATE.md`
- `docs/SESSION_HANDOFF.md`
- `docs/RESEARCH_PLAN.md`
- `docs/ANALYSIS_PLAN.md`
- `docs/DECISIONS.md`
- `docs/PREDICTION_PROTOCOL.md`
- `docs/WP02D_SPEC.md`
- `CHANGELOG_WP02D1.md`
- `CHANGELOG_WP02D2.md`
- `CHANGELOG_WP02D3.md`
- `docs/WP02A_SPEC.md`
- `docs/WP02B_SPEC.md`
- `docs/WP02C_SPEC.md`
- `CHANGELOG_WP02C.md`
- `CHANGELOG_WP02B.md`
- `src/fura_mappo/envs/`
- `src/fura_mappo/baselines/`

## WP-03A 当前文档

- `docs/PREDICTION_PROTOCOL.md`
- `src/fura_mappo/prediction/`
- `tests/test_prediction_*.py`

## WP-02 完成文档

### WP-02D3

- `docs/WP02D_SPEC.md`
- `CHANGELOG_WP02D3.md`：记录 D3 execution/persistence hardening、独立 review、CI/A100 CPU
  acceptance、accepted implementation SHA 规则与 Formal H1 未执行状态

### WP-02D2

- `docs/WP02D_SPEC.md`
- `CHANGELOG_WP02D2.md`

### WP-02D1

- `docs/WP02D_SPEC.md`
- `CHANGELOG_WP02D1.md`

### WP-02C

- `docs/WP02C_SPEC.md`
- `CHANGELOG_WP02C.md`

### WP-02B

- `docs/WP02B_SPEC.md`
- `CHANGELOG_WP02B.md`

### WP-02A

- `docs/WP02A_SPEC.md`
- `CHANGELOG_WP02A.md`

## WP-01 完成文档

### WP-01C
- `docs/WP01C_SPEC.md`
- `docs/WP01C_RUNBOOK.md`
- `docs/WP01C_REVIEW.md`
- `CHANGELOG_WP01C.md`

### WP-01B
- `docs/WP01B_SPEC.md`
- `docs/WP01B_RUNBOOK.md`
- `docs/WP01B_REVIEW.md`
- `CHANGELOG_WP01B.md`

### WP-01A
- `docs/WP01A_SPEC.md`
- `docs/WP01A_RUNBOOK.md`
- `docs/WP01A_REVIEW.md`
- `CHANGELOG_WP01A.md`

已完成工作包文档除勘误外不重写历史范围。
