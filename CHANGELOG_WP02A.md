# WP-02A Changelog

状态：已完成并通过 Mac、GitHub Actions 与 A100 验收。

稳定实现 Commit：`d01092831a227a9f520de4ff8ded1d9e13ba8262`。

## 完成范围

- deterministic `ResourceServiceEnvironment`
- 仅接受 `DemandTrace` 作为环境需求输入
- 连续二维欧氏移动与同质资源
- 精确位置服务与 Move/Serve slot 互斥
- 非抢占服务
- completion → expiration → truncation 边界顺序
- canonical `resource_to_event` assignment
- 事务式 `reset` / `step`
- future Serve side-channel 隔离
- 确定性 duplicate assignment resolution
- 组成指标与精确守恒检查

WP-02A 不包含 reward、RL、Reactive 或 Oracle，未改变 WP-01 冻结接口和协议。

## 独立 patch 审查

- 最终批准 patch SHA-256：`74b74cd9590eea1498152a81dc747cadf676d66890516c6460c07c819cd49e81`
- 第一轮独立审查发现并修复：合法移动浮点收缩 MAJOR、超大有限实数 `OverflowError` MINOR
- v2 独立复核：BLOCKER 0、MAJOR 0、MINOR 0

## 验收

### Mac

- Python 3.11.15
- WP-02A 专项：55 passed
- 全量：476 passed
- Ruff、format、diff-check：通过

### GitHub Actions

- `CPU checks`：success
- 未记录未经仓库确认的 run number

### A100

```text
Commit：d01092831a227a9f520de4ff8ded1d9e13ba8262
Python：3.11.15
Conda：fura-mappo
WP-02A 专项：55 passed in 0.26s
全量：476 passed in 17.45s
Ruff：通过
format：64 files already formatted
最终工作树：干净
```

服务器执行 `python -m pip install -e ".[dev]"` 时，build isolation 尝试通过失效
代理 `127.0.0.1:17890` 获取 `setuptools>=69`，因此依赖重装失败。该步骤未被记录
为成功，也没有因此修改项目依赖或环境配置。随后在现有 Conda 环境执行 pip
dependency check，结果为 `No broken requirements found`；WP-02A 专项与完整 CPU
验收均通过。

## 下一阶段

下一唯一阶段为 WP-02B Reactive baseline 的只读设计。必须先冻结当前信息集、
controller/environment 边界、feasibility、确定性 dispatch/tie-breaking、current
waiting task selection、paired rollout 接口、future 信息隔离，以及与未来 Oracle
共用环境动力学的边界。

WP-02B 尚不得实现；不得提前进入 Oracle、H1 正式门槛实验、预测、MAPPO 或
PyTorch/GPU。
