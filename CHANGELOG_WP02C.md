# WP-02C Rolling True-future Oracle 变更记录

状态：已完成并通过 Mac、独立候选审查、GitHub Actions 与 A100 CPU 验收。

稳定实现 Commit：`9159c841af4f605d6e32cca4b37940f0116a19cf`。

## 完成范围

- public immutable `TrueFutureView`
- public `build_true_future_view(...)`
- deterministic `RollingTrueFutureOracle`
- explicit nonnegative H-step bounded true-future information
- terminal-clamped future window
- official builder 的最低限度 prefix/pairing validation
- manual view 在 `oracle.act()` 中重新验证
- current/future ID overlap 防护
- stateless receding-horizon replanning；无 reservation、history、RNG 或 persistent plan
- current WAITING + bounded future event expanded greedy matching
- future arrival 前允许 Move/pre-position、禁止 Serve；提前到达目标后 Idle
- task 排序：`latest_service_start` → higher priority → earlier `arrival_step` → smaller `event_id`
- resource 排序：exact `travel_slots` → Euclidean distance → `resource_id`
- exact feasibility 复用 WP-02A/B shared movement physics
- empty view 或所有 future pair 均 physically infeasible 时结构性委托 Reactive
- H=0 action、`StepResult`、`EpisodeMetrics` 与 Reactive 完全一致

WP-02A、WP-02B 和 WP-01 的冻结公共行为与协议未改变。

## 科学信息边界

Oracle controller 本身不持有 `DemandTrace`。future view 只公开冻结 `DemandEvent` 的 event
ID、arrival step、zone ID、position、priority、service time 和 deadline；不公开 intensity、
counts、demand process/hidden state、seed、RNG、config 或 artifact manifest。

`TrueFutureView` 与 Oracle 无法仅从 public snapshot 证明完整 trace identity。后续 WP-02D
正式 paired experiment 必须把同一个内存 `DemandTrace` 同时传给 `env.reset(trace)` 和
official `build_true_future_view(trace, snapshot, H)`；正式实验不得手工拼装 view，也不为此
修改 `DemandTrace` 或 `EnvironmentSnapshot` 增加 fingerprint。

## Primary Oracle 能力边界

`RollingTrueFutureOracle` 是 H-step rolling true-future matched heuristic，不是 global
optimum、optimal controller 或 theoretical upper bound。它通过 canonical H=2 案例证明
bounded true-future event 可以引导 Move → Move → Serve 并完成任务，但若 Primary Oracle
未优于 Reactive，不能单独据此断言未来信息没有价值。

WP-02C 未实现 reference/exhaustive verifier。WP-02D 的 bounded diagnostic verifier 用于
诊断 weak Oracle false negative，已冻结规模上限为不超过 2 resources、4 steps、3 events，
必须使用真实 `ResourceServiceEnvironment`，不公开为正式 baseline，也不声称全局最优上界。
verifier priority、movement、weighted objective 和 exact action search ordering 尚未冻结。

## 独立候选审查

- 最终批准 review patch SHA-256：`5dad6a0c966548bfc981cc8f48a2f84d6f9a5cafe4b2a351c299e2b578c9558a`
- patch：4 diff sections，56,069 bytes
- 结论：BLOCKER 0、MAJOR 0、MINOR 0
- patch apply / whitespace check：passed
- `oracle.py` / test file syntax：passed
- 5000 randomized legal snapshot/future-view cases：passed
- canonical H=2 mechanism：Move → Move → Serve

上述随机探测是独立候选审查证据，不是完整仓库正式验收结果。

## Mac 验收

- Python：3.11.15
- WP-02C Oracle：49 passed
- WP-02B Reactive：38 passed
- WP-02A environment：61 passed
- 全量 CPU：569 passed in 5.69s
- `pip check`：`No broken requirements found`
- Ruff：通过
- format：74 files already formatted
- `git diff --check`：通过

开发中补充协议测试后，最终全量结果为 569 passed。

## GitHub Actions

- Commit：`9159c841af4f605d6e32cca4b37940f0116a19cf`
- `CPU checks`：success
- 未记录未经确认的 run number

## A100 验收

- Commit：`9159c841af4f605d6e32cca4b37940f0116a19cf`
- CPU 验收：全部通过

## 明确非范围

WP-02C 未实现 H1 正式 gate、bounded reference verifier、public generic runner、prediction、
uncertainty、reward、RL/MAPPO、PyTorch/GPU、ID/OOD 主实验或大型 optimizer。

## 下一阶段

下一唯一阶段为 WP-02D H1 Future-Information Value Gate 的只读设计分析。必须先冻结 H1
estimand、paired protocol、primary H、sensitivity、bounded verifier、stress cell、paired
metrics、统计估计/CI、minimum practical effect、decision rule 和失败路径；当前不得直接运行
H1，也不得实现 verifier 或进入 prediction/MAPPO。
