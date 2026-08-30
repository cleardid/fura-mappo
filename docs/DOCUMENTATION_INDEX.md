# 文档索引与维护规则

## 权威文档

- `README_zh.md`：项目总览
- `docs/PROJECT_REQUIREMENTS.md`：总体要求
- `docs/RESEARCH_PLAN.md`：科学路线
- `docs/PROJECT_STATE.md`：当前事实
- `docs/SESSION_HANDOFF.md`：会话交接
- `docs/CODEX_WORKFLOW.md`：协作流程
- `docs/DECISIONS.md`：关键决策
- `docs/EXPERIMENT_LEDGER.csv`：正式实验执行账本
- `docs/ANALYSIS_PLAN.md`：统计原则
- `docs/PREDICTION_PROTOCOL.md`：WP-03A prediction interface/dataset 冻结协议
- `docs/PREDICTION_BASELINE_PROTOCOL.md`：WP-03B prediction baseline/evaluation scientific 冻结协议

## 当前工作包

WP-02D Primary gate 已在 execution/provenance HEAD
`0b0742f51d59c2a8aa63614993e51131016cd33c` 上以 `SCIENTIFICALLY ACCEPTED PASS` 关闭：256/256
traces valid；formal sensitivity 未执行。WP-02D1 protocol/statistics baseline、WP-02D2
`bounded task-target root-information exhaustive diagnostic verifier`、WP-02D3
`Formal H1 execution orchestration / persistence hardening` 与 WP-03 Slice 1–17 均已完成并接受；
`WP-03 IMPLEMENTATION CLOSED`。该 engineering acceptance 不是 predictor/control scientific
evidence；没有执行真实 official prediction experiment，没有发生 FIRST OFFICIAL TEST EXECUTION，
test sets 仍为 UNSPENT。协议继续区分 TRAINING_FAILURE、
PREDICTION_MODEL_SELECTION_FAILURE、PREDICTION_BASELINE_SELECTION_FAILURE 与
PREDICTION_EVALUATION_FAILURE；Layer A pre-training freeze 早于全部 fitting/training/validation/
selection，Layer B pre-test freeze 不得改 Layer A。任何 executed P 的 B5 必须覆盖全部 required
`t+h`；P=2/P=4/P=8 各用独立 protocol/SHA/records，secondary failure 不影响 Primary。First
official test action 使 exact test_id/test_ood 成为 spent sets，failure recovery 必须使用满足 WP-03A
global disjointness 的 fresh unexposed tests 与新 manifest/provenance；spent sets 只可 audit/debug，不可重用于
official result 或 selection。当前阶段精确为
`WP-03 Official Prediction Experiment Specification Freeze`，只允许 read-only scientific
design/freeze。该 spec 完成独立 review、用户手动 Commit/Push 与 GitHub Actions acceptance 前，不得
生成 official prediction dataset、训练 predictor 或执行 official test；Formal H1 PASS 不构成 WP-03
official execution authorization。

WP-03A accepted implementation Commit 为 `13cb39933ac65926332ca6c528ef271e1c739aa5`，approved
review patch SHA-256 为 `5f5be8109784a5783caefc1e129edf2f2deb53aa52379b8be0c2c4120f8384b9`；
独立 review 为 BLOCKER 0、MAJOR 0、MINOR 0，GitHub Actions passed。

优先读取：

- `docs/PROJECT_STATE.md`
- `docs/SESSION_HANDOFF.md`
- `docs/RESEARCH_PLAN.md`
- `docs/ANALYSIS_PLAN.md`
- `docs/DECISIONS.md`
- `docs/PREDICTION_PROTOCOL.md`
- `docs/PREDICTION_BASELINE_PROTOCOL.md`
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

## WP-03A 已接受文档与实现

- `docs/PREDICTION_PROTOCOL.md`
- `src/fura_mappo/prediction/`
- `tests/test_prediction_*.py`

## WP-03 IMPLEMENTATION CLOSED

- `docs/PREDICTION_BASELINE_PROTOCOL.md`
- `docs/DECISIONS.md` D-040

D-040 frozen scientific protocol 继续完全有效；WP-03 Slice 1–17 engineering implementation 已
accepted。该 closure 不构成 prediction、control、uncertainty 或 MAPPO 科学结果。

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
