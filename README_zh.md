# FURA-MAPPO

面向非平稳时空需求的预测引导、不确定性感知多智能体资源预置研究项目。

## 当前状态

- WP-01：已完成（`wp01c-stable` -> `29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`）。
- WP-02A/B/C/D1/D2/D3 engineering：已完成并接受。
- WP-02D Primary gate：在 execution/provenance HEAD
  `0b0742f51d59c2a8aa63614993e51131016cd33c` 上以 `SCIENTIFICALLY ACCEPTED PASS` 关闭；
  256/256 traces valid。Formal sensitivity 未执行。
- `WP-03 IMPLEMENTATION CLOSED`；WP-03 accepted implementation Commit：
  `55dd9ef5f951d9328266b8e331ba5ae68854b414`。
- 当前没有 WP-03 scientific result，也没有执行 WP-03 official prediction experiment。
- 当前阶段：`WP-03 Official Prediction Experiment Specification Freeze`。

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

在 frozen Primary H=2 setting 中，True-future Oracle 相对 Reactive 的 normalized completion fraction
平均提高约 0.3175；这不是 learned predictor、forecast-control、uncertainty、MAPPO 或所有环境的
科学证据。下一阶段只进行 read-only official experiment specification design/freeze；在 spec 独立审查、
用户手动 Commit/Push 与 GitHub Actions acceptance 前，不得生成 official prediction dataset、训练
predictor 或执行 official test。
