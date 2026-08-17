# WP-01A 规范：平稳需求核心

## 1. 唯一目标

建立可复现、与策略完全解耦的需求生成核心，并实现平稳 Poisson 需求过程。

## 2. 范围

### 实现内容

- `DemandEvent`；
- `DemandStep`；
- `DemandTrace`；
- `DemandProcess` 抽象基类；
- `StationaryPoissonDemand`；
- `create_demand_process`；
- `create_numpy_generator`；
- 对应数据、状态、随机性、工厂和统计测试。

### 非目标

- Drifting Hotspot；
- Markov Switching；
- Burst Demand；
- YAML、NPZ、CSV 或 JSON 序列化；
- CLI 和绘图；
- PettingZoo、智能体运动、任务服务和奖励；
- MAPPO、PyTorch 和 GPU；
- 并行化和大规模性能优化。

## 3. 模块结构

```text
src/fura_mappo/demand/
├── __init__.py
├── models.py
├── processes.py
└── factory.py
```

需求模块位于顶层 `fura_mappo.demand`，强调其为外生科学组件，而不是智能体环境内部逻辑。

## 4. 数据接口

### DemandEvent

字段：

```text
event_id: int
arrival_step: int
zone_id: int
position: tuple[float, float]
priority: float
service_time: int
deadline: int
```

局部约束：非负 ID 和时间步、合法二维有限坐标、`priority ∈ [0,1]`、`service_time >= 1`、`deadline > arrival_step`。

### DemandStep

```text
step: int
intensity: np.ndarray   # [num_zones], float64
counts: np.ndarray      # [num_zones], int64
events: tuple[DemandEvent, ...]
```

按区域聚合的事件数必须与 `counts` 完全一致。

### DemandTrace

```text
start_step: int
counts: np.ndarray       # [num_steps, num_zones], int64
intensities: np.ndarray  # [num_steps, num_zones], float64
events: tuple[DemandEvent, ...]
```

按时间步和区域聚合的事件数必须与 `counts` 完全一致。WP-01A 不保存 metadata，也不重复保存 `DemandStep` 列表。

所有数组防御性复制并设为只读；数据类不依赖 NumPy 数组自动相等比较。

## 5. 状态语义

### 构造

- seed 必须显式提供；
- 构造后立即可调用 `step()`；
- 初始 `current_step = 0`；
- 初始 `next_event_id = 0`。

### reset

- `reset(None)`：使用当前基准 seed 完整重放；
- `reset(new_seed)`：永久更新基准 seed；
- RNG、时间步和 event ID 同时重置。

### step

- 生成当前绝对时间步；
- event ID 从 `next_event_id` 连续分配；
- 只有完整 `DemandStep` 成功构造后，公共时间和编号才推进；
- 不要求异常时回滚已消耗的 RNG 状态。

### generate

- `generate(n)` 从当前状态继续；
- `generate(n, seed=s)` 先重置为 seed `s`，从 step 0 开始；
- 完成后保留推进状态；
- `DemandTrace.start_step` 记录轨迹第一行的绝对时间步；
- `n` 必须是非 bool 正整数。

## 6. 平稳 Poisson 配置

```text
seed
intensities                # [num_zones]
zone_bounds                # [num_zones, 4]
priority_range             # (low, high)
service_time_range         # (low, high), 闭区间整数
deadline_offset_range      # (low, high), 闭区间整数
```

规则：

- 强度只接受逐区域向量，不接受标量；
- 强度有限且非负；
- 区域为轴对齐半开矩形 `[x_min,x_max) × [y_min,y_max)`；
- 各区域 Poisson 计数独立采样；
- 事件按时间步、zone ID、区域内采样顺序生成；
- priority 连续均匀采样；
- service time 和 deadline offset 在闭整数区间采样；
- 相等范围退化为确定值；
- 零强度区域不产生事件；
- 所有随机性来自实例私有 `numpy.random.Generator`。

## 7. 工厂

```text
create_demand_process(config: Mapping[str, object]) -> DemandProcess
```

WP-01A 仅支持区分大小写的：

```text
type: "stationary_poisson"
```

工厂严格拒绝缺失字段、多余字段和未知类型，不修改调用方映射、嵌套列表或 NumPy 数组。

## 8. 校验边界

- bool 和 `numpy.bool_` 不得作为整数或实数被接受；
- 混合数值序列中的 bool 必须在 NumPy dtype 强制转换前被发现；
- 范围必须是有序、可重复读取的非字符串 `Sequence`；
- set、frozenset、Mapping、generator 和其他 Iterator 被拒绝；
- generator 被拒绝时不得被消费；
- NaN、无穷、负强度、非法维度、浮点 counts 和区域数量不匹配被拒绝。

## 9. 验收重点

- 同种子完全复现；
- 不同种子通常不同；
- 不污染全局随机状态；
- 多实例互不影响；
- 输出数组形状、dtype 和只读性正确；
- counts 与事件一致；
- event ID 连续；
- 坐标、属性、deadline 合法；
- 零强度精确为零；
- 长序列经验均值在八个标准误内接近理论强度；
- 原有 WP-00 测试保持通过。
