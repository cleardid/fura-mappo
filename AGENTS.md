# FURA-MAPPO Codex 协作规范

本文件适用于仓库根目录及全部子目录。具体工作包中的约束如更严格，以工作包为准。

## 1. 项目与当前阶段

- 项目目标：研究非平稳时空需求下，利用未来需求预测及其不确定性进行多智能体主动资源预置。
- 当前主线：`WP-01` 外生需求生成器。
- `WP-01A` 已完成，冻结实现 Commit 为 `b7b48bb394bd4613652b4d1ff4158cb8503f52a5`。
- 当前子工作包：`WP-01B`，只处理 Drifting Hotspot、Markov Switching 和 Burst Demand。
- 当前第一阶段是 WP-01B 只读设计分析；设计审查通过前不得修改源码。
- WP-01B 期间继续 CPU-only，不安装 PyTorch，不修改 CUDA、NVIDIA 驱动或服务器系统环境。
- 不得提前实现 WP-01C、智能体环境、奖励、预测模型或强化学习功能。

完整研究范围见 `docs/PROJECT_REQUIREMENTS.md` 和 `docs/RESEARCH_PLAN.md`；当前状态见 `docs/PROJECT_STATE.md`。

## 2. 开发环境

1. 项目运行环境统一使用 Python 3.11。
2. A100 服务器系统 Python 2.7 不得用于本项目。
3. Mac 使用 Conda 环境 `fura-mappo-mac` 做快速 CPU 验收。
4. A100 服务器使用 Conda 环境 `fura-mappo` 做正式服务器验收。
5. GPU 训练、大型实验和多随机种子实验只能由用户在服务器明确启动。
6. Codex 不得自行安装依赖、修改驱动、启动 GPU 任务或长时间实验。

## 3. 代码和科学规范

1. 文件名、模块名、类名、函数名和变量名使用英文。
2. 模块说明、Docstring 和关键算法注释使用中文。
3. 公共函数和方法必须有类型标注。
4. NumPy 数组及未来张量必须在 Docstring 中注明形状，必要时注明 dtype。
5. 所有随机过程必须使用实例独立的 `numpy.random.Generator`。
6. 核心实现不得依赖或污染 NumPy 全局随机状态。
7. 禁止隐藏的全局可变状态、可变默认参数和使用 `assert` 校验用户输入。
8. 对类型、值域、维度和配置错误应抛出明确的 `TypeError` 或 `ValueError`。
9. 不得静默截断数值、接受维度不匹配或原地修改调用方配置。
10. 科学组件必须与策略、智能体状态、动作、奖励和模型参数解耦，除非后续工作包明确改变边界。
11. WP-01B 必须复用 WP-01A 已冻结的数据模型、RNG 隔离和 `reset`/`step`/`generate` 状态语义；任何接口变更都必须先形成明确决策。

## 4. 修改边界与真实性

1. 不得删除、跳过或放宽测试来绕过错误。
2. 不得虚构测试、性能、Git、服务器或 GitHub Actions 结果。
3. 无法执行的命令必须明确报告原因。
4. 不得提前实现当前工作包以外的功能。
5. 不得进行与任务无关的大规模重构。
6. 不得修改冻结公共接口，除非工作包明确授权。
7. 不得提交大型数据、日志、模型、检查点、Token、SSH 配置或敏感服务器信息。
8. 历史运行手册和已完成工作包的变更记录原则上只追加勘误，不重写历史事实。

## 5. Git 与审查交付

1. 项目采用单人 `main-only` 流程，不创建功能分支、额外 worktree 或必需 Pull Request。
2. Codex 只在用户指定的 Mac 本地 `main` 工作目录中分析、修改和测试。
3. Codex 不得执行 Commit、Push、Tag、Merge、Rebase、Reset、Clean、Stash、force push 或历史重写。
4. Commit 和 Push 由用户手工执行；服务器不得直接修改源码。
5. Codex 完成候选实现后，必须生成包含已跟踪和未跟踪改动的完整审查补丁。
6. 审查补丁只写入 `$HOME/Downloads/` 或 `$HOME/Desktop/`，不得写入 `/tmp`。
7. 用户将补丁上传到独立审查会话；审查通过前不得提交或推送。
8. 审查有问题时，只做聚焦修复并重新生成完整补丁；审查通过后再由用户提交到 `main`。
9. 已推送错误只能通过追加修复 Commit 或 `git revert` 处理，禁止 force push。
10. 完整流程与验收规则见 `docs/CODEX_WORKFLOW.md`。

## 6. 完成报告

Codex 每次任务结束至少报告：

- 实际修改和新增文件；
- 实现与设计偏离；
- 执行过的命令及真实结果；
- `git diff --check`；
- `git diff --stat`，并说明未跟踪文件是否计入；
- `git status --short`；
- 明确确认未 Commit、未 Push。
