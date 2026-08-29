# FURA-MAPPO

面向非平稳时空需求的预测引导、不确定性感知多智能体资源预置研究项目。

## 当前状态

- WP-01：已完成（`wp01c-stable` -> `29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`）。
- WP-02A/B/C/D1/D2/D3 engineering：已完成并接受。
- WP-02D overall：Formal H1 pending；Formal H1 尚未执行。
- `WP-03 IMPLEMENTATION CLOSED`；WP-03 accepted implementation Commit：
  `55dd9ef5f951d9328266b8e331ba5ae68854b414`。
- 当前没有 WP-03 scientific result，也没有执行 WP-03 official prediction experiment。
- 当前下一阶段：`Formal H1 execution-provenance refreeze and non-executing readiness audit`。
- Formal H1 execution 仍须用户 explicit authorization。

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

## 下一阶段

下一阶段只进行 Formal H1 execution-provenance refreeze 与 server non-executing readiness audit。
在用户 explicit authorization 前不得执行 Formal H1；official prediction science、WP-03 official
experiment、MAPPO 与 GPU scientific workload 继续锁定。
