# 项目状态

更新日期：2026-08-20

## 已验证稳定基线

```text
WP-02D1 实现 Commit：844de649c71e0a6a8fec6e1355cbf010db434f83
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
| WP-02D | 进行中 | D1 protocol/statistics 已完成；D2 bounded verifier 待实现；Formal H1 未运行 |
| WP-02D1 | 已完成 | strict H1 preregistration、artifact/results/verdict audit chain、paired runner 与统计基线 |
| WP-02D2 | 待实现 | 当前下一阶段：bounded task-target root-information exhaustive diagnostic verifier |

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
Formal experiment artifacts/results/verdict: 0
```

## 下一步：WP-02D2 bounded verifier

当前下一唯一工作是实现 `bounded task-target root-information exhaustive diagnostic verifier`，
仅用于诊断 Primary `RollingTrueFutureOracle` 是否因 greedy planning 太弱而产生 H1 false
negative；它不是新的 public baseline。

冻结边界：resources ≤ 2、episode steps ≤ 4、events ≤ 3；分支使用真实
`ResourceServiceEnvironment` 且只能通过 public `reset()` / `step()`。每个 root decision 的
`K = current active tasks + root official H-step future events`，搜索期间 K 冻结；下一真实 decision
boundary 才重建 K。不得读写 `env._state`、复制 transition logic 或引入 root H 外事件。

有限动作集为：SERVING 仅 Continue；AVAILABLE 可 Idle、legal Serve(K waiting) 或 Move(K event
positions)。Objective 仅最大化 K 中 completed count；完成数 tie 只使用 deterministic canonical
action-sequence ordering，不加入 priority、movement、waiting 或 reward weights。

预注册 suite 保留六类 fixtures：single-resource future preposition、current-vs-future conflict、
two future task greedy order、two-resource joint assignment、no-opportunity control，以及 6A/6B
H-window no-leakage pair。Fixture 6 的 root H 外 event 固定 `arrival=3`、position 为 `(+3,0)` /
`(-3,0)`、`service_time=1`、`deadline=4`、`H=2`；root snapshot/view 相同，root K IDs 为
`{0}`，Move targets 不含 `±3`，首个联合动作完全相同。不得退回旧 `±2` 版本。

WP-02D2 必须完成实现、完整 patch 审查、Commit/Push、GitHub Actions 与 Mac/A100 验收后，
才允许正式 artifact/H1 execution。当前不得生成 256 primary artifacts、运行 Primary H=2 或
formal H=0、运行 sensitivity、写 formal JSONL 或计算 verdict；也不得进入 prediction/MAPPO。
