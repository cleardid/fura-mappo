# WP-02D1 H1 Gate Protocol and Statistics 变更记录

状态：已完成并通过 Mac、独立候选审查、GitHub Actions 与 A100 CPU 验收。

稳定实现 Commit：`844de649c71e0a6a8fec6e1355cbf010db434f83`。

WP-02D1 是 protocol/statistics implementation，不是 H1 scientific result。本工作包没有生成
或查看任何正式 H1 outcome。

## 完成范围

- strict H1 preregistration spec
- `configs/experiments/wp02d_h1.yaml`
- deterministic experiment spec hash
- fixed 256-seed protocol：`20260819..20261074`
- Primary H=2；H sensitivity metadata 0/1/2/3/4
- Primary `DriftingHotspotDemand` stress cell 与固定 priority 0.5
- artifact plan 与 strict inventory protocol/read-back
- artifact config/content hash cross-validation
- same-`DemandTrace` paired rollout 与独立 Reactive / Oracle environments
- H=0 strict protocol invariant 与 canonical mechanism preflight
- same-state counterfactual diagnostics 与 realized Oracle trajectory diagnostics
- provenance-bound `PairedTraceResult`
- paired results digest、artifact inventory digest、environment config identity 与 experiment spec identity
- NumPy PCG64 paired percentile bootstrap：50,000 resamples，seed `90260819`
- `delta_min=0.02` 与 `PASS / FAIL / INCONCLUSIVE / PROTOCOL_FAIL`
- canonical JSON / JSONL helpers 与 atomic no-overwrite outputs
- locked primary verdict bound to exact spec/inventory/results/provenance
- local Git provenance hard gate
- sensitivity 只能在 exact valid locked primary verdict 后解锁，且不能改变 primary verdict

WP-02D1 没有实现 bounded verifier；没有修改 WP-02A/B/C 的冻结 environment/controller 语义。

## 冻结 H1 protocol

### Primary outcome

对 trace i：

```text
arrived > 0:
    D_i = (completed_oracle - completed_reactive) / arrived
arrived == 0:
    D_i = 0
```

Primary estimand 为 `mean(D_i)`；每条 trace 等权。

### Primary stress cell

```text
Demand: DriftingHotspot
base_intensities: [0.025, 0.025, 0.025, 0.025]
hotspot_amplitudes: [0.55]
hotspot_scales: [0.45]
initial hotspot: [0.5, 0.5]
velocity: [0.25, 0.0]
zones: four contiguous 1x1 zones, x in [0,4], y in [0,1]
priority_range: [0.5, 0.5]
service_time_range: [1, 2]
deadline_offset_range: [2, 3]
num_steps: 256
resources: 2
initial_resource_positions: (0.5,0.5), (3.5,0.5)
movement_speed: 0.75
Primary H: 2
```

### Bootstrap 与 verdict

```text
N = 256
seeds = 20260819..20261074
paired resampling unit = trace
resamples = 50000
Generator = numpy.random.Generator(PCG64(90260819))
method = percentile
np.quantile method = linear
one-sided LCB/UCB = 5%/95% quantiles
two-sided interval = [2.5%, 97.5%]
delta_min = 0.02 absolute completion fraction
```

```text
PASS: mean >= 0.02 AND one-sided 95% LCB > 0
FAIL: not PASS AND one-sided 95% UCB < 0.02
INCONCLUSIVE: all other valid results
PROTOCOL_FAIL: any protocol violation
```

Secondary metrics 和 sensitivity 均不能改变 primary verdict。

## Artifact/results audit chain

```text
validated H1 spec
-> experiment_spec_sha256
-> frozen ArtifactInventory
-> artifact_inventory_sha256
-> exact ArtifactInventoryEntry
-> safely loaded artifact
-> artifact config/content hashes
-> provenance-bound PairedTraceResult
-> paired_results_sha256
-> H1GateSummary
-> locked primary verdict
```

Formal sensitivity 必须重新验证 exact spec/inventory/results/provenance；旧 verdict 不能解锁
另一组 results。

## 独立候选审查

- 最终批准 WP-02D1 v2 patch SHA-256：
  `4ac551f9da3ab1e13e02173d8737336ad7aace4e1c233cf2b8b5036754af341e`
- patch：5 diff sections，159,896 bytes，4,062 insertions
- 最终结论：BLOCKER 0、MAJOR 0、MINOR 0

第一版审查曾发现两项 MAJOR：artifact/spec/environment 到 `PairedTraceResult` / aggregate 的
provenance 断链，以及 locked verdict 未绑定 exact inventory / paired results。v2 已全部修复并
独立复核通过。这是提交前 review gate 成功发现并修复的问题，不是发布失败。

## Mac 验收

- WP-02D1：60 passed
- WP-02A/B/C regression：148 passed
- 完整 CPU：629 passed
- Ruff：通过
- format：通过
- `git diff --check`：通过

## GitHub Actions

- Commit：`844de649c71e0a6a8fec6e1355cbf010db434f83`
- `CPU checks`：success
- 未记录未经确认的 run number

## A100 验收

```text
Commit：844de649c71e0a6a8fec6e1355cbf010db434f83
Ruff：All checks passed
format：79 files already formatted
完整 CPU：629 passed in 23.12s
CPU 验收：全部通过
最终工作树：干净
正式 H1：未运行
```

## Formal run remains zero

```text
Formal primary traces generated: 0 / 256
Formal H1 rollouts: 0
Formal artifacts/results/verdict: 0
```

没有运行 Primary H=2、formal H=0 set 或 sensitivity；没有写 formal primary JSONL，也没有计算
formal verdict。

## 下一阶段：WP-02D2

下一唯一工作是实现
`bounded task-target root-information exhaustive diagnostic verifier`，仅用于诊断 Primary
`RollingTrueFutureOracle` 的 greedy planning 是否可能造成 H1 false negative。它不是新的 public
baseline，也不声称 global optimum、continuous-control optimum 或 theoretical upper bound。

冻结硬边界为 resources ≤ 2、episode steps ≤ 4、events ≤ 3；环境分支必须使用真实
`ResourceServiceEnvironment` 并且只能调用 public `reset()` / `step()`。搜索期间 root K 冻结；
objective 只最大化 K 中 completed count，tie 只使用 deterministic canonical action-sequence
ordering。

预注册 suite 包含六类 fixtures；6A/6B H-window no-leakage pair 必须保留修正版 root H 外 event：
`arrival=3`、position `(+3,0)` / `(-3,0)`、`service_time=1`、`deadline=4`、`H=2`，不得退回旧
`±2` 版本。

WP-02D2 必须完成实现、完整候选 patch 审查、Commit/Push、GitHub Actions 与 Mac/A100
acceptance 后，才允许用户明确启动 formal artifact/H1 execution。
