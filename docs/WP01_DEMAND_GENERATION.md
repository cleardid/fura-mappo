# WP-01 外生需求生成规范

## 1. 工作包目标

WP-01 建立与策略完全解耦、可复现、可统计验证的外生需求生成系统。其输出将被环境、预测器和各类策略共同消费，但需求过程本身不得读取这些模块的内部状态。

WP-01 分为三个按顺序完成的子工作包：

- **WP-01A**：核心数据结构、公共状态接口和平稳 Poisson 需求；
- **WP-01B**：Drifting Hotspot、Markov Switching、Burst Demand；
- **WP-01C**：配置、工厂扩展、数据序列化、CLI、统计汇总和可选可视化。

不得在前一子工作包验收前提前实现后一子工作包。WP-01A 和 WP-01B 已完成；当前进入 WP-01C 只读设计阶段。

## 2. 全局科学约束

### 2.1 外生性

需求生成器不得读取或依赖：

- 智能体位置或数量；
- 策略动作；
- 奖励；
- 任务完成状态；
- 预测模型或强化学习模型。

### 2.2 随机数隔离

- 每个需求过程实例独占一个 `numpy.random.Generator`；
- 核心需求代码不得调用 NumPy 全局随机接口；
- 相同配置和 seed 必须产生相同轨迹；
- 不同实例的推进互不影响；
- 构造、`step`、`generate` 和 `reset` 不得污染 NumPy 或 Python 全局随机状态。

### 2.3 数据一致性

必须保证：

- 每步各区域计数之和等于该步事件数量；
- 过程生成的 `event_id` 唯一、连续且递增；
- `arrival_step`、`zone_id` 和坐标合法；
- `priority` 位于 `[0, 1]`；
- `service_time >= 1`；
- `deadline > arrival_step`；
- 强度有限且非负；
- 计数为非负整数。

### 2.4 配置安全

- 使用 `TypeError` 区分类型错误，使用 `ValueError` 区分值域或形状错误；
- 不使用 `assert` 校验用户输入；
- 不修改调用方配置或嵌套值；
- 不使用可变默认参数；
- 不静默接受维度不匹配、布尔数值或危险默认值；
- 输入数组与过程内部状态、输出数组之间不得共享可变内存。

## 3. WP-01A 公共数据接口

已实现并冻结的模块：

```text
src/fura_mappo/demand/
├── __init__.py
├── models.py
├── processes.py
└── factory.py
```

### 3.1 DemandEvent

冻结、带 slots 的数据对象：

```text
event_id: int
arrival_step: int
zone_id: int
position: tuple[float, float]
priority: float
service_time: int
deadline: int
```

对象验证局部字段约束；具体区域几何归属由生成器保证。

### 3.2 DemandStep

```text
step: int
intensity: np.ndarray  # [num_zones], float64
counts: np.ndarray     # [num_zones], int64
events: tuple[DemandEvent, ...]
```

要求：

- 至少一个区域；
- `intensity` 与 `counts` 形状一致；
- 事件到达步等于 `step`；
- 按区域聚合事件数与 `counts` 完全一致；
- 事件 ID 严格递增；
- 数组防御性复制并设置只读。

### 3.3 DemandTrace

```text
start_step: int
counts: np.ndarray       # [num_steps, num_zones], int64
intensities: np.ndarray  # [num_steps, num_zones], float64
events: tuple[DemandEvent, ...]
```

`start_step` 用于表示从过程当前状态继续生成的轨迹。轨迹至少包含一个时间步和一个区域，按时间步与区域聚合的事件数必须与 `counts` 完全一致。

WP-01A 不在 Step 或 Trace 中加入 metadata。实验配置、序列化元数据和版本信息在 WP-01C 统一设计。

## 4. DemandProcess 状态语义

`DemandProcess` 使用 ABC，由基类统一管理 RNG、时间步和事件编号。构造函数要求显式 seed，构造后可立即调用 `step()`。

初始状态：

```text
base_seed = seed
current_step = 0
next_event_id = 0
rng = 独立 Generator(seed)
```

### reset

```text
reset(seed: int | None = None) -> None
```

- `reset(None)`：使用当前 `base_seed` 创建新 Generator，时间步和事件编号归零；
- `reset(new_seed)`：验证并保存新 seed，创建新 Generator，时间步和事件编号归零；
- reset 后形成一条新轨迹，事件编号从 0 开始。

### step

```text
step() -> DemandStep
```

- 采样当前 `current_step`；
- 子类返回事件必须从 `next_event_id` 连续分配；
- 只有完整 `DemandStep` 成功构造并通过基类检查后，才推进时间步和事件编号；
- 不承诺在内部运行时异常后回滚 RNG 状态。

### generate

```text
generate(num_steps: int, seed: int | None = None) -> DemandTrace
```

- `num_steps` 必须是非布尔正整数；
- `seed=None` 时从当前过程状态继续；
- 指定 seed 时先执行等价于 `reset(seed)` 的操作；
- 返回轨迹后过程保持推进状态；
- 不支持零长度轨迹，不实现临时 RNG 或生成后恢复现场。

## 5. StationaryPoissonDemand

WP-01A 唯一过程类型：

```text
stationary_poisson
```

构造参数全部显式提供：

```text
seed
intensities
zone_bounds
priority_range
service_time_range
deadline_offset_range
```

### 5.1 强度

- `intensities` 只接受形状 `[num_zones]` 的一维向量；
- 标量不被接受；
- 含义为每个区域每个时间步的 Poisson 强度；
- 所有值有限、非负且位于 NumPy Poisson 安全范围；
- 零强度区域不产生事件。

### 5.2 区域

`zone_bounds` 形状为 `[num_zones, 4]`：

```text
(x_min, x_max, y_min, y_max)
```

每个区域为半开矩形：

```text
[x_min, x_max) × [y_min, y_max)
```

边界与跨度必须有限，且 `x_min < x_max`、`y_min < y_max`。

### 5.3 事件属性

- `priority_range=(low, high)`：连续均匀采样，满足 `0 <= low <= high <= 1`；
- `service_time_range=(low, high)`：闭区间离散均匀采样，满足 `1 <= low <= high`；
- `deadline_offset_range=(low, high)`：闭区间离散均匀采样，满足 `1 <= low <= high`；
- 上下界相等时退化为确定值；
- `deadline = arrival_step + deadline_offset`；
- 范围必须是有序、可重复读取的非字符串 Sequence；拒绝 set、Mapping、generator 和 Iterator。

### 5.4 采样顺序

每步先对完整强度向量采样区域计数，再按 `zone_id` 升序创建事件；区域内按采样数组顺序生成事件，事件 ID 连续分配。

## 6. 工厂接口

```text
create_demand_process(config: Mapping[str, object]) -> DemandProcess
```

WP-01A 配置字段：

```text
type: "stationary_poisson"
seed
intensities
zone_bounds
priority_range
service_time_range
deadline_offset_range
```

工厂区分大小写，不支持别名，严格拒绝缺失字段、多余字段和未知类型，不原地修改配置。

## 7. WP-01A 测试与验收要求

至少覆盖：

- 相同 seed 完全复现；不同 seed 通常不同；
- 不污染全局随机状态；实例交错调用仍独立；
- `reset`、`step`、`generate` 状态语义；
- 输出形状、dtype、只读和防御性复制；
- 按区域和时间的事件计数一致性；
- 连续 event ID、合法区域和半开坐标；
- 属性范围和截止时间；
- 零强度、非法强度、非法边界和非法配置；
- 混合 `bool` 数组、无序范围和一次性迭代器被拒绝；
- 固定 seed、20,000 步、逐区域八个标准误的 Poisson 均值检验；
- 原有 WP-00 测试继续通过。


## 8. WP-01B 已冻结非平稳过程

### 8.1 Drifting Hotspot

```text
type: "drifting_hotspot"
base_intensities[num_zones]
hotspot_amplitudes[num_hotspots]
hotspot_scales[num_hotspots]
initial_hotspot_positions[num_hotspots, 2]
hotspot_velocities[num_hotspots, 2]
```

每个热点使用区域中心、矩形面积和各向同性高斯构造 log-space 稳定权重。amplitude 表示每步总到达率增量，归一化后分配到各区域。当前热点位置先发射，完整 Step 成功后再按确定性反射推进。

### 8.2 Markov Switching

```text
type: "markov_switching"
state_intensities[num_states, num_zones]
transition_matrix[num_states, num_states]
initial_state
```

当前状态先发射，随后转移。转移矩阵严格校验并轻微归一化；只有一个正概率目标的确定性行不消费 RNG。

### 8.3 Burst Demand

```text
type: "burst"
base_intensities[num_zones]
burst_probability
burst_duration_range
burst_amplitude_range
burst_zone_weights[num_zones]
```

仅在空闲步抽启动，启动步立即发射，活动期间不重叠启动。活动强度为基础强度加 amplitude 乘稳定归一化区域权重。

### 8.4 状态与共享层

- 三类过程保持 WP-01A 的独立 Generator、`reset/step/generate` 和连续 event ID 语义；
- reset 候选 Generator 或隐状态重建失败时，原公共状态保持不变；
- 未导出的 `_PoissonDemandProcess` 统一四类过程的事件生成；
- Stationary 相同配置/seed 轨迹与 WP-01A 原实现精确一致；
- 不公开热点、Markov 或 burst 隐状态属性。

## 9. WP-01B 四类型工厂

```text
stationary_poisson
drifting_hotspot
markov_switching
burst
```

工厂按规范类型使用严格字段集合，区分大小写、无别名，同时排序报告缺失和多余字段，不修改调用方 Mapping、嵌套序列或数组。

## 10. WP-01B 测试与验收

至少覆盖：

- 同 seed 复现、不同实例隔离、全局 RNG 不污染；
- reset 原子性和三类隐状态时序；
- Stationary 精确回归；
- Drifting 独立参考强度、反射和总增量守恒；
- Markov 稳态占用、转移率和条件 Poisson；
- Burst 活动率、duration 语义和条件 Poisson；
- Poisson 安全上界、极端数值、配置不变性和退化配置随机消耗；
- 四类型工厂 schema。

已验收结果：Mac `293 passed`，独立审查通过，GitHub Actions run #5 成功，A100 Python 3.11.15 验收由用户确认通过。

## 11. WP-01C 规划边界

WP-01C 才允许加入：

- 安全配置文件读取和 schema/version；
- 工厂维护性完善；
- NPZ、JSON 或经设计批准的组合序列化；
- CLI；
- 统计汇总；
- 可选 Matplotlib 可视化；
- 复现 manifest、配置哈希和输出元数据。

设计必须明确格式版本、事件编码、dtype/shape、原子写入、覆盖策略、损坏文件、路径解析、stdout/stderr、退出码和可视化依赖。

## 12. WP-01 非目标

整个 WP-01 不实现 PettingZoo、智能体运动、任务服务逻辑、奖励、MAPPO、PyTorch、GPU 训练、多进程或大规模性能优化。

## 13. 当前状态

截至 2026-08-18：

- WP-01A 已完成，Commit `b7b48bb394bd4613652b4d1ff4158cb8503f52a5`，标签 `wp01a-stable`；
- WP-01B 已完成，Commit `d67f71b5d75ee47adb120686914d32572ea7d6d1`，标签 `wp01b-stable`；
- GitHub Actions `CPU checks` run #5 成功；
- A100 Python 3.11.15 验收通过；
- 当前只启动 WP-01C 只读设计分析。
