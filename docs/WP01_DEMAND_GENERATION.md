# WP-01 外生需求生成规范

## 1. 工作包目标

WP-01 建立与策略完全解耦、可复现、可统计验证的外生需求生成系统。其输出将被环境、预测器和各类策略共同消费，但需求过程本身不得读取这些模块的内部状态。

WP-01 分为三个按顺序完成的子工作包：

- **WP-01A**：核心数据结构、公共状态接口和平稳 Poisson 需求；
- **WP-01B**：Drifting Hotspot、Markov Switching、Burst Demand；
- **WP-01C**：配置、工厂扩展、数据序列化、CLI、统计汇总和可选可视化。

不得在前一子工作包验收前提前实现后一子工作包。

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

候选模块：

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

## 8. WP-01B 规划边界

WP-01B 仅增加：

- Drifting Hotspot；
- Markov Switching；
- Burst Demand。

必须复用 WP-01A 的数据模型、公共状态语义、RNG 隔离和工厂约定。具体参数化、状态暴露和 OOD 边界在 WP-01B 设计审查时冻结。

## 9. WP-01C 规划边界

WP-01C 才允许加入：

- 配置文件读取；
- 工厂扩展；
- NPZ、CSV 或 JSON 序列化；
- CLI；
- 统计汇总；
- 可选 Matplotlib 可视化。

不得在 WP-01A/01B 提前引入这些设施。

## 10. WP-01 非目标

整个 WP-01 不实现 PettingZoo、智能体运动、任务服务逻辑、奖励、MAPPO、PyTorch、GPU 训练、多进程或大规模性能优化。

## 11. 当前状态

截至 2026-08-17，WP-01A 候选 patch 已完成独立代码审查，专项测试在隔离审查环境中为 `164 passed`，补入远程基线两项原有测试后为 `166 passed`，未发现阻断性缺陷。独立环境使用 Python 3.13，结果不能替代 Python 3.11 正式验收。Mac 最终完整验收、Commit、Push、A100 验收和稳定 Commit 记录仍待完成，因此 WP-01A 尚未标记为正式完成。
