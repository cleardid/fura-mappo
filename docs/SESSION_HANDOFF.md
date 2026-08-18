# 会话交接

更新日期：2026-08-19

## 当前任务

WP-02B：Reactive baseline。

当前阶段严格为只读设计分析，尚不得实现。

## 稳定基线

```text
WP-02A 实现：d01092831a227a9f520de4ff8ded1d9e13ba8262
WP-01C 实现：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
WP-01C 标签：wp01c-stable
```

WP-02A docs-only 收尾 Commit 不自引用自身 SHA；后续会话必须真实读取当前 HEAD。

## WP-02A 完成结论

- deterministic `ResourceServiceEnvironment` 已实现并冻结，只消费 `DemandTrace`
- 连续二维欧氏移动、同质资源、精确位置服务、Move/Serve slot 互斥、非抢占服务
- completion → expiration → truncation；canonical `resource_to_event`
- 事务式 `reset` / `step`、future Serve side-channel 隔离、确定性 duplicate resolution
- 组成指标及精确守恒检查；没有 reward、RL、Reactive 或 Oracle
- 最终批准 patch SHA-256：`74b74cd9590eea1498152a81dc747cadf676d66890516c6460c07c819cd49e81`
- 第一轮独立审查的移动浮点收缩 MAJOR 与超大有限实数 `OverflowError` MINOR 均已修复
- v2 独立复核：BLOCKER 0、MAJOR 0、MINOR 0
- Mac Python 3.11.15：专项 55 passed，全量 476 passed，Ruff / format / diff-check 通过
- GitHub Actions `CPU checks`：success；未记录未经确认的 run number
- A100：指定 Commit、Python 3.11.15、Conda `fura-mappo`；专项 55 passed in 0.26s，全量 476 passed in 17.45s；Ruff 通过，64 files already formatted，最终工作树干净

## A100 依赖重装说明

`python -m pip install -e ".[dev]"` 因 build isolation 尝试经失效代理
`127.0.0.1:17890` 获取 `setuptools>=69` 而失败。这是依赖重装步骤的网络/代理
失败，不能记作成功；未因此修改依赖或环境配置。随后现有 Conda 环境的 pip
dependency check 为 `No broken requirements found`，专项和完整 CPU 验收均通过。

## WP-02B 只读设计必须冻结

1. Reactive controller 的当前信息集
2. controller/environment 边界
3. feasibility 计算
4. deterministic dispatch / tie-breaking
5. current waiting task selection
6. paired rollout 接口需求
7. Reactive 不得访问 future demand、intensity 或 hidden state
8. 与未来 Oracle 共用环境动力学的边界

## 非目标

WP-02B 实现、Oracle、H1 正式门槛实验、预测、不确定性模型、MAPPO、
PyTorch/GPU、正式 ID/OOD 主实验、最终 reward、大规模优化器、多进程。
