# WP-01C 变更记录

状态：已完成。

- 稳定实现 Commit：`29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`
- 稳定标签：`wp01c-stable`
- GitHub Actions：CPU checks run #7 success
- Mac：421 passed
- A100：421 passed

## 新增

- 严格 YAML `fura-mappo.demand-generation` v1
- `load_demand_config`
- `compute_config_hash`
- 四类 YAML 示例
- `DemandTraceArtifact`
- NPZ `fura-mappo.demand-trace` v1
- provenance、config/content hash
- 安全 ZIP/NPY/JSON 读取
- 同目录原子写入
- `summarize_demand_trace`
- `fura-mappo.demand-summary` v1
- `fura-demand generate` / `summarize`
- `python -m fura_mappo.demand`

## 独立审查修复

- YAML 内容错误统一为加载边界 `ValueError`
- Conda prefix provenance 规范为环境名
- NPZ 改为 `ZipExtFile` 流式 `np.load(..., allow_pickle=False)`
- artifact resolved_config 内容错误统一为 `ValueError`
- loader 拒绝外部 manifest 的 path-like Conda 值

## 未包含

Matplotlib/plot、环境/智能体、预测器、MAPPO、PyTorch/GPU、远程存储和正式 ID/OOD 调度。
