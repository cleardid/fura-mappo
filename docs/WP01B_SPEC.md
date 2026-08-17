# WP-01B 冻结规范：三类非平稳外生需求

## 1. 状态与基线

- 状态：已完成并冻结；
- 实现 Commit：`d67f71b5d75ee47adb120686914d32572ea7d6d1`；
- 稳定标签：`wp01b-stable`；
- 前序接口基线：`wp01a-stable`。

WP-01B 只增加 Drifting Hotspot、Markov Switching 和 Burst Demand，并保持 WP-01A 公共数据模型、状态语义和 Stationary 行为兼容。

## 2. 公共类

```python
DriftingHotspotDemand(
    *, seed, base_intensities, hotspot_amplitudes, hotspot_scales,
    initial_hotspot_positions, hotspot_velocities, zone_bounds,
    priority_range, service_time_range, deadline_offset_range,
)

MarkovSwitchingDemand(
    *, seed, state_intensities, transition_matrix, initial_state,
    zone_bounds, priority_range, service_time_range, deadline_offset_range,
)

BurstDemand(
    *, seed, base_intensities, burst_probability, burst_duration_range,
    burst_amplitude_range, burst_zone_weights, zone_bounds,
    priority_range, service_time_range, deadline_offset_range,
)
```

三类从 `DemandProcess` 继承 `base_seed`、`current_step`、`next_event_id`、`reset()`、`step()` 和 `generate()`。不公开热点位置、Markov 当前状态或 burst 活动状态。

## 3. 公共状态与 reset 原子性

- 基类构造函数不虚调用子类 reset 钩子；
- `reset(seed)` 先创建候选 Generator，再调用内部 `_reset_process_state()`；
- 钩子成功后一次提交基准 seed、Generator、step=0 和 event ID=0；
- 候选 Generator 或钩子失败时，原公共状态和 Generator 引用保持不变；
- `step()` 仍只在完整合法 Step 成功后推进；
- 子类可以在 `_sample_step()` 成功构造 Step 后提交自身下一隐状态；
- 不保证任意内部异常后的 RNG 回滚。

## 4. 内部共享 Poisson 层

`_PoissonDemandProcess` 和 `_build_demand_step(...)` 为未导出内部实现，统一：

- 动态逐区域强度校验；
- Poisson counts；
- 半开矩形事件位置；
- priority、service time 和 deadline；
- 连续 event ID；
- `DemandStep` 构造。

它不是公共 API。`StationaryPoissonDemand` 构造签名和相同 seed 轨迹必须与 WP-01A 精确一致。

## 5. DriftingHotspotDemand

### 5.1 参数形状

```text
base_intensities: [num_zones]
hotspot_amplitudes: [num_hotspots]
hotspot_scales: [num_hotspots]
initial_hotspot_positions: [num_hotspots, 2]
hotspot_velocities: [num_hotspots, 2]
zone_bounds: [num_zones, 4]
```

至少一个区域和一个热点。base/amplitude 非负，scale 严格正，所有数值有限并通过 Poisson 安全上界检查。

### 5.2 强度定义

对区域中心 `c_z`、矩形面积 `A_z`、热点位置 `h_k` 和尺度 `sigma_k`：

```text
log q_kz = log(A_z) - ||c_z - h_k||^2 / (2 * sigma_k^2)
w_kz = q_kz / sum_j q_kj
lambda_z = base_z + sum_k amplitude_k * w_kz
```

实现使用 log-space 减最大值归一化，避免面积、极端尺度和坐标导致溢出/下溢。每个热点的逐区增量和等于其 amplitude。

### 5.3 移动与时序

- 所有区域外包矩形定义反射边界；
- 当前热点位置用于当前步强度；
- Step 成功后按速度推进并反射；
- 反射使用周期折叠，支持正负速度、边界方向和单步多次跨界；
- reset 恢复初始位置和初始速度；
- amplitude 为 0 时不贡献强度，但热点仍移动。

## 6. MarkovSwitchingDemand

### 6.1 参数

```text
state_intensities: [num_states, num_zones]
transition_matrix: [num_states, num_states]
initial_state: int
```

至少一个状态。强度有限非负并在 Poisson 安全范围。`initial_state` 为非 bool 合法整数。

### 6.2 转移矩阵

- 拒绝 bool、object、complex、负值、NaN 和 inf；
- 浮点矩阵行和必须在明确容差内接近 1；
- 容差：`max(1e-12, min(1e-6, 8 * num_states * eps(source_dtype)))`；
- 整数矩阵只接受每行精确 one-hot；
- 通过后复制到 float64 并除以实际行和；
- 不修改调用方矩阵。

### 6.3 时序

- 当前状态 `s_t` 的强度先产生当前 Step；
- Step 成功后从 `P[s_t]` 选择 `s_{t+1}`；
- 只有一个正概率目标的行直接选择，不消费 RNG；
- reset 恢复 `initial_state`。

## 7. BurstDemand

### 7.1 参数

```text
base_intensities: [num_zones]
burst_probability: float in [0, 1]
burst_duration_range: integer closed interval, low >= 1
burst_amplitude_range: finite real closed interval, low >= 0
burst_zone_weights: [num_zones], nonnegative and at least one positive
```

权重先按最大正值缩放，再稳定归一化。构造期检查最大 amplitude 下逐区 Poisson 安全上界。

### 7.2 时序

- inactive 时按 `burst_probability` 判断是否启动；
- `p=0` 和 `p=1` 不消费无意义 Bernoulli RNG；
- 只有启动时采样 duration 和 amplitude；固定范围端点不消费 RNG；
- 启动步立即以 active 强度发射；
- active 期间不抽新启动、不重采样；
- Step 成功后剩余时长减一，归零时清除 amplitude；
- reset 恢复 inactive、remaining=0、amplitude=0。

活动强度：

```text
lambda = base_intensities + active_amplitude * normalized_weights
```

## 8. 四类型工厂 schema

共享字段：

```text
type, seed, zone_bounds, priority_range,
service_time_range, deadline_offset_range
```

规范类型及专属字段：

```text
stationary_poisson: intensities

drifting_hotspot:
  base_intensities, hotspot_amplitudes, hotspot_scales,
  initial_hotspot_positions, hotspot_velocities

markov_switching:
  state_intensities, transition_matrix, initial_state

burst:
  base_intensities, burst_probability, burst_duration_range,
  burst_amplitude_range, burst_zone_weights
```

类型名称区分大小写、无别名。工厂同时、排序报告缺失和多余字段，不修改顶层 Mapping、嵌套序列或数组。

## 9. 随机性和退化配置

必须保持：

- 同 seed 完全复现；
- 不同实例交错调用仍独立；
- Python `random` 和 NumPy 全局 RNG 不被污染；
- 确定性 Markov、burst p=0/p=1、固定 duration/amplitude、零计数区域和固定任务属性不消费无意义 RNG；
- 返回数组被强制改写后不影响内部状态或 reset 重放。

## 10. 测试与验收

- Drifting：20,000 步，独立参考 intensity、总强度守恒、反射和逐区八标准误 Poisson；
- Markov：50,000 步、1,000 burn-in，稳定占用率、转移率和条件 Poisson；
- Burst：50,000 步，活动率和 active/inactive 条件 Poisson；duration>1 使用理论活动率额外检查；
- Stationary：150 组随机配置与 WP-01A 原实现完全一致；
- 工厂：四 schema、未知/缺失/多余字段和输入不变性；
- Mac：`293 passed`，Ruff/格式通过；
- GitHub Actions run #5：成功；
- A100 Python 3.11.15：用户确认通过。

## 11. 非目标

WP-01B 不包含文件配置、序列化、CLI、统计汇总、可视化、metadata、ID/OOD 数值硬编码、环境、预测、RL、PyTorch、GPU 或并行化。
