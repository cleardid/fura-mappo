# WP-01A 候选变更记录

状态：代码补丁已独立审查，待 Mac Python 3.11 最终验收、Commit、Push 和 A100 服务器验收。

## 新增

- 顶层 `fura_mappo.demand` 包；
- 冻结的 `DemandEvent`、`DemandStep` 和 `DemandTrace`；
- 统一管理 RNG、时间步和事件编号的 `DemandProcess`；
- 平稳逐区域 Poisson 需求过程；
- 矩形区域内的位置采样；
- priority、service time 和 deadline offset 范围采样；
- 严格需求过程工厂；
- 独立 NumPy Generator 创建工具；
- 数据一致性、状态语义、随机隔离、输入边界和统计测试。

## 关键语义

- 显式 seed；
- `reset(None)` 重放当前基准 seed；
- `reset(seed)` 更新基准 seed；
- `generate(n)` 从当前状态继续；
- `generate(n, seed=s)` 从 step 0 重启；
- event ID 连续分配；
- 返回数组防御性复制并只读；
- 工厂不修改调用方配置。

## 独立审查

- 补丁 SHA-256：`97fe150926f746708b662126233553621595e1e234151fe40b98fa1ec4600195`；
- 专项测试：164 passed；
- 重建完整基线测试：166 passed；
- 结论：无已知阻断性缺陷，可进入正式 Mac 验收。

## 明确未包含

- 三类非平稳需求；
- 配置文件、序列化、CLI 和绘图；
- 智能体环境、任务服务和奖励；
- 预测模型、MAPPO、PyTorch 或 GPU。
