# 项目决策记录

状态可为：已接受、已修订、已撤销。被修订的决策保留历史，并指向替代决策。

## D-001：项目独立于指定原文

- 状态：已接受
- 决策：研究问题、代码、环境和实验独立建立，不依赖指定论文的隐藏实现细节。
- 原因：降低复现不可控风险，使创新主张能够通过自洽实验验证。

## D-002：先验证未来信息价值，再训练 MARL

- 状态：已接受
- 决策：在 MAPPO 开发前，必须比较反应式启发式与 Oracle 启发式。
- 原因：如果真实未来信息也不能改善结果，继续增加预测器或强化学习没有科学意义。

## D-003：WP-00 不安装 PyTorch

- 状态：已接受
- 决策：先核验服务器驱动、CUDA 和 Python；WP-01 继续保持 CPU-only。

## D-004：中文说明、英文标识符

- 状态：已接受
- 决策：模块、函数和变量使用英文；Docstring、关键算法说明和配置注释使用中文。

## D-005：仓库文档是跨会话事实来源

- 状态：已接受
- 决策：以 Commit、配置、测试和 `docs/` 状态文件为准，不依赖聊天记录恢复项目状态。

## D-006：采用单一 main 分支开发

- 状态：已接受
- 决策：项目只使用 `main` 分支开发，不创建功能分支、额外 worktree 或 Pull Request。
- 原因：保持 Mac、GitHub 和 A100 服务器之间的交付路径单一且可追溯。

## D-007：Codex 不执行版本发布操作

- 状态：已接受
- 决策：Codex 只负责修改和测试文件，不得执行 Commit、Tag 或 Push，也不得执行任何分支操作。
- 原因：版本历史和远程发布由用户手工确认并控制。

## D-008：使用 candidate 标签进行推送 main 前的验收

- 状态：已撤销
- 原决策：本地 Commit 后先只推送 candidate 标签，由 A100 服务器以 detached HEAD 验收；通过后才推送 `main`。
- 替代：见 D-014。当前流程使用提交前完整补丁审查，之后直接 Push `main` 并由服务器 `git pull --ff-only` 验收。

## D-009：稳定标签记录已验收阶段

- 状态：已修订
- 决策：已验收阶段可创建稳定标签，`wp00-stable` 保留为初始稳定标签；后续稳定标签不是默认必需步骤，除非工作包明确要求。

## D-010：Mac 仅执行快速 CPU 测试

- 状态：已接受
- 决策：Mac 端只执行工作包规定的快速 CPU 测试。
- 原因：快速发现工程错误，同时避免在本地承担不适合的计算任务。

## D-011：大型和 GPU 任务在 A100 服务器执行

- 状态：已接受
- 决策：大型训练、多随机种子实验和 GPU 任务仅由用户在 A100 服务器启动。
- 原因：集中使用适合的计算资源，并确保高成本任务由用户明确控制。

## D-012：禁止重写已推送 main 的历史

- 状态：已接受
- 决策：已推送的 `main` 禁止 force push、`git reset` 或其他历史重写；问题只能通过追加修复 Commit 或 `git revert` 处理。
- 原因：保护共享历史的一致性和可追溯性。

## D-013：服务器不直接修改源码

- 状态：已接受
- 决策：A100 服务器仅用于候选验收，不直接修改源码；失败日志返回 Mac 端，由 Codex 修复。
- 原因：保持 GitHub 为 Mac 和服务器间唯一代码中转来源，避免环境间产生未追踪分叉。

## D-014：采用提交前完整补丁独立审查

- 状态：已接受
- 决策：Codex 完成未提交候选实现后，在 Downloads 或 Desktop 生成覆盖全部已跟踪和未跟踪改动的补丁；用户上传，ChatGPT 在独立副本审查并复测。审查通过后才 Commit 和 Push。
- 原因：`git clone` 无法读取 Mac 未提交修改；完整补丁在保持 `main-only` 的同时提供独立质量关口。

## D-015：审查文件不得写入 /tmp

- 状态：已接受
- 决策：面向用户的补丁、报告和压缩包只生成在 Desktop、Downloads 或会话可下载目录，不使用 `/tmp`。
- 原因：降低终端操作和文件定位风险，避免临时目录清理造成丢失。

## D-016：需求过程位于顶层 fura_mappo.demand

- 状态：已接受
- 决策：外生需求过程不放入 `envs`，使用顶层 `fura_mappo.demand`。
- 原因：需求是策略无关科学组件，避免与未来智能体环境耦合。

## D-017：WP-01A 使用实例独立 Generator 和统一状态机

- 状态：已接受
- 决策：每个 `DemandProcess` 独占 `numpy.random.Generator`；ABC 统一实现 `reset`、`step` 和 `generate` 的时间、seed 和 event ID 语义。

## D-018：WP-01A 强度、几何和属性接口保持最小明确

- 状态：已接受
- 决策：只接受逐区域强度向量；区域限定轴对齐矩形；priority、service time 和 deadline offset 使用显式范围；不在 WP-01A 引入配置 dataclass、分布注册器或 metadata。

## D-019：WP-01A 数据输出防御性只读

- 状态：已接受
- 决策：含数组的数据对象使用防御性复制和只读标志，过程内部状态不依赖已返回数组；数据类不使用 NumPy 数组自动相等比较。

## D-020：WP-01A 稳定实现基线

- 状态：已接受
- 决策：WP-01A 的稳定实现 Commit 为 `b7b48bb394bd4613652b4d1ff4158cb8503f52a5`，里程碑标签为 `wp01a-stable`。
- 证据：独立补丁审查通过、GitHub Actions `CPU checks` run #3 成功、A100 CPU 与专项验收通过。
- 原因：为 WP-01B 提供明确、可回退且接口冻结的基线。

## D-021：WP-01B 继承 WP-01A 公共接口并先做只读设计

- 状态：已接受
- 决策：WP-01B 只增加 Drifting Hotspot、Markov Switching 和 Burst Demand；必须复用 WP-01A 数据模型、独立 RNG、状态语义和工厂安全原则。设计审查通过前不修改源码。
- 原因：避免三类过程形成不兼容状态机，防止为未来配置、序列化或强化学习提前扩张接口。

## D-022：WP-01B 使用内部共享 Poisson 生成层

- 状态：已接受
- 决策：四类过程通过未导出的 `_PoissonDemandProcess` 和共享 Step 构造逻辑复用区域计数、事件位置和任务属性采样；公共 API 不暴露该内部层。
- 约束：Stationary 的公共签名和相同 seed 轨迹必须与 WP-01A 精确兼容。
- 证据：150 组随机 Stationary 配置与 WP-01A 原实现完全一致。

## D-023：Drifting Hotspot 使用确定性反射和归一化总增量

- 状态：已接受
- 决策：热点以显式位置和速度确定性移动，在所有区域外包矩形边界反射；每个热点 amplitude 表示每步总到达率增量，按区域中心、面积和各向同性高斯权重稳定归一化。
- 时序：当前热点位置先发射，完整 Step 成功后再提交下一位置和速度。
- 原因：保证总需求增量含义明确、边界行为可复现，并避免极端尺度下数值溢出或下溢。

## D-024：Markov 与 Burst 的状态时序

- 状态：已接受
- 决策：Markov 使用“当前状态发射、随后转移”；确定性转移行不消费 RNG。Burst 为非重叠加法过程，只在空闲步抽启动，启动步立即发射，活动期间不重复启动。
- 原因：消除 off-by-one 和隐藏随机消耗歧义，使 reset 重放和理论统计可直接验证。

## D-025：WP-01B 稳定实现基线

- 状态：已接受
- 决策：WP-01B 稳定实现 Commit 为 `d67f71b5d75ee47adb120686914d32572ea7d6d1`，里程碑标签为 `wp01b-stable`。
- 证据：Mac `293 passed`、独立补丁审查通过、GitHub Actions `CPU checks` run #5 成功、A100 Python 3.11.15 验收通过。
- 原因：为 WP-01C 提供明确、可回退且行为冻结的四过程基线。

## D-026：WP-01C 先冻结数据与配置协议

- 状态：已接受
- 决策：WP-01C 在实现前必须通过只读设计审查，明确配置 schema、路径语义、序列化格式与版本、复现元数据、覆盖策略、CLI 子命令、统计定义和可选可视化依赖。
- 约束：WP-01C 不得改变四类过程的科学语义，不得夹带环境、预测或强化学习功能。
- 原因：文件与 CLI 接口一旦产生外部数据兼容性，修改成本高于纯内存接口，必须先冻结协议。

## D-027：WP-01C 使用严格 YAML v1 与稳定配置哈希

- 状态：已接受
- 决策：配置仅接受 `fura-mappo.demand-generation` version 1；安全 loader 拒绝重复键、anchor/alias、merge、对象标签和非 JSON-like 内容；resolved config 使用带类型标记的 canonical SHA-256。
- 原因：配置是可复现实验输入，必须避免隐式默认、类型碰撞和不安全对象构造。

## D-028：WP-01C 使用单文件 NPZ artifact v1

- 状态：已接受
- 决策：轨迹采用 `fura-mappo.demand-trace` version 1，固定成员、little-endian dtype、内嵌 strict JSON manifest、config/content hash、无 pickle。
- 安全：ZIP/NPY header 在分配前校验；symlink 拒绝；同目录原子写入；外部内容错误统一为 `ValueError`。

## D-029：WP-01C CLI 第一版只提供 generate 与 summarize

- 状态：已接受
- 决策：提供 `fura-demand generate` 和 `summarize`；默认拒绝覆盖和 dirty Git；第一版不加入 plot/Matplotlib。
- 原因：先冻结核心可复现数据协议，避免非核心可视化依赖扩大范围。

## D-030：WP-01C 稳定实现基线

- 状态：已接受
- 决策：WP-01C 稳定实现 Commit 为 `29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`，里程碑标签为 `wp01c-stable`。
- 证据：Mac 421 tests、提交前独立审查通过、GitHub Actions `CPU checks` run #7 成功、A100 Python 3.11.15 421 tests。
- 原因：WP-01 需求生成系统在此形成完整的科学与数据工具稳定基线。

## D-031：WP-02 先冻结环境与 Oracle 信息边界

- 状态：已接受
- 决策：WP-02 在实现前必须只读分析并冻结环境时间步、服务/移动语义、组成指标、反应式信息集和 Oracle 未来信息窗口；不得先实现最终 RL reward 或 MAPPO。
- 原因：H1 的 Oracle 价值门槛必须在可解释、固定的环境机制下验证。

## D-032：冻结 WP-02A 环境语义与稳定实现基线

- 状态：已接受
- 决策：WP-02A 的确定性资源服务环境语义已经冻结；稳定实现 Commit 为 `d01092831a227a9f520de4ff8ded1d9e13ba8262`。
- 冻结边界：环境仅消费 `DemandTrace`，采用连续二维欧氏移动、同质资源、精确位置服务、Move/Serve slot 互斥、非抢占服务、completion → expiration → truncation 边界顺序、canonical `resource_to_event`、事务式 `reset` / `step`、future Serve side-channel 隔离、确定性 duplicate assignment resolution，以及组成指标和精确守恒检查。
- 非范围：WP-02A 不定义 reward，不包含 RL、Reactive 或 Oracle。
- 证据：最终批准 patch SHA-256 为 `74b74cd9590eea1498152a81dc747cadf676d66890516c6460c07c819cd49e81`；v2 独立复核 BLOCKER 0、MAJOR 0、MINOR 0；Mac、GitHub Actions `CPU checks` 与 A100 验收通过。
- 后续约束：下一唯一阶段为 WP-02B Reactive baseline 只读设计；不得提前实现 WP-02B 或进入 Oracle、H1 正式门槛实验、预测与 MAPPO。

## D-033：冻结 WP-02B Reactive baseline 与共享 movement feasibility

- 状态：已接受
- 决策：Reactive 是 centralized、stateless、current-state-only 的 deterministic baseline；只动态消费当前 `EnvironmentSnapshot`，只额外持有 `movement_speed`，不访问 future demand、intensity 或 hidden demand state。
- 状态边界：controller 不拥有 RNG、history、movement target 或 task reservation；每个 step 依据当前 snapshot 重新规划。
- 物理边界：Reactive exact movement feasibility 必须复用 WP-02A 唯一的内部 single-slot movement primitive；`ceil(distance / speed)` 不作为 exact travel truth。该 primitive 是对 WP-02A 原算法的机械抽取，WP-02A 公共环境行为不变。
- 稳定实现：WP-02B 实现 Commit 为 `f290a45a67763b41941e919303b26fb16a67575a`。
- 证据：最终批准 patch SHA-256 为 `38648aac6ae7d92766244ee2d226cc2a32a4a6d2337b8a039432f0daaadf191f`；独立审查 BLOCKER 0、MAJOR 0、MINOR 0；Mac、GitHub Actions `CPU checks` 与 A100 CPU 验收通过。
- Oracle 边界：未来 Oracle 必须保持 WP-02A environment physics 与 movement feasibility，但不要求复用 Reactive 的完整 greedy planning；Oracle 的 information set、horizon 和 future planning 留待 WP-02C 独立只读设计，不在本决策中提前冻结。

## D-034：冻结 WP-02C Rolling True-future Oracle 与 bounded future information boundary

- 状态：已接受
- 决策：Primary Oracle 是 deterministic、stateless、receding-horizon 的 H-step true-future
  matched heuristic；只接收 explicit bounded `DemandEvent` future view，不持有完整
  `DemandTrace`。
- 信息边界：Oracle 不访问 intensity、counts、hidden demand state、RNG、seed、config 或
  artifact metadata。official builder 只执行最低限度 prefix/pairing validation；正式 paired
  experiment 必须由调用方使用同一个内存 `DemandTrace` 构造环境和 future view。
- 物理与控制边界：exact feasibility 与 Reactive/环境复用相同 single-slot movement
  semantics；H=0、empty future view，以及没有任何 physically feasible future-resource pair
  时必须结构性退化到冻结 Reactive。
- 稳定实现：WP-02C 实现 Commit 为 `9159c841af4f605d6e32cca4b37940f0116a19cf`。
- 科学解释：Primary Oracle 不是 global optimum、optimal controller 或 theoretical upper
  bound；Oracle 未优于 Reactive 时，不能单独据此断言未来信息没有价值。
- 后续诊断：bounded diagnostic verifier 留到 WP-02D，用于防止 weak Oracle 造成 H1 false
  negative；规模上限为不超过 2 resources、4 steps、3 events，使用真实环境，不公开为正式
  baseline，也不声称全局最优上界。
- WP-02D 边界：primary H、horizon sensitivity、verifier objective/exact search、H1 gate、
  paired statistical estimator、uncertainty 与 decision rule 均在 WP-02D 只读设计中冻结；本
  决策不包含正式 H1 结论。
- 证据：最终批准 patch SHA-256 为 `5dad6a0c966548bfc981cc8f48a2f84d6f9a5cafe4b2a351c299e2b578c9558a`；独立审查 BLOCKER 0、MAJOR 0、MINOR 0；Mac、GitHub Actions `CPU checks` 与 A100 CPU 验收通过。

## D-035：冻结 WP-02D H1 gate preregistration 与 WP-02D1 protocol/statistics baseline

- 状态：已接受
- Primary stress cell：预注册 `DriftingHotspotDemand` primary cell，256 steps、2 resources、
  `movement_speed=0.75`、固定 priority 0.5、Primary H=2；完整数值配置以
  `docs/WP02D_SPEC.md` 与 `configs/experiments/wp02d_h1.yaml` 为准。
- Seed protocol：N=256，固定 consecutive seeds `20260819..20261074`；Reactive 与 Oracle
  必须在独立环境中消费同一个内存 `DemandTrace`。
- Primary outcome：每条 trace 若 arrived > 0，
  `D_i=(completed_oracle-completed_reactive)/arrived`；若 arrived=0，`D_i=0`。Primary
  estimand 冻结为每条 trace 等权的 `mean(D_i)`。
- Gate：`delta_min=0.02` absolute completion fraction。PASS 要求 point estimate ≥ 0.02 且
  one-sided 95% LCB > 0；FAIL 要求不满足 PASS 且 one-sided 95% UCB < 0.02；其余有效结果为
  INCONCLUSIVE；任何 protocol violation 为 PROTOCOL_FAIL。Secondary metric 或 sensitivity
  不得改变 primary verdict。
- Uncertainty：paired resampling unit 为 trace，冻结 NumPy
  `Generator(PCG64(90260819))` percentile bootstrap、50,000 resamples、linear quantile。
- Audit chain：冻结 exact validated spec → experiment spec hash → frozen inventory/inventory
  hash → exact entry → safely loaded artifact 与 config/content hashes → provenance-bound paired
  result/results digest → gate summary → locked verdict。Verdict 必须绑定 exact
  spec/inventory/results/provenance；旧 verdict 不能解锁另一组 sensitivity results。
- Protocol controls：冻结 H=0 strict invariant、canonical mechanism preflight、same-state
  counterfactual diagnostics、realized Oracle diagnostics、strict JSON/JSONL 与 atomic
  no-overwrite outputs，以及 local Git provenance hard gate。
- 稳定实现：WP-02D1 implementation Commit 为
  `844de649c71e0a6a8fec6e1355cbf010db434f83`。
- 科学状态：WP-02D1 是 protocol/statistics implementation，不是 H1 scientific result；正式
  primary traces、controller rollouts、artifacts/results/verdict 均为零，formal H1 尚未运行。
- 下一门禁：必须先完成并验收 WP-02D2
  `bounded task-target root-information exhaustive diagnostic verifier`，包括完整候选 patch
  审查、Commit/Push、GitHub Actions 与 Mac/A100 acceptance，之后才允许用户明确启动正式
  artifact/H1 execution。WP-02D2 不是新的 public baseline，也不声称 global optimum、
  continuous-control optimum 或 theoretical upper bound。

## D-036：接受 WP-02D2 bounded root-information verifier implementation baseline

- 状态：已接受
- 稳定实现：WP-02D2 implementation Commit 为
  `cfab8c1b1981ef095d68969fff74faa2ac4f256d`，实现说明为
  `feat: add bounded root-information verifier`。
- 科学定位：WP-02D2 是 private、diagnostic-only 的
  `bounded task-target root-information exhaustive diagnostic verifier`，用于识别 weak greedy
  Primary Oracle 可能造成的 H1 false negative；它不是 formal baseline、global optimum、
  continuous-control optimum、theoretical upper bound、optimal policy 或 Primary adequacy proof，
  verifier output 不进入 formal primary verdict 输入。
- Root-information boundary：每个真实 decision boundary 使用 official
  `build_true_future_view(...)` 冻结
  `K = current active tasks + official H-step future view events`；一次 root search 内不刷新 K 或
  future view，不引入 root horizon 外事件，下一真实 boundary 才重新构造 K 并重新搜索。
- Replay 与环境边界：规模限制为 resources ≤ 2、episode steps ≤ 4、events ≤ 3；每个 branch
  使用 fresh `ResourceServiceEnvironment` 和 deterministic prefix replay，state transition 只能经
  public `reset()` / `step()`，禁止 private environment state 或复制 transition logic。
- 有限动作空间：SERVING 仅 Continue；AVAILABLE 可 Idle、对 frozen-K current WAITING event 的
  legal Serve，以及 target 来自 frozen-K event positions 的 Move；保留 zero-distance Move 与
  environment-legal duplicate Serve joint actions。搜索一直到 episode terminal，不使用 pruning、
  memoization、symmetry reduction 或 dominance。
- Objective 与 tie-break：唯一 objective 是 maximize completed count over frozen K；相同完成数仅
  按 canonical complete sequence key 的字典序最小值选择：Continue `(0,)`、Idle `(1,)`、Move
  `(2,x,y)`、Serve `(3,event_id)`，joint action 按 increasing resource_id，sequence 按 increasing
  time。该 ordering 不是 performance preference，不加入 priority、movement distance、wait、
  reward 或 secondary objective。
- 预注册 fixtures：handcrafted F1/F2/F3/F4/F5/F6A/F6B 的 Primary/Verifier 期望分别为
  `1/1`、`1/2`、`1/2`、`1/2`、`0/0`、`1/1`、`1/1`。Fixture 6 使用修正版外部位置
  `(3,0)` / `(-3,0)`，冻结相同 root snapshot/view、root K IDs `{0}`、排除 `±3` Move targets 与
  相同 first joint action；这些是 unit-test expectations，不是 Formal H1 evidence。
- Diagnostic classifier：任一预注册 fixture 的 verifier completed > Primary completed 时为
  `PRIMARY_HEURISTIC_MISS_DETECTED`，否则为
  `NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE`；后者不证明 Primary optimal
  或 heuristic adequacy，两个标签均不是 Formal H1 outcome。
- 接受证据：批准 patch SHA-256 为
  `f6cb0e8638847b4b84f84421f5bbc77926abc6995a4704f6cb11300ff8ff172f`，独立审查 BLOCKER 0、
  MAJOR 0、MINOR 0；Mac、GitHub Actions `CPU checks` 与 A100 server CPU acceptance 均通过。
  implementation 仅新增 verifier 私有模块和专项测试；public experiments API、`h1_gate.py`、
  environment physics、Reactive、Primary Oracle 与 formal H1 preregistration 均未修改。
- 当前科学状态：Formal H1 尚未运行，formal primary traces 为 `0 / 256`，正式 seeds 仍为
  `20260819..20261074`。WP-02D1 与 WP-02D2 已完成 / accepted，但 WP-02D overall 仍在进行中。
- 下一门禁：Formal H1 只能在本 docs-only checkpoint Commit/Push 完成、下一阶段 Formal H1
  execution preparation / audit gate 通过后，由用户明确授权启动；在有效 scientific gate 结果及
  解释完成前继续禁止 prediction、forecast uncertainty、MAPPO 与 PyTorch/GPU training。

## D-037：接受 WP-02D3 Formal H1 execution hardening baseline

- 状态：已修订
- 修订范围：WP-02D3 implementation acceptance、H1 science 与当时的 execution-hardening 事实继续
  有效；“未来永远以 `1092d9c...` 且其后只能 docs/changelog 作为 execution baseline”的前瞻性
  条款由 D-038 修订。服务器恢复后的下一次 Formal H1 必须重新冻结 latest accepted main 的
  execution provenance。
- 稳定实现：WP-02D3 implementation Commit 与 Formal H1 accepted implementation SHA 均为
  `1092d9c87bfff8ba6c1f2132734480112d7b5975`，准确定位是
  `Formal H1 execution orchestration / persistence hardening`。它不改变 H1 科学规格、环境科学、
  Reactive、Primary Oracle 或 D2 verifier。
- SHA 规则：本次及未来 docs-only checkpoint Commit 是 accepted implementation 的合法
  `docs/**` / `CHANGELOG_*` descendant，但不替代 accepted implementation SHA；未来 runner 的
  `--accepted-implementation-sha` 必须继续使用 `1092d9c87bfff8ba6c1f2132734480112d7b5975`。
- Private runner：正式入口为 private module
  `fura_mappo.experiments._formal_h1_runner`，未修改 `experiments/__init__.py`，不构成 public API。
  固定 spec 为 `configs/experiments/wp02d_h1.yaml`，固定 run root 为
  `artifacts/wp02d_h1_formal_v1/`，其 traces、inventory、paired JSONL、aggregate 与 verdict 路径
  均不得另设第二套正式位置。
- Provenance hard gates：要求真实 repository root、branch `main`、clean working tree、
  `actual HEAD == origin/main`、WP-02C stable 与 accepted implementation ancestry，以及 accepted
  SHA 后仅有 docs/changelog changes；同时把实际 loaded Python code 绑定到当前 repo 的
  `src/fura_mappo`。关键 publication 边界重复 revalidate provenance。
- Restart/resume 与 no-overwrite：已有 inventory 时不再生成 trace，并 strict validate inventory
  和全部 256 NPZ；inventory 不存在时，已存在 trace 只允许 provenance-bound strict reuse，缺失
  trace 才可在重新验证 provenance 后 exactly-once no-overwrite 生成。任何 missing、invalid、
  unknown 或 symlink evidence 均 hard fail，不自动删除、覆盖、修复或 replacement seed。
- Strict persistence：paired JSONL、aggregate 与 verdict 均 strict canonical readback；aggregate
  必须等于从 strict paired results 重新计算的 summary。`read_primary_verdict(...)` 可严格读取
  `PROTOCOL_FAIL`，但 `require_locked_primary_verdict(...)` 永不允许其解锁 sensitivity。
- Crash durability：protocol JSON/JSONL 与 no-overwrite NPZ 均在 temporary directory entry 消失
  后 fsync parent；首次创建 run root 后 fsync `artifacts/`，首次创建 `traces/` 后 fsync run root。
  这些持久化控制不改变 scientific content。
- 接受证据：最终批准 `wp02d3-review-v4.patch` SHA-256 为
  `f4dd19abd16723d19508b26f89ad1a93e4e4a1b468aa13a9785baa8ec86b82a9`，独立审查
  BLOCKER 0、MAJOR 0、MINOR 0；GitHub Actions two checks passed；A100 server CPU acceptance
  focused `207 passed in 16.87s`、full `720 passed in 34.31s`，Ruff、format 与 diff-check 通过，
  最终工作树干净。以上不是 GPU 或 Formal H1 验收。
- 当前科学状态：Formal H1 尚未运行，formal primary traces 为 `0 / 256`，formal controller
  rollouts、inventory、paired results、aggregate、verdict 与 sensitivity 均为零。WP-02D1、D2、
  D3 均 completed / accepted，但 WP-02D overall 仍在进行中。
- 下一门禁：`Final Formal H1 execution-readiness freeze / runbook freeze`。该只读 freeze、docs
  checkpoint Commit/Push 与用户明确授权全部完成前，不运行 Formal H1；在有效 scientific gate
  outcome 完成解释前，不进入 prediction、forecast uncertainty、MAPPO 或 PyTorch/GPU training。

## D-038：修订服务器不可用期间的研发顺序

- 状态：已接受
- 决策关系：D-002“先验证未来信息价值，再训练 MARL”继续有效且未被修订；official predictor
  science 与 MAPPO science 仍须等待 H1 gate。D-035/D-036 的 next-gate 文字是已经完成阶段的历史
  记录。D-037 的 WP-02D3 acceptance/science 继续有效，但其“`1092d9c...` 后永久只允许
  docs/changelog”的未来 execution-baseline 条款由本决策修订。
- 决策：服务器不可用期间，Mac 恢复正常 main-only 研发流程，允许 design、implementation、CPU
  tests、tiny smoke、full patch review、用户手动 Commit/Push 与 GitHub Actions。WP-03A 可以合法
  增加 source/tests/docs，不修改旧 Formal H1 runner 来放宽 provenance。
- 继续锁定：Formal H1、正式 seeds/artifacts/results、large multi-seed science、official predictor /
  uncertainty / forecast-control experiments、ID/OOD main experiments、MAPPO 与 GPU training。
- Server queue：服务器恢复后同步 latest accepted main，重新冻结 Formal H1 accepted execution
  baseline/provenance，重新做 readiness preflight，取得用户明确授权，再运行 Formal H1 与 primary
  evidence audit。
- 原因：不让服务器故障永久阻止安全、可审查的基础设施研发，同时保持 Formal H1 的假设、环境、
  estimand、bootstrap、gate 与 scientific identities 不变。

## D-039：冻结 WP-03A Prediction Interface & Dataset Protocol

- 状态：已接受
- 实现状态：设计决策已接受；candidate v3 独立 review 为 BLOCKER 0、MAJOR 1、MINOR 1，当前
  candidate v4 只修复 signed-zero intrinsic-hash canonicalization 与本条 stale wording，仍须独立
  review/acceptance，不能据此记录 accepted implementation。
- Target：lead `1..P` 的 future realized zone-level arrival counts，shape `[P,Z]`、`int64`；不使用
  intensity、future event list 或 controller-dependent state。
- Information boundary：context 只含 boundary `t` 及以前的 realized zone counts、absolute step、
  steps remaining 和静态 zone identity；训练 input 与 inference input 完全一致。
- 时间语义：history 为 `t-L+1..t`，左 zero padding + mask；forecast row 0 为 `t+1`；target 在 episode
  end 右 zero padding + mask；supervised anchor 为 `start <= t < stop-1`。
- Interface：immutable natural-scale `PredictionContext`、`PredictionTarget`、`PredictionSample` 与
  mandatory-mean/optional-variance-quantiles-scenarios `DemandForecast`；PyTorch-neutral，不选择模型
  architecture。
- Leakage guards：online history 不接收 `DemandTrace`；offline context 只复制 realized count prefix；
  source/provenance 与 controller-visible payload 分离；ZoneSchema 与 safe-loaded artifact source
  hard binding；authoritative source 内部计算不含 intensity/metadata 的 intrinsic realized-trace
  identity，并把 realized float fields 的 `+0.0`/`-0.0` canonicalize 为相同逻辑值；authoritative
  split 只能从 verified artifacts 构造/复核；全 trace split、global
  seed/content/realized-trace/trace ID disjointness 与 OOD condition holdout；forecast 必须与其 context
  的 boundary、horizon、zone schema、zone count 和 terminal mask 完全一致。
- Reproducibility：ZoneSchema/protocol/condition/sample/split 使用既有 stable config hash；protocol /
  manifest strict canonical JSON、exact schema、no-overwrite 与 strict readback；dataset derivation RNG-free。
- 非目标：不冻结正式 L/P、normalization、split seeds、OOD conditions、predictor、controller、training、
  reward 或 MAPPO。没有 forecasting 改善 control 的科学结论。
