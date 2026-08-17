# Codex main-only 协作、补丁审查与交付流程

## 1. 基本原则

- 项目只使用 `main` 分支，不创建功能分支或额外 worktree。
- Pull Request 和 candidate 标签不是必需流程。
- Codex 只负责只读分析、文件修改和测试。
- Commit、Push、Tag 和服务器操作由用户手工执行。
- GitHub 是 Mac 和 A100 服务器之间唯一的源码中转来源。
- A100 服务器不直接修改源码。
- 大型数据、训练日志、模型和检查点不通过 GitHub 传输。
- 每个工作包开始前记录远程基线 Commit、当前分支和工作树状态。

## 2. 四种状态必须区分

1. **远程基线**：`origin/main` 上已存在的 Commit；
2. **Mac 候选工作树**：Codex 修改但尚未提交的代码；
3. **审查补丁**：从 Mac 候选工作树生成并上传的完整 Diff；
4. **服务器验收 Commit**：用户 Push 后由服务器拉取的确定 Commit。

`git clone` 只能看到远程基线或已推送 Commit，不能看到 Mac 未提交修改。因此提交前独立审查必须使用完整补丁。

## 3. 标准流程

### 阶段 1：只读设计分析

1. 用户确认 Mac 本地 `main`、远程基线和工作树状态。
2. Codex 读取 `AGENTS.md`、当前状态、决策、交接、工作包规范、相关源码和测试。
3. Codex 只返回结构、接口、状态语义、测试方案、风险和文件范围。
4. 不修改文件，不运行可能污染工作树的命令，不执行 Git 写操作。

### 阶段 2：设计审查

1. 用户把 Codex 分析报告交给 ChatGPT 独立审查。
2. 审查接口是否过度设计、随机状态是否隔离、统计测试是否稳定、是否夹带未来范围。
3. 设计确认后生成聚焦实现任务。

### 阶段 3：Codex 实现和 Mac 快速测试

1. Codex 在 Mac 主工作目录的 `main` 上修改明确文件。
2. Codex 运行专项测试、Ruff、格式检查和 `scripts/verify_cpu.sh`。
3. Codex 不得 Commit、Push、Tag、切换分支或创建 worktree。
4. Codex 报告真实结果和工作树状态。

### 阶段 4：生成完整审查补丁

1. 补丁必须同时包含已跟踪修改和全部相关未跟踪新文件。
2. Codex 将补丁写入：

```text
$HOME/Downloads/<work-package>-review.patch
```

或：

```text
$HOME/Desktop/<work-package>-review.patch
```

3. 不得使用 `/tmp`。
4. Codex 报告补丁路径、Diff 段数、字节数和 SHA-256。
5. 用户只需上传补丁文件，不必复制粘贴大段 Diff。

### 阶段 5：独立补丁审查

1. ChatGPT 读取远程 `origin/main` 基线。
2. 在隔离副本中执行补丁完整性和应用检查。
3. 审查完整源码、测试、状态管理、随机性、统计断言和范围边界。
4. 在可用环境中运行专项和完整测试；环境不一致时明确其证据等级。
5. 有问题时，给出聚焦 Codex 修复任务；Codex 修复后覆盖生成完整补丁并重新上传。
6. 无阻断问题时，明确批准进入 Mac 最终验收。

### 阶段 6：Mac 最终验收、Commit 和 Push

用户在 Mac 执行：

```bash
git diff --check
git status --short
conda run --no-capture-output \
  -n fura-mappo-mac \
  bash scripts/verify_cpu.sh
```

通过后：

```bash
git add <明确文件>
git diff --cached
git commit -m "<原子提交说明>"
git push origin main
```

禁止 force push。提交前必须确认暂存区没有补丁文件、日志、缓存、数据或模型。

### 阶段 7：A100 服务器验收

```bash
cd ~/fura-mappo
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate fura-mappo
git pull --ff-only origin main
python -m pip install -e ".[dev]"
bash scripts/verify_cpu.sh
```

再运行工作包专项验收。服务器失败时不得直接改源码；把脱敏日志返回 Mac，由 Codex 追加修复，重新审查、Commit 和 Push。

GitHub Actions 是被动附加检查，不是服务器开始验收的前置条件。最终稳定状态应记录其实际结果。

### 阶段 8：状态更新

服务器通过后更新：

- `docs/PROJECT_STATE.md`；
- `docs/SESSION_HANDOFF.md`；
- `docs/DECISIONS.md`，如形成新决策；
- 工作包变更记录或审查记录；
- 实际 Commit 和测试结果。

稳定标签可由用户在阶段完成后创建，但除工作包另有规定外不是必需步骤。

## 4. 失败处理和历史保护

- 已推送 `main` 禁止 force push、reset 或历史重写；
- 使用追加修复 Commit 或 `git revert`；
- 服务器不修改源码；
- 不删除或放宽测试；
- 审查补丁必须每次覆盖完整候选状态，不只提交局部修复 Diff；
- 不把容器复测写成 Mac 或服务器验收；
- 日志不得包含 Token、SSH 配置、完整主机名、私有路径或其他敏感信息。
