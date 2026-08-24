# 统计分析计划

状态：WP-02D1 primary H1 gate、WP-02D2 bounded diagnostic verifier 与 WP-02D3 Formal H1
execution hardening 均已完成并接受。formal data 尚未生成，formal H1 尚未运行。服务器不可用期间
允许 WP-03A prediction interface/dataset 基础设施开发，但不启动任何 official predictor、
forecast-control、uncertainty、ID/OOD 或 MAPPO scientific analysis。

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

服务器恢复后，必须以最新 accepted main 重新冻结 Formal H1 accepted execution baseline，随后在
执行前及关键 publication 边界验证真实 repo root、`main`、clean working tree、HEAD/origin、
accepted implementation/WP-02C ancestry 与实际 loaded code path。重新冻结 execution provenance
不得改变 H1 science 或下列科学 identities。

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

## 当前 formal execution 状态

```text
Formal primary traces generated: 0 / 256
Formal H1 controller rollouts: 0
Formal artifact inventory: 0
Formal paired results: 0
Formal aggregate: 0
Formal verdict: 0
Formal sensitivity: 0
```

WP-02D1、WP-02D2 与 WP-02D3 均已完成并接受；WP-02D overall 仍在进行中。当前允许 WP-03A
prediction interface/dataset 基础设施 implementation/review，不运行 prediction science 或 MAPPO。
Formal H1 只能在服务器恢复、latest accepted main 同步、execution provenance 重新冻结、readiness
preflight 与用户明确授权全部完成后启动。

正式 seeds 仍为 `20260819..20261074`，当前未生成 256 formal NPZ、formal artifact inventory、
formal paired JSONL、formal aggregate 或 formal primary verdict，也未运行 Primary H=2、formal
H=0、H sensitivity 或 stress sensitivity。本 checkpoint 不启动或解锁 formal data generation；
不得记录 formal point estimate、LCB/UCB 或正式 PASS/FAIL/INCONCLUSIVE/PROTOCOL_FAIL outcome。
在有效 Formal H1 scientific gate 结果产生并完成解释前，不进行 official predictor、forecast
uncertainty/control、ID/OOD、MAPPO 或 PyTorch/GPU training；WP-03A 的 deterministic interface /
dataset protocol 基础设施不构成科学结果。
