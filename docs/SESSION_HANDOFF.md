# 会话交接

更新日期：2026-08-19

## 当前唯一任务

WP-02D：H1 Future-Information Value Gate，只读设计分析。

当前不得运行正式 H1 gate，不得实现 bounded diagnostic verifier，也不得进入 predictor、
uncertainty、MAPPO/RL、PyTorch/GPU、ID/OOD 主实验、大规模 optimizer 或论文主结果实验。

## 稳定基线

```text
WP-02C 实现：9159c841af4f605d6e32cca4b37940f0116a19cf
WP-02B 实现：f290a45a67763b41941e919303b26fb16a67575a
WP-02A 实现：d01092831a227a9f520de4ff8ded1d9e13ba8262
WP-01C 实现：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
WP-01C 标签：wp01c-stable
```

docs-only 收尾 Commit 不自引用自身 SHA；后续会话必须真实读取当前 HEAD。

## WP-02C 完成结论

- public immutable `TrueFutureView`
- public `build_true_future_view(...)`
- deterministic `RollingTrueFutureOracle`
- H-step terminal-clamped true-future `DemandEvent` view
- controller 不持有 `DemandTrace`，不访问 intensity、counts、hidden demand state、seed、
  RNG、config 或 artifact manifest
- explicit nonnegative horizon；H=0 view 严格为空
- official builder 做最低限度 prefix/pairing validation；manual view 在 `act()` 中重新验证
- current/future ID overlap 防护
- arrival 前允许 Move/pre-position，禁止 Serve；提前到达目标后 Idle
- future 到达后由 current WAITING task 表示
- stateless receding-horizon replanning；无 reservation、history、RNG 或 persistent plan
- expanded current + future candidate greedy matching
- task 排序：`latest_service_start` → higher priority → earlier `arrival_step` → smaller `event_id`
- resource 排序：exact `travel_slots` → Euclidean distance → `resource_id`
- exact feasibility 与 WP-02A/B 共享 movement physics，不使用 `ceil(distance / speed)`
- empty view 或所有 future pair 均 physically infeasible 时结构性委托 Reactive
- H=0 action、`StepResult`、`EpisodeMetrics` 与 Reactive 完全一致
- canonical mechanism：Move → Move → Serve → completed

Primary Oracle 是 H-step rolling true-future matched heuristic，不是 global optimum、optimal
controller 或 theoretical upper bound。它能证明 bounded future event 可以影响 pre-position /
matching；若未优于 Reactive，不能单独据此断言未来信息没有价值。

## WP-02C 验收事实

### 独立候选审查

- 最终批准 patch SHA-256：`5dad6a0c966548bfc981cc8f48a2f84d6f9a5cafe4b2a351c299e2b578c9558a`
- 4 diff sections，56,069 bytes
- BLOCKER 0、MAJOR 0、MINOR 0
- patch apply / whitespace check：passed
- `oracle.py` / test file syntax：passed
- 5000 randomized legal snapshot/future-view cases：passed
- canonical H=2 mechanism：Move → Move → Serve

上述随机探测只属于独立候选审查证据，不是完整仓库验收。

### Mac / GitHub / A100

- Mac：Python 3.11.15；Oracle 49 passed；Reactive 38 passed；WP-02A environment 61 passed；
  全量 569 passed in 5.69s；pip check、Ruff、format、diff-check 通过
- GitHub Actions：Commit `9159c841af4f605d6e32cca4b37940f0116a19cf`；`CPU checks` success；
  未记录未经确认的 run number
- A100：Commit `9159c841af4f605d6e32cca4b37940f0116a19cf`；CPU 验收全部通过

## Paired trace 契约

`TrueFutureView` / Oracle 无法从 public snapshot 证明 view 来自环境 reset 的同一完整 trace。
WP-02D 正式实验必须把同一个内存 `DemandTrace` 同时传给：

```text
env.reset(trace)
build_true_future_view(trace, snapshot, H)
```

official builder 是正式实验唯一允许的 view 构造路径。不得修改 `DemandTrace` 或
`EnvironmentSnapshot` 增加 fingerprint。

## WP-02D 只读设计必须冻结

1. H1 precise estimand
2. Reactive / Oracle paired rollout unit 与 same-`DemandTrace` protocol
3. official `TrueFutureView` construction
4. primary H、horizon sensitivity、H=0 negative control
5. deterministic mechanism control
6. bounded diagnostic verifier objective、exact search boundary 与诊断规则
7. primary stress cell 和 resource/demand/deadline/mobility dimensions
8. seed / artifact generation protocol
9. paired primary/secondary metrics 与 effect direction
10. paired estimator、uncertainty/CI、minimum practical effect 和 gate threshold
11. false-positive / false-negative protections 与 Oracle heuristic failure diagnosis
12. negative-result failure path 和 WP-02D implementation/file boundary

verifier 已冻结的规模边界为不超过 2 resources、4 steps、3 events，必须使用真实
`ResourceServiceEnvironment`，不公开为正式 baseline，也不声称 global optimum 或 upper
bound。priority、movement、weighted objective 和 exact action search ordering 尚未冻结。

## 当前非目标

正式 H1 运行、大规模 artifact 生成、bounded verifier 实现、predictor、uncertainty、
MAPPO/RL、PyTorch/GPU、ID/OOD 主实验、大规模 optimizer、多进程和论文主结果实验。
