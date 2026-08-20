# 会话交接

更新日期：2026-08-20

## 当前唯一任务

WP-02D2 `bounded task-target root-information exhaustive diagnostic verifier` implementation。
必须先形成完整候选 patch 并通过独立审查；本 docs-only checkpoint 不实现 verifier。

WP-02D1 已完成，WP-02D overall 仍在进行中。正式 H1 未运行。WP-02D2 完成实现、完整 patch
审查、Commit/Push、GitHub Actions 与 Mac/A100 acceptance 前，不得生成或运行正式 H1。

## 稳定基线

```text
WP-02D1 实现：844de649c71e0a6a8fec6e1355cbf010db434f83
WP-02C 实现：9159c841af4f605d6e32cca4b37940f0116a19cf
WP-02B 实现：f290a45a67763b41941e919303b26fb16a67575a
WP-02A 实现：d01092831a227a9f520de4ff8ded1d9e13ba8262
WP-01C 实现：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
WP-01C 标签：wp01c-stable
```

docs-only 收尾 Commit 不自引用自身 SHA；后续会话必须真实读取当前 HEAD。

## WP-02D1 完成结论

WP-02D1 是已冻结的 protocol/statistics implementation，不是 H1 scientific result。它至少
完成：

- strict H1 preregistration spec 与 deterministic experiment spec hash
- 固定 256-seed protocol：`20260819..20261074`
- Primary H=2；H sensitivity metadata 0/1/2/3/4；H=0 strict protocol invariant
- same-`DemandTrace` paired rollout 与独立 Reactive / Oracle environments
- canonical mechanism preflight、same-state counterfactual diagnostics 与 realized Oracle diagnostics
- strict artifact inventory/read-back 与 artifact config/content hash cross-validation
- provenance-bound `PairedTraceResult`、paired results digest、inventory digest
- environment config identity 与 experiment spec identity
- NumPy PCG64 paired percentile bootstrap：50,000 resamples，seed `90260819`
- `delta_min=0.02` 与 `PASS / FAIL / INCONCLUSIVE / PROTOCOL_FAIL`
- canonical JSON/JSONL、atomic no-overwrite outputs、locked primary verdict
- verdict 对 exact spec/inventory/results/provenance 的绑定
- local Git provenance hard gate；sensitivity 不能借旧 verdict 解锁或改变 primary verdict

## 冻结 Primary gate

每条 trace：

```text
arrived > 0:
    D_i = (completed_oracle - completed_reactive) / arrived
arrived == 0:
    D_i = 0

Primary estimand = mean(D_i)
Primary H = 2
N = 256
delta_min = 0.02 absolute completion fraction
```

Verdict：

```text
PASS: mean >= 0.02 AND one-sided 95% LCB > 0
FAIL: not PASS AND one-sided 95% UCB < 0.02
INCONCLUSIVE: all other valid results
PROTOCOL_FAIL: any protocol violation
```

Secondary metrics 与 sensitivity 均不能改变 primary verdict。

## 冻结 Primary stress cell

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

## Formal audit chain

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

## WP-02D1 审查与验收事实

### 独立候选审查

- 最终批准 v2 patch SHA-256：`4ac551f9da3ab1e13e02173d8737336ad7aace4e1c233cf2b8b5036754af341e`
- patch：5 diff sections，159,896 bytes，4,062 insertions
- 结论：BLOCKER 0、MAJOR 0、MINOR 0
- 第一版曾发现 artifact/spec/environment 到 result/aggregate 的 provenance 断链，以及 locked
  verdict 未绑定 exact inventory/results；v2 已修复并独立复核通过。这是提交前 review gate
  成功发现并修复的问题，不是发布失败。

### Mac / GitHub / A100

- Mac：WP-02D1 60 passed；WP-02A/B/C regression 148 passed；完整 CPU 629 passed；Ruff、
  format、`git diff --check` 通过
- GitHub Actions：Commit `844de649c71e0a6a8fec6e1355cbf010db434f83`；`CPU checks` success；
  未记录未经确认的 run number
- A100：同一 Commit；Ruff `All checks passed`；format `79 files already formatted`；完整 CPU
  `629 passed in 23.12s`；CPU 验收全部通过；最终工作树干净；正式 H1 未运行

## 当前 formal execution 状态

```text
Formal primary traces generated: 0 / 256
Formal H1 controller rollouts: 0
Formal experiment artifacts/results/verdict: 0
```

## WP-02D2 冻结实现边界

准确名称：`bounded task-target root-information exhaustive diagnostic verifier`。目标仅是诊断
Primary `RollingTrueFutureOracle` 是否因 greedy planning 太弱而产生 H1 false negative；它不是
新的 public baseline，也不是 global optimum、continuous-control optimum 或 theoretical upper
bound。

硬边界：resources ≤ 2、episode steps ≤ 4、events ≤ 3。环境分支使用真实
`ResourceServiceEnvironment`，只能通过 public `reset()` / `step()`，不得读写 `env._state` 或
复制 environment transition logic。

每个 root decision time：

```text
K = current active tasks + root official H-step future events
```

搜索期间 K 冻结，不刷新 future view 或引入 root H 外事件；下一真实 decision boundary 才重建
K。有限动作集：SERVING 仅 Continue；AVAILABLE 可 Idle、legal Serve(K waiting) 或 Move(K event
positions)。Objective 仅最大化 K 中 completed count；完成数 tie 只使用 deterministic canonical
action-sequence ordering，不加入 priority、movement、waiting 或 reward weights。

## 预注册 verifier suite

六类 fixtures 已冻结：

1. single-resource future preposition
2. current-vs-future conflict
3. two future task greedy order
4. two-resource joint assignment
5. no-opportunity control
6. 6A/6B H-window no-leakage pair

Fixture 6 必须使用修正版：root H 外 event 为 `arrival=3`、position `(+3,0)` / `(-3,0)`、
`service_time=1`、`deadline=4`、`H=2`。两条 trace 的 root snapshot 相同、root official view
相同、root K IDs 精确为 `{0}`、root Move targets 不含 `±3`，且 first joint action 完全相同。
不得退回旧 `±2` 版本。

## 当前禁止事项

WP-02D2 实现与全部验收完成前，不得：

- generate 256 primary artifacts
- run Primary H=2 或 formal H=0 set
- run sensitivity
- write formal primary JSONL
- calculate formal verdict
- 进入 prediction、uncertainty、MAPPO/RL、PyTorch/GPU 或正式主实验
