# 统计分析计划

状态：WP-02D1 primary H1 gate、WP-02D2 bounded diagnostic verifier 与 WP-02D3 Formal H1
execution hardening 均已完成并接受。`WP-03 IMPLEMENTATION CLOSED`：WP-03 Slice 1–17
implementation 已 accepted，WP-03 accepted implementation Commit 为
`55dd9ef5f951d9328266b8e331ba5ae68854b414`（`feat: close WP-03B official evaluation
orchestration`），GitHub Actions CPU checks run #40 为 `completed / success`。formal data 尚未生成，
formal H1 尚未运行；该 engineering acceptance 不是 predictive/control evidence。当前不启动任何
official predictor、forecast-control、uncertainty、ID/OOD 或 MAPPO scientific analysis。

## 第一科学门槛

```text
ReactiveController
vs
RollingTrueFutureOracle (Primary H=2)
```

实验单位是一条预注册 seed 产生的 `DemandTrace`。Reactive 与 Oracle 必须使用同一个内存
trace、相同环境配置和独立环境实例；仅 information set/controller 不同。Oracle future view
必须由 official `build_true_future_view()` 构造。

## 冻结 Primary stress cell

- `DriftingHotspotDemand`
- 四个连续 1×1 zones：`x in [0,4]`、`y in [0,1]`
- `base_intensities=[0.025,0.025,0.025,0.025]`
- `hotspot_amplitudes=[0.55]`，`hotspot_scales=[0.45]`
- initial hotspot `(0.5,0.5)`，velocity `(0.25,0.0)`
- `priority_range=[0.5,0.5]`
- `service_time_range=[1,2]`，`deadline_offset_range=[2,3]`
- 256 steps；2 resources at `(0.5,0.5)` and `(3.5,0.5)`
- `movement_speed=0.75`

## 冻结 Primary outcome 与 estimand

对 trace i，两侧必须满足相同 arrived count `A_i`：

```text
A_i > 0:
    D_i = (completed_oracle - completed_reactive) / A_i
A_i == 0:
    D_i = 0
```

Primary estimand 为 `mean_i(D_i)`。每条 trace 等权；禁止 ratio-of-total-counts、priority
reward、best-seed subset，或删除/替换 zero-arrival seed。

## 冻结 seeds、bootstrap 与 gate

```text
Primary H = 2
N = 256
seeds = 20260819..20261074
paired resampling unit = trace
resamples = 50000
Generator = numpy.random.Generator(PCG64(90260819))
bootstrap method = percentile
np.quantile method = linear
one-sided LCB = 5% quantile
one-sided UCB = 95% quantile
two-sided interval = [2.5%, 97.5%]
delta_min = 0.02 absolute completion fraction
```

```text
PASS:
    point_estimate >= 0.02 and one_sided_lcb > 0

FAIL:
    not PASS and one_sided_ucb < 0.02

INCONCLUSIVE:
    all other valid results

PROTOCOL_FAIL:
    any protocol violation; not a scientific inference result
```

Secondary metric、H sensitivity 或其他 sensitivity 不得改变 primary verdict。H metadata 为
0/1/2/3/4；H=0 是逐 step/action/result/terminal-metrics 精确相等的 hard protocol invariant，
不是 superiority sensitivity。

## 配对诊断与 secondary metrics

Primary verdict 只读取 `D_i`。每条 trace 另保存完整 `EpisodeMetrics`，aggregate 分别报告：

- completed 与 completion rate
- expired/expiration rate、truncated/truncation rate
- completed priority sum
- service/movement/idle slots 与 movement distance
- mean service-start wait 与 mean completed response
- duplicate assignment conflicts 与 zero-distance moves

同时报告 same-state counterfactual opportunity/action-difference/preposition diagnostics 与 realized
Oracle pre-arrival movement diagnostics。服务改善与移动成本分开，不组合成 reward。

## Formal protocol 与 audit chain

正式 evaluator 必须严格验证 exact 256 records、seed 集与顺序、H=2、两侧 arrived 相等、finite
differences、无 protocol failure，以及每条 result 的 spec/artifact/environment provenance。

```text
validated H1 spec
-> experiment_spec_sha256
-> exact planned artifacts
-> provenance-bound NPZ artifacts
-> frozen ArtifactInventory
-> artifact_inventory_sha256
-> strict artifact readback
-> H=0 invariant
-> canonical mechanism preflight
-> provenance-bound PairedTraceResult
-> strict paired JSONL readback
-> paired_results_sha256
-> recomputed H1GateSummary
-> strict aggregate readback
-> locked primary verdict
-> strict verdict readback
-> optional sensitivity unlock guard
```

Verdict 必须绑定 exact spec/inventory/results/provenance；formal sensitivity 必须重新验证该完整
链，旧 verdict 不能解锁另一组 results。任何生成、读取、hash、配对或 provenance 失败均 hard
fail，不得删除 seed、替换 seed 或静默排除。

## Formal execution governance

WP-02D3 历史 accepted implementation SHA 为
`1092d9c87bfff8ba6c1f2132734480112d7b5975`。其 private runner 调用作为历史 execution checkpoint
记录如下，但 WP-03A source changes 后不得在 latest main 上直接执行：

```bash
python -m fura_mappo.experiments._formal_h1_runner \
  --accepted-implementation-sha 1092d9c87bfff8ba6c1f2132734480112d7b5975
```

本阶段不执行。runner 固定使用 `configs/experiments/wp02d_h1.yaml` 与唯一 formal root
`artifacts/wp02d_h1_formal_v1/`，并固定 `traces/`、artifact inventory、primary paired JSONL、
aggregate 与 verdict 路径。不存在第二套 formal evidence path。

`55dd9ef5f951d9328266b8e331ba5ae68854b414` 是已接受的 WP-03 implementation/code-content
reference；它不是将传给 Formal H1 provenance gate 的 final refrozen execution SHA，也不是 Formal H1
execution authorization。下一阶段精确为
`Formal H1 execution-provenance refreeze and non-executing readiness audit`，未来允许顺序精确为：

```text
sync latest accepted main
-> refreeze exact Formal H1 execution provenance against that accepted HEAD
-> server non-executing readiness audit
-> explicit user authorization
-> Formal H1 execution
```

在 explicit user authorization 前不得执行最后一步。Refreeze 后，必须在执行前及关键 publication
边界验证真实 repo root、`main`、clean working tree、HEAD/origin、accepted implementation/WP-02C
ancestry 与实际 loaded code path。重新冻结 execution provenance 不得改变 H1 science 或下列科学
identities。

Restart/resume 必须是 provenance-bound、strict、no-overwrite：inventory 已存在时不生成 trace；
inventory 不存在时只复用严格有效的既有 trace，缺失 trace 才可在重新验证 provenance 后生成
exactly once；invalid、missing、unknown 或 symlink evidence hard fail，不自动修复、删除或替换。
paired JSONL、aggregate 与 verdict 均 strict canonical readback，disk aggregate 必须等于从 strict
paired results 重新计算的 summary。`PROTOCOL_FAIL` verdict 可 strict read，但不能通过 sensitivity
unlock guard。

Protocol JSON/JSONL、NPZ no-overwrite 与首次 formal directory creation 均包含 parent-directory
fsync durability。这些 execution/persistence controls 不改变本计划冻结的 hypothesis、estimand、
bootstrap、gate 或 scientific identities。H1 spec SHA-256 继续为
`fc719e4634ab13ba55d0b95e63497688b3ab07c259d1421c5ed0c468cec3fade`，Primary environment
config SHA-256 继续为
`d1d856b13ac8edf79422428a96bddc03b901053dbeaabe56571e9baeef6eafa1`。

## Negative-result 诊断

Primary 不 PASS 时，依次检查 H=0、canonical mechanism、load/opportunity diagnostics、统计
precision，最后运行预注册 WP-02D2 bounded verifier suite。Accepted implementation Commit 为
`cfab8c1b1981ef095d68969fff74faa2ac4f256d`。该 verifier 是 bounded、task-target、
root-information、diagnostic-only exhaustive search，不是 formal baseline、global optimum、
continuous-control optimum、theoretical upper bound、optimal policy 或 Primary adequacy proof。

Verifier 每个真实 boundary 冻结
`K = current active tasks + official H-step future view events`，以真实环境 public `reset()` /
`step()`、fresh environment 与 deterministic prefix replay 穷举到 episode terminal。有限动作只指向
frozen K；唯一 objective 是 maximize completed count over K，tie 仅 lexicographically minimize
canonical complete sequence key。Verifier miss 只能阻止把 negative result 解释为“未来信息没有
价值”，不能把 primary verdict 改成 PASS；verifier output 不进入 formal primary verdict 输入。

冻结 handcrafted fixture unit-test expectations 为：

```text
        Primary    Verifier
F1         1           1
F2         1           2
F3         1           2
F4         1           2
F5         0           0
F6A        1           1
F6B        1           1
```

这些 fixture 结果不是 Formal H1 outcome 或 formal primary evidence。任一 fixture 的 verifier
completed > Primary completed 时，diagnostic label 为 `PRIMARY_HEURISTIC_MISS_DETECTED`；否则为
`NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE`。第二个 label 不表示 Primary
optimal 或 heuristic adequacy proven，两个 label 均不能改变冻结 primary verdict。

## WP-03B predictive analysis protocol

权威定义见 `docs/PREDICTION_BASELINE_PROTOCOL.md`。Primary horizon 为 P=2；P=4/8 只能作为独立、
预注册、不能 rescue P=2 的 secondary protocols。History candidate grid 为 L={4,8,16,32}，只用
train/validation 选择，相同 validation score 选择更短 L。

对 trace `i`、lead `h`、zone `z`，以 `A_i,h` 表示该 lead 有效 anchors：

```text
MSE[i,h,z] = mean over t in A_i,h of
    (prediction_mean[i,t,h,z] - target_count[i,t,h,z])^2

Primary MSE = mean_i mean_h mean_z MSE[i,h,z]
Primary RMSE = sqrt(Primary MSE)
```

因此 complete trace 是科学单位，trace、official horizon、zone 各自等权，只有 trace 内 anchors 先
平均；zero targets/zero-demand traces 不删除。Sample-cell weighted RMSE 仅为 volume-weighted
diagnostic。Official secondary metrics 只有同权 MAE 与 signed mean bias (`prediction-target`)；必须
报告 per horizon、zone、trace distribution、zero/positive target、condition、ID/near-OOD/structural-
OOD 与 training seed breakdown。WAPE、sMAPE、MASE、Poisson deviance 不进入 official inferential set。

Learned objective candidates 只有 O0 masked raw-scale MSE 与 O1 masked Poisson NLL/quasi-likelihood，
均使用 trace/horizon/zone-equal weighting。Objective/transform/L/architecture/hyperparameter config
统一按下述 `Validation Algorithm RMSE` 与后述唯一 total order 选择；objective rank 为 O0<O1。
T0/T1 只作用于
`history_counts` count values：T0 为 identity，T1 为 elementwise log1p，padding zero 保持 0；
history mask、absolute step、steps remaining、zone identity、prediction horizon、target 与 output 均不
transform。允许的 non-count fields 如何编码必须在未来 model config 中预冻结并进入 identity。Metric
永远在 raw counts 上计算；不使用 target log、per-zone fitted standardization、test adaptive scaling、
rounding 或 test-time clipping。

Operational baseline hierarchy 为 B0 Zero、B1 Persistence、B2 masked context mean、B3 EWMA、B4
static train climatology 与 B5 absolute-step train climatology。B2 在 L={4,8,16,32} 中按 lower
validation Primary RMSE、shorter L 锁定。B3 在 L={4,8,16,32} 与
alpha={0.25,0.50,0.75} 完整 Cartesian product 中按 lower validation Primary RMSE、shorter L、
smaller alpha 锁定。B2/B3 selected L 必须对应明确 `DatasetProtocolSpec`/SHA，并连同 B3 alpha
进入 provenance。

`B*` 使用 two-stage rule：先分别锁定 B0/B1 fixed、B2 selected L、B3 selected (L,alpha)、B4/B5
train-fitted artifacts，再按 validation Primary RMSE 比较六个 locked variants；tie 顺序为
`B0 < B1 < B2 < B3 < B4 < B5`。Test_id/test_ood 不得改变 internal variant 或重选 B*。B4 对每条
train trace 先按 unique steps 求 zone mean，再跨 traces 等权；B5 对 supported absolute step/zone
跨 train traces 等权。两者只由 train 拟合 immutable artifacts。

Baseline selection 前必须 preflight train/validation/test_id/test_ood absolute-step forecast support；对
任意正式执行 P，B5 train-fitted table 必须覆盖每个 required valid `(t,h)`、`h in 1..P` 的 `t+h`。
Primary P=2 与各自独立 `DatasetProtocolSpec`/SHA 的 secondary P=4/P=8 使用同一 invariant；secondary
support failure 不 alter/rescue/invalidate 有效 Primary result。任一 B0–B5 locked
variant 不能在完整 validation set 产生 complete finite valid forecasts 时，或 preflight 发现任一
required support gap 时，状态为
`PREDICTION_BASELINE_SELECTION_FAILURE`：没有 B*，不得删除 baseline、缩小/renormalize hierarchy、
赋 penalty 或 fallback，也不得进入 official test/scientific label。Preflight 通过并锁定后，official
test 执行/readback 时出现 support 缺失才进入 `PREDICTION_EVALUATION_FAILURE`。Point calibration
empty/sealed，不参与 B5 selection。

Layer A `PRE-TRAINING DATA/SEARCH FREEZE` 必须先于 B4/B5/statistics fitting、learned training、任何
validation forecast/metric、early stopping、B2/B3/B*/objective/transform/L/model selection。它锁定
ZoneSchema、全部将执行的 DatasetProtocolSpecs、source inventory、DatasetSplitManifest、各 split 的
exact membership/canonical order、calibration disposition、trace/seed/content/realized/condition
identities、ID/OOD assignment、training seeds/RNG、candidate schema/search/complexity/order、grids、
budget 与 stopping rules。Activity 开始后禁止 move/add/remove/replace trace/seed 或改变 split、
calibration、test membership、OOD assignment、protocol/inventory。Before-activity invalid freeze 可 STOP
并建立 new explicit version；activity 后发现 error 则当前 experiment development/protocol failure，必须
以新 identity 从 fitting/training/model selection 起点重启，不继承 numerical result。

所有 learned candidate configs 使用同一预冻结、至少 3 个 distinct training seeds。每个 config 的
每个 seed 独立训练，并只按该 run 自身 validation Primary RMSE 执行 frozen early-stopping/checkpoint
rule。Checkpoint 锁定后计算 `Validation MSE_r`，config score 唯一定义为：

```text
Validation Algorithm MSE = mean_r(Validation MSE_r)
Validation Algorithm RMSE = sqrt(Validation Algorithm MSE)
```

禁止以 `mean_r(RMSE_r)` 代替。Test point estimate 对 locked config 定义为
`Test Algorithm RMSE = sqrt(mean_r(Test MSE_r))`；learned side 不是 best seed、mean per-seed RMSE 或
ensemble forecast。任一 fixed seed 缺失/crash、无 valid checkpoint、forecast/MSE nonfinite 或未通过
deterministic validation 时，config 为 `TRAINING_FAILURE`：没有 Validation Algorithm RMSE，不进入
numerical ranking 或 official test；不得删除/替换 seed、平均剩余 seeds、填 0/penalty 或 test 后
重训。所有 configs 均失败时状态为 `PREDICTION_MODEL_SELECTION_FAILURE`，不构造 scientific result，
且不与 Formal H1 `PROTOCOL_FAIL` 混用。Failure reason 必须记录。Train 只做 fitting/update，
validation 只做 selection/stopping，point-track calibration empty/sealed，test_id/test_ood 对相同 locked
predictors 在同一个 sealed phase 做 one-shot evaluation。

Test_id primary comparison 定义
`Delta_RMSE = Test Algorithm RMSE - B* RMSE`。Paired whole-trace cluster percentile bootstrap 的
replicate `b` 对 learned 所有 fixed-seed runs 与 B* 复用同一 trace indices；逐 seed 重算
`MSE_r^(b)`，再计算 `Algorithm RMSE^(b) = sqrt(mean_r(MSE_r^(b)))`、同一 sample 的
`B*_RMSE^(b)` 与两者差。CI 从 replicate differences 构造。Bootstrap 只 resample test traces，
training-seed set 固定；因此 CI 是 conditional on preregistered finite seed set 的 test-trace sampling
uncertainty，不完整量化 training stochasticity。Per-seed MSE/RMSE 与 dispersion 单独报告，不改变
Primary point estimate/CI。禁止 window/cell/scenario/best-seed bootstrap 或在 primary bootstrap 内
resample training seeds。Prediction bootstrap 使用独立 PCG64 namespace，不复用 H1 的 50,000
resamples 或 seed `90260819`；exact resamples/seed/quantile method 必须早于 official evaluation 冻结。
OOD 不能 rescue ID Primary result。

有效 Primary ID prediction comparison 使用 `Delta_RMSE` 与 `[CI_L,CI_U]` 唯一解释：

```text
LEARNED_BETTER: Delta_RMSE < 0 AND CI_U < 0
LEARNED_WORSE: Delta_RMSE > 0 AND CI_L > 0
NO_CLEAR_DIFFERENCE: otherwise
```

没有 practical-effect delta；raw effect size/CI 必须报告。NO_CLEAR_DIFFERENCE 不表示等价；
horizon/zone/secondary/OOD/control 均不能改变 Primary ID label。该 label 只描述 prediction error，
不是 Formal H1 verdict、control gate 或 MAPPO gate。

Official sealed test_id/test_ood phase 只有在 exact locked trace sets/order、fixed checkpoint set、B*、
DatasetProtocolSpec/SplitManifest/ZoneSchema identities 全部匹配，且每个 required valid anchor/horizon/
zone 都有 complete finite valid/bound forecast、finite metric/bootstrap inputs、无 missing/duplicate record
时才有效。任一 missing/duplicate trace/checkpoint/record、readback/identity/binding failure、invalid
context/forecast、NaN/Inf 或 incomplete metric/bootstrap input 都触发
`PREDICTION_EVALUATION_FAILURE`。此时没有 official Test Algorithm MSE/RMSE、B* point comparison、
Delta/CI 或任何 scientific label；必须记录 reason。不得 drop/exclude/replace/impute/fallback、平均
remaining seeds 或以 smaller n 继续；zero-demand observation 合法。Sealed phase failure 后不得修改
pipeline 伪装 first rerun；新正式 evaluation 必须有新的 explicit protocol/version/provenance。

Layer B `PRE-TEST EXECUTION FREEZE` 必须先于 first official test，锁定 B*、B2/B3 variants、selected
learned config、全部 checkpoints、exact test identities/order、metric/bootstrap implementation/plan、
final OOD cells 与 Git/runtime provenance，且不能改变 Layer A。第一次 official forecast generation、
target/result evaluation、metric/bootstrap computation 或 scientific readback 即触发 `SPENT TEST SET`；
pure structural metadata preflight 不触发。无论 success/failure/partial failure，exact test_id/test_ood
sets 都不能再次成为 one-shot scientific set。Failure 后保留 failure/spent identities；旧 sets 仅用于
audit/debug，不得迁入 train/validation、用于 selection/recovery protocol，或产生 replacement label/CI。
未来 official recovery 必须用 previously unexposed test sets，满足 WP-03A trace_id/seed/content SHA/
realized_trace_sha256 disjointness 与 condition/OOD rules，并建立新 manifest/protocol/provenance。

Learned config 只能由 `Validation Algorithm RMSE` 选择，B* 只能由 deterministic validation baseline
Primary RMSE 选择。VALID learned configs 的唯一 total order 为 lower Validation Algorithm RMSE、
lower predeclared model-complexity key、shorter L、O0<O1、T0<T1、canonical config ordering。
Model-complexity key、candidate schema/search space、canonical serialization/final ordering 必须在任何
candidate training 前冻结并进入 config identity。两者都不能读取 control、Oracle 或 MAPPO outcome。
所有 inference 必须是当前
有限 `PredictionContext` 与 immutable fitted artifact 的 pure, stateless function，且 official WP-03B
不启用 intensity diagnostic。Scientific identities/config/checkpoint hashes 必须在 first official test
execution 之前锁定，任何 test_id/test_ood evaluation、结果读取或 publication 后均不得回改。

## 当前 formal execution 状态

```text
primary traces: 0/256
paired: 0
aggregate: 0
verdict: 0
sensitivity: 0
artifact root: absent
```

WP-02D1、WP-02D2、WP-02D3 与 WP-03 Slice 1–17 均已完成并接受；WP-02D overall 仍在进行中。
WP-03 implementation engineering acceptance 不构成 prediction scientific evidence。当前没有真实
WP-03 scientific result，没有执行真实 official prediction experiment，没有发生 `FIRST OFFICIAL TEST
EXECUTION`，`test_id` / `test_ood` 均未真实 `SPENT`。Formal H1 只能按上述顺序并在用户明确授权后
启动。

正式 seeds 仍为 `20260819..20261074`，当前未生成 256 formal NPZ、formal artifact inventory、
formal paired JSONL、formal aggregate 或 formal primary verdict，也未运行 Primary H=2、formal
H=0、H sensitivity 或 stress sensitivity。本 checkpoint 不启动或解锁 formal data generation；
不得记录 formal point estimate、LCB/UCB 或正式 PASS/FAIL/INCONCLUSIVE/PROTOCOL_FAIL outcome。
在有效 Formal H1 scientific gate 结果产生并完成解释前，不进行 official predictor training、
official prediction dataset generation、official ID/OOD experiment、large multi-seed prediction runs、
GPU predictor training、forecast-guided controller main experiment、MAPPO training 或其他 official
forecast uncertainty/control science；WP-03A 的 deterministic interface/dataset protocol 基础设施
不构成 predictor scientifically validated、forecasting improves control、probabilistic uncertainty
beneficial 或 MAPPO beneficial 的科学结果。WP-03B 不决定 Transformer/LSTM/TCN/MLP、optimizer、
learning rate、hidden size、official split sizes、official prediction seeds 或 MAPPO architecture。
