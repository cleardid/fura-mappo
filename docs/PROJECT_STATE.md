# 项目状态

更新日期：2026-08-21

## 已验证稳定基线

```text
WP-02D3 实现 Commit：1092d9c87bfff8ba6c1f2132734480112d7b5975
WP-02D2 docs checkpoint：6c2e8c67598f0d2ceda727d3c975a18fa6037fdd
WP-02D2 实现 Commit：cfab8c1b1981ef095d68969fff74faa2ac4f256d
WP-02D1 实现 Commit：844de649c71e0a6a8fec6e1355cbf010db434f83
WP-02D1 docs checkpoint：fe1b97496c937ec6f660c48419441eb9569e31ba
WP-02C 实现 Commit：9159c841af4f605d6e32cca4b37940f0116a19cf
WP-02B 实现 Commit：f290a45a67763b41941e919303b26fb16a67575a
WP-02A 实现 Commit：d01092831a227a9f520de4ff8ded1d9e13ba8262
WP-01C 实现 Commit：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
稳定标签：wp01c-stable
WP-01B：wp01b-stable
WP-01A：wp01a-stable
WP-00：wp00-stable
```

docs-only 收尾 Commit 不自引用自身 SHA；当前 HEAD 以 `git rev-parse HEAD` 为准。

## 工作包状态

| 工作包 | 状态 | 说明 |
|---|---|---|
| WP-00 | 已完成 | 项目骨架、环境、测试、CI、系统审计 |
| OPS-01 | 已完成 | main-only、补丁审查、CPU 验收 |
| WP-01A | 已完成 | 核心数据结构、状态机、Stationary |
| WP-01B | 已完成 | Drifting、Markov、Burst |
| WP-01C | 已完成 | YAML、hash、NPZ artifact、CLI、summary |
| WP-02A | 已完成 | 确定性资源服务环境；Mac、GitHub Actions、A100 验收通过 |
| WP-02B | 已完成 | Reactive baseline；Mac、独立审查、GitHub Actions、A100 验收通过 |
| WP-02C | 已完成 | Rolling True-future Oracle；Mac、独立审查、GitHub Actions、A100 验收通过 |
| WP-02D | 进行中 | D1、D2、D3 均已接受；Formal H1 scientific gate 未运行 |
| WP-02D1 | 已完成 | strict H1 preregistration、artifact/results/verdict audit chain、paired runner 与统计基线 |
| WP-02D2 | 已完成 | bounded task-target root-information exhaustive diagnostic verifier 已接受 |
| WP-02D3 | 已完成 | Formal H1 execution orchestration / persistence hardening 已接受 |

## WP-01 冻结接口与协议

```text
DemandEvent
DemandStep
DemandTrace
DemandProcess
StationaryPoissonDemand
DriftingHotspotDemand
MarkovSwitchingDemand
BurstDemand
create_demand_process
create_numpy_generator
load_demand_config
compute_config_hash
DemandTraceArtifact
save_demand_trace
load_demand_trace
summarize_demand_trace
```

```text
fura-mappo.demand-generation v1
fura-mappo.demand-trace v1
fura-mappo.demand-summary v1
sha256-logical-v1
```

## WP-01C 验收

### Mac
- Python 3.11.15
- 421 passed
- Ruff / format / diff-check：通过

### 独立审查
- 最终批准候选 patch：`bea26147f19ed6db311040ae54a4192e0e82731a0b17c65296e5dfd2c79b917d`
- 多轮安全边界审查与聚焦修复后无阻断问题
- 发布时仅 Diff 段顺序不同；经逐文件字节比较确认内容一致

### GitHub
- Commit：`29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`
- CPU checks：run #7
- 结论：success

### A100
```text
Commit：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
Python：3.11.15
Conda：fura-mappo
Pytest：421 passed in 16.54s
CPU 验收：通过
```

## WP-02A 冻结能力

- deterministic `ResourceServiceEnvironment`
- 仅接受 `DemandTrace` 作为环境需求输入
- 连续二维欧氏移动与同质资源
- 精确位置服务，Move/Serve slot 互斥
- 非抢占服务
- completion → expiration → truncation 边界顺序
- canonical `resource_to_event` assignment
- 事务式 `reset` / `step`
- future Serve side-channel 隔离
- 确定性 duplicate assignment resolution
- 组成指标与精确守恒检查
- 不包含 reward、RL、Reactive 或 Oracle

稳定实现 Commit：`d01092831a227a9f520de4ff8ded1d9e13ba8262`。

## WP-02A 验收

### 独立 patch 审查

- 最终批准 patch SHA-256：`74b74cd9590eea1498152a81dc747cadf676d66890516c6460c07c819cd49e81`
- 第一轮独立审查发现并修复：合法移动浮点收缩 MAJOR、超大有限实数 `OverflowError` MINOR
- v2 独立复核：BLOCKER 0、MAJOR 0、MINOR 0

### Mac

- Python 3.11.15
- WP-02A 专项：55 passed
- 全量：476 passed
- Ruff、format、diff-check：通过

### GitHub Actions

- `CPU checks`：success
- 未记录未经仓库确认的 run number

### A100

```text
Commit：d01092831a227a9f520de4ff8ded1d9e13ba8262
Python：3.11.15
Conda：fura-mappo
WP-02A 专项：55 passed in 0.26s
全量：476 passed in 17.45s
Ruff：通过
format：64 files already formatted
最终工作树：干净
```

`python -m pip install -e ".[dev]"` 因 build isolation 尝试经失效代理
`127.0.0.1:17890` 获取 `setuptools>=69` 而失败。这是依赖重装步骤的网络/代理
失败，不是项目测试成功；未将其伪装为成功，也未据此修改项目依赖或环境配置。
随后在现有 Conda 环境执行 pip dependency check，结果为
`No broken requirements found`，且上述专项与完整 CPU 验收全部通过。

## WP-02B 冻结能力

- deterministic `ReactiveController`
- centralized、current-state-only、stateless、RNG-free、reservation-free
- controller 只动态消费 `EnvironmentSnapshot`，只额外持有 `movement_speed`
- 不访问 `DemandTrace`、future events、intensity 或 hidden demand state
- SERVING resource 固定返回 `ContinueAction`
- 仅 WAITING task 进入候选
- exact bounded travel feasibility
- 环境与 baseline 共用唯一内部 single-slot movement primitive
- 不使用 `ceil(distance / speed)` 作为 exact physical truth
- task 排序：`latest_service_start` → higher priority → earlier `arrival_step` → smaller `event_id`
- resource 排序：exact `travel_slots` → Euclidean distance → `resource_id`
- unique greedy matching；无 controller-side reservation
- 正常 Reactive rollout 不主动产生 duplicate Serve
- 直接使用 WP-02A `EpisodeMetrics`
- 不包含 reward、Oracle、prediction 或 RL

WP-02A 公共环境行为未改变；原 single-slot movement physics 仅机械抽取为共享内部
primitive。稳定实现 Commit：`f290a45a67763b41941e919303b26fb16a67575a`。

## WP-02B 验收

### Mac

- Python 3.11.15
- 全量：520 passed in 5.80s
- Ruff、format、diff-check：通过

### 独立候选审查

- 最终批准 patch SHA-256：`38648aac6ae7d92766244ee2d226cc2a32a4a6d2337b8a039432f0daaadf191f`
- 结论：BLOCKER 0、MAJOR 0、MINOR 0
- 隔离复测 WP-02B + WP-02A regression：99 passed
- 额外确定性 rollout 探测：1000 episodes，无非法动作、非确定行为或 duplicate Serve

上述 99 tests 与 1000 episodes 是独立候选审查证据，不是完整仓库验收结果。

### GitHub Actions

- `CPU checks`：success
- 未记录未经确认的 run number

### A100

```text
Commit：f290a45a67763b41941e919303b26fb16a67575a
全量：520 passed in 16.67s
CPU 验收：全部通过
最终工作树：干净
```

## WP-02C 冻结能力

- public immutable `TrueFutureView`
- public `build_true_future_view(...)`
- deterministic `RollingTrueFutureOracle`
- H-step bounded true-future `DemandEvent` information
- controller 不持有 `DemandTrace`，不访问 intensity、counts、hidden demand state、seed、
  RNG、config 或 artifact manifest
- explicit nonnegative horizon；H=0 view 严格为空；future window 受 episode 终点裁剪
- official builder 执行最低限度 prefix/pairing validation；manual view 在 `act()` 中复核
- future/current event ID overlap 防护
- future arrival 前允许 Move/pre-position，禁止 Serve；提前到达目标后 Idle
- future 到达后由 `EnvironmentSnapshot` current WAITING task 表示
- stateless receding-horizon replanning；无 reservation、history、RNG 或 persistent plan
- expanded current + future candidate greedy matching
- task 排序：`latest_service_start` → higher priority → earlier `arrival_step` → smaller `event_id`
- resource 排序：exact `travel_slots` → Euclidean distance → `resource_id`
- exact feasibility 复用 WP-02A/B shared movement physics，不以 `ceil(distance / speed)`
  作为物理真值
- empty future view 或所有 future-resource pair 均 physically infeasible 时结构性委托 Reactive
- H=0 action、`StepResult`、`EpisodeMetrics` 与 Reactive 完全一致
- canonical mechanism：Move → Move → Serve → completed

稳定实现 Commit：`9159c841af4f605d6e32cca4b37940f0116a19cf`。

Primary Oracle 的准确含义是 H-step rolling true-future matched heuristic；它不是 global
optimum、optimal controller 或 theoretical upper bound。它证明 bounded true-future event
可以影响 pre-position/matching，但 Oracle 未优于 Reactive 时，不能单独据此断言未来信息
没有价值。

## WP-02C 验收

### Mac

- Python 3.11.15
- WP-02C Oracle：49 passed
- WP-02B Reactive：38 passed
- WP-02A environment：61 passed
- 全量：569 passed in 5.69s
- `pip check`：`No broken requirements found`
- Ruff：通过
- format：74 files already formatted
- `git diff --check`：通过

### 独立候选审查

- 最终批准 patch SHA-256：`5dad6a0c966548bfc981cc8f48a2f84d6f9a5cafe4b2a351c299e2b578c9558a`
- patch：4 diff sections，56,069 bytes
- 结论：BLOCKER 0、MAJOR 0、MINOR 0
- patch apply / whitespace check：passed
- `oracle.py` / test file syntax：passed
- 5000 randomized legal snapshot/future-view cases：passed
- canonical H=2 mechanism：Move → Move → Serve

上述随机探测属于独立候选审查证据，不是完整仓库正式验收。

### GitHub Actions

- Commit：`9159c841af4f605d6e32cca4b37940f0116a19cf`
- `CPU checks`：success
- 未记录未经确认的 run number

### A100

- Commit：`9159c841af4f605d6e32cca4b37940f0116a19cf`
- CPU 验收：全部通过

## WP-02D1 冻结能力

WP-02D1 是 protocol/statistics implementation，不是 H1 scientific result。稳定实现 Commit：
`844de649c71e0a6a8fec6e1355cbf010db434f83`。

- strict H1 preregistration spec 与 deterministic experiment spec hash
- 固定 256 seeds：`20260819..20261074`
- Primary H=2；H metadata 为 0/1/2/3/4；H=0 strict protocol invariant
- same-`DemandTrace` paired rollout 与独立 Reactive / Oracle environments
- canonical mechanism preflight、same-state counterfactual diagnostics 与 realized Oracle diagnostics
- strict artifact inventory/read-back、artifact config/content hash cross-validation
- provenance-bound `PairedTraceResult`、paired results digest 与 artifact inventory digest
- environment config identity 与 experiment spec identity
- NumPy `Generator(PCG64(90260819))` paired percentile bootstrap，50,000 resamples
- `delta_min=0.02` 与 `PASS / FAIL / INCONCLUSIVE / PROTOCOL_FAIL`
- canonical JSON/JSONL、atomic no-overwrite outputs 与 locked primary verdict
- verdict 绑定 exact spec/inventory/results/provenance；sensitivity 不能借旧 verdict 解锁
- local Git provenance hard gate；sensitivity 不能改变 primary verdict

## WP-02D Primary gate

每条 trace 若 `arrived > 0`：

```text
D_i = (completed_oracle - completed_reactive) / arrived
```

若 `arrived == 0`，`D_i = 0`。Primary estimand 为 `mean(D_i)`，每条 trace 等权。

```text
Primary H = 2
N = 256
delta_min = 0.02 absolute completion fraction

PASS: mean >= 0.02 AND one-sided 95% LCB > 0
FAIL: not PASS AND one-sided 95% UCB < 0.02
INCONCLUSIVE: all other valid results
PROTOCOL_FAIL: any protocol violation
```

Secondary metrics 与 sensitivity 均不能改变 primary verdict。

## WP-02D Primary stress cell

- `DriftingHotspotDemand`
- `base_intensities=[0.025,0.025,0.025,0.025]`
- `hotspot_amplitudes=[0.55]`，`hotspot_scales=[0.45]`
- initial hotspot `(0.5,0.5)`，velocity `(0.25,0.0)`
- 四个连续 1×1 zones：`x in [0,4]`、`y in [0,1]`
- `priority_range=[0.5,0.5]`
- `service_time_range=[1,2]`，`deadline_offset_range=[2,3]`
- 256 steps；2 resources，初始位置 `(0.5,0.5)` 与 `(3.5,0.5)`
- `movement_speed=0.75`；Primary H=2

## WP-02D1 formal audit chain

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

## WP-02D1 验收

### 独立候选审查

- 最终批准 v2 patch SHA-256：`4ac551f9da3ab1e13e02173d8737336ad7aace4e1c233cf2b8b5036754af341e`
- patch：5 diff sections，159,896 bytes，4,062 insertions
- 结论：BLOCKER 0、MAJOR 0、MINOR 0
- 第一版发现的两项 provenance / verdict binding MAJOR 已在提交前 review gate 修复；不是发布失败

### Mac

- WP-02D1：60 passed
- WP-02A/B/C regression：148 passed
- 完整 CPU：629 passed
- Ruff、format、`git diff --check`：通过

### GitHub Actions

- Commit：`844de649c71e0a6a8fec6e1355cbf010db434f83`
- `CPU checks`：success
- 未记录未经确认的 run number

### A100

```text
Commit：844de649c71e0a6a8fec6e1355cbf010db434f83
Ruff：All checks passed
format：79 files already formatted
完整 CPU：629 passed in 23.12s
CPU 验收：全部通过
最终工作树：干净
正式 H1：未运行
```

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

## WP-02D2 冻结能力

WP-02D2 accepted implementation Commit：
`cfab8c1b1981ef095d68969fff74faa2ac4f256d`（`feat: add bounded root-information verifier`）。
准确定位是 `bounded task-target root-information exhaustive diagnostic verifier`。它仅用于诊断
Primary `RollingTrueFutureOracle` 是否因 greedy planning 太弱而产生 H1 false negative；不是
formal baseline、global optimum、continuous-control optimum、theoretical upper bound、optimal
policy 或 Primary adequacy proof。Verifier 保持在 `fura_mappo.experiments` 私有模块中，未进入
public API；`h1_gate.py`、environment physics、Reactive、Primary Oracle 和 formal H1
preregistration 均未修改。

硬边界为 resources ≤ 2、episode steps ≤ 4、events ≤ 3。分支使用真实
`ResourceServiceEnvironment`，transition 只允许 public `reset()` / `step()`；禁止访问
`env._state` 或其他 private environment state，禁止复制 transition logic。每个 candidate branch
使用 fresh environment 和 deterministic prefix replay，并执行精确 public replay consistency
checks。

每个真实 decision boundary 由 `build_true_future_view(...)` 生成 official view，并冻结：

```text
K = current active tasks + official H-step future view events
```

root search 内 K 不缩减、不刷新 future view、不引入 root horizon 外事件；一直穷举到 episode
terminal，不使用 pruning、memoization、symmetry reduction 或 dominance。下一真实 boundary 才
重新构造 K 并重新搜索。SERVING 仅有 `ContinueAction`；AVAILABLE 可 `IdleAction`、对 frozen-K
current WAITING event 的 legal `ServeAction`，以及 target 来自 frozen-K event positions 的
`MoveAction`。zero-distance Move 与 environment-legal duplicate Serve joint actions 均保留。

唯一 objective 是 maximize `completed_over_K`；tie-break 仅按 deterministic canonical complete
action-sequence key 的字典序最小值，不使用 priority、movement distance、wait、reward 或任何
secondary objective。Canonical ordering 是：

```text
ContinueAction -> (0,)
IdleAction     -> (1,)
MoveAction     -> (2, x, y)
ServeAction    -> (3, event_id)
```

Joint action 按 increasing `resource_id`，sequence 按 increasing time。rolling verifier 在每个真实
boundary 只采用最佳完整 sequence 的 first joint action。

## WP-02D2 预注册 fixtures 与 diagnostic label

以下仅为 handcrafted fixture unit-test expectations，不是 Formal H1 outcome 或 formal primary
evidence：

| Fixture | Primary | Verifier |
|---|---:|---:|
| F1 | 1 | 1 |
| F2 | 1 | 2 |
| F3 | 1 | 2 |
| F4 | 1 | 2 |
| F5 | 0 | 0 |
| F6A | 1 | 1 |
| F6B | 1 | 1 |

Fixture 6 使用修正版：6A root-H 外 event position 为 `(3,0)`，6B 为 `(-3,0)`，不得退回旧
`±2`。测试冻结 root snapshots identical、root official views identical、root K IDs 为 `{0}`、
root Move targets 排除 `(3,0)` 与 `(-3,0)`，且 6A/6B verifier first joint action identical；不预先
指定该动作必须为某个 Idle/Move。

冻结 classifier：任一 preregistered fixture 满足 verifier completed > Primary completed 时，标签为
`PRIMARY_HEURISTIC_MISS_DETECTED`；否则为
`NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE`。后一个标签不表示 Primary
optimal 或 heuristic adequacy proven，任何标签都不是 Formal H1 scientific outcome，verifier
output 也不进入 formal primary verdict 输入。

## WP-02D2 验收

### 独立 patch 审查

- 批准 patch SHA-256：`f6cb0e8638847b4b84f84421f5bbc77926abc6995a4704f6cb11300ff8ff172f`
- patch：2 diff sections，38,147 bytes，2 files changed，998 insertions，0 deletions
- 结论：BLOCKER 0、MAJOR 0、MINOR 0
- accepted implementation 仅新增 `src/fura_mappo/experiments/_bounded_verifier.py` 与
  `tests/test_bounded_verifier.py`

### Mac

- WP-02D2 dedicated：35 passed
- WP-02A/B/C/D1 relevant regression：208 passed
- full CPU：664 passed
- Ruff：passed
- format：82 files already formatted

### GitHub Actions

- Commit：`cfab8c1b1981ef095d68969fff74faa2ac4f256d`
- `CPU checks`：success
- 未记录未经仓库确认的 run number

### A100 server CPU acceptance

```text
Commit: cfab8c1b1981ef095d68969fff74faa2ac4f256d
WP-02D2 dedicated: 35 passed in 6.35s
full CPU: 664 passed in 26.76s
Ruff: All checks passed!
format: 82 files already formatted
git diff --check: passed
final working tree: clean
```

上述为 A100 CPU acceptance，不是 GPU test，未执行 PyTorch/GPU workload。

## WP-02D3 冻结能力

WP-02D3 accepted implementation Commit 与 Formal H1 accepted implementation SHA：
`1092d9c87bfff8ba6c1f2132734480112d7b5975`。准确定位是
`Formal H1 execution orchestration / persistence hardening`；它不改变 H1 scientific
specification、environment science、Reactive、Primary Oracle、D2 verifier 或 preregistration。

最终实现精确修改以下 6 个文件：

```text
src/fura_mappo/demand/serialization.py
src/fura_mappo/experiments/h1_gate.py
src/fura_mappo/experiments/_formal_h1_runner.py
tests/test_demand_serialization.py
tests/test_h1_gate.py
tests/test_formal_h1_runner.py
```

冻结能力包括：

- private `fura_mappo.experiments._formal_h1_runner`，不进入 public experiments API
- real repo root、exact `main`、clean tree、HEAD/origin、accepted/WP-02C ancestry 与
  docs-only descendant Git provenance hard gates，并在关键 publication 边界重复 revalidate
- actual loaded Python modules 必须来自 current repo `src/fura_mappo` 的 code-path binding
- 唯一固定 spec、formal run root、traces、inventory、paired JSONL、aggregate 与 verdict 路径
- path confinement、symlink/unknown evidence rejection 与不自动删除、覆盖、修复的 no-overwrite
  policy
- provenance-bound exact 256 trace plan 与 strict restart/resume；无 replacement seed
- H=0 invariant、canonical mechanism preflight、Primary H=2 paired rollouts 的冻结 pipeline order
- strict canonical paired JSONL、aggregate 与 verdict readback；disk summary 必须等于 recomputation
- `PROTOCOL_FAIL` strict verdict read 与 sensitivity unlock guard 分离；PROTOCOL_FAIL 永不解锁
- protocol JSON/JSONL、NPZ hard-link publication 与首次 formal directory creation 的 crash durability
- final verdict strict readback 前不输出 per-seed `D_i` 或 provisional scientific statistics/verdict

固定 formal 路径：

```text
spec:       configs/experiments/wp02d_h1.yaml
run root:   artifacts/wp02d_h1_formal_v1/
traces:     artifacts/wp02d_h1_formal_v1/traces/
inventory:  artifacts/wp02d_h1_formal_v1/artifact_inventory.json
paired:     artifacts/wp02d_h1_formal_v1/primary_paired_results.jsonl
aggregate:  artifacts/wp02d_h1_formal_v1/primary_aggregate.json
verdict:    artifacts/wp02d_h1_formal_v1/primary_verdict.json
```

未来调用必须继续传 accepted implementation SHA：

```bash
python -m fura_mappo.experiments._formal_h1_runner \
  --accepted-implementation-sha 1092d9c87bfff8ba6c1f2132734480112d7b5975
```

未来 docs checkpoint Commit 是该 implementation 的合法 docs-only descendant，不替代 accepted
implementation SHA。本 checkpoint 不执行上述命令。

## WP-02D3 验收

### 独立 patch 审查

- 最终批准 patch：`wp02d3-review-v4.patch`
- SHA-256：`f4dd19abd16723d19508b26f89ad1a93e4e4a1b468aa13a9785baa8ec86b82a9`
- 120,831 bytes；6 diff sections；6 files changed；2,718 insertions；80 deletions
- 结论：BLOCKER 0、MAJOR 0、MINOR 0
- v1-v4 发现项均为提交前质量关口识别并修复的 execution-readiness 问题，不是 Formal H1 或
  scientific failure

### GitHub Actions

- Commit：`1092d9c87bfff8ba6c1f2132734480112d7b5975`
- two Actions/checks passed
- 未记录未经确认的 run number、job ID、duration 或 workflow name

### A100 server CPU acceptance

```text
Commit: 1092d9c87bfff8ba6c1f2132734480112d7b5975
Focused WP-02D3 acceptance: 207 passed in 16.87s
Full CPU: 720 passed in 34.31s
Ruff: All checks passed!
Format: 85 files already formatted
git diff --check: passed
Final working tree: clean
```

这是 A100 server CPU acceptance，不是 PyTorch、CUDA、GPU test 或 Formal H1 execution。

冻结 scientific identities 保持不变：

```text
H1 spec SHA-256:
fc719e4634ab13ba55d0b95e63497688b3ab07c259d1421c5ed0c468cec3fade

Primary environment config SHA-256:
d1d856b13ac8edf79422428a96bddc03b901053dbeaabe56571e9baeef6eafa1
```

## 下一步：Final Formal H1 execution-readiness freeze / runbook freeze

WP-02D1、WP-02D2 与 WP-02D3 均已完成并接受，但 WP-02D overall 仍在进行中，因为 Formal H1
scientific gate 尚未执行。下一阶段是在生成任何正式 primary trace 前进行最终只读
execution-readiness/runbook freeze，验证本 docs checkpoint 已 Push、current `main` clean、
HEAD 等于 `origin/main`、`1092d9c...` ancestry、accepted SHA 后仅 docs/changelog changes、actual
loaded code path、exact spec/environment identities、formal-data-zero、exact frozen invocation 与
用户明确授权。

Formal H1 只能在本 docs-only checkpoint Commit/Push、最终 freeze 与用户明确授权全部完成后启动。
本 checkpoint 不启动或解锁 formal data generation。当前 Formal H1 仍未运行，formal primary
traces 仍为 `0 / 256`，正式 seeds 仍为 `20260819..20261074`；未生成 256 formal NPZ、formal
artifact inventory、formal paired JSONL、formal aggregate 或 formal primary verdict，也未运行
formal H=0 set、formal H=2 primary rollout、H sensitivity 或 stress sensitivity。不得记录任何
formal point estimate、LCB/UCB 或 PASS/FAIL/INCONCLUSIVE/PROTOCOL_FAIL outcome。

在 Formal H1 scientific gate 产生有效结果并完成解释前，继续禁止进入 prediction、forecast
uncertainty、MAPPO、PyTorch/GPU training 或 ID/OOD main experiment。
