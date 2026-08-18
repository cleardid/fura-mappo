# WP-02B Reactive Baseline 变更记录

状态：已完成并通过 Mac、独立候选审查、GitHub Actions 与 A100 CPU 验收。

稳定实现 Commit：`f290a45a67763b41941e919303b26fb16a67575a`。

## 实现范围

- 新增 deterministic `ReactiveController`
- centralized、current-state-only、stateless、RNG-free、reservation-free
- controller 只动态消费当前 `EnvironmentSnapshot`，只额外持有 `movement_speed`
- 不访问 `DemandTrace`、future events、intensity、hidden state、seed 或需求 RNG
- SERVING resource 固定返回 `ContinueAction`
- 仅 WAITING task 进入候选
- exact bounded travel feasibility
- 环境与 baseline 共用唯一内部 single-slot movement primitive
- 不使用 `ceil(distance / speed)` 作为 exact physical truth
- task 排序：`latest_service_start` → higher priority → earlier `arrival_step` → smaller `event_id`
- resource 排序：exact `travel_slots` → Euclidean distance → `resource_id`
- unique greedy matching；无 controller-side reservation
- 正常 Reactive rollout 不主动产生 duplicate Serve
- 直接使用 WP-02A `EpisodeMetrics`

WP-02A public environment behavior 未改变；原 single-slot movement physics 仅机械抽取为
共享内部 primitive。

## 明确非范围

WP-02B 未实现 reward、Oracle、future view、prediction、uncertainty、RL/MAPPO、
Gym/PettingZoo、PyTorch/GPU、H1 正式门槛实验、ID/OOD 主实验或公共 rollout protocol。

## 独立候选审查

- 最终批准 review patch SHA-256：`38648aac6ae7d92766244ee2d226cc2a32a4a6d2337b8a039432f0daaadf191f`
- 结论：BLOCKER 0、MAJOR 0、MINOR 0
- ChatGPT 隔离复测 WP-02B + WP-02A regression：99 passed
- 额外确定性 rollout 探测：1000 episodes，无非法动作、非确定行为或 duplicate Serve

上述 99 tests 与 1000 episodes 是独立候选审查证据，不是完整仓库验收结果。

## Mac 验收

- Commit：`f290a45a67763b41941e919303b26fb16a67575a`
- Python：3.11.15
- 全量 CPU tests：520 passed in 5.80s
- Ruff、format、diff-check：通过

## GitHub Actions

- `CPU checks`：success
- 未记录未经确认的 run number

## A100 验收

- Commit：`f290a45a67763b41941e919303b26fb16a67575a`
- 全量 CPU tests：520 passed in 16.67s
- CPU 验收：全部通过
- 最终工作树：干净

此前 WP-02A 的 pip build-isolation 代理失败属于 WP-02A 历史事实，不是 WP-02B 新失败。

## 下一阶段

下一唯一阶段为 WP-02C True-future Oracle 的只读设计分析。WP-02C 尚不得实现，必须先
冻结 information set、future view、horizon H/H=0、future event 可见边界、pre-position、
receding-horizon、reservation/plan state、physics 隔离、Reactive H=0 控制、Oracle 能力
验证、文件/测试范围和 WP-02D H1 gate 接口。

当前不得提前进入 H1 正式门槛运行、predictor、uncertainty、MAPPO、PyTorch/GPU、
ID/OOD 主实验或大规模 optimizer。
