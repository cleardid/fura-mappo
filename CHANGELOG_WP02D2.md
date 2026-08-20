# WP-02D2 Bounded Root-Information Verifier 变更记录

## 状态

WP-02D2 已完成并接受。accepted implementation Commit：

```text
cfab8c1b1981ef095d68969fff74faa2ac4f256d
feat: add bounded root-information verifier
```

WP-02D1 implementation 为 `844de649c71e0a6a8fec6e1355cbf010db434f83`，WP-02D1 docs
checkpoint 为 `fe1b97496c937ec6f660c48419441eb9569e31ba`。WP-02D1 与 WP-02D2 均已
completed / accepted，但 WP-02D overall 仍在进行中，因为 Formal H1 scientific gate 尚未执行。

## 实现范围

WP-02D2 的准确定位是：

```text
bounded task-target root-information exhaustive diagnostic verifier
```

它是 private diagnostic verifier，不是 formal baseline、global optimum、continuous-control
optimum、theoretical upper bound、optimal policy 或 Primary adequacy proof。accepted implementation
仅新增：

```text
src/fura_mappo/experiments/_bounded_verifier.py
tests/test_bounded_verifier.py
```

`fura_mappo.experiments` public API 未导出 verifier；`h1_gate.py`、environment physics、Reactive、
Primary Oracle 与 formal H1 preregistration 均未修改。

## 冻结 verifier semantics

- resources ≤ 2
- episode steps ≤ 4
- events ≤ 3
- 使用真实 `ResourceServiceEnvironment`
- branch transition 仅通过 public `reset()` / `step()`
- 禁止访问 `env._state` 或其他 private environment state
- 禁止复制 environment transition logic
- 每个 branch 使用 fresh environment、deterministic prefix replay 与 exact public replay
  consistency checks
- root search 一直搜索到 episode terminal
- 不使用 pruning、memoization、symmetry reduction 或 dominance
- rolling verifier 每个真实 boundary 只采用最佳完整 sequence 的 first joint action

## Root-information / no-leakage

每个真实 decision boundary 通过 official `build_true_future_view(...)` 构造 future view，并冻结：

```text
K = current active tasks + official H-step future view events
```

一次 root search 内 K 不缩减、不刷新 future view、不加入 root horizon 外事件。下一真实 decision
boundary 才重新构造 K 并重新 exhaustive search。分支搜索只能把完整 trace 交给环境
reset/replay，不能用完整 trace future events 扩张 action、score 或 tie-break。

## Finite action space

```text
SERVING:
    ContinueAction only

AVAILABLE:
    IdleAction
    legal ServeAction for frozen-K current WAITING event
    MoveAction whose target is a frozen-K event position
```

保留 zero-distance Move 和 environment-legal duplicate Serve joint actions。Joint actions 是按
increasing `resource_id` 的 Cartesian product。

## Objective / canonical tie-break

唯一 objective 是 maximize completed count over frozen K。完成数相同时，只选择
lexicographically minimum canonical complete sequence key；不使用 priority、movement distance、
wait、reward 或任何 secondary objective。

```text
ContinueAction -> (0,)
IdleAction     -> (1,)
MoveAction     -> (2, x, y)
ServeAction    -> (3, event_id)
```

Joint action key 按 increasing resource_id，sequence key 按 increasing time。Canonical ordering 只
提供 deterministic tie-break，不是 performance preference。

## Preregistered fixtures

冻结 handcrafted fixture unit-test expectations：

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

这些是 unit-test expectations，不是 Formal H1 outcome 或 formal primary evidence。

Fixture 6 使用修正版：6A outside-H event position 为 `(3,0)`，6B 为 `(-3,0)`，不得退回旧
`±2`。冻结验证为：

```text
root snapshots identical
root official views identical
root K IDs == {0}
root Move targets exclude (3,0) and (-3,0)
6A/6B verifier first joint action identical
```

不预先规定 first joint action 必须是某个特定 Idle/Move。

冻结 diagnostic classifier：

```text
any preregistered fixture:
verifier completed > Primary completed

=> PRIMARY_HEURISTIC_MISS_DETECTED
```

否则：

```text
NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE
```

第二个 label 不表示 Primary optimal 或 heuristic adequacy proven。两个 label 都不是 Formal H1
scientific outcome；verifier output 不进入 formal primary verdict 输入。

## Independent review

```text
Approved WP-02D2 review patch SHA-256:
f6cb0e8638847b4b84f84421f5bbc77926abc6995a4704f6cb11300ff8ff172f

Patch:
2 diff sections
38,147 bytes
2 files changed
998 insertions
0 deletions

Independent review:
BLOCKER 0
MAJOR 0
MINOR 0
```

## Mac acceptance

```text
WP-02D2 dedicated: 35 passed
WP-02A/B/C/D1 relevant regression: 208 passed
full CPU: 664 passed
Ruff: passed
format: 82 files already formatted
```

未记录未提供的精确耗时。

## GitHub Actions

```text
WP-02D2 implementation Commit:
cfab8c1b1981ef095d68969fff74faa2ac4f256d

GitHub Actions:
CPU checks success
```

仓库中没有在本 checkpoint 引用可靠 run number，因此不记录 run number。

## A100 CPU acceptance

```text
Commit: cfab8c1b1981ef095d68969fff74faa2ac4f256d
WP-02D2 dedicated: 35 passed in 6.35s
full CPU: 664 passed in 26.76s
Ruff: All checks passed!
format: 82 files already formatted
git diff --check: passed
final working tree: clean
```

这是 A100 server CPU acceptance，不是 GPU test；未执行 PyTorch/GPU workload。

## Formal H1 remains zero

```text
Formal H1 has NOT run.
Formal primary traces generated: 0 / 256.
Formal seeds: 20260819..20261074
```

当前没有生成或运行：

- 256 formal NPZ
- formal artifact inventory
- formal paired JSONL
- formal aggregate
- formal primary verdict
- formal H=0 set
- formal H=2 primary rollout
- H sensitivity
- stress sensitivity

未产生任何 formal point estimate、formal LCB/UCB 或正式
PASS/FAIL/INCONCLUSIVE/PROTOCOL_FAIL outcome。Primary specification、secondary metrics 约束与
formal audit chain 保持不变：

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

Sensitivity 与 secondary metrics 不能改变或救活 primary failure。

## Next stage

下一阶段是：

```text
Formal H1 execution preparation / audit gate
```

任何正式 primary trace 生成前，execution-readiness / audit review 必须确认 accepted
implementation ancestry、clean main、exact preregistered spec、正式 seed prohibition 解除前的人工
确认、exact output paths / artifact root、provenance hard gate、no-overwrite policy、formal run
command sequence，以及 sensitivity 仍锁定在 primary verdict 之后。

Formal H1 只能在本 docs-only checkpoint Commit/Push 完成、下一阶段 execution-readiness audit
通过后，由用户明确授权启动。本 checkpoint 不启动或解锁 formal data generation。

在 Formal H1 scientific gate 产生有效结果并完成解释前，继续禁止进入 prediction、forecast
uncertainty、MAPPO、PyTorch/GPU training 或 ID/OOD main experiment。
