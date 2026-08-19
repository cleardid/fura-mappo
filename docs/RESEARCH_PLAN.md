# FURA-MAPPO 研究计划

WP-01 外生需求生成系统、WP-02A 确定性资源服务环境、WP-02B Reactive baseline 与
WP-02C Rolling True-future Oracle 已完成；当前唯一阶段为 WP-02D H1
Future-Information Value Gate 的只读设计分析。

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

### True-future Oracle——已完成

WP-02C 已冻结 public immutable `TrueFutureView`、official builder 和 deterministic、
stateless、receding-horizon 的 `RollingTrueFutureOracle`。Oracle 只看 H-step bounded
`DemandEvent`，不持有完整 `DemandTrace`，不访问 intensity、counts、hidden state、seed、
RNG、config 或 artifact metadata；exact feasibility 与 Reactive/环境复用相同 movement
semantics。H=0、empty view 和没有可利用 future pair 时结构性退化到 Reactive。

Primary Oracle 是 H-step rolling true-future matched heuristic，不是 global optimum 或
theoretical upper bound。稳定实现：`9159c841af4f605d6e32cca4b37940f0116a19cf`。

### H1 Future-Information Value Gate——当前只读设计

WP-02D 必须先冻结 precise estimand、same-`DemandTrace` paired rollout、official view、
primary H 与 sensitivity、H=0 negative control、mechanism control、bounded diagnostic
verifier、primary stress cell、paired metrics、统计估计/CI、minimum practical effect、gate
threshold、false-positive/false-negative 防护和 negative-result failure path。

正式实验必须让环境与 builder 使用同一个内存 `DemandTrace`。WP-02D 当前不得运行 H1、
实现 verifier 或生成大规模 artifact。只有 H1 gate 支持未来信息具有控制价值后，才进入
prediction interface、prediction baseline、uncertainty 和 MAPPO；若 H1 不通过，则暂停主线并
检查 formulation、stress regime 与 Oracle heuristic adequacy。

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
6. 已完成 WP-02C Rolling True-future Oracle
7. 当前：WP-02D H1 gate 只读设计分析
8. WP-02D 实现与 H1 正式门槛验证（仅在只读设计冻结后）
9. 预测接口与预测基线（仅在 H1 gate 通过后）
10. 不确定性感知 MAPPO（仅在 H1 gate 通过后）
11. ID/OOD、消融和相图
12. 最终统计分析与论文结果

当前不得运行 H1 正式门槛、实现 bounded verifier、生成大规模实验 artifact，或进入
predictor、uncertainty、MAPPO、PyTorch/GPU、ID/OOD 主实验、大规模 optimizer 和论文
主结果实验。
