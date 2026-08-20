# 统计分析计划

状态：WP-02D1 primary H1 gate 已预注册冻结并实现；formal data 尚未生成，formal H1 尚未运行。

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

Verdict 必须绑定 exact spec/inventory/results/provenance；formal sensitivity 必须重新验证该完整
链，旧 verdict 不能解锁另一组 results。任何生成、读取、hash、配对或 provenance 失败均 hard
fail，不得删除 seed、替换 seed 或静默排除。

## Negative-result 诊断

Primary 不 PASS 时，依次检查 H=0、canonical mechanism、load/opportunity diagnostics、统计
precision，最后运行预注册 WP-02D2 bounded verifier suite。Verifier miss 只能阻止把 negative
result 解释为“未来信息没有价值”，不能把 primary verdict 改成 PASS。

## 当前 formal execution 状态

```text
Formal primary traces generated: 0 / 256
Formal H1 controller rollouts: 0
Formal experiment artifacts/results/verdict: 0
```

WP-02D2 完成实现、完整候选 patch 审查、Commit/Push、GitHub Actions 与 Mac/A100 acceptance
前，不得运行 Primary H=2、formal H=0 或 sensitivity，也不得计算 formal verdict。
