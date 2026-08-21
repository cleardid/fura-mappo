# WP-02D3 Formal H1 Execution Hardening 变更记录

## 状态

WP-02D3 implementation 已完成、独立审查并接受。

```text
WP-02D3 accepted implementation:
1092d9c87bfff8ba6c1f2132734480112d7b5975

Commit message:
feat: harden formal H1 execution
```

准确定位是 `Formal H1 execution orchestration / persistence hardening`。WP-02D3 不改变 H1
scientific specification、environment science、Reactive、Primary Oracle、WP-02D2 verifier 或
preregistration；它补齐正式执行、持久化、provenance、restart/resume 与 strict readback。

Formal H1 尚未运行，formal primary traces 为 `0 / 256`。本文不包含 scientific outcome。

## 背景：readiness audit blocked

WP-02D1 已冻结 H1 protocol/statistics，WP-02D2 已完成 bounded diagnostic verifier，但正式 H1
execution readiness audit 发现：仅有统计与 artifact primitives 还不足以安全生成不可替换的正式
evidence。D3 因此专门封闭 orchestration、provenance、loaded-code identity、restart/resume、strict
persistence 与 crash durability 边界。

多轮独立 review 发现的事项均在 implementation Commit 前修复。这些是提交前质量关口成功识别的
execution-readiness 问题，不是 Formal H1 failure、scientific failure 或已发布运行失败。

## 实现范围

最终 accepted implementation 精确修改 6 个文件：

```text
src/fura_mappo/demand/serialization.py
src/fura_mappo/experiments/h1_gate.py
src/fura_mappo/experiments/_formal_h1_runner.py
tests/test_demand_serialization.py
tests/test_h1_gate.py
tests/test_formal_h1_runner.py
```

未修改 environment science、Reactive、Primary Oracle、D2 verifier、H1 preregistration、
`configs/experiments/wp02d_h1.yaml` 或 public `experiments/__init__.py`。

## Private Formal runner

新增 private module：

```text
fura_mappo.experiments._formal_h1_runner
```

它不是 public API。未来正式调用冻结为：

```bash
python -m fura_mappo.experiments._formal_h1_runner \
  --accepted-implementation-sha 1092d9c87bfff8ba6c1f2132734480112d7b5975
```

本 docs-only checkpoint 不执行该命令。

## Accepted implementation SHA 规则

Formal H1 accepted implementation SHA 始终为：

```text
1092d9c87bfff8ba6c1f2132734480112d7b5975
```

本次及未来 docs-only checkpoint Commit 会形成新的 actual execution HEAD。该 HEAD 是 accepted
implementation 的合法 `docs/**` / `CHANGELOG_*` descendant，但 docs Commit 不是新的 implementation
baseline，不得替代 `--accepted-implementation-sha`。

```text
accepted implementation SHA
1092d9c87bfff8ba6c1f2132734480112d7b5975
-> only docs/** / CHANGELOG_* descendants
-> actual execution HEAD
```

## Git provenance hard gates

未来 runner 要求：

- cwd 是真实、非 symlink repository root
- branch 精确为 `main`
- working tree、index 与 untracked state 全部 clean
- actual HEAD 精确等于 `origin/main`
- accepted implementation SHA 是 actual HEAD ancestor
- WP-02C stable SHA 是 actual HEAD ancestor
- accepted implementation SHA 后只允许 `docs/**` / `CHANGELOG_*` changes
- 正式 publication 关键边界重复 revalidate provenance

任何失败都 hard fail，不继续生成或发布 formal evidence。

## Loaded-code binding

runner 不只验证 cwd Git，还要求实际 imported Python code 来自：

```text
<repo>/src/fura_mappo
```

至少绑定 `fura_mappo.__file__`、`fura_mappo.__path__`、private runner、`h1_gate`、loaded demand
modules、loaded environment modules 与 loaded baselines modules。old wheel、other checkout 或
unrelated package path 均 hard fail。

## Fixed Formal paths

唯一冻结路径：

```text
spec:
configs/experiments/wp02d_h1.yaml

run root:
artifacts/wp02d_h1_formal_v1/

traces:
artifacts/wp02d_h1_formal_v1/traces/

inventory:
artifacts/wp02d_h1_formal_v1/artifact_inventory.json

paired results:
artifacts/wp02d_h1_formal_v1/primary_paired_results.jsonl

aggregate:
artifacts/wp02d_h1_formal_v1/primary_aggregate.json

verdict:
artifacts/wp02d_h1_formal_v1/primary_verdict.json
```

不得提出第二套正式路径。正式 path 必须 confined 于真实 repo root；symlink path component、run
root/traces/output symlink、unknown run-root file、unknown trace file 与 invalid existing evidence
均 hard fail。runner 不自动删除、覆盖或修复 formal evidence。

## Artifact provenance

每个正式 NPZ artifact 必须绑定：

```text
seed
trace_<seed>.npz
process type
resolved config
config SHA
content SHA
start_step
num_steps
num_events
manifest.git_commit == formal_provenance.actual_head
manifest.git_dirty is False
```

caller 不能手工提供 hash 绕过 formal acceptance。

## Restart/resume

Inventory 已存在时：

- 不再生成 trace
- strict read inventory
- strict validate 全部 256 NPZ
- missing/invalid evidence hard fail
- 不 regenerate

Inventory 不存在时，对冻结 256-plan：

- 已存在 trace 必须 provenance-bound strict validate；valid 才 reuse，invalid hard fail
- 缺失 trace 必须先 revalidate provenance，再 exactly once generate、save no-overwrite、strict reload
  与 provenance-bound validate
- 全部 256 valid 后才 build inventory、atomic no-overwrite write、strict readback 与计算 digest

没有 replacement seed。

## Formal pipeline

```text
clean main / provenance / code-path hard gate
-> exact spec validation
-> exact seed/artifact plan
-> trace generation or strict resume
-> frozen inventory + strict readback
-> H=0 invariant on all 256 artifacts
-> canonical mechanism preflight
-> Primary H=2 paired rollouts
-> strict paired JSONL publication/readback
-> paired-results digest
-> recompute primary aggregate
-> strict aggregate publication/readback
-> locked primary verdict publication/readback
-> only valid locked primary verdict may unlock sensitivity
```

## Strict paired results

Paired JSONL reader 冻结：

- strict UTF-8、no blank lines、duplicate keys rejected
- NaN/Infinity、exponent overflow/non-finite 与 invalid Unicode canonicalization rejected as protocol
  error
- exact fields/schema/version 与 strict `EpisodeMetrics` reconstruction
- exact 256 rows、exact seed order、exact H=2
- exact spec、artifact 与 environment hashes
- primary difference consistency
- canonical writer representation
- strict readback 后才计算 digest

## Strict aggregate

`read_h1_summary(...)` strict read PASS、FAIL、INCONCLUSIVE 与 PROTOCOL_FAIL representation。runner
必须从 strict paired results 重新计算，并要求：

```text
disk summary == recomputed summary
```

本文只记录 reader capability，不记录任何 Formal H1 verdict。

## Locked verdict、PROTOCOL_FAIL 与 sensitivity

`read_primary_verdict(...)` strict validate exact spec/inventory/results/provenance/payload，并可读取
PASS、FAIL、INCONCLUSIVE 或 PROTOCOL_FAIL representation。

`require_locked_primary_verdict(...)` 只用于 sensitivity unlock；仅 valid non-PROTOCOL_FAIL
verdict 可通过。PROTOCOL_FAIL 永不解锁 sensitivity。

CLI error classification：

```text
H1ProtocolError:
formal_verdict=PROTOCOL_FAIL
exit code = 2

ordinary runtime/I/O error:
exit code = 1
```

这不是 Formal H1 outcome；本 checkpoint 未调用 runner。

## Crash durability

Protocol JSON/JSONL：

```text
write/fsync temp
publish target
remove temp entry
fsync parent
```

NPZ no-overwrite：

```text
write/fsync temp
strict validate temp
hard-link temp -> target
unlink temp
fsync parent
```

Formal directories：首次创建 run root 后 fsync `artifacts/`；首次创建 `traces/` 后 fsync run root。
这些 durability controls 不改变 scientific content、schema、hash 或 bytes semantics。

## Runner output discipline

在 final verdict strict readback 前，不打印 per-seed `D_i`、point estimate、LCB/UCB 或 provisional
PASS/FAIL/INCONCLUSIVE。允许输出 stage、progress counts、hashes 与 protocol status。

## Independent review history

```text
v1:
BLOCKER 1 / MAJOR 2 / MINOR 1
SHA-256 a1c9608ce94cfc66bc9ea35f269c97123c2b355b5b4b979f55afd9f59c0c1f2e

v2:
BLOCKER 0 / MAJOR 0 / MINOR 1
SHA-256 3534b2208a92610981c2d979119547bf58d9faf2d9c32863b66ca750b88b7bf5

v3:
BLOCKER 0 / MAJOR 2 / MINOR 0
SHA-256 e82ca1c8db33dc670a6645ee4ef5a1b06a921b0d877d3480f6963deb45c8fcdb

v4:
BLOCKER 0 / MAJOR 0 / MINOR 0
SHA-256 f4dd19abd16723d19508b26f89ad1a93e4e4a1b468aa13a9785baa8ec86b82a9
```

最终批准 `wp02d3-review-v4.patch` metadata：

```text
Bytes: 120,831
Diff sections: 6
Patch stat: 6 files changed, 2718 insertions(+), 80 deletions(-)
```

上述 findings 都是提交前 review gate 发现并修复的 execution-readiness 问题，不是 Formal H1 或
scientific failure。

## GitHub Actions

```text
Commit:
1092d9c87bfff8ba6c1f2132734480112d7b5975

GitHub Actions:
two Actions/checks passed
```

未记录未经用户确认的 run number、job ID、精确 duration 或 workflow name。

## A100 server CPU acceptance

```text
Commit:
1092d9c87bfff8ba6c1f2132734480112d7b5975

Focused WP-02D3 acceptance:
207 passed in 16.87s

Full CPU:
720 passed in 34.31s

Ruff:
All checks passed!

Format:
85 files already formatted

git diff --check:
passed

Final working tree:
clean
```

这是 A100 server CPU acceptance，不是 GPU test，未执行 PyTorch、CUDA 或 Formal H1。

## Scientific identities unchanged

```text
H1 spec SHA-256:
fc719e4634ab13ba55d0b95e63497688b3ab07c259d1421c5ed0c468cec3fade

Primary environment config SHA-256:
d1d856b13ac8edf79422428a96bddc03b901053dbeaabe56571e9baeef6eafa1
```

WP-02D3 不改变 N=256、seeds、Primary H=2、`D_i`、bootstrap、`delta_min`、gate、H=0 invariant、
canonical mechanism 或 sensitivity lock。

## Formal H1 remains zero

```text
Formal primary traces generated: 0 / 256
Formal H1 controller rollouts: 0
Formal artifact inventory: 0
Formal paired results: 0
Formal aggregate: 0
Formal verdict: 0
Formal sensitivity: 0
```

`artifacts/wp02d_h1_formal_v1/` 尚未创建。没有 Formal H1 point estimate、interval 或 scientific
verdict。WP-02D1、WP-02D2 与 WP-02D3 completed / accepted；WP-02D overall 仍在进行中。

## Next stage

下一阶段唯一任务：

```text
Final Formal H1 execution-readiness freeze / runbook freeze
```

最终只读 freeze 必须验证 docs checkpoint Commit 已 push、current clean main、HEAD/origin、
`1092d9c...` ancestry、accepted SHA 后 only docs/changelog changes、loaded code path、exact scientific
identities、formal root absent、traces `0 / 256`、exact frozen invocation 与用户明确授权。

在该 freeze 与用户明确授权完成前，不运行 Formal H1；在有效 Formal H1 scientific gate outcome
完成解释前，不进入 prediction、forecast uncertainty、MAPPO、PyTorch/GPU training、sensitivity
或 ID/OOD main experiment。
