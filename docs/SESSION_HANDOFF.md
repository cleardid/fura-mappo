# 会话交接

更新日期：2026-08-21

## 当前唯一任务

下一阶段唯一任务为：

```text
Final Formal H1 execution-readiness freeze / runbook freeze

DO NOT RUN FORMAL H1 YET
Formal traces = 0 / 256

accepted implementation SHA =
1092d9c87bfff8ba6c1f2132734480112d7b5975
```

WP-02D1、WP-02D2 与 WP-02D3 均已完成并接受，但 WP-02D overall 仍在进行中，因为 Formal H1
scientific gate 尚未执行。本 docs-only checkpoint 只记录 accepted facts，不启动或解锁 formal
data generation。未来 docs checkpoint SHA 不替代上述 accepted implementation SHA。

## 稳定基线

```text
WP-02D3 实现：1092d9c87bfff8ba6c1f2132734480112d7b5975
WP-02D2 docs checkpoint：6c2e8c67598f0d2ceda727d3c975a18fa6037fdd
WP-02D2 实现：cfab8c1b1981ef095d68969fff74faa2ac4f256d
WP-02D1 docs checkpoint：fe1b97496c937ec6f660c48419441eb9569e31ba
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

## WP-02D2 接受结论

accepted implementation Commit 为 `cfab8c1b1981ef095d68969fff74faa2ac4f256d`，提交说明为
`feat: add bounded root-information verifier`。准确名称是
`bounded task-target root-information exhaustive diagnostic verifier`。它是 private、
diagnostic-only verifier，不是 formal baseline、global optimum、continuous-control optimum、
theoretical upper bound、optimal policy 或 Primary adequacy proof。

实现只新增：

```text
src/fura_mappo/experiments/_bounded_verifier.py
tests/test_bounded_verifier.py
```

`fura_mappo.experiments` public API 未导出 verifier；`h1_gate.py`、environment physics、Reactive、
Primary Oracle 与 formal H1 preregistration 均未修改。

### 独立审查与验收

- 批准 patch SHA-256：`f6cb0e8638847b4b84f84421f5bbc77926abc6995a4704f6cb11300ff8ff172f`
- patch：2 diff sections，38,147 bytes，2 files changed，998 insertions，0 deletions
- 独立审查：BLOCKER 0、MAJOR 0、MINOR 0
- Mac：WP-02D2 dedicated 35 passed；WP-02A/B/C/D1 relevant regression 208 passed；full CPU
  664 passed；Ruff passed；format 82 files already formatted
- GitHub Actions：Commit `cfab8c1b1981ef095d68969fff74faa2ac4f256d`；`CPU checks` success；
  未记录未经仓库确认的 run number
- A100 server CPU acceptance：同一 Commit；WP-02D2 dedicated `35 passed in 6.35s`；full CPU
  `664 passed in 26.76s`；Ruff `All checks passed!`；format `82 files already formatted`；
  `git diff --check` passed；final working tree clean

A100 记录是 CPU acceptance，不是 GPU test，未执行 PyTorch/GPU workload。

## WP-02D3 接受结论

WP-02D3 accepted implementation Commit 与 Formal H1 accepted implementation SHA 均为：

```text
1092d9c87bfff8ba6c1f2132734480112d7b5975
```

准确定位是 `Formal H1 execution orchestration / persistence hardening`。它不改变 H1 科学规格，
不修改 environment science、Reactive、Primary Oracle、D2 verifier 或 preregistered H1 statistics。
最终实现精确修改 6 个文件：

```text
src/fura_mappo/demand/serialization.py
src/fura_mappo/experiments/h1_gate.py
src/fura_mappo/experiments/_formal_h1_runner.py
tests/test_demand_serialization.py
tests/test_h1_gate.py
tests/test_formal_h1_runner.py
```

Private runner `fura_mappo.experiments._formal_h1_runner` 未从 `experiments/__init__.py` 导出。
未来冻结调用为：

```bash
python -m fura_mappo.experiments._formal_h1_runner \
  --accepted-implementation-sha 1092d9c87bfff8ba6c1f2132734480112d7b5975
```

本 checkpoint 禁止执行。未来 docs-only checkpoint Commit 是 `1092d9c...` 的合法
`docs/**` / `CHANGELOG_*` descendant，但不是新的 implementation baseline，不得作为
`--accepted-implementation-sha`。

### Execution hard gates

- cwd 必须是真实 repository root；branch 精确为 `main`；working tree clean；
  `actual HEAD == origin/main`
- WP-02C stable SHA 与 accepted implementation SHA 必须是 actual execution HEAD ancestors；
  accepted SHA 后只允许 docs/changelog changes
- 实际 imported `fura_mappo`、runner、H1 gate、demand、env 与 baselines code 必须来自当前 repo
  的 `src/fura_mappo`；old wheel、其他 checkout 或无关 package path hard fail
- 正式 spec 固定为 `configs/experiments/wp02d_h1.yaml`；正式 root 固定为
  `artifacts/wp02d_h1_formal_v1/`，其 `traces/`、inventory、paired JSONL、aggregate 与 verdict
  路径均唯一固定
- symlink component、unknown file、invalid evidence hard fail；不自动删除、覆盖或修复
- provenance 在正式 publication 关键边界重复 revalidate

### Restart/resume、strict readback 与 durability

Inventory 已存在时不得再生成 trace，必须 strict read inventory 并 strict validate 全部 256 NPZ；
missing/invalid hard fail，不 regenerate。Inventory 不存在时，已有 trace 只能 provenance-bound
strict reuse；缺失 trace 才能在 provenance revalidation 后 exactly-once no-overwrite 生成、strict
reload 并验证。全部 256 valid 后才能发布并 strict readback inventory。

Paired JSONL 使用 strict UTF-8、duplicate/non-finite/Unicode/schema/order/hash checks 与 canonical
writer representation；aggregate 必须从 strict paired results 重新计算并与 strict disk summary
相等；verdict 必须 strict bind exact spec/inventory/results/provenance。`PROTOCOL_FAIL` 可由 strict
reader 读取，但永不能通过 sensitivity unlock guard。

Protocol JSON/JSONL publication、NPZ no-overwrite publication 与首次 formal directory creation
均冻结 parent-directory fsync crash durability；这些不改变 scientific content。runner 在 final
verdict strict readback 前不输出 per-seed `D_i` 或 provisional scientific statistics/verdict。

### 独立审查与验收

- 最终批准 `wp02d3-review-v4.patch`：120,831 bytes，6 diff sections，6 files changed，
  2,718 insertions、80 deletions
- SHA-256：`f4dd19abd16723d19508b26f89ad1a93e4e4a1b468aa13a9785baa8ec86b82a9`
- 独立 review：BLOCKER 0、MAJOR 0、MINOR 0
- GitHub Actions：Commit `1092d9c87bfff8ba6c1f2132734480112d7b5975`，two checks passed
- A100 server CPU：focused `207 passed in 16.87s`；full `720 passed in 34.31s`；Ruff
  `All checks passed!`；format `85 files already formatted`；`git diff --check` passed；final
  working tree clean

以上是 CPU acceptance，不是 GPU、PyTorch、CUDA 或 Formal H1 execution。

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

## WP-02D2 冻结实现边界

目标仅是诊断 Primary `RollingTrueFutureOracle` 是否因 greedy planning 太弱而产生 H1 false
negative。Verifier output 不进入 formal primary verdict 输入。

硬边界：resources ≤ 2、episode steps ≤ 4、events ≤ 3。环境分支使用真实
`ResourceServiceEnvironment`，只能通过 public `reset()` / `step()`，不得读写 `env._state` 或
其他 private environment state，也不得复制 environment transition logic。每个 candidate branch
使用 fresh environment、deterministic prefix replay 和 exact public replay consistency checks。

每个 root decision time：

```text
K = current active tasks + root official H-step future events
```

official view 由 `build_true_future_view(...)` 构造。搜索期间 K 冻结，不刷新 future view 或引入
root H 外事件；下一真实 decision boundary 才重建 K 并重新 exhaustive search。有限动作集：
SERVING 仅 Continue；AVAILABLE 可 Idle、legal Serve(frozen-K current WAITING) 或 Move(frozen-K
event positions)；保留 zero-distance Move 与 environment-legal duplicate Serve joint actions。

Root search 一直搜索至 episode terminal，不使用 pruning、memoization、symmetry reduction 或
dominance。Objective 仅 maximize `completed_over_K`；tie 仅 lexicographically minimize canonical
complete sequence key，不加入 priority、movement distance、wait、reward 或 secondary objective：

```text
ContinueAction -> (0,)
IdleAction     -> (1,)
MoveAction     -> (2, x, y)
ServeAction    -> (3, event_id)
```

Joint action 按 increasing resource_id，sequence 按 increasing time。该 ordering 不是 performance
preference。rolling verifier 每个真实 boundary 只采用最佳完整 sequence 的 first joint action。

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

Handcrafted fixture unit-test expectations 为：

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

这些是 unit-test expectations，不是 Formal H1 outcome 或 formal primary evidence。冻结 classifier：
任一 fixture 的 verifier completed > Primary completed 时为
`PRIMARY_HEURISTIC_MISS_DETECTED`；否则为
`NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE`。后者不表示 Primary optimal
或 heuristic adequacy proven；两个标签都不是 Formal H1 scientific outcome。

## 下一阶段 final readiness/runbook freeze 与当前禁止事项

`Final Formal H1 execution-readiness freeze / runbook freeze` 必须在任何正式 primary trace 生成前
只读验证：本 docs checkpoint 已 Commit/Push；current `main` clean；HEAD 等于 `origin/main`；
`1092d9c...` 是 current HEAD ancestor；accepted SHA 后仅有 docs/changelog changes；loaded code
来自当前 repo；exact spec/environment hashes 不变；formal root 不存在；traces 为 `0 / 256`；冻结
调用精确无误；最后取得用户明确授权。

当前 Formal H1 未运行，formal primary traces 为 `0 / 256`，正式 seeds 仍为
`20260819..20261074`。尚未生成或运行：

- 256 formal NPZ、formal artifact inventory、formal paired JSONL、formal aggregate、formal primary
  verdict
- formal H=0 set、formal H=2 primary rollout、H sensitivity、stress sensitivity
- formal point estimate、LCB/UCB 或 PASS/FAIL/INCONCLUSIVE/PROTOCOL_FAIL outcome

本 docs checkpoint 不启动或解锁上述工作。WP-02D overall 仍未完成。在 Formal H1 scientific
gate 产生有效结果并完成解释前，不得进入 prediction、forecast uncertainty、MAPPO、PyTorch/GPU
training 或 ID/OOD main experiment。
