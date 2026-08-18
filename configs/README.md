# 配置目录

WP-01C 提供四个小型需求生成示例：

- `demand/stationary_poisson.yaml`；
- `demand/drifting_hotspot.yaml`；
- `demand/markov_switching.yaml`；
- `demand/burst.yaml`。

这些文件均使用 `fura-mappo.demand-generation` schema v1，可直接交给
`load_demand_config()`、内存工厂或 `fura-demand generate`。示例只用于接口演示和快速
CPU 验证，不代表正式 ID/OOD 参数边界，也不支持 include、继承、环境变量或路径字段。

正式训练、开发和 OOD 实验配置将在后续实验工作包中预先冻结；大型轨迹、日志和模型
不得提交 GitHub。完整协议见 `docs/WP01C_SPEC.md`。
