# 项目状态

更新日期：2026-08-18

## 1. 已验证基线

- 项目：FURA-MAPPO
- 仓库：`https://github.com/cleardid/fura-mappo`
- 分支：`main`
- WP-01B 实现 Commit：`d67f71b5d75ee47adb120686914d32572ea7d6d1`
- 实现提交说明：`feat: add WP-01B nonstationary demand processes`
- WP-01B 稳定标签：`wp01b-stable`
- 标签目标：`d67f71b5d75ee47adb120686914d32572ea7d6d1`
- WP-01A 稳定标签：`wp01a-stable`
- WP-01A 实现 Commit：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`
- 初始稳定标签：`wp00-stable`

本文件所在的文档收尾 Commit 不硬编码自身 SHA；当前仓库 HEAD 以 `git rev-parse HEAD` 为准。科研实现稳定基线固定为上述 WP-01B Commit。

## 2. 工作包状态

| 工作包 | 状态 | 说明 |
|---|---|---|
| WP-00 | 已完成 | 项目骨架、环境、Ruff、Pytest、CI、系统审计和状态文档 |
| OPS-01 | 已完成 | Codex 协作、补丁审查、工作包模板和 CPU 验收流程 |
| WP-01A | 已完成 | 核心数据结构、统一状态接口和平稳 Poisson |
| WP-01B | 已完成 | Drifting Hotspot、Markov Switching、Burst Demand 和四类型工厂 |
| WP-01C | 准备开始 | 先做只读设计；配置、序列化、CLI、统计汇总和可选可视化 |

当前唯一目标是 WP-01C 只读设计分析。设计确认前不得修改源码或提前进入智能体、预测和强化学习工作。

## 3. 已冻结公共接口

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
```

核心语义：

- 每个需求过程实例独占 `numpy.random.Generator`；
- `reset(None)` 重放当前基准 seed，`reset(seed)` 切换基准 seed；
- reset 的候选 Generator 或隐状态重建失败时，原公共状态保持不变；
- `step()` 仅在完整合法 `DemandStep` 成功后推进公共状态；
- `generate(n)` 从当前状态继续，`generate(n, seed=s)` 从 step 0 重启；
- event ID 连续递增；输出数组防御性复制并只读；
- 过程不读取智能体、动作、奖励或服务结果。

WP-01C 必须保持这些行为兼容。

## 4. WP-01B 科学定义

### Drifting Hotspot

- 基础强度加一个或多个热点总增量；
- 热点按确定性速度移动，在区域外包矩形边界反射；
- 当前热点位置先发射，成功后推进；
- 高斯空间权重在 log-space 稳定归一化；
- 每个热点 amplitude 的逐区增量和保持为该 amplitude。

### Markov Switching

- `state_intensities[num_states, num_zones]`；
- 当前状态决定当前步强度，随后按转移矩阵更新下一状态；
- 确定性转移行不消费 RNG；
- reset 恢复显式 `initial_state`。

### Burst Demand

- 基础强度加活动 burst 的总增量；
- 仅空闲步按概率启动，启动步立即发射；
- 活动期间不重复启动；
- 持续时间结束后清除活动幅度；
- 区域权重稳定归一化。

## 5. WP-01B 验收证据

### Mac Python 3.11

- 聚焦测试：`214 passed`；
- 完整 CPU 验收：`293 passed`；
- Ruff、格式和 `git diff --check`：通过。

### 独立补丁审查

- 批准补丁 SHA-256：`04f2e705d05deafbb3d14bfd9e031dd58ddb7f98c57bb456a45dde39ac713449`；
- 独立聚焦测试：`214 passed`；
- 独立完整测试：`293 passed`；
- Stationary 精确回归：150/150 配置一致；
- Drifting 反射与强度守恒、Markov 稳态、Burst 长期活动率额外检查：通过；
- 结论：无阻断问题。

独立容器使用 Python 3.13，只作为补充证据，不替代正式 Python 3.11 验收。

### GitHub

- `main` 实现 Commit：`d67f71b5d75ee47adb120686914d32572ea7d6d1`；
- GitHub Actions：`CPU checks` run #5；
- 结论：成功。

### A100 服务器

用户返回摘要：

```text
Commit：d67f71b5d75ee47adb120686914d32572ea7d6d1
Python：Python 3.11.15
Conda 环境：fura-mappo
```

用户确认服务器端全部测试通过。返回摘要未包含逐项测试数量，因此不补造服务器测试计数。

## 6. 服务器环境

```text
CPU：80 核级
内存：502 GiB
GPU：2 × NVIDIA A100-SXM4-80GB
GPU 显存：每张 80GB
NVIDIA 驱动：590.48.01
Compute Capability：8.0
Conda：24.9.2
项目环境：fura-mappo
项目 Python：3.11.15
系统 Python：2.7.18，不得使用
nvcc：不可用
tmux：2.9a
```

WP-01 继续 CPU-only。

## 7. WP-01C 下一步

1. 只读分析现有四类型工厂、数据模型、配置目录和依赖；
2. 冻结配置 schema、文件格式、路径和覆盖语义；
3. 冻结轨迹序列化格式、schema 版本和复现元数据；
4. 设计 CLI 子命令、退出码、输出安全和统计汇总；
5. 决定可选可视化是否需要新的 optional dependency；
6. 制定往返、损坏文件、配置安全和 CLI 集成测试；
7. 设计审查通过后才进入实现。

## 8. 当前风险

- 配置、metadata 和序列化 schema 尚未冻结；
- `PyYAML` 已是项目依赖，但安全加载和错误报告尚未设计；
- 可视化是否引入 Matplotlib optional dependency 尚未决定；
- 文件兼容性一旦发布将形成长期约束，WP-01C 不得边实现边决定格式；
- `pyproject.toml` 允许 Python 3.10–3.12、Ruff 为 py310，而运行规范固定 Python 3.11；该差异不在 WP-01 中顺带修改。
