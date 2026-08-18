# FURA-MAPPO

面向非平稳时空需求的预测引导、不确定性感知多智能体资源预置研究项目。

## 当前状态

- WP-01A：完成，`wp01a-stable`。
- WP-01B：完成，`wp01b-stable`。
- WP-01C：完成，`wp01c-stable` -> `29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`。
- Mac Python 3.11.15：`421 passed`。
- A100 Python 3.11.15 / Conda `fura-mappo`：`421 passed`。
- GitHub Actions `CPU checks`：run #7，成功。
- 当前唯一目标：WP-02 只读设计——资源服务环境与反应式/Oracle 控制基线。

## WP-01 已完成能力

- `DemandEvent` / `DemandStep` / `DemandTrace`
- 统一 `DemandProcess.reset/step/generate`
- Stationary Poisson
- Drifting Hotspot
- Markov Switching
- Burst Demand
- 严格 YAML schema v1
- 稳定配置 SHA-256
- NPZ demand-trace artifact v1
- provenance、内容哈希、安全读取和同目录原子写入
- `fura-demand generate` / `summarize`
- JSON summary v1

## WP-02 当前边界

当前只做设计，不实现代码。必须先冻结：

- 环境时间步；
- 资源、容量、位置和移动；
- 任务等待、服务、完成和 deadline；
- 指标与成本分解；
- Reactive 信息集；
- Oracle 未来信息边界；
- 配对 DemandTrace/artifact 的公平比较；
- WP-02 子工作包拆分。

在 Oracle 价值门槛成立前，不实现预测模型或 MAPPO，不冻结最终 RL reward。
