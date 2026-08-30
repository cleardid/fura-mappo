# FURA-MAPPO 研究计划

WP-01 外生需求生成系统、WP-02A 确定性资源服务环境、WP-02B Reactive baseline、
WP-02C Rolling True-future Oracle、WP-02D1 H1 protocol/statistics baseline、WP-02D2 bounded
diagnostic verifier 与 WP-02D3 Formal H1 execution hardening 已完成并接受。WP-02D Primary gate 已在
execution/provenance HEAD `0b0742f51d59c2a8aa63614993e51131016cd33c` 上以
`SCIENTIFICALLY ACCEPTED PASS` 关闭；formal sensitivity 未执行。`WP-03 IMPLEMENTATION CLOSED`：
WP-03 Slice 1–17 implementation 已
accepted，WP-03 accepted implementation Commit 为 `55dd9ef5f951d9328266b8e331ba5ae68854b414`（`feat: close
WP-03B official evaluation orchestration`），GitHub Actions CPU checks run #40 为 `completed / success`。
这是 engineering acceptance，不是科学结果；当前阶段仅为
`WP-03 Official Prediction Experiment Specification Freeze`，正式 predictor science、uncertainty 与
MAPPO 仍锁定。

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

### H1 Future-Information Value Gate——Primary scientifically accepted PASS

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

不得再次机械执行该历史命令。本次已接受的 Formal H1 Primary 使用 exact execution/provenance HEAD
`0b0742f51d59c2a8aa63614993e51131016cd33c`；本 docs closure 不重新执行 Primary、不执行
sensitivity，也不修改 Formal evidence。该 evidence closure 不改变 H1 hypothesis、environment、
estimand、bootstrap、gate 或 scientific identities：

```text
H1 spec SHA-256:
fc719e4634ab13ba55d0b95e63497688b3ab07c259d1421c5ed0c468cec3fade

Primary environment SHA-256:
d1d856b13ac8edf79422428a96bddc03b901053dbeaabe56571e9baeef6eafa1
```

WP-02D2 的 frozen handcrafted fixture expectations 已作为 unit tests 验收；它们不是 Formal H1
outcome 或 formal primary evidence。Formal H1 Primary accepted evidence 为：

```text
N planned / valid: 256 / 256
verdict: PASS
point estimate: 0.31754293614860113
one-sided LCB: 0.3133852915914393
one-sided UCB: 0.32170536510653147
two-sided 95% interval: [0.3126219878069711, 0.3225008920637088]
delta_min: 0.02
sensitivity: not executed
server artifact root: artifacts/wp02d_h1_formal_v1/
```

在 frozen Primary H=2 setting 中，True-future Oracle 相对 Reactive 的 normalized completion fraction
平均提高约 `0.3175`。这满足 D-002 在该 frozen setting 下的 Primary future-information gate，但不代表
predictor 已科学验证、forecasting 改善 control、uncertainty 有价值、MAPPO 获益或所有环境都有同等
效果。Sensitivity 未执行，不能 rescue、reverse 或改变 Primary verdict，也不是进入下一 design stage
的前置条件。

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

### Prediction Baseline Scientific Protocol 与 implementation——WP-03 IMPLEMENTATION CLOSED

WP-03B 权威协议见 `docs/PREDICTION_BASELINE_PROTOCOL.md`。Operational hierarchy 冻结为 B0 Zero、
B1 Persistence、B2 Masked context mean、B3 EWMA、B4 static train climatology、B5 absolute-step
train climatology 与 L0 learned point predictor。B4/B5 均只从 unique train trace/step 统计拟合并形成
immutable artifact。B2 按 lower validation Primary RMSE、shorter L 锁定；B3 在完整 L×alpha grid
按 lower validation Primary RMSE、shorter L、smaller alpha 锁定；selected DatasetProtocolSpec
SHA/alpha 进入 provenance。随后才以 validation Primary RMSE 比较六个 locked variants，tie 为
B0<B1<B2<B3<B4<B5。

Baseline selection 前 preflight train/validation/test_id/test_ood absolute-step support；对任意 executed P，
B5 必须覆盖每个 required anchor `t` 与 valid `h in 1..P` 的 `t+h`。Primary P=2 与各自
独立 `DatasetProtocolSpec`/SHA/preflight/records 的 secondary P=4/P=8 使用同一 invariant；
secondary failure 不得 alter/rescue/invalidate 有效 Primary。任一 support gap 或 locked B0–B5 不能
完整产生 validation finite valid forecasts 时为
`PREDICTION_BASELINE_SELECTION_FAILURE`，不删除/缩小 hierarchy、penalize/fallback，也不产生 B*。
Preflight 通过并锁定后，official test execution/readback 的 support 缺失才为
`PREDICTION_EVALUATION_FAILURE`；unknown-step fallback 禁止。

Layer A `PRE-TRAINING DATA/SEARCH FREEZE` 在 B4/B5/statistics fit、learned training、任何 validation
forecast/metric、early stopping 或 candidate/internal/B* selection 前锁定 schema/protocol/source inventory、
exact manifest 与 split membership/order/identities、calibration、ID/OOD assignment、training seeds 与全部
search/config/grid/budget/order/complexity identities。数值 activity 开始后不得移动、增删、替换
trace/seed 或改变 calibration/test/OOD/protocol/inventory，B4/B5 只读 frozen train。Activity 前发现
invalid freeze 则 STOP 并可新建 explicit version；activity 后发现则记录 development/protocol failure，
使用新 identity 从 fitting/training/model selection 完整重启，不继承旧 numerical results。

所有 operational predictor/baseline 均为 stateless pure inference：只读取当前有限 causal
`PredictionContext` 与 immutable fitted artifact，跨调用不保存 hidden/history/episode state。
Primary P=2，secondary P={4,8}，L grid={4,8,16,32}。Objective candidates 为 raw-scale MSE 与
Poisson NLL。T0 identity/T1 log1p 只作用于 `history_counts` count values；其他 context fields、target
与 output 不 transform，non-count feature encoding 必须进入未来 config identity。

Primary estimand 是 trace/zone/horizon-equal raw-scale RMSE。每个 learned run 只按自身 validation
RMSE 锁定 checkpoint；全部 objective/transform/L/model configs 统一按
`Validation Algorithm RMSE = sqrt(mean_r(Validation MSE_r))` 选择。Test point estimate 为
`Test Algorithm RMSE = sqrt(mean_r(Test MSE_r))`，不是 mean per-seed RMSE、best seed 或 ensemble。
任一 fixed seed 无 valid run/checkpoint/forecast/MSE 时 config 为 `TRAINING_FAILURE`，无 score/test；
所有 configs 失败则为 `PREDICTION_MODEL_SELECTION_FAILURE`，不产生 predictor science result。
VALID configs 唯一排序为 lower Validation Algorithm RMSE、lower predeclared complexity key、shorter
L、O0<O1、T0<T1、canonical config ordering；keys/schema/search space/order 均在 candidate training
前冻结。
Layer B `PRE-TEST EXECUTION FREEZE` 在 first official test execution 前锁定 selected variants/config、全部
checkpoints、exact test identities、metric/bootstrap、final OOD cells 与 Git/runtime，且不能改 Layer A。
Test_id bootstrap 对 learned 全部 fixed-seed runs 与 locked B* 复用同一 trace sample，replicate 使用
`Algorithm RMSE^(b)=sqrt(mean_r(MSE_r^(b)))` 作差；它只 resample test traces，CI conditional on
frozen seed set，seed dispersion 另报。ID、single-axis near-OOD、held-out-family structural-OOD 分开
报告；prediction/control selection 严格隔离。全部 identities/config/checkpoints 在 first official test
execution 前锁定。WP-03B 不启用 intensity diagnostic。

Primary ID interpretation 只使用 raw `Delta_RMSE` 与 two-sided 95% CI `[CI_L,CI_U]`：point<0 且
upper<0 为 `LEARNED_BETTER`；point>0 且 lower>0 为 `LEARNED_WORSE`；否则为
`NO_CLEAR_DIFFERENCE`。没有 practical-effect delta，后者不表示等价，secondary/OOD/control 不得
改变 label；该 label 不是 Formal H1 verdict 或 control/MAPPO gate。

Sealed official evaluation 必须 exact 匹配 locked trace sets/order、fixed checkpoints、B*、protocol /
manifest/schema identities，并有每个 valid anchor/horizon/zone 的 complete finite valid/bound forecast、
finite complete metric/bootstrap input、无 missing/duplicate record。任何 failure 进入
`PREDICTION_EVALUATION_FAILURE`，不产生 Test Algorithm score、Delta/CI 或 scientific label；记录
reason，且不得 drop/replace/exclude/impute/fallback、平均 remaining seeds 或 smaller-n continuation。
Zero-demand observation 合法。第一次 official forecast、target/result evaluation、metric/bootstrap 或
scientific readback 使 exact test_id/test_ood 立即成为 `SPENT TEST SET`，无论 success/failure/
partial；不读取 target/outcome/result 的 structural metadata preflight 不暴露。Spent sets 只可 audit/debug，
不得进入 train/validation/selection/recovery design，不得再产生 official score/CI/label。Recovery 必须
使用 fresh previously unexposed test_id/test_ood，相对 spent sets 的 trace_id、seed、artifact content
SHA 与 `realized_trace_sha256` 全局不相交，满足 condition/OOD rules，并新建 manifest、test
identities、protocol/version/provenance 与两层 freezes；failure record/spent identities 必须保留。

WP-03 Slice 1–17 implementation acceptance 不是 predictor performance、forecasting/control benefit、
uncertainty benefit 或 MAPPO evidence。当前没有真实 WP-03 scientific result，没有执行真实 official
prediction experiment，没有发生 `FIRST OFFICIAL TEST EXECUTION`，`test_id` / `test_ood` 均未真实
`SPENT`。Formal H1 PASS 只解锁当前阶段
`WP-03 Official Prediction Experiment Specification Freeze`，不解锁直接 execution。该 read-only stage
必须为未来 official experiment 冻结 exact split sizes/source inventories/conditions、training seeds、
Primary/secondary P、DatasetProtocolSpecs/L、architecture schema/complexity key、optimizer/lr/
architecture/objective/transform/non-count encoding grids、training budget/early stopping/checkpoint rules、
B2/B3 grids、OOD cells、prediction bootstrap 与 runtime/Git/dependency provenance，以及 exact Layer A
identity 与 Layer B requirements；本轮不决定这些值。Spec 独立审查、用户手动 Commit/Push 与 GitHub
Actions acceptance 前，禁止 official dataset generation、predictor training、official ID/OOD test、
forecast-control、uncertainty、MAPPO 或 GPU scientific execution。

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
11. 已完成并接受 WP-03 Slice 1–17；`WP-03 IMPLEMENTATION CLOSED`
12. 已完成并接受 WP-02D Formal H1 Primary execution/evidence audit；verdict `PASS`
13. 当前：`WP-03 Official Prediction Experiment Specification Freeze`
14. spec 独立 review、用户手动 Commit/Push 与 GitHub Actions acceptance
15. 另行 explicit authorization 后才可执行 WP-03 official prediction experiment
16. 不确定性感知 MAPPO（仍锁定）
17. ID/OOD、消融和相图
18. 最终统计分析与论文结果

Formal H1 Primary verdict 已接受为 `PASS`；formal sensitivity 未执行。服务器 evidence root 及其
artifacts 不在本轮复制或修改，也不加入 Git。当前只允许 WP-03 official experiment read-only
specification design/freeze；不得进行 official dataset generation/training/test、forecast uncertainty/control
science、MAPPO、PyTorch/GPU training、ID/OOD 主实验、大规模 optimizer 或论文主结果实验。
