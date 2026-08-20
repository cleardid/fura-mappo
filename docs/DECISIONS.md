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
