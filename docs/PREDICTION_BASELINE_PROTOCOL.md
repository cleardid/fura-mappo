# WP-03B Prediction Baseline Scientific Protocol

状态：WP-03B scientific design 已冻结；implementation preparation 仅在本 design-freeze docs 完成
独立审查、用户手动 Commit/Push 与 GitHub Actions 后解锁。历史 review facts：candidate v1 为
BLOCKER 0、MAJOR 2、MINOR 1；candidate v2 为 BLOCKER 0、MAJOR 3、MINOR 1；candidate v3 在关闭
B2/B3/B* selection、failed-seed semantics、Primary ID labels 与 learned-config total ordering 后为
BLOCKER 0、MAJOR 2、MINOR 1；candidate v4 在关闭 evaluation/B5 completeness 与 stale-status issues
后为 BLOCKER 0、MAJOR 2、MINOR 1。本次聚焦补齐 pre-training data freeze、spent-test governance 与
generic-P B5 support；不预先声称本修订已通过审查。本 acceptance 仅接受 prediction baseline /
evaluation protocol，不是 predictor performance、forecasting benefit、control value 或 MAPPO 的科学
证据。开始任何
WP-03B implementation preparation 前，本 docs patch 必须完成独立审查、用户手动 Commit/Push，
且 GitHub Actions 通过。

## 1. 范围与硬门禁

WP-03B 冻结 architecture-neutral point-prediction baseline、objective、metric、model-selection、
uncertainty 与 ID/OOD governance。它不实现 predictor、baseline、metric evaluator、training code，
也不选择 Transformer/LSTM/TCN/MLP、optimizer、learning rate、hidden dimension、official split
sizes、official prediction seeds 或 MAPPO architecture。

在有效 Formal H1 scientific outcome 产生并完成解释前，继续禁止 official prediction dataset
generation、official predictor training、official ID/OOD experiment、large multi-seed prediction run、
GPU predictor training、forecast-guided controller main experiment、MAPPO training 与 Formal H1。

WP-03A information boundary 完整继承：canonical target 是 decision boundary `t` 之后的 future
realized zone-level arrival counts，forecast row 0 是 `t+1`，shape 为 `[P,Z]`。Core context、target、
forecast 与 metric 都使用 raw natural count scale；forecast 不 round，不强制为整数。

Predictor 动态输入仅允许：

```text
PredictionContext.history_counts
PredictionContext.history_mask
PredictionContext.absolute_step
PredictionContext.steps_remaining
PredictionContext.zone_schema_sha256
PredictionContext.prediction_horizon
```

禁止把 `DemandTrace.intensities`、future counts、future `DemandEvent`、hidden demand-process state、
seed、RNG state、process type、artifact/config/split provenance、`TrueFutureView` 或其他 future / privileged
information 用作 dynamic feature。`DemandTrace.intensities` 也不得进入 split、forecast 或 controller。

## 2. Inference purity 与 statelessness

所有 official operational predictors 与 baselines 必须满足：

```text
forecast = f(current PredictionContext, immutable fitted artifact)
```

连续 `predict()` 调用之间不得保留或更新 hidden state、rolling history、episode memory、previous
forecast、previous target、previous error，或任何会影响 output 的 call counter。未来 recurrent
architecture 可以在一次调用内部处理完整、有限的 `history_counts[L,Z]`，但调用结束后不得保留
hidden state。该规则防止绕过冻结的 `L`，以及 evaluation-order leakage、cross-episode leakage 与
online/offline information mismatch。

未来 implementation tests 必须证明：

```text
same context + same fitted artifact -> exactly same forecast
forecast is independent of prior predict() calls
forecast is independent of trace evaluation order
new episode requires no hidden-state reset because no persistent state exists
```

## 3. Operational output contract

所有 operational baselines 与 learned point predictor：

- 输出 `DemandForecast.mean[P,Z]`；
- 输出 raw-scale、nonnegative、finite float；
- 使用与 context 匹配的 terminal `valid_mask`；
- 必须通过 `validate_forecast_for_context()`；
- 不 round；
- 不读取 validation/test/OOD target 来产生 forecast；
- 不读取 intensity 或其他 privileged simulator state。

## 4. Baseline hierarchy

### B0 — Zero

```text
mean[h,z] = 0
```

B0 只是 sanity floor，不是强 comparator。

### B1 — Persistence

对每个 zone，把 context 中 latest valid observed count 复制到所有 leads。若没有 valid history row，
输出 0。

### B2 — Masked context mean

对每个 zone：

```text
mean[h,z] = mean(history_counts[row,z] over history_mask[row] == True)
```

将该值复制到所有 leads；无 valid row 时输出 0。B2 只能使用当前长度 `L` 的 context，不得称为
unrestricted historical mean。Full-window moving average 与 B2 等价，因此不重复列入 hierarchy。

B2 internal candidates 精确使用 `L in {4,8,16,32}`。只按 validation Primary RMSE 排序：

```text
1. lower validation Primary RMSE
2. shorter L
```

锁定后得到唯一 B2 variant，记为 `B2*`。Selected L 必须对应明确的 `DatasetProtocolSpec` 及其 SHA，
进入 future official experiment provenance；test_id/test_ood 不得临时改变 L。

### B3 — EWMA recency baseline

按 oldest-to-newest 处理 valid rows。对每个 zone，以 first valid count 初始化 `state_z`，随后递推：

```text
state_z = alpha * current_count_z + (1 - alpha) * state_z
```

最终将 `state_z` 复制到全部 leads；无 valid row 时输出 0。B3 internal candidate grid 是完整 Cartesian
product：

```text
L in {4, 8, 16, 32}
alpha in {0.25, 0.50, 0.75}
```

只按以下 total order 使用 validation Primary RMSE 锁定唯一 B3 variant：

```text
1. lower validation Primary RMSE
2. shorter L
3. smaller alpha
```

Selected L 必须对应明确的 `DatasetProtocolSpec` 及其 SHA，并与 selected alpha 一起进入 future
official experiment provenance；test_id/test_ood 不得临时改变 L/alpha。Short-window moving average
最多能在未来明确预注册为 secondary sensitivity，不能替代 B3。

### B4 — Static train climatology

对 train trace `i` 和 zone `z`，先在该 trace 的 unique realized time steps 上计算：

```text
trace_mean[i,z] = mean(realized_count[i,s,z] over unique step s)
climatology[z] = equal-weight mean over train traces i of trace_mean[i,z]
mean[h,z] = climatology[z]
```

每条 train trace 等权，不得从重复 sliding windows 估计。Fitted values 是 immutable artifact；只能
在第 19 节 Layer A freeze 之后从 frozen train split 拟合，validation/test/OOD 不得更新。

### B5 — Absolute-step train climatology

对 absolute step `s` 和 zone `z`：

```text
step_climatology[s,z] =
    equal-weight mean over train traces of realized_count[i,s,z]

forecast at anchor t:
mean[h-1,z] = step_climatology[t+h,z], h = 1..P
```

该 comparator 用于判断 learned predictor 是否只利用 time phase，而不是 realized demand history。
它只能在第 19 节 Layer A freeze 之后由 frozen train split 拟合，每条 trace 在每个 supported step
等权，不能由 duplicated windows 估计，且 fitted table 是 immutable artifact。Train/test 主协议必须共享预注册的 absolute-step support；
main traces 必须有兼容 `start_step` 与 episode length。Validation/test/OOD 不得补齐 unknown step；
official support 外的 step 是 protocol/config error，不能临时 fallback。

在任何 baseline fitting/selection 前，必须 preflight 每个将正式执行的 prediction protocol 在 train、
validation、test_id 与 test_ood 上的 absolute-step forecast support。对任意 executed horizon `P`、
每个 required anchor `t` 及 valid `h in 1..P`，`t+h` 必须存在于该 protocol 预注册、train-fitted B5
support。每个 protocol 必须预先保证 compatible `start_step`、episode time support 与 required
forecast absolute steps，覆盖 train fitting、validation B* selection、test_id 与 test_ood。
Point-track calibration 为 empty/sealed，不参与 B5 selection；未来若使用 calibration，必须另行冻结
support requirements。

Primary P=2 按该 generic invariant 执行。若未来正式执行 secondary P=4/P=8，每个 P 使用自己的
`DatasetProtocolSpec`/SHA、support preflight、baseline locking 与 evaluation records。Secondary support
failure 只使该 secondary protocol failure，不得 alter、rescue 或 invalidate 已有效完成的 Primary P=2
result。所有 secondary execution 同样受第 12 节 spent-test governance 约束，unknown-step fallback
继续禁止。

若 Layer A freeze/preflight 发现 train/validation/test_id/test_ood 任一 required B5 support gap，或 B5 不能为完整
validation required cells 产生 finite valid forecasts，状态为 `PREDICTION_BASELINE_SELECTION_FAILURE`。
不得移除 B5、renormalize B* candidate set、赋 arbitrary penalty、使用 fallback climatology，或从
validation/test 填充 unknown step。若 preflight 已通过并完成锁定，但 official test 执行/readback 时
仍出现 B5 missing step，则进入第 12 节的 `PREDICTION_EVALUATION_FAILURE`，不得 test-time fallback。

### L0 — Learned point predictor

L0 学习从 finite causal context 到 conditional arithmetic mean count forecast 的映射。本协议不选择
architecture、optimizer 或 capacity。

## 5. Primary baseline comparator B*

`B*` 必须通过 two-stage validation-only procedure 锁定：

执行任何 B2/B3 internal selection、B* validation forecast/metric 或 B* selection 前，第 19 节 Layer A
freeze 必须已经锁定。Split、source inventory、protocol candidates 或 OOD assignment 此后不得改变。

```text
Step 1: lock each baseline's internal variant
  B0 fixed
  B1 fixed
  B2 -> lock L using the B2 rule
  B3 -> lock (L, alpha) using the B3 rule
  B4 fixed train-fitted artifact
  B5 fixed train-fitted artifact

Step 2: compare the six locked B0..B5 variants
  using validation Primary RMSE
```

Step 2 完全相同的 RMSE 使用：

```text
B0 < B1 < B2 < B3 < B4 < B5
```

执行 Step 2 的前提是全部 B0–B5 locked variants 都能在完整 validation set 上产生 complete、finite、
valid forecasts。任一 required baseline 不可计算或不完整时，状态为：

```text
PREDICTION_BASELINE_SELECTION_FAILURE
```

此状态没有 `B*`，不得静默删除 baseline、缩小/renormalize candidate hierarchy、赋 arbitrary score，
也不得进入 official test 或产生 prediction-science label。它与单个 learned config 的
`TRAINING_FAILURE`、无 valid learned config 的 `PREDICTION_MODEL_SELECTION_FAILURE` 及 locked test
phase 的 `PREDICTION_EVALUATION_FAILURE` 相互独立，也不复用 Formal H1 `PROTOCOL_FAIL` schema。

一旦 `B*` 锁定，test_id/test_ood 不得重新选择。B2/B3 selected `DatasetProtocolSpec` SHA 与 B3
alpha 必须随 baseline identities 一起锁定；learned predictor 的 primary comparison 只对锁定 `B*`，
但 B0–B5 locked variants 的完整 test breakdown 仍必须报告。不得在 test 后改变 internal variant 或
换成更有利 baseline。

## 6. Privileged intensity diagnostic

WP-03B official protocol 不启用 `DemandTrace.intensities` diagnostic。它不是 operational baseline、
deployable comparator、controller-visible forecast 或 model-selection input。若未来确有需要，只能在
primary prediction evaluation 完全锁定并完成后，按新的、单独预注册的 post-lock diagnostic 运行；
它不得改变 `B*`、learned predictor selection、Primary predictive result 或 control experiment。

## 7. Point-prediction objective

Canonical learned output 是 raw-count scale 上的 predictive arithmetic mean。冻结 objective candidates：

```text
O0: masked raw-scale MSE
O1: masked Poisson NLL / Poisson quasi-likelihood
```

二者只使用 valid target cells，并采用 trace-equal、horizon-equal、zone-equal weighting，使长 trace
或高流量 zone 不会隐式主导；只用 train 更新参数、只用 validation 选择。O0/O1 的 config-level
selection 使用第 9 节唯一的 `Validation Algorithm RMSE`。Objective preference 只作为第 14 节唯一
total ordering 的第 4 项：

```text
O0 MSE < O1 Poisson NLL
```

Poisson NLL 的 exact numerical stability、positive link 与 floor 必须在未来 implementation spec 中
冻结，并在任何训练前进入 config hash；不得按 test 结果调整。选择 O1 不表示 Poisson variance
正确、完整 predictive distribution 已校准，或 counts 真正 conditionally Poisson。

MAE、Huber 与 `log1p(target)` MSE 不作为 canonical mean objective，因为它们不能在当前协议下直接
替代 conditional arithmetic mean estimand。

## 8. Primary predictive metric

Primary metric 是 trace-equal、zone-equal、horizon-equal、raw-scale RMSE。对 trace `i`、official
lead `h`、zone `z`，令 `A_i,h` 为该 lead valid 的 anchors：

```text
MSE[i,h,z] = mean over t in A_i,h of
    (prediction_mean[i,t,h,z] - target_count[i,t,h,z])^2

Primary MSE = mean over traces i
              mean over official horizons h
              mean over zones z
              MSE[i,h,z]

Primary RMSE = sqrt(Primary MSE)
```

每条 trace、每个 horizon、每个 zone 等权，只有 trace 内 anchors 先平均。Sliding windows 不是独立
科学单位；zero target 必须保留，不能删除 zero-demand trace/cell。Official trace 必须满足
`num_steps >= P + 1`。Sample-cell weighted RMSE 只能作为 volume-weighted secondary diagnostic。

## 9. Multiple-training-seed estimand

所有 candidate configs 必须使用同一个、预先冻结的 training-seed set，至少包含 3 个 distinct
seeds。Exact 数量和值须在服务器恢复后的 official prediction experiment spec 中、任何训练前冻结。
同一个 fixed seed set 用于全部 objective、transform、L、architecture 与 hyperparameter configs。
任何 candidate training、validation forecast/metric 或 early stopping 前，第 19 节 Layer A freeze
必须已完成；训练只能读取 frozen train split，validation 只能读取 frozen validation split。

### Fixed-seed validity 与 failure semantics

对任一 candidate config，只有所有 fixed training seeds 都产生以下全部结果时，该 config 才是
`VALID`：

```text
valid completed run
valid locked checkpoint
finite valid validation forecasts
finite Validation MSE_r
required deterministic validation passed
```

任一 fixed seed 缺失、training crash、没有 checkpoint、产生 NaN/Inf、不能产生有效
`DemandForecast` 或未通过 required deterministic validation 时：

```text
config status = TRAINING_FAILURE
```

Failure reason 必须记录。不得删除 failed seed、使用 replacement seed、只对剩余 seeds 求平均、把
failed seed 当作 0 或 manually chosen penalty，也不得在看到 test 后重训该 seed。
`TRAINING_FAILURE` config 没有 `Validation Algorithm MSE/RMSE`，不得进入正常 numerical config
ranking，也不得进入 official test_id/test_ood evaluation。

如果所有 candidate configs 都是 `TRAINING_FAILURE`：

```text
prediction model-selection status = PREDICTION_MODEL_SELECTION_FAILURE
```

此时不得构造伪 scientific predictor result，也不得产生 LEARNED_BETTER/LEARNED_WORSE/
NO_CLEAR_DIFFERENCE label。该状态不是 Formal H1 `PROTOCOL_FAIL` artifact/verdict schema。进入 official
test 前，selected learned config 必须是 `VALID`，所有 fixed-seed checkpoints/identities 已存在并锁定，
且全部 validation records finite/valid；test 阶段不得补 seed、换 seed、重训 seed 或重选 config。

### Validation config selection

对每个 candidate config 和 fixed training seed `r`：

1. 训练一个独立 run；
2. 该 run 只能按自身 per-seed validation Primary RMSE 执行冻结的 early-stopping/checkpoint rule；
3. checkpoint 锁定后，在完整 validation traces 上计算该 seed 的 trace/zone/horizon-equal
   `Validation MSE_r`；
4. config-level score 精确定义为：

```text
Validation Algorithm MSE = mean_r(Validation MSE_r)
Validation Algorithm RMSE = sqrt(Validation Algorithm MSE)
```

Objective O0/O1、transform T0/T1、L、architecture 与 hyperparameter config 的 config-level selection
全部使用同一个 `Validation Algorithm RMSE`，不能改用 `mean_r(sqrt(Validation MSE_r))`、pooled
sample-cell MSE 或其他 seed aggregation。Selection 顺序见第 14 节。

### Primary test point estimate

对锁定 config、全部 fixed training-seed checkpoints 与完整 test_id traces：

```text
Test MSE_r = trace/zone/horizon-equal MSE for training seed r
Test Algorithm MSE = mean_r(Test MSE_r)
Test Algorithm RMSE = sqrt(Test Algorithm MSE)

B* RMSE = deterministic locked baseline Primary RMSE
Delta_RMSE = Test Algorithm RMSE - B* RMSE
```

Learned side 不是 best training seed、`mean_r(sqrt(Test MSE_r))` 或 ensemble forecast；除非未来
另行预注册新的 estimand，当前全部禁止。不得删除 failed seed，或在 test 后决定使用 single seed /
ensemble。每个 seed 的 MSE、RMSE 与 fixed-seed dispersion 必须作为 diagnostics 单独报告，但不得
改变 Primary point estimate。

## 10. Secondary metrics 与 mandatory breakdowns

Official secondary metrics 仅冻结：

1. trace/zone/horizon-equal MAE；
2. signed mean bias，定义为 `prediction - target`。

Mandatory breakdowns 为 per horizon、per zone、per-trace distribution、`target == 0`、`target > 0`、
per condition、ID、near-OOD、structural-OOD 与 per training seed。

WAPE、sMAPE、MASE、Poisson deviance 不进入 WP-03B official inferential metric set；未来若使用，
必须另行冻结为 diagnostic，且不能 rescue Primary RMSE。

## 11. History length L 与 horizon P

H1-aligned Primary prediction horizon 冻结为：

```text
P = 2
```

这不声称 `P=2` 最优。允许单独预注册 `P=4` 与 `P=8` secondary protocols；每个 P 使用独立
`DatasetProtocolSpec` / SHA、单独报告，且不能改变或 rescue Primary P=2 result，也不能从 test
选择最有利 P。

History grid 冻结为：

```text
L in {4, 8, 16, 32}
```

Learned configs 只使用 `Validation Algorithm RMSE` 选择；test_id/test_ood/calibration 不参与；
shorter L 只作为第 14 节唯一 learned-config total ordering 的第 3 项。Candidate methods 可在相同
冻结 grid 与预算下独立选择 `L`。Deterministic B2/B3 的 internal L 分别按第 4 节冻结的 baseline
rules 锁定。B0、B1、B4、B5 不因不使用全部 history 而被伪装为 L-dependent。

## 12. Split usage 与 sealed evaluation

```text
train:
  parameter fitting, train-only baseline statistics,
  transform/normalization fitting, optimizer updates

validation:
  L/objective/baseline/hyperparameter/model selection,
  early stopping, checkpoint selection

calibration:
  empty or sealed for point-only WP-03B main track;
  never used for point training/selection

test_id:
  locked one-shot ID evaluation

test_ood:
  one-shot OOD evaluation of the same locked predictors
```

`test_id` 与 `test_ood` 必须在同一个 sealed evaluation phase 执行；看到 test_id 后不得修改
pipeline 再运行 test_ood。Unused calibration traces 不得在看到任何结果后并回 train。

`FIRST OFFICIAL TEST EXECUTION` 定义为第一次对 locked test_id 或 test_ood 执行任一 official forecast
generation、target/result evaluation、metric computation、bootstrap computation 或 scientific result
readback。只检查 file existence、hash/identity、absolute-step support 或 schema，且不读取 target、
outcome 或 prediction result 的 purely structural metadata preflight，不构成 test exposure。

FIRST OFFICIAL TEST EXECUTION 一开始，exact locked test_id 与 test_ood trace sets 都立即成为
`SPENT TEST SET`，无论 evaluation success、failure 或 partial failure，都不能再次取得 one-shot
scientific status。所有在同一 exposure 前已预注册并纳入同一 sealed phase 的 protocol evaluations
属于该次 one-shot use；未预注册的 later evaluation 不能复用 spent sets。

### Official evaluation completeness 与 failure semantics

有效 sealed test_id/test_ood evaluation 必须同时满足：

```text
exact locked test_id/test_ood trace sets
exact locked trace order within each split
exact fixed training-seed checkpoint set
exact locked B*
exact DatasetProtocolSpec / SplitManifest / ZoneSchema identities
complete predictions for every required valid anchor/horizon/zone
all forecasts finite and valid
all context/forecast bindings valid
all Primary metric inputs finite
complete finite bootstrap inputs
no missing or duplicate required record
```

任何 required trace/checkpoint/record 缺失或重复、artifact/readback failure、invalid
`PredictionContext`/`DemandForecast`、forecast/context binding failure、NaN/Inf prediction/metric、wrong
trace identity/order、wrong protocol/manifest/schema identity、incomplete anchor/horizon/zone coverage 或
incomplete bootstrap input，都触发：

```text
evaluation status = PREDICTION_EVALUATION_FAILURE
```

必须记录 failure reason。发生后没有 official `Test Algorithm MSE/RMSE`、B* comparison point estimate、
`Delta_RMSE` CI 或 LEARNED_BETTER/LEARNED_WORSE/NO_CLEAR_DIFFERENCE label。任何已计算 intermediate
value 只能作为 failure audit diagnostic，不得发布为 scientific result。Zero-demand trace/cell 是合法
observation，不是 failure。

失败时禁止删除 failed trace、排除 failed anchor/window/cell、替换 test trace/training seed、drop
failed checkpoint、平均 remaining seeds、impute failed forecast、使用 fallback predictor、静默修复
identity mismatch 或以 smaller n 继续。若 test_id 失败，不得据此修改 pipeline 后再运行 test_ood；
sealed phase 开始后的任何 failure 都只能记录，不能 patch code/config、换 checkpoint/B*/L/P/
transform/objective，或把 rerun 伪装成 first official evaluation。未来重新正式 evaluation 必须使用
fresh、previously unexposed test_id/test_ood traces，并建立新的 `DatasetSplitManifest`、test-set
identities 与 explicit protocol/version/provenance，重新完成 Layer A/Layer B freezes；不能覆盖第一次
failure。本 WP 不设计具体 failure artifact schema，且该状态不与 Formal H1 `PROTOCOL_FAIL` 共用
schema/verdict。

Fresh recovery test traces 必须继续满足 WP-03A global disjointness：相对 spent sets 具有不同
`trace_id`、seed、artifact content SHA 与 `realized_trace_sha256`，并满足适用的 condition/OOD rules。
Failure record 与 spent-test identities 必须保留。Spent traces 仅可作为 failure audit/debug evidence；
不得迁入 train/validation、用于 hyperparameter/B* selection 或 choosing recovery protocol。可以为 audit
读取，但不能基于同一 spent set 产生 new scientific label、new Primary CI 或 replacement official
result。若旧 test numerical outcome 用于调整 model/protocol，该 set 永久不能再产生 confirmatory
scientific result。

## 13. Input transform 与 output scale

Core context、target、forecast、metrics 永远是 raw counts。Primary point track 只允许下列
`PredictionContext.history_counts` count-value transforms：

```text
T0: x = history_counts
T1: x = log1p(history_counts)
```

T0/T1 仅作用于 `history_counts` 的 count values；padding zero 在两者下都保持 0。
`history_mask`、`absolute_step`、`steps_remaining`、`prediction_horizon` 不 transform；
`zone_schema_sha256` 只作为 identity/binding，不做数值 transform；target 与 output 不 transform，
evaluation metric 继续在 raw count scale。T0/T1 的 config-level selection 使用 `Validation Algorithm
RMSE`；`T0 identity < T1 log1p` 只作为第 14 节唯一 total ordering 的第 5 项。

是否以及如何把允许的 non-count context fields 编码为 learned-model features，必须在未来
implementation/model config 中预先冻结并进入 config identity，不能在 test 后改变；T0/T1 不是
任意 context-field feature engineering 的隐藏开关。不做 fitted per-zone standardization、test/OOD
adaptive scaling；output 直接表示 nonnegative raw-scale mean，不 round，test time 不得临时 clipping。
若未来加入 fitted standardization，必须形成新的预注册 protocol version，不能成为本 main track 的
隐藏选项。

## 14. Reproducible training 与 model selection

下列 RNG namespaces 必须相互分离：

```text
demand RNG
split RNG
model-init RNG
data-loader RNG
training RNG
inference-scenario RNG
prediction-bootstrap RNG
```

禁止从 demand seed 派生 training/evaluation seed，禁止 NumPy global RNG。所有 candidate configs
使用相同 fixed training-seed set、相同预算和相同 validation Primary metric，且不读取 test/OOD；
每个 seed 的 checkpoint 只按其自身 validation Primary RMSE 与冻结 early-stopping rule 锁定。所有
learned config-level choices 使用第 9 节定义的 `Validation Algorithm RMSE`。所有 `VALID` configs
只使用以下唯一 total ordering：

```text
1. lower Validation Algorithm RMSE
2. lower predeclared model-complexity key
3. shorter L
4. objective rank: O0 < O1
5. transform rank: T0 < T1
6. canonical config ordering
```

未来 implementation/model spec 必须在任何 candidate training 前定义 deterministic model-complexity
key；本 WP 不定义具体 architecture 或 complexity formula。Candidate config schema、candidate set /
search space、canonical serialization 与 canonical final ordering 也必须在任何 candidate training 前
冻结，并进入 experiment/config identity。不得在 validation/test 结果出现后定义何者更简单、改变
search space 或改变 tie order。

Early stopping 只读取 validation。未来 implementation spec 必须在训练前冻结 max epochs、patience、
minimum improvement 与 earliest-best-checkpoint tie-break。WP-03B 推荐 no final retrain：选择后不合并
train+validation 重训，避免产生未经相同 validation checkpoint-selection 审核的新程序。

## 15. Statistical uncertainty

统计单位是 one complete `DemandTrace`。Primary test_id point estimate 使用第 9 节定义的
`Test Algorithm RMSE`，并以 paired whole-trace cluster percentile bootstrap 比较 learned algorithm
与锁定 `B*`：

```text
Delta_RMSE = Test Algorithm RMSE - B* RMSE
Delta_RMSE < 0 means lower learned-predictor error
```

对 bootstrap replicate `b`：

1. 从完整 test_id traces 以 trace 为单位有放回抽取 indices；
2. learned 的所有 fixed training-seed runs 与 B* 使用同一组 trace indices；
3. 对每个 training seed `r`，在该 bootstrap trace sample 上重新计算 trace/zone/horizon-equal
   `MSE_r^(b)`；
4. 计算 `Algorithm MSE^(b) = mean_r(MSE_r^(b))` 与
   `Algorithm RMSE^(b) = sqrt(Algorithm MSE^(b))`；
5. 在同一 trace sample 上重新计算 deterministic `B*_RMSE^(b)`；
6. 计算 `Delta_RMSE^(b) = Algorithm RMSE^(b) - B*_RMSE^(b)`；
7. 从全部 `{Delta_RMSE^(b)}` 构造 two-sided 95% percentile interval。

Bootstrap 只 resample test traces；training-seed set 保持固定，不在 primary bootstrap 内 resample。
该 CI 表示 conditional on the preregistered finite training-seed set 的 test-trace sampling uncertainty，
不声称完整量化 training stochasticity。Per-seed MSE/RMSE 与 frozen training-seed dispersion 必须单独
报告，但不能改变 Primary point estimate 或 CI。

禁止 window bootstrap、sample-cell bootstrap、scenario-draw bootstrap、best-seed bootstrap 与
primary bootstrap 内 training-seed resampling；未来若改变，必须另行预注册新的 inferential estimand。

Prediction bootstrap 使用独立 PCG64 namespace，不复用 H1 的 50,000 resamples 或 seed
`90260819`。Exact resample count、seed 与 quantile method 必须在服务器恢复后的 official prediction
experiment spec 中、任何 official evaluation 前冻结。OOD 单独报告，不能 rescue 或改变 ID Primary
comparison。

### Primary ID interpretation rule

令 point estimate 为 `Delta_RMSE`，two-sided 95% percentile CI 为 `[CI_L, CI_U]`。有效 Primary ID
evaluation 必须产生且只产生以下一个 prediction-science label：

```text
LEARNED_BETTER:
    Delta_RMSE < 0 AND CI_U < 0

LEARNED_WORSE:
    Delta_RMSE > 0 AND CI_L > 0

NO_CLEAR_DIFFERENCE:
    otherwise
```

本协议没有 practical-effect `delta_min`；必须同时报告 raw `Delta_RMSE` effect size 与 CI。
`NO_CLEAR_DIFFERENCE` 不表示两者等价；CI crossing zero 不能声称 learned superiority。Per-zone、
per-horizon、secondary metric、OOD 或 control outcome 均不能 rescue/change Primary ID label。该 label
只描述 prediction error comparison，不是 Formal H1 verdict、forecast-control gate 或 MAPPO gate；
Formal H1 保持独立且优先的 scientific gate。若 training/model-selection、baseline-selection 或
evaluation failure，则不产生上述 scientific label；failure state 不是 `NO_CLEAR_DIFFERENCE`。

## 16. ID/OOD taxonomy reservation

ID 是相同 frozen condition 下的新 trace realizations/seeds。Near-OOD 保持 process family 与
`ZoneSchema`，只做一个预注册单轴 shift，例如 overall load、drift speed、hotspot amplitude/scale、
Markov transition persistence 或 burst frequency/duration；每个 cell 单独报告。

Structural-OOD 是 held-out demand process family，该 family 不得出现在 train/validation/calibration。
Primary OOD protocol 保持相同 `ZoneSchema`、zone ordering、episode length/time support。Zone geometry
shift 属于未来独立 protocol，不能与 main OOD 混合。`condition_sha256` 是 identity guard，不自动
代表科学 OOD taxonomy。Exact OOD cells、weights、seeds 与 split sizes 在服务器恢复后的 official
experiment spec 中冻结。

## 17. Prediction 与 control 严格隔离

Canonical learned config 只能按 `Validation Algorithm RMSE` 选择；deterministic `B*` 只能按
validation baseline Primary RMSE 选择。Validation control completion、test control outcome、Oracle
outcome 与 MAPPO reward 均不得参与选择。顺序为：

```text
prediction model/spec locked
-> one-shot prediction evaluation
-> predictor artifacts/results locked
-> separate forecast-guided control protocol
```

Control 结果不得回改 predictor、L、P、objective、transform、checkpoint 或 baseline selection。Formal
H1 尚未执行，因此 official forecast-control experiment 仍被禁止。

## 18. Probabilistic forecast handoff

WP-03B 只冻结 point mean protocol。未来 uncertainty work package 可扩展 variance、quantiles、
scenarios，但 mean 仍按本协议 Primary/secondary point metrics 评估；quantiles 使用预注册 proper
quantile scores/coverage；scenarios 使用预注册 path/distribution scores；inference RNG 独立；scenario
draws 不是独立统计单位；CI 继续以 trace 为 cluster；calibration split 只服务已锁定 probabilistic
model 的 post-hoc calibration。本协议不选择 distribution family 或 uncertainty architecture。

## 19. Official experiment provenance requirements

Provenance 使用两个不可逆 freeze layers。

### Layer A — PRE-TRAINING DATA/SEARCH FREEZE

在 B4/B5 或任何 train-fitted normalization/statistics fitting、任何 learned candidate training、任何
validation forecast/metric、early stopping、hyperparameter/objective/transform/L selection、B2/B3
internal selection 或 B* selection 之前，必须锁定：

- `ZoneSchema` identity；
- Primary `DatasetProtocolSpec`，以及任何将正式执行的 secondary `DatasetProtocolSpec` 与各自 SHA；
- exact source artifact inventory 与 artifact identities；
- exact `DatasetSplitManifest`；
- exact train/validation/test_id/test_ood trace membership 与各 split canonical order；
- exact calibration empty/sealed disposition；
- 每条 source/trace 的 trace ID、seed、content SHA、`realized_trace_sha256` 与 `condition_sha256`；
- ID、near-OOD、structural-OOD assignment；
- fixed training-seed set 与 RNG namespace plan；
- candidate config schema、candidate set/search space、model-complexity key、canonical serialization /
  ordering；
- objective/transform/L grids、training budget、early-stopping rule 与 checkpoint-selection rule；
- generic-P B5 support plan、baseline definitions 与 two-stage B* rule。

Layer A 一旦锁定并且任何 fitting/training/validation activity 开始，禁止移动 trace between splits、
add/remove trace、replace seed、改变 calibration disposition、test_id/test_ood membership、existing trace
的 OOD taxonomy assignment、`DatasetProtocolSpec` 或 source inventory。不能根据 validation score、
training failure 或 model behavior 修改 split。B4/B5 与任何 train-fitted statistics 只能在 Layer A
之后拟合，且只能读取 frozen train split。

若在任何 fitting/training/selection/result 之前发现 manifest invalid、artifact missing、split leakage、
B5 support incompatibility 或 identity mismatch，记录 governance state
`PRE_TRAINING_DATA_FREEZE_FAILURE` 并 STOP；只有在尚无 candidate training、baseline selection、
validation result 或 test result 的前提下，才可建立新的 explicit pre-training protocol/manifest version。
若任何 fitting/training/validation 已开始后才发现 Layer A split/provenance error，当前 experiment 必须
停止并记录 development/protocol failure；不得修改 manifest 后继续沿用已有 numerical results。新的
experiment 必须使用新的 explicit protocol/manifest identity，从 fitting/training/model-selection 起点
完整重启，且不得继承旧 experiment 的 numerical selection result。该 governance state 不复用 Formal
H1 `PROTOCOL_FAIL` schema。

### Layer B — PRE-TEST EXECUTION FREEZE

在第 12 节 `FIRST OFFICIAL TEST EXECUTION` 之前，必须进一步锁定：

- selected B* 及 B2/B3 variants、对应 `DatasetProtocolSpec` SHA 与 B3 alpha；
- selected learned config、exact predictor identities 与所有 fixed-seed checkpoints/identities；
- exact locked test_id/test_ood identities 与 canonical orders；
- metric implementation identity、metric weighting 与 evaluation completeness requirements；
- prediction bootstrap resamples、seed、method 与 implementation identity；
- final ID/OOD cells；
- official prediction failure-state identities；
- Git Commit 与 runtime provenance。

Layer B 不得修改任何 Layer A identity。全部 Layer B scientific identities/spec/config/checkpoint hashes
必须先于 official forecast generation、target/result evaluation、metric/bootstrap computation、scientific
result readback 或 publication 锁定。FIRST OFFICIAL TEST EXECUTION 随即触发第 12 节 SPENT TEST SET
规则。

## 20. Formal H1 guard

Formal H1 scientific specification 保持不变：Primary H=2、N=256、seeds
`20260819..20261074`、`delta_min=0.02`、50,000 bootstrap resamples、PCG64 seed `90260819`。

```text
H1 spec SHA-256:
fc719e4634ab13ba55d0b95e63497688b3ab07c259d1421c5ed0c468cec3fade

Primary environment SHA-256:
d1d856b13ac8edf79422428a96bddc03b901053dbeaabe56571e9baeef6eafa1
```

当前 Formal primary traces 为 `0 / 256`；Formal paired results、aggregate、verdict、sensitivity 均为
0。`1092d9c...` 仅是历史 WP-02D3 accepted implementation checkpoint。WP-03A 后合法 source changes
已终止旧的 docs-only descendant execution freeze。服务器恢复后必须 sync latest accepted main，
重新冻结 Formal H1 execution provenance/accepted execution baseline，完成 server readiness preflight，
并取得用户明确授权后才可运行 Formal H1；不得机械运行旧 runner command。

## 21. Acceptance boundary 与下一阶段

WP-03B acceptance 只表示本 scientific protocol/design 已接受，不表示 predictor 已验证、forecasting
改善 control、uncertainty 有益、controller 获益或 MAPPO 有益。下一阶段仅记录为：

```text
WP-03B implementation preparation
```

它只能在本 docs patch 独立审查通过、用户手动 Commit/Push 且 GitHub Actions 通过后开始，并继续
受 Formal H1 门禁约束。
