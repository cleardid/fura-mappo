# WP-02B：确定性 Reactive Baseline 规范

## 1. 范围与冻结边界

WP-02B 只增加集中式、无状态、确定性、无随机数且无 reservation 的
`ReactiveController`。控制器只消费当前 `EnvironmentSnapshot`，并额外保存与配对
`ResourceServiceEnvironment` 相同的 `movement_speed`。正式 rollout 直接使用 WP-02A 的
`ResourceAction`、`StepResult` 和 `EpisodeMetrics`。

本工作包不实现 Oracle、future view、Oracle horizon、H1 正式实验、预测器、不确定性、
reward、RL/MAPPO、Gym/PettingZoo、PyTorch/GPU、ID/OOD 主实验、大型优化器、公共 rollout
或 policy protocol、多进程。WP-02C 将独立设计 future planning。

WP-02B 不改变 WP-02A 的环境公共 API、轨迹、指标、deadline/terminal 语义和 duplicate
resolution，也不改变 WP-01 的任何冻结接口或协议。

## 2. 公共接口与状态

公共接口为：

```python
ReactiveController(movement_speed: float)

controller.act(
    snapshot: EnvironmentSnapshot,
) -> tuple[ResourceAction, ...]
```

`movement_speed` 显式拒绝 Python/NumPy bool 和非 `Real`；转换为 Python `float` 时的
`OverflowError` 作为 `ValueError`；NaN、无穷和非正值作为 `ValueError`。实例最终只保存
一个规范化 Python `float`。

控制器不保存 config、初始位置、环境、DemandTrace、历史动作、movement target、task
reservation、RNG 或需求过程信息，也不提供 episode reset。每次 `act()` 完全依据当前
snapshot 重新规划；已经移动过的 AVAILABLE resource 下一步可以重定向。

`act()` 要求输入为 `EnvironmentSnapshot`，且：

```text
snapshot.resources[index].resource_id == index
```

不满足时抛 `ValueError`。正常动态信息只来自 `absolute_step`、`steps_remaining`、
`resources` 和 `active_tasks`。`current_arrivals` 不参与单独预测或历史逻辑。控制器不访问
future event、intensity、hidden state、seed/config、artifact、预测或环境私有状态。

## 3. 共享单槽移动原语

WP-02A 原 `ResourceServiceEnvironment._calculate_move()` 的实现机械提取到未公开的
`fura_mappo.envs._movement`。`_MoveResult` 同时迁入该内部模块。环境原方法保留为薄
wrapper，Reactive 的 exact feasibility 也调用同一原语。

提取保持原有运算顺序、`math.hypot`、单槽 target 精确 clamp、zero-distance、逐坐标
`math.nextafter` 收缩、finite checks、不可表示正移动拒绝、公开异常类型/消息和
`actual_distance <= movement_speed` 严格规则，不引入 epsilon。

## 4. 当前资源与任务集合

每个 SERVING resource 固定返回 `ContinueAction()`，且不参加新任务 matching。只有
AVAILABLE resources 参加 matching；未匹配 AVAILABLE resource 最终返回 `IdleAction()`。

只有 `TaskStatus.WAITING` 任务进入候选，IN_SERVICE 和其他状态均忽略。令：

```text
t = snapshot.absolute_step
stop_step = t + snapshot.steps_remaining
work = task.remaining_service
effective_deadline = min(task.event.deadline, stop_step)
latest_service_start = effective_deadline - work
```

任务严格按以下键升序处理：

1. 更小的 `latest_service_start`；
2. 更高 priority；
3. 更早 arrival_step；
4. 更小 event_id。

不使用 reward、权重或其他 score。

## 5. Exact feasibility

对 AVAILABLE resource 与 WAITING task：

```text
travel_budget = effective_deadline - work - t
```

预算为负时 pair 不可行。若当前位置与 event position 精确相等，`travel_slots = 0`。
否则从当前浮点位置开始，最多重复 `travel_budget` 次共享单槽移动原语；首次位置精确等于
event position 时得到 exact `travel_slots`。预算内未到达则不可行。共享移动原语针对该
pair 抛出预期数值 `ValueError` 时，只拒绝该 pair，继续检查其他 resource/task pair。

不得以 `ceil(distance / movement_speed)` 替代 exact simulation，也不得复制移动物理。
可行性最终为：

```text
earliest_service_start = t + travel_slots
earliest_completion = earliest_service_start + work
earliest_completion <= effective_deadline
```

该定义保持 Move/Serve 同槽互斥；移动到目标后只能在下一 slot Serve；允许 deadline
equality、terminal equality、last-slot completion 和非零 absolute step。

## 6. 确定性 matching 与动作

对当前 task 的所有 feasible、AVAILABLE、尚未匹配 resource，严格按以下键升序选择：

1. 更小的 exact `travel_slots`；
2. 更小的有限初始欧氏距离；
3. 更小 `resource_id`。

若当前 task 没有可行 resource，则跳过该 task 并继续处理下一个 task；不可行的高紧迫
任务不能阻断后续任务。选中后 task 和 resource 都从本 step matching 集合移除。

选中 resource 已精确位于 event position 时返回 `ServeAction(event_id)`，否则返回
`MoveAction(event.position)`。最终动作 tuple 长度严格等于资源数，按 resource_id 排列，
每个 resource 恰有一个动作。Reactive 自身产生唯一 matching，不主动产生 duplicate
Serve；正常 rollout 的 `duplicate_assignment_conflicts == 0`。WP-02A 原有 duplicate
resolution 保持不变。

## 7. Rollout 与 Oracle 边界

WP-02B 不新增公共 rollout runner。测试或实验调用方可局部循环：

```text
snapshot = env.reset(trace)
while snapshot is not None:
    actions = controller.act(snapshot)
    result = env.step(actions)
    snapshot = result.next_snapshot
```

实验调用方必须用构造配对环境的同一 `ResourceServiceConfig.movement_speed` 构造控制器；
控制器不持有环境，因此一致性由调用方保证。结果直接使用 `EpisodeMetrics`，不增加 reward、
weighted objective 或 baseline-specific 公共指标。

未来 Oracle 必须共享 WP-02A 环境、单槽移动原语、物理可达性、服务/deadline/terminal
语义、公共动作和 EpisodeMetrics，但不要求复用 Reactive 的任务紧迫度、贪心 matching、
当前任务 dispatch 或 no-reservation 规划。

## 8. 验证边界

确定性小测试覆盖共享移动机械回归与浮点反例、构造校验、信息隔离、snapshot 顺序、资源与
任务状态、四级任务排序、三级资源排序、唯一 matching、不可行任务跳过、单 pair 数值失败
隔离、deadline/terminal equality、Move/Serve 时序、非零 absolute step、环境 rollout
完成时间一致性、重复 rollout 动作/指标一致、全局 Python/NumPy RNG 不污染，以及全部
WP-02A 和既有 CPU tests 回归。禁止随机统计测试。
