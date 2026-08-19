# WP-02D：H1 Future-Information Value Gate 规范

## 1. 状态与范围

WP-02D 检验：在冻结的非平稳、资源受限、deadline-sensitive 场景中，仅向
`RollingTrueFutureOracle` 增加 H-step bounded `DemandEvent` 信息，是否相对
`ReactiveController` 产生稳定且具有实际意义的完成率改善。

WP-02D1 只实现 experiment spec、artifact inventory、配对 runner、统计、输出、provenance
和 preflight 协议。WP-02D2 才实现私有 bounded verifier。正式 H1 必须等待 D1/D2
实现完成、独立 patch 审查、Commit/Push、GitHub Actions、Mac/A100 验收之后，由用户明确
启动。本规范不包含任何正式 H1 结果。

Primary Oracle 是冻结的 H-step rolling true-future matched heuristic，不是 global optimum、
optimal controller 或 theoretical upper bound。Negative result 必须进行 heuristic-adequacy
诊断，不能直接解释为未来信息没有价值。

## 2. 冻结 Primary cell

需求过程为 `drifting_hotspot`：

```yaml
base_intensities: [0.025, 0.025, 0.025, 0.025]
hotspot_amplitudes: [0.55]
hotspot_scales: [0.45]
initial_hotspot_positions: [[0.5, 0.5]]
hotspot_velocities: [[0.25, 0.0]]
zone_bounds:
  - [0.0, 1.0, 0.0, 1.0]
  - [1.0, 2.0, 0.0, 1.0]
  - [2.0, 3.0, 0.0, 1.0]
  - [3.0, 4.0, 0.0, 1.0]
priority_range: [0.5, 0.5]
service_time_range: [1, 2]
deadline_offset_range: [2, 3]
num_steps: 256
```

Primary priority 严格固定为 0.5。Primary outcome 和 bounded verifier objective 都是未加权
completed count/fraction，而 Reactive/Oracle 排序包含 priority。固定 priority 消除了该排序项
与 primary objective 的不必要错配；不改变 load、空间漂移或未来预置机制，也不引入 weighted
reward。

环境：

```text
initial_resource_positions = ((0.5, 0.5), (3.5, 0.5))
movement_speed = 0.75
num_resources = 2
```

Primary horizon 为 2；H 集为 `[0, 1, 2, 3, 4]`。H=0 是 hard negative control，不是
superiority sensitivity。

## 3. Estimand 与 Primary metric

实验单位是一条由预注册 demand seed 产生的 `DemandTrace`。Reactive 和 Oracle 必须使用
同一 trace、相同环境配置与独立环境实例。只允许 controller information set/policy 不同。

对 trace i：

```text
arrived_R == arrived_O == A_i

A_i > 0:
    D_i = (completed_oracle - completed_reactive) / A_i

A_i == 0:
    D_i = 0.0
```

Primary estimand 是 `mean_i(D_i)`。每条 trace 等权；禁止 ratio-of-total-counts、priority
reward、best-seed subset、删除或替换 zero-arrival seed。

## 4. Seed 与 artifact 协议

```text
N = 256
seed_i = 20260819 + i, i=0..255
正式 seeds = 20260819..20261074
```

正式阶段 offline-first：每个 seed 只生成一次 canonical `DemandTrace`，通过既有
`save_demand_trace()` 保存为 `trace_<seed>.npz`，安全回读后写入冻结 inventory。Reactive、
Primary H=2 和 H sensitivities 全部读取同一个 artifact。生成、读取、hash 或运行失败均 hard
fail；不得 silent exclusion、replacement seed 或 overwrite。

Inventory v1 至少记录：

```text
schema/version
experiment_spec_sha256
wp02c_stable_sha
planned_seed_count
entries[]:
    seed
    relative_path
    process_type
    config_sha256
    content_sha256
    start_step
    num_steps
    num_events
```

Inventory 不保存绝对路径。Experiment spec hash 对完整 validated plain tree 调用已有
`fura_mappo.demand.compute_config_hash()`；不建立第二套 spec hash。每条 entry 的
`config_sha256` 必须重新由冻结 spec 与该 seed 构造的完整 resolved demand config 计算，不能
只与 artifact manifest 自洽；primary `start_step` 固定为 0。

冻结 inventory 必须通过 `read_artifact_inventory(path, spec, artifact_root)` 回读。该入口使用
strict UTF-8 JSON，拒绝 duplicate key、NaN/Infinity、未知/缺失字段、非法 path/seed/hash、
symlink inventory 文件，并重新调用完整 artifact/manifest validation；不得把普通
`json.loads()` 的结果当作已验证 inventory。`artifact_inventory_sha256` 对完整 inventory 普通树
复用 `compute_config_hash()` 计算。

WP-02D1 测试只允许 handcrafted tiny trace、非正式 seed 和 `tmp_path`。正式 256 个 seeds
只能计算 tuple，不能传入 `DemandProcess.generate()`。

## 5. Paired rollout

每个方法创建独立 `ResourceServiceEnvironment`，但 reset 必须接收同一个内存
`DemandTrace` 对象。Oracle 每一步只通过：

```text
build_true_future_view(same_trace_object, oracle_snapshot, H)
oracle.act(oracle_snapshot, official_view)
```

禁止复用已经推进的 environment、共享 mutable environment、手工构造 view、访问环境私有
state，或改变 WP-02A/B/C 物理与公共接口。

低层 `run_paired_trace()` 只保留给 handcrafted tiny deterministic tests；它允许调用方注入
测试 provenance，不能作为正式 artifact entrypoint。正式 primary 必须调用
`run_primary_artifact(spec, inventory_entry, artifact_root)`：wrapper 从 entry 的相对路径安全回读
artifact，重新验证 manifest，由 entry 冻结 seed/trace identity，由 spec 冻结环境和 H，并把同一
次加载得到的 `DemandTrace` 对象同时交给两个 `env.reset()` 与 official future-view builder。
调用方不能覆盖环境、seed、trace ID 或 horizon。

每条 `PairedTraceResult` 除两侧完整 `EpisodeMetrics`、primary difference、same-state diagnostic
counts/denominators、realized Oracle diagnostic 和 protocol status 外，必须正式记录：

```text
seed
trace_id（artifact relative_path）
experiment_spec_sha256
artifact_config_sha256
artifact_content_sha256
environment_config_sha256
horizon
```

四个 provenance hash 都是 64 位小写完整 SHA-256。环境 hash 的规范普通树只含
`initial_resource_positions` 与 `movement_speed`，并复用 `compute_config_hash()`。`trace_id` 只是一
项 artifact identity，不得单独承担 provenance。

## 6. H=0 与 canonical mechanism

H=0 对每条 formal trace 逐步要求：

- action tuple 逐值完全相等；
- `StepResult` 逐值完全相等；
- terminal `EpisodeMetrics` 逐值完全相等。

任一差异为 `PROTOCOL_FAIL`，不允许 tolerance、CI 或平均放宽。

Canonical preflight：一个资源从 `(0,0)` 以 speed 1 面对 arrival 2、position `(2,0)`、
service 1、deadline 3 的事件；H=2 Oracle 必须 Move、Move、Serve并完成，Reactive 不完成。
该 fixture 只验证机制，不是 H1 evidence。

## 7. Same-state opportunity diagnostics

在 Reactive 正式 trajectory 每个 actionable pre-terminal snapshot 上计算：

```text
a_R(t) = Reactive.act(snapshot_R(t))
view_R(t) = build_true_future_view(same_trace, snapshot_R(t), H=2)
a_O_cf(t) = Oracle.act(snapshot_R(t), view_R(t))
```

`a_O_cf` 只求值，绝不能 step 到 Reactive environment。冻结：

```text
reference_nonempty_view_steps
reference_feasible_future_pair_steps
reference_oracle_would_differ_steps
reference_oracle_would_preposition_steps
actionable_steps
has_reference_feasible_future_pair
has_reference_oracle_action_difference
```

Step fraction 的分母是该 trace 全部 actionable pre-terminal steps；trace fraction 分母是
`N_valid`。Feasible pair 复用 WP-02C 冻结 exact pair semantics，不使用
`ceil(distance/speed)`。

Same-state preposition 要求 Oracle/Reactive action tuple 不同，且 Oracle 至少一个
`MoveAction.target_position` 精确等于 official view 中尚未到达事件的位置。

可另外报告 `realized_oracle_prearrival_move_step_fraction`，但它来自 Oracle 自身 trajectory，
不能称为纯 information-set counterfactual difference。

## 8. Secondary metrics

逐 trace 保存完整 `EpisodeMetrics`。Aggregate 至少分别报告 Reactive/Oracle 的：

- completed、completion rate；
- expired/expiration rate；
- truncated/truncation rate；
- completed priority sum；
- service/movement/idle slots；
- movement distance；
- mean service-start wait；
- mean completed response；
- duplicate assignment conflicts；
- zero-distance moves。

服务改善与移动成本分开，不组合成 reward。Primary verdict 只读取 `D_i`。

## 9. Bootstrap 与 Gate rule

冻结 bootstrap：

```text
paired resampling unit = trace
resamples = 50000
Generator = numpy.random.Generator(PCG64(90260819))
method = percentile
np.quantile method = linear
one-sided LCB = 5% quantile
one-sided UCB = 95% quantile
two-sided interval = [2.5%, 97.5%]
delta_min = 0.02 absolute completion fraction
```

Verdict：

```text
PASS:
    point_estimate >= 0.02 and one_sided_lcb > 0

FAIL:
    not PASS and one_sided_ucb < 0.02

INCONCLUSIVE:
    all other valid results

PROTOCOL_FAIL:
    protocol invalid; not a scientific inference result
```

Formal evaluator 必须同时接收 validated H1 spec、validated frozen inventory 和 results。它要求
exactly 256 records、精确 seed 集和顺序、H=2、无重复、finite differences、两侧 arrived 相等
且无 protocol failure，并逐 seed 验证 result 的 spec、artifact config/content、relative path 和
冻结 environment hash 与 spec/inventory 完全一致。交换 artifacts 但保留 seed label、伪造
metrics 或任一 provenance mismatch 都是 `PROTOCOL_FAIL`；不得计算 scientific estimate，也
不得删除 bad record。

## 10. 输出与 verdict locking

Per-trace 使用 JSONL，aggregate 和 inventory 使用 JSON。格式统一 UTF-8、`sort_keys=True`、
`allow_nan=False`、固定 separators 和末尾换行。不使用 pickle、SQLite 或数据库。

写入必须 atomic、默认 no overwrite、拒绝 symlink target。完整、按 formal seed 顺序排列的
`paired_result_to_dict()` 内容先编码为既有 canonical JSON 字符串，再由
`compute_config_hash()` 对 wrapper Mapping 计算 `paired_results_sha256`；这样 bool/None 等正式
字段也被完整绑定，而不新建哈希算法。

Primary verdict 文件至少包含 `experiment_spec_sha256`、`artifact_inventory_sha256`、
`paired_results_sha256`、完整 summary 和 canonical `payload_sha256`，并记录调用方 hard gate
提供的 `wp02d_accepted_implementation_sha` 与 `actual_execution_head`。写入后必须回读验证。
Sensitivity execution 必须向 `read_primary_verdict()` / `require_locked_primary_verdict()` 提供
当前期望的 spec、inventory、results 三个 digest 和 formal provenance，逐值一致且 summary 非
`PROTOCOL_FAIL` 才能解锁。回读侧还必须验证 summary 的完整字段集合、N=256、bootstrap 常量、
quantile 顺序、gate rule、secondary 和 diagnostic schema。旧 verdict、另一组 results/inventory，
或攻击者只重算 payload hash，都不能解锁当前 sensitivity。

冻结 formal audit chain 为：

```text
validated H1 spec
-> frozen artifact inventory
-> exact artifact entry
-> provenance-bound PairedTraceResult
-> paired results digest
-> aggregate summary
-> locked verdict
```

正式输出不得写入 GitHub 仓库。

## 11. Formal provenance hard gate

正式 artifact generation/H1 run 必须记录：

```text
WP-02C stable SHA = 9159c841af4f605d6e32cca4b37940f0116a19cf
WP-02D accepted implementation SHA = 实现验收后由调用方传入
actual execution HEAD
origin/main
git dirty
experiment_spec_sha256
```

启动要求：

- working tree/index/untracked clean；
- actual HEAD == origin/main；
- WP-02C stable SHA 是 actual HEAD ancestor；
- WP-02D accepted SHA 是 actual HEAD ancestor；
- accepted SHA 后若存在提交，只允许 `docs/**` 或 `CHANGELOG_*`；
- `src/**`、`tests/**`、`configs/**`、`scripts/**`、`pyproject.toml` 等后续变化全部拒绝。

只使用本地 Git refs，不进行网络操作。当前实现不得硬编码尚未知的 WP-02D accepted SHA，
不得自引用 Commit 或修改 Git history。

## 12. Sensitivity 顺序

正式顺序严格为：

1. provenance 与 validated H1 spec；
2. strict inventory 回读、artifact validation 与 inventory digest；
3. H=0 invariant；
4. canonical mechanism；
5. 逐 entry 执行 provenance-bound Primary H=2 rollout；
6. paired results digest；
7. Primary statistics；
8. 绑定 exact spec/inventory/results 的 atomic primary verdict；
9. verdict 回读与 exact-chain 锁定；
10. 才允许 sensitivity outcome。

Sensitivity artifacts 可以提前生成，但 verdict 锁定前不得运行 sensitivity controller 或查看
outcome。所有 sensitivity 均 NON-GATE，不能救活 primary。

冻结 sensitivity metadata：

- H：0/1/2/3/4；H=0 仅为 invariant；
- priority heterogeneity：`[0.25,0.75]`。

现有仓库文档与本工作包输入没有给出 Markov、resource、speed、deadline sensitivity 的完整
数值 preregistration，因此 D1 不自行发明这些数值。它们不影响 primary gate，必须在对应
NON-GATE sensitivity 实现前另行完成结果不可见的预注册。

## 13. D1/D2 分解与 negative-result 诊断

WP-02D1 实现协议、配置、artifact inventory、paired runner、统计、输出和 provenance。
WP-02D2 单独实现下面的私有 bounded verifier。D1 不新增 `_bounded_verifier.py`，不执行
search、action enumeration或fixture suite。

Primary 不 PASS 时依次检查 H=0、canonical mechanism、load/opportunity diagnostics、统计
precision，最后运行预注册 bounded suite。Verifier发现 miss 不能把 H1 改成 PASS；它只阻止
将 negative result 解释为未来信息没有价值。

## 14. WP-02D2 root-information verifier

冻结名称：`bounded task-target root-information exhaustive diagnostic verifier`。

硬边界：不超过 2 resources、4 episode steps、3 events。每个 root decision time t：

```text
K = current active tasks + official H-step future view events
```

搜索分支不刷新 view，不把 root horizon 外事件加入 K。下一真实 decision boundary 才重建 K。
环境分支必须使用 fresh `ResourceServiceEnvironment` 加 deterministic prefix replay，并且只调用
public `reset()`/`step()`；禁止读写私有 `_state` 或复制 transition logic。

有限动作：

```text
SERVING: Continue only
AVAILABLE: Idle / legal Serve(K current waiting) / Move(K event positions)
```

Objective 只最大化 K 中 completed count；tie 仅使用 deterministic canonical action-sequence
ordering，不加入 priority、movement、wait 或 reward。它不枚举任意 continuous waypoint，不是
continuous-action global optimum、stochastic optimal policy或Primary adequacy证明。

## 15. 预注册 bounded fixture suite

所有事件 `zone_id=0`。Fixture 1：4步、1资源 `(0,0)`、speed 1、H=2；event 0 为
arrival 2、position `(2,0)`、priority 0.5、service 1、deadline 3。

Fixture 2：4步、1资源 `(0,0)`、speed 1、H=2：

- event 0：arrival 0、position `(0,0)`、priority 0.5、service 1、deadline 4；
- event 1：arrival 2、position `(1,0)`、priority 0.5、service 1、deadline 3。

Fixture 3：4步、1资源 `(0,0)`、speed 1、H=2：

- event 0：arrival 1、position `(0,0)`、priority 0.5、service 1、deadline 4；
- event 1：arrival 2、position `(0,0)`、priority 0.5、service 2、deadline 4。

Fixture 4：4步、2资源 `((0,0),(3,0))`、speed 1、H=2：

- event 0：arrival 2、position `(1,0)`、priority 0.5、service 1、deadline 3；
- event 1：arrival 2、position `(-2,0)`、priority 0.5、service 1、deadline 3。

Fixture 5：3步、1资源 `(0,0)`、speed 1、H=2；event 0 为 arrival 2、position `(3,0)`、
priority 0.5、service 1、deadline 3。

Fixture 6A/6B：4步、2资源 `((0,0),(0,0))`、speed 1、H=2。共同 event 0 为 arrival 2、
position `(0,0)`、priority 0.5、service 1、deadline 3。Event 1 均为 arrival 3、priority 0.5、
service 1、deadline 4；6A position `(3,0)`，6B position `(-3,0)`。

Fixture 6 在 t=0 的 root snapshot、official view 必须相同；root K event IDs 精确为 `{0}`；
finite Move targets 不得包含 `(3,0)` 或 `(-3,0)`；两条 trace 的 verifier 首个联合动作必须逐值
相同，但不预先要求特定 Idle/zero-distance动作。

Position ±3 是关键修正：event 1 在 t=1 才进入 H=2 view，此后只有 t1/t2 两个移动槽，合法
rolling policy 无法在 t3 Serve 前移动3单位；错误读取完整trace则可从t0开始执行三次Move并在
t3 Serve。因此该pair能检测有completed-count incentive的root look-ahead leakage。

Suite label：

```text
任一 fixture verifier completed > Primary completed:
    PRIMARY_HEURISTIC_MISS_DETECTED

否则:
    NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE
```

后者不等于Primary optimal或heuristic adequacy proven。Suite在正式H1前冻结，不得根据结果
增删fixture。

## 16. 当前正式执行状态

WP-02D1 候选实现阶段尚未运行正式 H1，尚未生成任何正式 primary `DemandTrace`、NPZ、
inventory、JSONL、aggregate 或 verdict，也未运行 sensitivity 或 bounded verifier。
