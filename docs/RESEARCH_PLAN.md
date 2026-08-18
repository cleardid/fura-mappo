# FURA-MAPPO 研究计划

WP-01 外生需求生成系统已完成；当前进入 WP-02 资源服务环境与反应式/Oracle 控制基线。

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

### 资源服务环境——当前
需要冻结位置、移动、容量、服务、deadline、冲突、episode、观察/动作和组成指标。

### 基线
优先完成 Reactive 与 True-future Oracle，并验证 H1。Oracle 门槛成立后再进入预测与 MAPPO。

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
4. 当前：WP-02 环境与 Reactive/Oracle
5. H1 门槛验证
6. 预测接口与预测基线
7. 不确定性感知 MAPPO
8. ID/OOD、消融和相图
9. 最终统计分析与论文结果
