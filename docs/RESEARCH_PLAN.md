# FURA-MAPPO 研究计划

WP-01 外生需求生成系统、WP-02A 确定性资源服务环境、WP-02B Reactive baseline、
WP-02C Rolling True-future Oracle、WP-02D1 H1 protocol/statistics baseline、WP-02D2 bounded
diagnostic verifier 与 WP-02D3 Formal H1 execution hardening 已完成并接受。WP-02D overall 仍在
进行中，formal H1 尚未运行。WP-03A Prediction Interface & Dataset Protocol 已完成并接受；当前
进入 WP-03B Prediction Baseline Scientific Protocol Design，只允许 architecture-neutral 设计，正式
predictor science、uncertainty、MAPPO 与 Formal H1 仍锁定。

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
只能有 docs/changelog changes；WP-03A 已在其后合法修改 `src/**`，因此这份旧 execution freeze
已结束且不再是未来最终 execution baseline。旧调用
仅作为历史记录保留，不得在当前或未来 latest main 上机械执行：

```bash
python -m fura_mappo.experiments._formal_h1_runner \
  --accepted-implementation-sha 1092d9c87bfff8ba6c1f2132734480112d7b5975
```

本阶段不执行该命令。服务器恢复后必须同步最新 accepted main，重新冻结 Formal H1 accepted
execution baseline/provenance，重新做 readiness preflight，并取得用户明确授权。该治理调整不改变
H1 hypothesis、environment、estimand、bootstrap、gate 或 scientific identities：

```text
H1 spec SHA-256:
fc719e4634ab13ba55d0b95e63497688b3ab07c259d1421c5ed0c468cec3fade

Primary environment SHA-256:
d1d856b13ac8edf79422428a96bddc03b901053dbeaabe56571e9baeef6eafa1
```

WP-02D2 的 frozen handcrafted fixture expectations 已作为 unit tests 验收；它们不是 Formal H1
outcome 或 formal primary evidence。正式 seeds 仍为 `20260819..20261074`，formal primary traces
为 `0 / 256`，H1 rollouts、inventory、paired results、aggregate、verdict 与 sensitivity 均为零。
Formal H1 只能在未来重新冻结 execution baseline、完成 readiness preflight 并取得用户明确授权后
启动。

H1 outcome 产生前，已接受的 prediction interface/dataset 基础设施可以作为 protocol-design 边界；
这不代表 predictor 已科学验证或 forecasting 具有控制价值。Official predictor dataset generation、
training/evaluation、uncertainty science、forecast-guided control science 与 MAPPO 仍须等待 H1 gate
及后续治理授权。若 H1 不通过，则按预注册路径检查 formulation、stress regime 与 Oracle heuristic
adequacy。

### 预测接口与 Dataset Protocol——已完成并接受

WP-03A 已冻结 future realized zone-level arrival counts target、`ZoneSchema`、
`PredictionContext` / `PredictionTarget` / `PredictionSample`、`DemandForecast`、`DemandPredictor`
Protocol、`ObservedDemandHistory` 与 exact online/offline context parity。它还冻结
`VerifiedPredictionArtifact` → `PredictionSource` authoritative trust boundary、排除
`DemandTrace.intensities` 的 predictor information boundary、`realized_trace_sha256`、trace-level split
leakage guards、`condition_sha256` ID/OOD reservation、forecast/context hard validation，以及 canonical
protocol/manifest serialization。Core 保持 PyTorch-neutral。详细协议见
`docs/PREDICTION_PROTOCOL.md`。

Accepted implementation Commit 为 `13cb39933ac65926332ca6c528ef271e1c739aa5`；approved review
patch SHA-256 为 `5f5be8109784a5783caefc1e129edf2f2deb53aa52379b8be0c2c4120f8384b9`；
独立 review 为 BLOCKER 0、MAJOR 0、MINOR 0，GitHub Actions passed。该 acceptance 只证明工程
interface/protocol 已接受，不声称 predictor scientifically validated、forecasting improves control、
probabilistic uncertainty beneficial 或 MAPPO beneficial。

### Prediction Baseline Scientific Protocol Design——下一阶段

WP-03B 当前只允许 read-only analysis、scientific protocol design、candidate metric/loss/evaluation
design 与 architecture-neutral experiment planning。在 Formal H1 scientific outcome 产生前，禁止
official predictor training、official prediction dataset generation、official ID/OOD experiment、large
multi-seed prediction runs、GPU predictor training、forecast-guided controller main experiment 与
MAPPO training。本阶段不决定 Transformer/LSTM/TCN、optimizer、learning rate、hidden size、official
L/P、official split sizes、official prediction seeds 或 MAPPO architecture。

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
10. 已完成并接受 WP-03A Prediction Interface & Dataset Protocol
11. 当前：WP-03B Prediction Baseline Scientific Protocol Design（只读/设计）
12. 服务器恢复后：latest accepted main 同步与 Formal H1 execution provenance 重新冻结
13. 用户授权后的 WP-02D Formal H1 与 primary evidence audit
14. 仅按 H1/governance 结果解锁 official predictor、uncertainty 与 forecast-control science
15. 不确定性感知 MAPPO（仍锁定）
16. ID/OOD、消融和相图
17. 最终统计分析与论文结果

当前未生成 256 formal NPZ、formal artifact inventory、formal paired JSONL、formal aggregate 或
formal primary verdict，也未运行 Primary H=2、formal H=0、H sensitivity 或 stress sensitivity；
不得记录 formal point estimate、LCB/UCB 或正式 PASS/FAIL/INCONCLUSIVE/PROTOCOL_FAIL outcome。
在 Formal H1 scientific gate 产生有效结果并完成解释前，只允许 WP-03B 的 read-only analysis、
scientific protocol design、candidate metric/loss/evaluation design 与 architecture-neutral experiment
planning；不得进行 official predictor science/dataset generation/training、forecast uncertainty/control
science、MAPPO、PyTorch/GPU training、ID/OOD 主实验、大规模 optimizer 或论文主结果实验。
