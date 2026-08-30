# WP-03 Official Point-Prediction Experiment Specification v1

Scientific design status：

```text
WP-03 OFFICIAL POINT-PREDICTION v1 SCIENTIFIC SPEC FROZEN — D-043
```

Repository publication：本文件不得以自身文字断言当前 Commit 已 accepted。其 accepted-main
publication 状态由 external governance（independent patch review -> user manual Commit/Push -> GitHub
Actions success）确定；该 publication rule 不是 execution authorization。

本文件记录 `wp03_point_primary_v1` 的 exact scientific design。它不授权生成 official data、baseline
fitting、learned training、validation selection、Layer A/Layer B construction、forecast generation、
official test evaluation、`FIRST OFFICIAL TEST EXECUTION` 或 `SPENT` transition。

既有 `docs/PREDICTION_PROTOCOL.md` 与 `docs/PREDICTION_BASELINE_PROTOCOL.md` 的 causal boundary、
metric、selection、failure、Layer A/Layer B、Primary-ID 与 prediction/control isolation governance 继续
完全有效；本文件只冻结此前明确留给 official experiment spec 的 exact values。

## 1. Experiment identity

```text
experiment_id: wp03_point_primary_v1
Primary prediction: P = 2
Secondary P=4/P=8: NOT EXECUTED IN v1
calibration disposition: EMPTY
calibration trace count: 0
```

未来若执行 `P=4` 或 `P=8`，不得在本 experiment 的 test sets `SPENT` 后追加。必须建立新的
experiment/protocol identity，并使用 fresh previously unexposed test sets；secondary result 不得 rescue、
改变或替代本 v1 Primary result。

## 2. Zone 与 episode identity

全部 official source traces 精确使用：

```text
start_step = 0
num_steps = 256
num_zones = 4
```

`ZoneSchema` bounds 按 `zone_id` ascending 为：

```text
[0.0, 1.0, 0.0, 1.0]
[1.0, 2.0, 0.0, 1.0]
[2.0, 3.0, 0.0, 1.0]
[3.0, 4.0, 0.0, 1.0]
```

该 geometry 与 accepted Formal H1 Primary geometry 相同；这不合并两项实验的 result、verdict、
provenance 或 scientific interpretation。

## 3. ID demand condition

TRAIN、VALIDATION 与 TEST_ID 除 `demand.seed` 外精确共享以下 condition：

```yaml
type: drifting_hotspot
base_intensities: [0.025, 0.025, 0.025, 0.025]
hotspot_amplitudes: [0.55]
hotspot_scales: [0.45]
initial_hotspot_positions:
  - [0.5, 0.5]
hotspot_velocities:
  - [0.25, 0.0]
zone_bounds:
  - [0.0, 1.0, 0.0, 1.0]
  - [1.0, 2.0, 0.0, 1.0]
  - [2.0, 3.0, 0.0, 1.0]
  - [3.0, 4.0, 0.0, 1.0]
priority_range: [0.5, 0.5]
service_time_range: [1, 2]
deadline_offset_range: [2, 3]
generation:
  num_steps: 256
```

该 demand condition 与 Formal H1 demand condition 对齐，但 WP-03 prediction result 与 Formal H1
verdict 继续严格独立。

## 4. Exact splits、demand seeds 与 trace IDs

```text
TRAIN:
  count: 128
  seeds: 410000..410127
  cell: ID_DRIFT_V025
  trace_id: wp03-train-id-<seed>

VALIDATION:
  count: 64
  seeds: 420000..420063
  cell: ID_DRIFT_V025
  trace_id: wp03-validation-id-<seed>

CALIBRATION:
  count: 0
  disposition: EMPTY

TEST_ID:
  count: 128
  seeds: 430000..430127
  cell: ID_DRIFT_V025
  trace_id: wp03-test-id-<seed>

TEST_OOD:
  count: 96
```

TEST_OOD 精确分为：

```text
NEAR_OOD / NEAR_DRIFT_V020:
  count: 32
  seeds: 440000..440031
  trace_id: wp03-test-ood-near-v020-<seed>

NEAR_OOD / NEAR_DRIFT_V030:
  count: 32
  seeds: 441000..441031
  trace_id: wp03-test-ood-near-v030-<seed>

STRUCTURAL_OOD / STRUCT_MARKOV_V1:
  count: 32
  seeds: 450000..450031
  trace_id: wp03-test-ood-struct-markov-<seed>
```

全部 demand seeds 全局唯一。Demand seeds、training seeds 与 prediction-bootstrap seed 属于不同
namespaces，不得相互派生或混用。

## 5. Near-OOD conditions

两个 near-OOD cells 都只改变一个 scientific axis：hotspot velocity 的 x component。

```text
NEAR_DRIFT_V020:
  hotspot_velocities = [[0.20, 0.0]]

NEAR_DRIFT_V030:
  hotspot_velocities = [[0.30, 0.0]]
```

除上述 velocity 值与 `demand.seed` 外，全部字段必须与第 3 节 ID condition 完全相同。不得同时改变
load、hotspot amplitude、scale、geometry、priority、service-time 或 deadline attributes。

## 6. Structural-OOD condition

Held-out family 精确为 `markov_switching`；该 family 不得出现在 TRAIN、VALIDATION 或 TEST_ID。

```yaml
type: markov_switching
state_intensities:
  - [0.50, 0.10, 0.025, 0.025]
  - [0.025, 0.025, 0.10, 0.50]
transition_matrix:
  - [0.95, 0.05]
  - [0.05, 0.95]
initial_state: 0
zone_bounds:
  - [0.0, 1.0, 0.0, 1.0]
  - [1.0, 2.0, 0.0, 1.0]
  - [2.0, 3.0, 0.0, 1.0]
  - [3.0, 4.0, 0.0, 1.0]
priority_range: [0.5, 0.5]
service_time_range: [1, 2]
deadline_offset_range: [2, 3]
generation:
  num_steps: 256
```

每个 Markov state 的 nominal total intensity 精确为 `0.65`：

```text
0.50 + 0.10 + 0.025 + 0.025 = 0.65
0.025 + 0.025 + 0.10 + 0.50 = 0.65
```

它与 ID condition 的 nominal scale `sum(base_intensities) + hotspot_amplitude = 0.10 + 0.55 =
0.65` 对齐。设计意图是在尽量保持 aggregate arrival-rate scale 的同时改变 temporal/spatial demand
mechanism；这不是对 realized per-step aggregate intensity 完全相等的额外声明。

Structural-OOD result 不得 rescue、改变或替代 ID Primary label。

## 7. OOD reporting

```text
OOD cell weights: NONE
cross-cell pooled official OOD score: NONE
```

`NEAR_DRIFT_V020`、`NEAR_DRIFT_V030` 与 `STRUCT_MARKOV_V1` 三个 cells 分别执行既有 mandatory
descriptive reporting。不得定义 pooled OOD inferential estimator。

## 8. Dataset protocols

v1 只执行 `P=2`。Frozen candidate protocol set 为：

```text
(P=2, L=4)
(P=2, L=8)
(P=2, L=16)
(P=2, L=32)
```

现有 `PreTrainingFreeze` API 的 representation convention 精确为：

```text
primary_protocol:
  (P=2, L=4)

secondary_protocols:
  (P=2, L=8)
  (P=2, L=16)
  (P=2, L=32)
```

这里 `secondary_protocols` 只是当前 infrastructure 对其他 frozen `DatasetProtocolSpec` 的容器名，
不表示 P=4/P=8 secondary science；`L=4` 也不表示已被 model selection 选中。全部四个 protocols
必须在 Layer A 前冻结并进入 protocol SHA set。

B0/B1/B4/B5 使用 canonical `(P=2,L=4)` protocol 做 validation/test dataset construction，其 forecast
数值本身不依赖 L。B2/B3 与 learned candidates 使用各自 matching-L protocol。四个 protocols 的
target/anchor identity 必须相同，从而保持 metric comparison 公平。

## 9. Learned feature encoding v1

Official numeric learned-model input 依次为：

1. Transformed `history_counts[L,4]`：oldest-to-newest、`zone_id` ascending、row-major flatten；
2. `history_mask[L]`：float32 `0.0/1.0`；
3. normalized absolute step：`absolute_step / 255.0`。

`steps_remaining`、`prediction_horizon` 与 `zone_schema_sha256` 不作为 numeric learned features，但继续
用于 structural validation、terminal masking 与 protocol binding。

禁止加入 process type、seed、trace ID、condition identity、artifact provenance、intensity、future
information 或 controller/environment state。

```text
T0: history count values unchanged
T1: log1p(history count values)
```

Padding zeros 在 T0/T1 下均保持零。全部 numeric inputs 转为 float32；不执行 fitted z-score 或
per-zone normalization。

## 10. Learned architecture v1

唯一 architecture family 为 stateless feed-forward MLP：

```text
input
-> Linear(d, W)
-> ReLU
-> Linear(W, W)
-> ReLU
-> Linear(W, 8)
-> softplus
-> + 1e-6
```

```text
W in {64, 128}
output dimension = P * Z = 8
```

禁止 dropout、batch normalization、layer normalization、residual state 与 persistent hidden state。
Valid cells 的 output link 为 `mu = softplus(raw) + 1e-6`，表示 finite positive raw-scale arithmetic-mean
forecast。Reshape 后的 forecast shape 为 `[2,4]`；existing terminal `valid_mask` contract 继续有效，
invalid terminal rows 必须归零。

## 11. Complexity key

输入维度与 trainable parameter count 精确为：

```text
d = 4L + L + 1 = 5L + 1
params = d*W + W*W + 10*W + 8
```

Frozen model-complexity key 为：

```text
(num_trainable_parameters,)
```

该值必须由 canonical architecture/config 精确计算，不接受 caller 任意填写。

## 12. Search space

```text
L:             4, 8, 16, 32
objective:     O0, O1
transform:     T0, T1
hidden width:  64, 128
learning rate: 0.0003, 0.001
```

因此：

```text
candidate configs = 4 * 2 * 2 * 2 * 2 = 64
fixed training seeds = 610001, 610002, 610003
official candidate training runs = 64 * 3 = 192
```

必须完整执行 Cartesian product。禁止 random search、successive halving、test-informed pruning 或未预注册
early candidate deletion。

## 13. Canonical candidate ordering

```text
width rank:        64 -> 0; 128 -> 1
learning-rate rank: 0.0003 -> 0; 0.001 -> 1
L rank:            4 -> 0; 8 -> 1; 16 -> 2; 32 -> 3
objective rank:    O0 -> 0; O1 -> 1
transform rank:    T0 -> 0; T1 -> 1
```

固定 nested order 为：

```text
width -> learning rate -> L -> objective -> transform
```

`transform` 是最内层、变化最快的维度。`canonical_order` 精确为：

```text
((((width_rank * 2 + learning_rate_rank) * 4 + L_rank) * 2
   + objective_rank) * 2 + transform_rank)
```

其值域为 `0..63`。不得按 hash、validation result 或 runtime enumeration order 改变 candidate order。
既有 learned selection total order继续为 Validation Algorithm RMSE、model complexity key、shorter L、
O0 before O1、T0 before T1、canonical order。

## 14. Objective weighting

对 valid train target cell `(i,t,h,z)`：

```text
w(i,t,h,z)
= 1 / (
    N_train
    * P
    * Z
    * number_of_valid_anchors_for_trace_i_and_lead_h
  )
```

全部 valid weights 总和必须为 1。

```text
O0 = sum w * (mu - y)^2
O1 = sum w * (mu - y * log(mu))
mu = softplus(raw) + 1e-6
```

Poisson `log(y!)` 是 outcome-only constant，不进入 optimization objective。O1 不声称 conditional
variance 真正 Poisson。Validation/model selection 只使用 frozen raw-scale Validation Algorithm RMSE，
不使用 training objective value。

## 15. Optimizer、training 与 checkpoint selection

```text
optimizer: AdamW
betas: (0.9, 0.999)
eps: 1e-8
weight_decay: 1e-4
amsgrad: false
learning-rate scheduler: NONE
gradient clipping: NONE
```

```text
training mode: full-batch
sample order: canonical fixed order
shuffle: no
sampler RNG: none
numeric dtype: float32
AMP: disabled
device count per run: one
max epochs: 300
patience: 30 consecutive epochs
absolute checkpoint improvement threshold: 1e-5
final retrain: no
```

每个 epoch 执行一次完整 TRAIN forward/backward/update，随后对完整 VALIDATION traces 求该 training
seed 的 validation Primary RMSE。首个 finite epoch 为 initial best；只有
`new_rmse < best_rmse - 1e-5` 时替换 checkpoint。未达到该 absolute improvement 的较小 RMSE 不替换，
因此 earliest-best tie rule 唯一确定。

该 checkpoint score 是既有 protocol 要求的 run-local、per-training-seed validation Primary RMSE。
三个 seeds 的 checkpoints 全部锁定后，才计算 `Validation Algorithm RMSE =
sqrt(mean_r(Validation MSE_r))` 用于 config-level selection；cross-seed score 不用于替代单 seed 的
checkpoint rule。

## 16. Initialization 与 RNG v1

```text
demand-generation RNG: each trace uses its frozen source seed
learned training seeds: 610001, 610002, 610003
training-seed role: local model-initialization RNG root for that run only
```

Initialization 必须使用 local explicit generator；禁止 NumPy global RNG 与 torch global RNG。固定
layer construction/init order如下：

```text
hidden Linear weights: Xavier uniform, gain=sqrt(2)
output Linear weights: Xavier uniform, gain=1
all biases: 0
```

Full-batch training 无 sampler RNG；AdamW 不引入额外 RNG；point inference 不使用 RNG。Prediction
bootstrap 使用第 18 节的独立 namespace。不得机械复用项目现有会设置 NumPy global RNG 的 helper。

## 17. Determinism requirements

Future implementation 必须满足：

```text
float32
no AMP
no stochastic layers
no torch.compile
deterministic algorithms required
TF32 disabled
cuDNN benchmark disabled
single GPU/device
```

Exact runtime-specific settings 必须在 execution-stack implementation review 中锁定，并早于 Layer A。
每个 successful seed checkpoint 必须通过：

1. safe-load 同一 checkpoint 两次；
2. 对完整 validation traces 生成 canonical-order forecasts；
3. 再按 reversed trace order 生成 forecasts；
4. 以 sample identity 对齐，全部 mean arrays 与 valid masks exact equal；
5. 两次 `PointMetricSummary` exact equal；
6. 全部 parameters、forecasts 与 metrics finite。

只有通过上述检查，future trainer 才能提供 `deterministic_validation_passed=true`；runner 不得任意填写。

## 18. Prediction bootstrap

```text
num_resamples = 20000
rng_seed = 910001
generator = PCG64
method = paired whole-test-trace percentile
quantile_method = linear
CI = two-sided 95%
```

该 namespace 与 Formal H1 的 `50000 / 90260819` 完全独立。Bootstrap 只 resample complete TEST_ID
traces；training seeds 固定，不在 bootstrap 内 resample。OOD 不产生可 rescue ID 的 inferential label。

## 19. Dataset feasibility ledger

对 `N=256, P=2, Z=4`：

```text
anchors per trace = N - 1 = 255
valid target cells per trace = Z * (2N - 3) = 4 * 509 = 2036
```

```text
TRAIN:
  traces: 128
  anchors: 32640
  valid target cells: 260608

VALIDATION:
  traces: 64
  anchors: 16320
  valid target cells: 130304

TEST_ID:
  traces: 128
  anchors: 32640
  valid target cells: 260608

TEST_OOD:
  traces: 96
  anchors: 24480
  valid target cells: 195456
```

L 不改变 anchor 或 target-cell count。

## 20. B5 support

全部 official traces 使用 `start_step=0, num_steps=256`，因此：

```text
train common absolute support: [0, 256)
required future support per trace: [1, 256)
```

v1 spec 在结构上满足 frozen B5 support invariant；actual Layer-A authoritative B5 preflight 仍必须执行，
本文件不能替代该 preflight。

## 21. OOD 与 inference boundary

Primary scientific label 只来自 TEST_ID。以下三个 OOD cells 均为 descriptive-only：

```text
NEAR_DRIFT_V020
NEAR_DRIFT_V030
STRUCT_MARKOV_V1
```

不得 pool cells 创建新 official OOD score，不得按 OOD outcome 重选 model/B*，也不得 rescue/change
Primary-ID。

## 22. Runtime provenance policy

Exact Python、NumPy、PyTorch、CUDA、driver、cuDNN、GPU 与 OS versions 不作为 scientific search
dimension。但在 Layer A 前必须满足：

- training/evaluation stack implementation 已 accepted；
- exact runtime/dependency snapshot 已捕获；
- canonical runtime provenance artifact 与 SHA 已锁定；
- training、selection 与 test 期间 runtime 不得漂移。

Runtime version变化必须建立新 experiment/provenance identity，从 Layer A 重新开始。本 specification
不猜测 PyTorch version。

## 23. Artifact 与 execution governance

Reserved future official evidence root：

```text
artifacts/wp03_prediction_official_v1/
```

本 specification 不创建该目录。Future artifacts 必须 no-overwrite、safe/canonical readback、content/hash
bound 且不进入 Git。Exact checkpoint/result serialization 属于下一 engineering implementation stage，
必须在任何 training 前 accepted；禁止 unsafe arbitrary pickle 作为 authoritative checkpoint trust root。

## 24. Layer-A mapping

Future Layer-A protocol set 为：

```text
P2L4 canonical primary_protocol anchor
P2L8/P2L16/P2L32 additional frozen protocols
```

Layer A 还必须绑定：

```text
exact verified source artifacts
exact DatasetSplitManifest
EMPTY calibration
exact TraceOODAssignment records
training seeds 610001, 610002, 610003
64 LearnedConfigFreezeIdentity records
rng namespace plan SHA
training plan SHA
baseline plan SHA
```

本 specification 不构造 Layer A。

## 25. Layer B 与 SPENT

既有 governance 完全不变。在 `FIRST OFFICIAL TEST EXECUTION` 前必须锁定 selected B*、B2/B3
variants、selected learned config、三个 exact checkpoints、predictor/metric/evaluation/bootstrap
implementation identities、exact test IDs/order、final OOD assignments、runtime provenance、Git Commit
与 failure-state plan。

Future runner 顺序必须为：

```text
UNSPENT
-> record first official test execution
-> immediate SPENT for test_id + test_ood
-> generate all locked forecasts
-> existing finalizer exactly once
```

本 spec 不授权执行。

## 26. Scientific status、publication boundary 与 handoff

Scientific design 与 execution state 为：

```text
WP-03 OFFICIAL POINT-PREDICTION v1 SCIENTIFIC SPEC FROZEN — D-043
WP-03 official experiment: NOT EXECUTED
FIRST OFFICIAL TEST EXECUTION: NOT OCCURRED
test_id/test_ood: UNSPENT
```

本文件不自证其所在 Commit 已成为 latest accepted main；accepted-main publication 由 independent patch
review、用户手工 Commit/Push 与 GitHub Actions success 的外部治理事实确定。Accepted-main publication
后的下一 engineering stage 为：

```text
NEXT: WP-03 Execution Stack Implementation Preparation
```

下一阶段只允许 trainer、safe checkpoint、plan serialization、runtime provenance 与 official
orchestration engineering；仍不得生成 official data、训练 predictor 或执行 official test，除非未来另有
explicit authorization 和全部既有 gates 均已满足。
