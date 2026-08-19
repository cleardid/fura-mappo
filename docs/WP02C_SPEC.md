# WP-02C：Rolling True-future Oracle 规范

## 1. 范围与冻结边界

WP-02C 只增加有限 horizon、真实未来事件可见、无状态且确定性的
`RollingTrueFutureOracle`，以及严格有界的 `TrueFutureView` 和 official builder。
Oracle 与 Reactive 使用同一 `ResourceServiceEnvironment`、公共动作、组成指标、
deadline/terminal 语义和精确单槽移动物理。

本工作包不实现 WP-02D H1 正式 gate、reference/exhaustive verifier、预测器、不确定性、
reward、RL/MAPPO、PyTorch/GPU、ID/OOD 主实验、大型 optimizer、公共 generic rollout
runner、reservation 或 persistent plan。WP-02A、WP-02B 和 WP-01 的冻结接口保持不变。

## 2. TrueFutureView

公共不可变模型为：

```python
TrueFutureView(
    absolute_step: int,
    horizon: int,
    future_events: tuple[DemandEvent, ...],
)
```

模型使用 frozen dataclass 和 slots。`absolute_step`、`horizon` 接受 Python/NumPy 整数，
显式拒绝 Python/NumPy bool，并要求非负；horizon 没有默认值。事件被防御性转换为 tuple，
每项必须是 `DemandEvent`，event ID 必须唯一，并按 `(arrival_step, event_id)` 规范排序。

view 自身只完成不依赖 episode 终点的局部约束：

```text
absolute_step < arrival_step <= absolute_step + horizon
```

H=0 时事件必须为空。view 不知道 `stop_step`，不得声称已经验证 terminal clamp。

未来信息只包含冻结 `DemandEvent` 的 event ID、arrival step、zone ID、position、priority、
service time 和 deadline。view 不包含 counts、intensity、需求类型、Markov/Burst/Hotspot
隐状态、seed、RNG、config 或 artifact manifest。

## 3. Official builder 与 pairing

official builder 为：

```python
build_true_future_view(
    source: DemandTrace,
    snapshot: EnvironmentSnapshot,
    horizon: int,
) -> TrueFutureView
```

令：

```text
t = snapshot.absolute_step
stop_step = t + snapshot.steps_remaining
source_stop = source.start_step + source.counts.shape[0]
```

builder 验证 source/snapshot 类型、horizon、`source.start_step <= t < source_stop`、
`source_stop == stop_step`、source 在 t 的事件与 `snapshot.current_arrivals` 一致，以及每个
active task 的事件可按 event ID 在 source 中找到且字段完全一致。正式 view 只包含：

```text
t < arrival_step <= min(t + H, stop_step - 1)
```

这些 prefix 检查只能降低误配风险，不能证明 trace identity，也无法检测已经 terminal 且不再
出现在 snapshot 中的历史 ID 冲突。不得修改 `DemandTrace` 或 `EnvironmentSnapshot` 增加
fingerprint/hash。

WP-02D 正式 paired runner 必须把同一个内存 `DemandTrace` 对象同时传给
`env.reset(trace)` 与 `build_true_future_view(trace, snapshot, H)`。正式实验不得手工拼装
view。手工 view 可以通过公开构造函数创建，但 controller 无法判断它是否遗漏窗口内事件。

## 4. Oracle 公共接口与状态

```python
RollingTrueFutureOracle(
    movement_speed: float,
    horizon: int,
)

oracle.act(
    snapshot: EnvironmentSnapshot,
    future_view: TrueFutureView,
) -> tuple[ResourceAction, ...]
```

Oracle 内部组合冻结 `ReactiveController(movement_speed)`，因此速度验证与 WP-02B 完全
一致。Oracle 只保存 horizon 和 stateless Reactive 实例；不保存 DemandTrace、环境、RNG、
history、reservation、movement target、future assignment 或 previous plan。每个 step 根据
当前 snapshot 与 fresh bounded view 重新规划，预置中的 AVAILABLE resource 下一步可以改向。

## 5. act 输入与窗口复核

每次 `act()` 都重新验证 snapshot/view 类型、连续 resource ID 和合法 resource status，且：

```text
view.absolute_step == snapshot.absolute_step
view.horizon == oracle.horizon
```

future event ID 必须唯一，不得与 active task 或 current arrival 的 event ID 重叠。每个事件
必须再次满足 episode-clamped 窗口：

```text
t < arrival_step <= min(t + H, stop_step - 1)
```

因此正常手工构造不能绕过 horizon、terminal clamp、current/future overlap 或 arrival window；
但 controller 没有完整 trace，不能证明 view completeness 或完整 trace identity。

## 6. 零额外信息与不可行未来 identity

完成全部输入校验后，只要：

```text
future_view.future_events == ()
```

无论 H 为零还是正数，必须直接返回 `ReactiveController.act(snapshot)`。H=0 因而是结构性
hard negative control，而不是另一份 current greedy 的近似复现。

若 view 非空，但当前 pre-step snapshot 中不存在任何 future event × AVAILABLE resource
满足本规范 future feasibility，也必须直接委托 Reactive。SERVING resource 不参与该判断；
共享移动物理产生的预期 `ValueError` 只令对应 pair 不可行。future pair 结果只在本次 `act()`
局部缓存，并供后续 expanded matching 复用，不形成跨 step 状态。

H=0 完整 rollout 必须分别验证每步 action sequence、每个 `StepResult` 和 terminal
`EpisodeMetrics` 均与 Reactive 完全相等；不要求 action 对象 identity。

## 7. Primary expanded-candidate greedy

只有存在至少一个 physically feasible future pair 时，Oracle 才进入 expanded planning。
候选集合由当前 `TaskStatus.WAITING` task 和 bounded future `DemandEvent` 组成。IN_SERVICE
task、intensity、counts、hidden state 和 prediction 不进入候选。

当前 task 使用 `remaining_service`，future event 使用完整 `service_time`。统一定义：

```text
effective_deadline = min(event.deadline, stop_step)
latest_service_start = effective_deadline - work
```

所有 candidate 按以下键升序：

1. 更小 `latest_service_start`；
2. 更高 priority；
3. 更早 arrival step；
4. 更小 event ID。

不增加 current/future bonus、reward 或 weighted score。SERVING resource 固定
`ContinueAction` 且不参与新 matching；AVAILABLE resource 参加统一 greedy。一个 resource
和一个 candidate 在本 step 至多匹配一次。无 feasible 未匹配 resource 的 candidate 被跳过，
不能阻断后续 candidate。

## 8. 精确 feasibility 与资源排序

禁止以 `ceil(distance / speed)` 作为物理真值。Oracle 复用 WP-02B 的 exact travel 路径，
最终调用 WP-02A/B 唯一共享的单槽移动原语。pair 数值 `ValueError` 只拒绝该 pair。

统一 travel budget 为：

```text
travel_budget = effective_deadline - work - t
```

负预算不可行。current WAITING task 的：

```text
earliest_service_start = t + exact_travel_slots
```

future event 的：

```text
earliest_service_start = max(event.arrival_step, t + exact_travel_slots)
```

两者都要求：

```text
earliest_service_start + work <= effective_deadline
```

单个 candidate 的 feasible resources 按 exact travel slots、当前有限欧氏距离、resource ID
升序选择。该定义保留 Move/Serve 同槽互斥、deadline equality、terminal equality、非零绝对
时间和共享浮点移动语义。

## 9. 动作与 pre-position

current WAITING candidate 被选中时，资源已精确位于事件位置则 `ServeAction(event_id)`，
否则 `MoveAction(event.position)`。

future candidate 被选中时，资源不在目标位置则 `MoveAction(event.position)`；已经提前到达
目标则 `IdleAction()`。arrival 前绝不发出 `ServeAction`。事件到达当前边界后，official
builder 不再把它放入 future view；环境 snapshot 将它表示为 current WAITING task，此后走
current action 语义。

## 10. 能力、名称与 WP-02D 边界

`RollingTrueFutureOracle` 应在文档和论文中准确解释为：

> H-step rolling true-future matched heuristic

它是有限 horizon、receding-horizon、deterministic matched heuristic，不是 global optimum、
optimal oracle 或 theoretical upper bound。WP-02C 只冻结 horizon 参数语义；primary H 数值
和 sensitivity set 留给 WP-02D 在 H1 gate 前预注册。

WP-02C 不实现 reference/exhaustive verifier。WP-02D 未来诊断 verifier 暂定最多 2 个
resources、4 steps、3 events，必须使用真实 `ResourceServiceEnvironment`，不公开为正式
baseline，也不声称 global optimum 或 upper bound。其 priority、movement、weighted
objective 与详细搜索顺序不在 WP-02C 冻结。

canonical 机制证明使用一个位于 `(0, 0)`、速度 1 的资源，以及 arrival 2、位置 `(2, 0)`、
service time 1、deadline 3 的事件。H=2 Oracle 必须产生 Move → Move → Serve 并在 boundary 3
完成；Reactive 无法完成。该确定性测试不是 H1 正式统计实验。
