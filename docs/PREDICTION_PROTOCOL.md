# WP-03A Prediction Interface & Dataset Protocol

状态：设计决策已接受；candidate v3 独立复审为 BLOCKER 0、MAJOR 1、MINOR 1，candidate v4
只修复 realized float signed-zero canonicalization 与 D-039 stale wording 后等待完整 patch 独立审查。
本文只定义 prediction 基础设施，不是预测性能或控制价值的科学结果。

## 1. 范围与治理

WP-03A 建立 point forecast、probabilistic forecast、未来 forecast-guided controller、centralized
baseline 与 MAPPO 共用的因果数据和接口边界。核心层保持 NumPy/Python、PyTorch-neutral、
architecture-neutral，不实现神经网络、optimizer、训练 loop、reward、forecast-guided controller
或 MAPPO。

服务器不可用期间允许在 Mac 开发、测试和审查本基础设施。下列工作继续锁定：

- Formal H1 与正式 seeds `20260819..20261074`；
- official prediction dataset generation、predictor training 和 calibration；
- official forecast-control、ID/OOD、uncertainty 与 MAPPO 实验；
- PyTorch/GPU/large multi-seed workload；
- forecasting 改善 control 的任何科学结论。

Formal H1 science 不因 WP-03A 改变：Primary H=2、N=256、estimand、bootstrap、gate、spec hash
`fc719e4634ab13ba55d0b95e63497688b3ab07c259d1421c5ed0c468cec3fade` 与 environment hash
`d1d856b13ac8edf79422428a96bddc03b901053dbeaabe56571e9baeef6eafa1` 均保持不变。

`1092d9c87bfff8ba6c1f2132734480112d7b5975` 仍是历史 WP-02D3 accepted implementation，
但 WP-03 source changes 会有意结束其“后继只能是 docs/changelog”的旧 execution freeze。服务器
恢复后，必须先同步最新 accepted main、重新冻结 Formal H1 execution provenance/accepted
execution baseline、做 readiness preflight 并取得用户明确授权，才可运行 Formal H1。WP-03A 不修改
旧 runner 来提前放宽此门禁。

## 2. Canonical prediction task

在 decision boundary `t`，canonical target 是未来 realized zone-level arrival counts：

```text
Y[h, z] = count of arrivals in zone z at absolute step t + h
h = 1..P
z = 0..Z-1
```

数组 shape 为 `[P,Z]`、dtype 为 `int64`。行 0 对应 `t+1`，绝不把 boundary 已知的当前到达
`t` 当作 future label。

以下内容不是 v1 target：latent intensity、future event list、future active tasks、future
controller-dependent queue state 或 demand hidden state。`DemandTrace.intensities` 是 privileged
simulator state；它可以保留在 WP-01 artifact 内，但不得影响 context、model feature、online
history、split、forecast 或 controller。

## 3. Causal information boundary

Predictor 在 boundary `t` 只读取：

```text
realized zone arrival counts at t-L+1..t
absolute_step
steps_remaining
static ZoneSchema identity / zone ordering
```

训练和 inference 的 feature schema 完全相同。Target 只作为监督标签存在。禁止把 seed、process
type、process parameters、artifact hash、trace ID、split label、resource/controller state 或任意
provenance 放入 `PredictionContext`。

历史 shape 为 `[L,Z]`、dtype 为 `int64`，按 oldest-to-newest 排列，最后一行必为 `t`。Episode
开始前使用全零左 padding 与 `history_mask=False`；真实观测行 mask 为 true。Mask 必须是 false
prefix + true suffix，因而真实零需求与 padding 无歧义。

## 4. Horizon 与 episode boundary

Dataset protocol 参数化 `history_length=L>=1` 与 `prediction_horizon=P>=1`，WP-03A 不冻结正式
科学数值。未来 controller planning horizon `Hc` 与 prediction horizon 解耦，正式配置必须满足
`Hc<=P`。若用于支持与 Primary H=2 的信息跨度比较，正式 `P` 必须至少为 2。

Near episode end，target 超出 `stop_step` 的行固定为零且 `valid_mask=False`；真实 future row 即使
count 全零也保持 mask true。Supervised anchor 精确为：

```text
start_step <= t < stop_step - 1
```

因此每个 `PredictionSample` 至少有有效 lead 1；一时间步 trace 合法产生零个 sample。

## 5. Core immutable models

### ZoneSchema

`bounds` 是只读 C-order `float64[Z,4]`，每行 `(x_min,x_max,y_min,y_max)`，严格满足矩形边界。
Axis `z` 精确对应 WP-01 zero-based ascending `zone_id`。`sha256` 对 schema/version、zone ordering
与 bounds 使用既有 `compute_config_hash()` 计算；不包含 demand dynamics。

### PredictionContext

```text
absolute_step: int >= 0
steps_remaining: int >= 1
history_counts: int64[L,Z]
history_mask: bool[L]
zone_schema_sha256: SHA-256
prediction_horizon: int >= 1
```

### PredictionTarget

```text
counts: int64[P,Z]
valid_mask: bool[P]
```

Mask 是 true prefix + false suffix。Padding 行必须为零。

### PredictionSample

```text
sample_id: SHA-256
context: PredictionContext
target: PredictionTarget
```

Sample ID 精确为：

```text
compute_config_hash({
  dataset_protocol_sha256,
  source_artifact_content_sha256,
  anchor_absolute_step
})
```

Identity 不依赖目录遍历顺序，但不得作为模型 feature。

### DemandForecast

Controller-visible payload：

```text
absolute_step: int
horizon: int
zone_schema_sha256: SHA-256
valid_mask: bool[P]
mean: float64[P,Z]
variance: float64[P,Z] | None
quantile_levels: float64[Q] | None
quantiles: float64[Q,P,Z] | None
scenarios: int64[S,P,Z] | None
```

全部 projection 位于自然 count scale。Mean 必须有限非负；variance 单位为 count²；quantile
levels 严格递增且位于 `(0,1)`，quantiles 沿 Q 非递减；scenarios 是非负整数 count paths。
Point forecast 只需 mean。Probabilistic forecast 可提供一种或多种 projection，不绑定 parametric
family。Invalid horizon rows 必须为零。

Predictor output 不能仅凭自身局部结构进入后续 orchestrator/controller。公共
`validate_forecast_for_context(context, forecast)` 必须 hard-check：absolute step、protocol horizon、
ZoneSchema SHA、zone 数量全部相等；并强制 episode mask 为：

```text
num_valid = min(P, max(context.steps_remaining - 1, 0))
valid_mask = [True] * num_valid + [False] * (P - num_valid)
```

Predictor 不得自行声明任意 horizon validity。

`ForecastRecord` 将 `DemandForecast` 与显式 `ForecastProvenance` 分离。未来 controller 只能收到
snapshot 与 `DemandForecast`，不能收到 record provenance、predictor、dataset、artifact、
`DemandTrace` 或 `TrueFutureView`。

所有核心数组均防御性复制、canonical dtype、C contiguous、read-only，且不与 caller/trace
arrays 共享内存。

## 6. Online/offline construction

`ObservedDemandHistory` 的唯一动态输入是 `EnvironmentSnapshot`。它在 boundary `t` 聚合
`snapshot.current_arrivals`，因此 context 最后一行包含已经观测到的当前 `t`。连续调用必须保持
`absolute_step+1` 与相同 episode stop boundary。对象不接收或保存 `DemandTrace`。

Offline builder 可临时持有完整 trace 以构造 label，但 context 只显式复制
`trace.counts[:t+1]` 所需 rows，不读取 intensity、future events、seed 或 config。必须保持：

```text
same realized counts through t -> identical PredictionContext(t)
same realized counts, different intensities -> identical contexts and targets
online current-arrival aggregation -> exact offline context parity
```

## 7. Dataset protocol 与 condition identity

`DatasetProtocolSpec` 冻结 derivation 语义字段：schema/version、L、P、ZoneSchema hash、realized
count history/target kinds、history/target padding rules、anchor rule 与 zone ordering。Protocol hash
只覆盖这些稳定字段，不包含 runtime、timestamp、path、Git 或 official experiment values。

`PredictionSource` 是 controller-hidden audit descriptor：

```text
trace_id, seed, process_type
config_sha256, content_sha256, realized_trace_sha256, condition_sha256
zone_schema_sha256
start_step, num_steps, num_zones
```

直接构造的 `PredictionSource` 只具备字段级结构校验，用于 synthetic fixture 或 strict manifest
readback，不能作为 scientific provenance trust root。Authoritative 路径严格为：

```text
WP-01 NPZ path
-> load_demand_trace() strict safe loading
-> VerifiedPredictionArtifact
-> PredictionSource derived from the same validated manifest/trace
-> samples / split manifest
```

WP-01 loader 已交叉验证 member/schema/dtype/shape、resolved config、config SHA、logical content
SHA、seed、process type 与 reconstructed trace。本层再从同一 validated
`resolved_config.demand.zone_bounds` 构造 `ZoneSchema`，把其 SHA 写入 source；condition identity
也从同一 resolved config 派生。Authoritative sample derivation hard-check source zone SHA 等于
`DatasetProtocolSpec.zone_schema_sha256`，不能以相同 `num_zones` 代替 geometry identity。

`realized_trace_sha256` 是 manifest/path/seed/runtime/Git/timestamp-independent 的 intrinsic identity。
其 v1 hash 使用 domain separator 与 uint64 length-prefixed logical fields，依次绑定：typed decimal
`start_step`；canonical little-endian `counts`；按合法 `DemandTrace.events` 顺序排列的 `event_id`、
`arrival_step`、`zone_id`、`positions`、`priority`、`service_time`、`deadline`。每个数组都绑定 field
name、dtype、shape 与 C-order bytes。`positions`/`priority` 转为 canonical little-endian float64 后，
所有满足 `value == 0.0` 的元素统一写为 `+0.0`，因此 IEEE `+0.0` 与 `-0.0` hash 相同；非零 float
差异仍保留。Hash 明确不读取 `DemandTrace.intensities`、manifest、seed、
process/config、artifact content hash、runtime、path 或 trace ID。该 hash 只在 WP-01 safe load 完成后
从 reconstructed `DemandTrace` 内部计算，caller 不能为 verified source 提供它。

`condition_sha256` 的精确规则：防御性复制完整 WP-01 resolved config，只删除 `demand.seed`，
保留 config schema/version、全部 demand dynamics、zone geometry 与 generation protocol，然后对完整
tree 调用 `compute_config_hash()`。因此不同 realization seed 共享 condition，任何真正的 process、
geometry 或 generation 变化都会产生不同 identity。

## 8. Split protocol

`DatasetSplitManifest` 只分配完整 `DemandTrace`，labels 保留为：

```text
train
validation
calibration
test_id
test_ood
```

Calibration 可以没有 entry。Manifest canonical ordering 固定为 split order、condition、seed、
trace ID、content hash。全局拒绝重复 trace ID、artifact content hash、intrinsic
`realized_trace_sha256` 与 seed，杜绝同一 realized trajectory 即使被不同 metadata/config 重新封装
后跨 split。

`DatasetSplitManifest` 单独只是一份结构合法 declaration。Scientific manifest 必须由
`build_split_manifest_from_artifacts(...)` 从 verified bindings 构造；strict JSON readback 后必须用
`validate_split_manifest_artifacts(...)` 对每个 descriptor 与其 safe-loaded artifact 逐字段复核。
因此 caller 伪造 seed/config/content/realized-trace/condition/zone metadata 不能把同一 trace 伪装成
不同 source；同一 artifact 即使换 trace ID 再加载，仍因相同 content SHA、realized trace SHA 与
seed 被 global guards 拒绝；同一 realized trace 即使以不同合法 seed/config 保存成两个 artifact，
也因相同 intrinsic hash 被拒绝。

`test_id` 可与 train 共用 condition，但必须使用不同 seed/content。`test_ood` condition 必须与
train/validation/calibration/test_id 全部隔离。Official OOD conditions 与 exact seeds 留给未来
结果不可见的 experiment preregistration；WP-03A 不自行发明。

## 9. Natural units 与 RNG

Core context、target 和 forecast 永远保留 natural units，不在科学对象中做 log、z-score 或其他
normalization。未来 model adapter 若拟合 normalization，statistics 只能来自 train valid cells，
不能读取 validation/calibration/test_id/test_ood 或整个 dataset；具体 transform 另行冻结。

WP-03A derivation、hash、split 与 serialization 全部 RNG-free。未来 RNG namespaces 必须隔离：
demand generation、model initialization、training sampler、optimizer stochasticity、inference
scenario 与 evaluation/bootstrap。禁止 NumPy global RNG，也禁止从 demand trace seed 派生 inference
scenario RNG。

## 10. Serialization 与 reproducibility

WP-03A 只序列化 ndarray-free protocol 与 split manifest，格式为 strict canonical UTF-8 JSON：

- exact schema/version/field sets；
- sorted keys、fixed separators、单个末尾换行；
- duplicate key、NaN/Inf、unknown/missing field 拒绝；
- safe `.json` regular-file read；
- atomic same-directory no-overwrite publication；
- strict canonical readback 与 self hash validation。

Protocol/manifest 不记录 volatile timestamp/runtime。Prediction arrays 暂不建立第二套 NPZ artifact
格式；未来如需持久化 forecast，必须另行冻结 little-endian arrays、logical content hash 与安全 loader。

## 11. Acceptance 与当前科学状态

WP-03A tests 必须覆盖 immutable models、shape/dtype/finite checks、padding masks、exact indexing、
one-step trace、sample ordering/identity、prefix/intensity isolation、no aliasing、online/offline parity、
zone geometry mismatch、forged artifact descriptor/cross-split identity、forecast/context mismatch、
terminal mask、same-trace/different-artifact repackaging、intensity-isolated realized trace hash、
position/priority signed-zero equivalence、artifact-level signed-zero split rejection、nonzero float
sensitivity、split/OOD leakage、strict serialization 和 frozen H1 hash regression。

当前 Formal H1 仍未运行：formal traces、controller rollouts、inventory、paired results、aggregate、
verdict 与 sensitivity 全部为零。WP-03A 不提供预测性能结果，不解锁 predictor science，不解锁
MAPPO，也不支持“forecasting 已证明有控制价值”的表述。
