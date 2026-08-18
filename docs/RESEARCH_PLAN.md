# FURA-MAPPO 研究计划

WP-01 外生需求生成系统、WP-02A 确定性资源服务环境与 WP-02B Reactive baseline
已完成；当前唯一阶段为 WP-02C True-future Oracle 的只读设计分析。

## 核心假设

### H1
真实未来信息在资源受限、需求变化时具有控制价值。Oracle 应优于纯反应式配置。这是继续预测和 MARL 的前置门槛。

### H2
预测价值取决于非平稳程度、资源供需比、移动成本和 deadline。

### H3
预测不确定性质量影响主动预置风险。

### H4
预测引导 MAPPO 可学习接近 Oracle 的分散协同行为。

## 研究模块

### 外生需求——已完成
四类过程、YAML、hash、artifact、CLI、summary 已冻结。
稳定实现：`29a042f7b9fc80d3356cd5c63df1cd26b4078d9b` / `wp01c-stable`。

### 资源服务环境——已完成

WP-02A 已冻结仅消费 `DemandTrace` 的 deterministic `ResourceServiceEnvironment`、
连续二维欧氏移动、同质资源、精确位置与非抢占服务、事务式环境转换、确定性冲突
处理、future Serve 隔离、组成指标和精确守恒检查。

稳定实现：`d01092831a227a9f520de4ff8ded1d9e13ba8262`。

### Reactive baseline——已完成

WP-02B 已冻结 centralized、current-state-only、stateless、RNG-free、reservation-free
的 deterministic `ReactiveController`。它只动态消费当前 `EnvironmentSnapshot`，只额外
持有 `movement_speed`；exact bounded travel feasibility 与环境复用唯一 single-slot
movement primitive，不以 `ceil(distance / speed)` 作为 exact physical truth。任务和资源
均使用冻结的确定性排序与 unique greedy matching，直接输出 WP-02A actions 并使用
`EpisodeMetrics`。

稳定实现：`f290a45a67763b41941e919303b26fb16a67575a`。

### True-future Oracle——当前只读设计

WP-02C 必须先冻结 Oracle 精确信息集、True-future view 边界、horizon H 与 H=0、future
event 可见/不可见字段、pre-position action、current/future task 规划关系、receding-horizon
行为、reservation/plan state、与 WP-02A physics 的隔离、H=0 对 Reactive 的零差异控制、
防止弱 Oracle 造成 H1 false negative 的 verifier 策略、文件与测试范围，以及 WP-02D H1
gate 所需接口边界。

WP-02C 当前不得实现 Oracle。Reactive 与未来 Oracle 必须复用同一环境动力学；两者就绪后
才在 WP-02D 验证 H1，门槛成立后再进入预测与 MAPPO。

### 预测与决策
后续分别冻结预测接口、预测基线和不确定性感知 MAPPO。

## 科学控制

- 方法间使用相同外生 DemandTrace/artifact 配对
- 需求 RNG 与控制器随机性分离
- 训练/验证/测试集合分离
- 同时报告组成指标和综合指标
- Oracle 不参与学习
- OOD 边界预先冻结

## 当前执行顺序

1. 已完成 WP-01A
2. 已完成 WP-01B
3. 已完成 WP-01C
4. 已完成 WP-02A 确定性资源服务环境
5. 已完成 WP-02B Reactive baseline
6. 当前：WP-02C True-future Oracle 只读设计分析
7. H1 正式门槛验证
8. 预测接口与预测基线
9. 不确定性感知 MAPPO
10. ID/OOD、消融和相图
11. 最终统计分析与论文结果

当前不得提前进入 WP-02C 实现、H1 正式门槛运行、predictor、uncertainty、MAPPO、
PyTorch/GPU、ID/OOD 主实验或大规模 optimizer。
