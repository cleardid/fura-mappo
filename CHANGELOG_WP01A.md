# WP-01A 变更记录

状态：已完成并通过 GitHub Actions 与 A100 验收。

- 实现 Commit：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`
- 稳定标签：`wp01a-stable`
- 标签目标：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`
- GitHub Actions：`CPU checks` run #3，成功
- A100 验收：用户确认 CPU 与 WP-01A 专项测试全部通过

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

## 审查与验收证据

- 最终补丁 SHA-256：`97fe150926f746708b662126233553621595e1e234151fe40b98fa1ec4600195`；
- 隔离审查专项测试：`164 passed`；
- 补入远程基线测试后的隔离完整测试：`166 passed`；
- 早期混合 bool 与一次性范围迭代器缺陷已修复；
- GitHub Actions 对最终实现 Commit 验证成功；
- A100 正式验收通过。

隔离审查使用 Python 3.13，仅作为补充证据；正式项目环境仍为 Python 3.11。A100 原始日志和大型输出不提交仓库。

## 明确未包含

- 三类非平稳需求；
- 配置文件、序列化、CLI 和绘图；
- 智能体环境、任务服务和奖励；
- 预测模型、MAPPO、PyTorch 或 GPU。
