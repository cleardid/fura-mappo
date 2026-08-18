# 项目状态

更新日期：2026-08-19

## 已验证稳定基线

```text
WP-02B 实现 Commit：f290a45a67763b41941e919303b26fb16a67575a
WP-02A 实现 Commit：d01092831a227a9f520de4ff8ded1d9e13ba8262
WP-01C 实现 Commit：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
稳定标签：wp01c-stable
WP-01B：wp01b-stable
WP-01A：wp01a-stable
WP-00：wp00-stable
```

docs-only 收尾 Commit 不自引用自身 SHA；当前 HEAD 以 `git rev-parse HEAD` 为准。

## 工作包状态

| 工作包 | 状态 | 说明 |
|---|---|---|
| WP-00 | 已完成 | 项目骨架、环境、测试、CI、系统审计 |
| OPS-01 | 已完成 | main-only、补丁审查、CPU 验收 |
| WP-01A | 已完成 | 核心数据结构、状态机、Stationary |
| WP-01B | 已完成 | Drifting、Markov、Burst |
| WP-01C | 已完成 | YAML、hash、NPZ artifact、CLI、summary |
| WP-02A | 已完成 | 确定性资源服务环境；Mac、GitHub Actions、A100 验收通过 |
| WP-02B | 已完成 | Reactive baseline；Mac、独立审查、GitHub Actions、A100 验收通过 |
| WP-02C | 只读设计 | True-future Oracle；设计冻结前不得实现 |

## WP-01 冻结接口与协议

```text
DemandEvent
DemandStep
DemandTrace
DemandProcess
StationaryPoissonDemand
DriftingHotspotDemand
MarkovSwitchingDemand
BurstDemand
create_demand_process
create_numpy_generator
load_demand_config
compute_config_hash
DemandTraceArtifact
save_demand_trace
load_demand_trace
summarize_demand_trace
```

```text
fura-mappo.demand-generation v1
fura-mappo.demand-trace v1
fura-mappo.demand-summary v1
sha256-logical-v1
```

## WP-01C 验收

### Mac
- Python 3.11.15
- 421 passed
- Ruff / format / diff-check：通过

### 独立审查
- 最终批准候选 patch：`bea26147f19ed6db311040ae54a4192e0e82731a0b17c65296e5dfd2c79b917d`
- 多轮安全边界审查与聚焦修复后无阻断问题
- 发布时仅 Diff 段顺序不同；经逐文件字节比较确认内容一致

### GitHub
- Commit：`29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`
- CPU checks：run #7
- 结论：success

### A100
```text
Commit：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
Python：3.11.15
Conda：fura-mappo
Pytest：421 passed in 16.54s
CPU 验收：通过
```

## WP-02A 冻结能力

- deterministic `ResourceServiceEnvironment`
- 仅接受 `DemandTrace` 作为环境需求输入
- 连续二维欧氏移动与同质资源
- 精确位置服务，Move/Serve slot 互斥
- 非抢占服务
- completion → expiration → truncation 边界顺序
- canonical `resource_to_event` assignment
- 事务式 `reset` / `step`
- future Serve side-channel 隔离
- 确定性 duplicate assignment resolution
- 组成指标与精确守恒检查
- 不包含 reward、RL、Reactive 或 Oracle

稳定实现 Commit：`d01092831a227a9f520de4ff8ded1d9e13ba8262`。

## WP-02A 验收

### 独立 patch 审查

- 最终批准 patch SHA-256：`74b74cd9590eea1498152a81dc747cadf676d66890516c6460c07c819cd49e81`
- 第一轮独立审查发现并修复：合法移动浮点收缩 MAJOR、超大有限实数 `OverflowError` MINOR
- v2 独立复核：BLOCKER 0、MAJOR 0、MINOR 0

### Mac

- Python 3.11.15
- WP-02A 专项：55 passed
- 全量：476 passed
- Ruff、format、diff-check：通过

### GitHub Actions

- `CPU checks`：success
- 未记录未经仓库确认的 run number

### A100

```text
Commit：d01092831a227a9f520de4ff8ded1d9e13ba8262
Python：3.11.15
Conda：fura-mappo
WP-02A 专项：55 passed in 0.26s
全量：476 passed in 17.45s
Ruff：通过
format：64 files already formatted
最终工作树：干净
```

`python -m pip install -e ".[dev]"` 因 build isolation 尝试经失效代理
`127.0.0.1:17890` 获取 `setuptools>=69` 而失败。这是依赖重装步骤的网络/代理
失败，不是项目测试成功；未将其伪装为成功，也未据此修改项目依赖或环境配置。
随后在现有 Conda 环境执行 pip dependency check，结果为
`No broken requirements found`，且上述专项与完整 CPU 验收全部通过。

## WP-02B 冻结能力

- deterministic `ReactiveController`
- centralized、current-state-only、stateless、RNG-free、reservation-free
- controller 只动态消费 `EnvironmentSnapshot`，只额外持有 `movement_speed`
- 不访问 `DemandTrace`、future events、intensity 或 hidden demand state
- SERVING resource 固定返回 `ContinueAction`
- 仅 WAITING task 进入候选
- exact bounded travel feasibility
- 环境与 baseline 共用唯一内部 single-slot movement primitive
- 不使用 `ceil(distance / speed)` 作为 exact physical truth
- task 排序：`latest_service_start` → higher priority → earlier `arrival_step` → smaller `event_id`
- resource 排序：exact `travel_slots` → Euclidean distance → `resource_id`
- unique greedy matching；无 controller-side reservation
- 正常 Reactive rollout 不主动产生 duplicate Serve
- 直接使用 WP-02A `EpisodeMetrics`
- 不包含 reward、Oracle、prediction 或 RL

WP-02A 公共环境行为未改变；原 single-slot movement physics 仅机械抽取为共享内部
primitive。稳定实现 Commit：`f290a45a67763b41941e919303b26fb16a67575a`。

## WP-02B 验收

### Mac

- Python 3.11.15
- 全量：520 passed in 5.80s
- Ruff、format、diff-check：通过

### 独立候选审查

- 最终批准 patch SHA-256：`38648aac6ae7d92766244ee2d226cc2a32a4a6d2337b8a039432f0daaadf191f`
- 结论：BLOCKER 0、MAJOR 0、MINOR 0
- 隔离复测 WP-02B + WP-02A regression：99 passed
- 额外确定性 rollout 探测：1000 episodes，无非法动作、非确定行为或 duplicate Serve

上述 99 tests 与 1000 episodes 是独立候选审查证据，不是完整仓库验收结果。

### GitHub Actions

- `CPU checks`：success
- 未记录未经确认的 run number

### A100

```text
Commit：f290a45a67763b41941e919303b26fb16a67575a
全量：520 passed in 16.67s
CPU 验收：全部通过
最终工作树：干净
```

## 下一步：WP-02C True-future Oracle 只读设计

必须冻结：

1. Oracle 精确信息集
2. True-future view 的公开/内部边界
3. horizon H 的定义与 H=0 语义
4. future event 可见字段
5. future event 不可见内容：intensity、hidden state、seed、RNG 等
6. pre-position action semantics
7. current tasks 与 future tasks 的规划关系
8. Rolling horizon / receding-horizon 行为
9. Oracle 是否需要 reservation / plan state
10. 如何保证只改变 information set 而不改变 environment physics
11. H=0 与 Reactive 的零差异控制应如何定义
12. Oracle 能力不足导致 false-negative H1 的防护
13. 是否需要极小 reference/exhaustive verifier
14. WP-02C 文件范围和测试
15. WP-02D H1 gate 所需但不在 C 中执行的接口边界

WP-02C 当前仅做只读设计分析，尚不得实现。不得提前进入 H1 正式门槛运行、预测、
不确定性、MAPPO、PyTorch/GPU、ID/OOD 主实验或大规模 optimizer。
