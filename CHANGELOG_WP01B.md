# WP-01B 变更记录

状态：已完成。

- 实现 Commit：`d67f71b5d75ee47adb120686914d32572ea7d6d1`
- 提交说明：`feat: add WP-01B nonstationary demand processes`
- 稳定标签：`wp01b-stable`
- 前序稳定标签：`wp01a-stable`

## 新增

- `DriftingHotspotDemand`：确定性反射移动热点、归一化空间高斯强度和总热点增量守恒；
- `MarkovSwitchingDemand`：有限状态强度、严格转移矩阵校验和“当前状态发射、随后转移”；
- `BurstDemand`：非重叠加法突发、启动概率、持续时间、幅度和区域权重；
- `src/fura_mappo/demand/nonstationary.py`；
- 三类过程各自的边界、状态、随机性和长期统计测试。

## 修改

- 提取内部 `_PoissonDemandProcess`，统一四类过程的事件生成；
- 为 `DemandProcess.reset()` 增加内部隐状态重建钩子，并保持失败原子性；
- 扩展 `create_demand_process()`，严格支持四个规范类型；
- 显式导出三类非平稳过程；
- 增加 Stationary 精确回归和工厂配置安全测试。

## 科学与状态语义

- Drifting 每步先以当前位置发射，再提交反射后的下一位置和速度；
- Markov 每步先用当前状态发射，再采样并提交下一状态；
- Burst 仅在空闲步抽启动，启动步立即发射，活动期间不重叠启动；
- 三类过程均复用 WP-01A 的独立 Generator、连续 event ID、只读输出和 `reset/step/generate` 语义；
- 未公开隐状态属性，未加入 metadata。

## 验收

- Mac 聚焦测试：`214 passed`；
- Mac 完整 CPU 验收：`293 passed`，Ruff 和格式检查通过；
- 独立补丁审查：通过；
- GitHub Actions `CPU checks` run #5：成功；
- A100 服务器：Commit `d67f71b5d75ee47adb120686914d32572ea7d6d1`、Python 3.11.15、Conda 环境 `fura-mappo`，用户确认全部验收通过。

服务器返回摘要未包含逐项测试数量，因此不在本文件补造服务器测试计数。

## 明确未包含

- YAML 或其他文件配置读取；
- NPZ、CSV、JSON 轨迹序列化；
- CLI、统计汇总和可视化；
- ID/OOD 数值边界硬编码；
- PettingZoo、智能体、服务、奖励、预测、MAPPO、PyTorch、GPU 或并行化。
