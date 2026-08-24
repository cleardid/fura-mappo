# FURA-MAPPO 研究计划

WP-01 外生需求生成系统、WP-02A 确定性资源服务环境、WP-02B Reactive baseline、
WP-02C Rolling True-future Oracle、WP-02D1 H1 protocol/statistics baseline、WP-02D2 bounded
diagnostic verifier 与 WP-02D3 Formal H1 execution hardening 已完成并接受。WP-02D overall 仍在
进行中，formal H1 尚未运行。由于服务器暂不可用，当前阶段调整为 WP-03A prediction interface /
dataset protocol 基础设施开发；正式 predictor science、uncertainty、MAPPO 与 Formal H1 仍锁定。

## 核心假设

### H1
真实未来信息在资源受限、需求变化时具有控制价值。Oracle 应优于纯反应式配置。这是继续预测和 MARL 的前置门槛。

### H2
预测价值取决于非平稳程度、资源供需比、移动成本和 deadline。

### H3
预测不确定性质量影响主动预置风险。

### H4
预测引导 MAPPO 可学习接近 Oracle 的分散协同行为。

## 研究模块

### 外生需求——已完成
四类过程、YAML、hash、artifact、CLI、summary 已冻结。
稳定实现：`29a042f7b9fc80d3356cd5c63df1cd26b4078d9b` / `wp01c-stable`。

### 资源服务环境——已完成

WP-02A 已冻结仅消费 `DemandTrace` 的 deterministic `ResourceServiceEnvironment`、
连续二维欧氏移动、同质资源、精确位置与非抢占服务、事务式环境转换、确定性冲突
处理、future Serve 隔离、组成指标和精确守恒检查。

稳定实现：`d01092831a227a9f520de4ff8ded1d9e13ba8262`。

### Reactive baseline——已完成

WP-02B 已冻结 centralized、current-state-only、stateless、RNG-free、reservation-free
的 deterministic `ReactiveController`。它只动态消费当前 `EnvironmentSnapshot`，只额外
持有 `movement_speed`；exact bounded travel feasibility 与环境复用唯一 single-slot
movement primitive，不以 `ceil(distance / speed)` 作为 exact physical truth。任务和资源
均使用冻结的确定性排序与 unique greedy matching，直接输出 WP-02A actions 并使用
`EpisodeMetrics`。

稳定实现：`f290a45a67763b41941e919303b26fb16a67575a`。

### True-future Oracle——已完成

WP-02C 已冻结 public immutable `TrueFutureView`、official builder 和 deterministic、
stateless、receding-horizon 的 `RollingTrueFutureOracle`。Oracle 只看 H-step bounded
`DemandEvent`，不持有完整 `DemandTrace`，不访问 intensity、counts、hidden state、seed、
RNG、config 或 artifact metadata；exact feasibility 与 Reactive/环境复用相同 movement
semantics。H=0、empty view 和没有可利用 future pair 时结构性退化到 Reactive。

Primary Oracle 是 H-step rolling true-future matched heuristic，不是 global optimum 或
theoretical upper bound。稳定实现：`9159c841af4f605d6e32cca4b37940f0116a19cf`。

### H1 Future-Information Value Gate——进行中

WP-02D1 已冻结并实现 strict H1 preregistration、same-`DemandTrace` paired rollout、official
view、Primary H=2、N=256 consecutive seeds `20260819..20261074`、H=0 negative control、
canonical mechanism control、primary stress cell、paired diagnostics/metrics、formal
artifact/results/verdict audit chain、locked verdict 与 local Git provenance hard gate。稳定实现：
`844de649c71e0a6a8fec6e1355cbf010db434f83`。

Primary outcome 对每条 trace 为
`(completed_oracle-completed_reactive)/arrived`，zero-arrival 时为 0；estimand 是每条 trace
等权的 mean。冻结 `delta_min=0.02`，并用 paired trace percentile bootstrap（NumPy PCG64、
50,000 resamples、seed `90260819`）形成 one-sided 95% bounds。PASS/FAIL/INCONCLUSIVE 与任何
protocol violation 对应的 PROTOCOL_FAIL 已预注册；secondary metric 和 sensitivity 不能改变
primary verdict。

WP-02D2 accepted implementation Commit 为
`cfab8c1b1981ef095d68969fff74faa2ac4f256d`。它实现不超过 2 resources、4 steps、3 events 的
`bounded task-target root-information exhaustive diagnostic verifier`，用于诊断 weak greedy
Oracle 是否可能产生 H1 false negative。它使用真实环境与 public `reset()` / `step()`，不公开为
baseline，也不声称 global optimum、continuous-control optimum、theoretical upper bound、optimal
policy 或 Primary adequacy proof。每个真实 decision boundary 以 official view 冻结
`K = current active tasks + official H-step future view events`；branch 使用 fresh environment 与
deterministic prefix replay，root search 不刷新 future view 并一直穷举到 episode terminal。有限
action space 只含 frozen-K task targets；objective 仅 maximize completed count over frozen K，tie
仅按 deterministic canonical complete sequence ordering，不使用 priority、movement、wait、reward
或 secondary objective。Verifier output 不进入 formal primary verdict 输入。

WP-02D3 accepted implementation Commit 为
`1092d9c87bfff8ba6c1f2132734480112d7b5975`。它完成 Formal H1 execution orchestration /
persistence hardening，不改变 H1 科学规格：private runner 固定正式路径与 exact artifact plan，
把 main/clean/origin/ancestry Git provenance 和实际 loaded code 绑定到当前 repo，提供 no-overwrite、
provenance-bound strict restart/resume、paired JSONL / aggregate / verdict strict readback，以及
protocol/NPZ/formal directory crash durability。`PROTOCOL_FAIL` 可被严格读取，但永不解锁
sensitivity。

`1092d9c...` 是历史 WP-02D3 accepted implementation。它冻结时的 execution provenance 要求其后
只能有 docs/changelog changes；WP-03A source changes 会有意结束这份旧 execution freeze。旧调用
仅作为历史记录保留，不得在当前或未来 latest main 上机械执行：

```bash
python -m fura_mappo.experiments._formal_h1_runner \
  --accepted-implementation-sha 1092d9c87bfff8ba6c1f2132734480112d7b5975
```

本阶段不执行该命令。服务器恢复后必须同步最新 accepted main，重新冻结 Formal H1 accepted
execution baseline/provenance，重新做 readiness preflight，并取得用户明确授权。该治理调整不改变
H1 hypothesis、environment、estimand、bootstrap、gate 或 scientific identities。

WP-02D2 的 frozen handcrafted fixture expectations 已作为 unit tests 验收；它们不是 Formal H1
outcome 或 formal primary evidence。正式 seeds 仍为 `20260819..20261074`，formal primary traces
为 `0 / 256`，H1 rollouts、inventory、paired results、aggregate、verdict 与 sensitivity 均为零。
Formal H1 只能在未来重新冻结 execution baseline、完成 readiness preflight 并取得用户明确授权后
启动。

H1 outcome 产生前允许实现和审查 prediction interface/dataset 基础设施；这不代表 forecasting
具有控制价值。Official predictor dataset/training/evaluation、uncertainty science、forecast-guided
control science 与 MAPPO 仍须等待 H1 gate 及后续治理授权。若 H1 不通过，则按预注册路径检查
formulation、stress regime 与 Oracle heuristic adequacy。

### 预测接口与 Dataset Protocol——实现候选

WP-03A 已冻结 future realized zone-level arrival counts target、causal count history、lead 1 为
`t+1`、episode masks、immutable point/probabilistic forecast、trace-level split/OOD isolation、
condition identity、controller/provenance separation 与 deterministic serialization。详细协议见
`docs/PREDICTION_PROTOCOL.md`。Candidate v2 冻结 safe-loaded artifact → verified source →
sample/split 的 authoritative trust boundary、source ZoneSchema identity，以及 forecast/context 的
boundary/horizon/zone/terminal-mask hard validation；candidate v3 再加入只绑定 realized
start/counts/events、排除 intensity 与 artifact metadata 的 intrinsic trace identity，防止同一 realized
trajectory 重新封装后跨 split；candidate v4 将 realized float fields 的 signed zero 规范为相同逻辑
值，同时保留非零差异。当前只实现基础设施和 tiny deterministic CPU tests，不实现 predictor
architecture、forecast-guided controller、training 或科学实验。

## 科学控制

- 方法间使用相同外生 DemandTrace/artifact 配对
- 需求 RNG 与控制器随机性分离
- 训练/验证/测试集合分离
- 同时报告组成指标和综合指标
- Oracle 不参与学习
- OOD 边界预先冻结

## 当前执行顺序

1. 已完成 WP-01A
2. 已完成 WP-01B
3. 已完成 WP-01C
4. 已完成 WP-02A 确定性资源服务环境
5. 已完成 WP-02B Reactive baseline
6. 已完成 WP-02C Rolling True-future Oracle
7. 已完成 WP-02D1 H1 protocol/statistics baseline
8. 已完成 WP-02D2 bounded diagnostic verifier implementation / acceptance
9. 已完成 WP-02D3 Formal H1 execution orchestration / persistence hardening
10. 当前：WP-03A Prediction Interface & Dataset Protocol implementation/review
11. 服务器恢复后：latest accepted main 同步与 Formal H1 execution provenance 重新冻结
12. 用户授权后的 WP-02D Formal H1 与 primary evidence audit
13. 仅按 H1/governance 结果解锁 official predictor、uncertainty 与 forecast-control science
14. 不确定性感知 MAPPO（仍锁定）
15. ID/OOD、消融和相图
16. 最终统计分析与论文结果

当前未生成 256 formal NPZ、formal artifact inventory、formal paired JSONL、formal aggregate 或
formal primary verdict，也未运行 Primary H=2、formal H=0、H sensitivity 或 stress sensitivity；
不得记录 formal point estimate、LCB/UCB 或正式 PASS/FAIL/INCONCLUSIVE/PROTOCOL_FAIL outcome。
在 Formal H1 scientific gate 产生有效结果并完成解释前，只允许 architecture-neutral prediction
interface/dataset 基础设施、unit tests 与 tiny smoke tests；不得进行 official predictor science、
forecast uncertainty/control science、MAPPO、PyTorch/GPU training、ID/OOD 主实验、大规模 optimizer
或论文主结果实验。
