# FURA-MAPPO 研究计划

WP-01 外生需求生成系统与 WP-02A 确定性资源服务环境已完成；当前唯一阶段为
WP-02B Reactive baseline 的只读设计。

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

### Reactive baseline——当前只读设计

WP-02B 先冻结当前信息集、controller/environment 边界、feasibility、确定性 dispatch
与 tie-breaking、current waiting task selection、paired rollout 接口，以及禁止访问
future demand、intensity 和 hidden state 的边界。设计确认前不得实现。

### 后续基线

WP-02B 完成后才单独处理 True-future Oracle；Reactive 与未来 Oracle 必须复用同一
环境动力学。Oracle 与 Reactive 就绪后才验证 H1，门槛成立后再进入预测与 MAPPO。

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
5. 当前：WP-02B Reactive baseline 只读设计
6. 后续：True-future Oracle
7. H1 正式门槛验证
8. 预测接口与预测基线
9. 不确定性感知 MAPPO
10. ID/OOD、消融和相图
11. 最终统计分析与论文结果

当前不得提前进入 WP-02B 实现、Oracle、H1 正式门槛实验、预测、MAPPO 或
PyTorch/GPU。
