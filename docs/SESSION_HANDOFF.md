# 会话交接

更新日期：2026-08-19

## 当前任务

WP-02C：True-future Oracle，只读设计分析。

当前阶段不得修改环境或 baseline 源码，不得实现 Oracle，也不得运行 H1 正式门槛实验。

## 稳定基线

```text
WP-02B 实现：f290a45a67763b41941e919303b26fb16a67575a
WP-02A 实现：d01092831a227a9f520de4ff8ded1d9e13ba8262
WP-01C 实现：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
WP-01C 标签：wp01c-stable
```

docs-only 收尾 Commit 不自引用自身 SHA；后续会话必须真实读取当前 HEAD。

## WP-02B 完成结论

- deterministic `ReactiveController`
- centralized、current-state-only、stateless、RNG-free、reservation-free
- 只动态消费当前 `EnvironmentSnapshot`，只额外持有 `movement_speed`
- 不访问 `DemandTrace`、future events、intensity、hidden state、seed 或需求 RNG
- SERVING resource 固定 Continue；仅 WAITING task 进入候选
- exact bounded travel feasibility 复用 WP-02A 唯一内部 single-slot movement primitive
- `ceil(distance / speed)` 不作为 exact physical truth
- task 排序：`latest_service_start` → higher priority → earlier `arrival_step` → smaller `event_id`
- resource 排序：exact `travel_slots` → Euclidean distance → `resource_id`
- unique greedy matching；无 controller-side reservation；正常输出不主动产生 duplicate Serve
- 直接使用 WP-02A `EpisodeMetrics`；不包含 reward、Oracle、prediction 或 RL
- WP-02A 公共环境行为未改变；single-slot movement physics 仅机械抽取为共享内部 primitive

## WP-02B 验收事实

### 独立候选审查

- 最终批准 patch SHA-256：`38648aac6ae7d92766244ee2d226cc2a32a4a6d2337b8a039432f0daaadf191f`
- BLOCKER 0、MAJOR 0、MINOR 0
- 隔离复测 WP-02B + WP-02A regression：99 passed
- 额外确定性 rollout 探测：1000 episodes，无非法动作、非确定行为或 duplicate Serve

上述 99 tests 与 1000 episodes 只属于独立候选审查，不是完整仓库验收。

### Mac / GitHub / A100

- Mac：Commit `f290a45a67763b41941e919303b26fb16a67575a`；Python 3.11.15；全量 520 passed in 5.80s；Ruff、format、diff-check 通过
- GitHub Actions：`CPU checks` success；未记录未经确认的 run number
- A100：Commit `f290a45a67763b41941e919303b26fb16a67575a`；全量 520 passed in 16.67s；CPU 验收全部通过；最终工作树干净

WP-02A 的 pip build-isolation 代理失败只属于 WP-02A 历史记录，不是 WP-02B 失败。

## WP-02C 只读设计必须冻结

1. Oracle 精确信息集
2. True-future view 的公开/内部边界
3. horizon H 的定义与 H=0 语义
4. future event 可见字段
5. future event 不可见内容：intensity、hidden state、seed、RNG 等
6. pre-position action semantics
7. current tasks 与 future tasks 的规划关系
8. Rolling horizon / receding-horizon 行为
9. Oracle 是否需要 reservation / plan state
10. 如何保证只改变 information set 而不改变 environment physics
11. H=0 与 Reactive 的零差异控制应如何定义
12. Oracle 能力不足导致 false-negative H1 的防护
13. 是否需要极小 reference/exhaustive verifier
14. WP-02C 文件范围和测试
15. WP-02D H1 gate 所需但不在 C 中执行的接口边界

## 当前非目标

WP-02C 实现、H1 正式门槛运行、predictor、uncertainty、MAPPO、PyTorch/GPU、
ID/OOD 主实验、大规模 optimizer、多进程或任何环境物理改动。
