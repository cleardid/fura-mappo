# WP-02A：确定性资源服务环境规范

## 1. 范围与兼容性边界

WP-02A 只实现消费冻结 `DemandTrace` 的确定性资源服务环境。它不实现
Reactive、Oracle、预测器、不确定性模型、RL/MAPPO、reward、Gym/PettingZoo、
新 CLI 或新配置协议，也不改变 WP-01 的 demand 模型、artifact、schema、hash、
summary、CLI 与固定种子行为。

环境唯一的公共 demand 输入是：

```python
reset(source: DemandTrace) -> EnvironmentSnapshot
```

不接受 `DemandProcess`、`DemandStep` generator、callback 或在线 `demand.step()`。
环境从 trace 的 event 构建私有绝对时间 arrival schedule，但动力学不读取
intensity、需求类型、seed、config、RNG 或 manifest，也不向调用方暴露 source、
future schedule、future index 或 future accessor。future event 仅在其到达边界加入
task ledger。因此控制动作不能影响需求实现，改变 intensity 而保持 events 不变也
不能改变环境轨迹。

## 2. 公共模型

环境构造接口为：

```python
ResourceServiceEnvironment(config: ResourceServiceConfig)
```

`ResourceServiceConfig` 包含 `initial_resource_positions` 与 `movement_speed`。
至少需要一个资源；位置必须是有限二维坐标；速度必须是有限正实数；布尔值不能
充当数值。构造时将输入防御性规范化为 Python `float` tuple，不修改调用方输入。

公共动作是：

- AVAILABLE：`IdleAction`、`MoveAction(target_position)`、
  `ServeAction(event_id)`；
- SERVING：仅 `ContinueAction`。

`EnvironmentSnapshot` 是环境全局状态快照，并不是未来 RL actor observation。
它包含 `absolute_step`、`steps_remaining`、不可变 resource/task snapshots 和
`current_arrivals`，不包含未来需求、intensity、hidden state、prediction 或 reward。

`StepResult` 包含 `next_snapshot`、`step_metrics`、`is_terminal` 和
`episode_metrics`。非 terminal 时 `next_snapshot` 非空且 `episode_metrics` 为空；
terminal 时正好相反。

## 3. 连续二维资源与移动

资源同质，`resource_id = 0..R-1`，位于连续二维欧氏空间。每个资源每 slot
最多提供一个 service work unit。多资源可以共址；没有碰撞、障碍、道路或 zone
capacity；`zone_id` 只用于统计。

服务要求规范化 Python float tuple 精确相等：

```python
resource.position == event.position
```

不使用隐藏 epsilon。`MoveAction` 的 target 必须是有限二维坐标。若到 target 的
距离不超过 `movement_speed`，candidate position 直接等于原 target；否则沿目标
方向移动最多一个 `movement_speed`。Move 与 Serve 在同一 slot 互斥，移动到任务
位置后也只能在下一 slot 服务。空闲资源在下一边界可重新定向，不保存持续移动
承诺。

零距离 Move 合法，计作 idle slot，并令 `zero_distance_moves += 1`。正距离移动
才计入 `movement_slots`。计算必须保证 displacement、欧氏距离、candidate
position 和 actual distance 均有限；正距离目标必须产生可表示的正位移；实际
位移不得超过速度。违反条件在 commit 前抛出 `ValueError`。距离使用稳定的
`math.hypot`，浮点累计使用 `math.fsum`，累计移动距离不得成为无穷值。

## 4. Canonical state 与生命周期

环境只保存一份 canonical assignment：

```text
resource_to_event[resource_id] -> event_id | None
```

其余 mutable core 是 `resource_positions` 与 private task ledger。每个 task entry
只保存 immutable `DemandEvent`、`remaining_service`、`service_start_step`、
`completion_time` 和 `terminal_outcome`。`terminal_outcome` 只能是 `None`、
`COMPLETED`、`EXPIRED` 或 `TRUNCATED`。

不额外保存 task 的 assigned resource、resource status 或 task 的
WAITING/IN_SERVICE status。公共 snapshot 中这些值全部从 canonical assignment
和 terminal outcome 派生：

- WAITING：outcome 为空且没有 resource 引用；
- IN_SERVICE：outcome 为空且恰有一个 resource 引用；
- 一个 event 最多被一个 resource 引用；
- terminal task 不得被 resource 引用；
- `remaining_service == 0` 当且仅当 outcome 为 COMPLETED。

服务开始后不可抢占、暂停、迁移、换资源或由多个资源合作加速。

## 5. 绝对时间与事务语义

绝对 step `t` 表示 slot `[t, t+1)`：

```text
start_step = source.start_step
stop_step  = start_step + source.counts.shape[0]
```

不假定 `start_step == 0`，也不假定 events 已按 arrival 分组。

`reset` 完整构造 candidate episode、私有 schedule、初始资源状态与
`t = start_step`，注入 `arrival_step == t` 的任务并成功构造初始 snapshot 后，
才一次性替换旧状态。failed reset 保留原 episode。初始 snapshot 满足：

```text
steps_remaining = stop_step - t = num_steps
current_arrivals = 在边界 t 刚注入的任务
```

最后一个可行动 snapshot 的 `steps_remaining == 1`。

`step(actions_t)` 的语义顺序为：

1. 对 pre-step state 全量验证动作；
2. 对 pre-step CURRENT WAITING 集合解析 duplicate Serve；
3. 在 candidate 中计算所有移动；
4. 建立 candidate assignment；
5. Continue 与新 assignment 各提供一个 service work unit；
6. 记录 slot `[t,t+1)` 的 service/movement/idle 指标；
7. 在边界 `t+1` 先处理 completion；
8. 再令仍未完成且 `deadline <= t+1` 的任务 EXPIRED；
9. 非 terminal 时注入 `arrival_step == t+1` 的任务；
10. terminal 时将尚未完成且未 expired 的任务记为 TRUNCATED；
11. 构造并验证 candidate metrics、snapshot/result 和全部不变量；
12. 全部成功后一次性 commit。

任意异常都不推进时间，不改变 positions、assignments、ledger 或累计指标。
首次成功 reset 前 step、以及 terminal 后 step，均抛 `ValueError` 且状态不变。

## 6. 服务与 deadline

新 `ServeAction` 在当前 slot 立即提供第一个 work unit。因此，资源若在边界 `t`
已位于任务位置，`service_time=1` 的任务可在 `[t,t+1)` 获得一个 unit，并在
边界 `t+1` 完成：

```text
service_start_step = t
completion_time    = t + 1
```

`deadline=d` 是排他时间边界，最后合法 service slot 是 `[d-1,d)`。若该 slot
令 remaining work 在边界 `d` 变为零，任务先记 COMPLETED；只有随后仍未完成且
`deadline <= d` 才记 EXPIRED。in-service expiration 会解除 assignment，资源
从该边界重新 available，已投入 work 仍纳入指标。

terminal boundary 的顺序固定为最后一个 service slot、completion、expiration、
truncation。不增加 drain tail；terminal 后 assignment 全部为空。

## 7. Serve 隔离与冲突规则

`ServeAction` 只能查询当前边界的 CURRENT WAITING registry。任何合法整数
`event_id` 只要不在该集合中，无论它是不存在、future、completed、expired、
truncated 或正在服务，都统一抛：

```text
ValueError("event_id 必须引用当前 WAITING 任务")
```

验证路径不查询 future schedule 来判断原因，避免 future side-channel。

若 `k` 个 AVAILABLE resources 在同一 pre-step 边界合法请求同一 WAITING task，
最小 `resource_id` 获胜；其余 `k-1` 个请求本 slot 为 no-op 并计作 idle，且
`duplicate_assignment_conflicts += k - 1`。该计数是失败的合法重复请求数，不是
冲突组数。

## 8. 指标与守恒

WP-02A 不定义综合 reward。`StepMetrics` 将边界 `t` 已注入的 arrivals 归入
step `t`，将 slot `[t,t+1)` 内的 resource 使用以及边界 `t+1` 的 completion、
expiration、terminal truncation 归入同一个 step。

terminal `EpisodeMetrics` 从 task ledger 重建 outcome、priority、service-work 与
delay 指标，并报告：

- `arrived`、`completed`、`expired`、`truncated`；
- 四类对应的 priority sums；
- `demanded_service_work`；
- `service_slots`、`movement_slots`、`idle_slots`、`movement_distance`；
- completed/expired/truncated service work；
- expired/truncated remaining work；
- service-start wait sum/count 与 completed response sum/count；
- duplicate conflicts 与 zero-distance moves；
- 每个 zone 的 arrived/completed/expired/truncated。

对 task `e`：

```text
delivered_work(e) = e.service_time - remaining_service(e)
waiting_time      = service_start_step - arrival_step
response_time     = completion_time - arrival_step
```

waiting 只统计真正开始过服务的任务，response 只统计 COMPLETED 任务。rate 或
mean 的分母为零时返回 `None`，不是 `0.0`。整数计数使用 Python integer；priority
与 distance 求和使用 `math.fsum`。

终局严格满足：

```text
arrived = completed + expired + truncated

service_slots = completed_service_work
              + expired_service_work
              + truncated_service_work

demanded_service_work = completed_service_work
                       + expired_service_work
                       + expired_remaining_work
                       + truncated_service_work
                       + truncated_remaining_work

num_resources * num_steps = service_slots + movement_slots + idle_slots
```

各 zone 同样满足 outcome 守恒。TRUNCATED task 已得到的服务量只称
`truncated_service_work`，不命名为 wasted work。

## 9. 验证边界

确定性测试覆盖 reset/current arrival、非零 start step、deadline/completion 顺序、
in-service expiration、last-slot completion、terminal expiration/truncation、无
drain tail、移动数值边界、精确位置、不可抢占/迁移/合作、duplicate tie-break、
canonical assignment、不变量、事务失败路径、future Serve 隔离、外生需求独立性、
可复现轨迹、全部 outcome/work/resource/per-zone 守恒与零分母指标。

WP-02A 不增加第三方依赖，且必须保持全部 WP-01 CPU tests 通过。
