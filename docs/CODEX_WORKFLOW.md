# Codex main-only 协作与交付流程

## 基本原则

- 项目只使用 `main` 分支，不创建功能分支、额外 worktree 或 Pull Request。
- 一个工作包对应一个或少量紧密相关的原子 Commit。
- Codex 只负责分析、修改和测试文件；Commit、Tag 和 Push 全部由用户手工完成。
- GitHub 是 Mac 和 A100 服务器之间唯一的代码中转来源。
- 训练数据、模型和日志不通过 GitHub 传输。
- 每次新任务开始前，必须记录基线 Commit 和基线稳定标签。

## 标准流程

1. 用户确认本地 `main` 与 `origin/main` 一致，工作树干净，并记录基线 Commit 和稳定标签。
2. Codex 对现有代码和文档进行只读分析，核对工作包的允许范围与禁止范围。
3. Codex 在当前 Mac 主工作目录的 `main` 上修改文件，不执行任何版本管理写操作。
4. 用户检查 `git diff` 和 `git diff --check`，确认修改范围与内容正确。
5. 在 Mac 端项目 Conda 环境中执行工作包规定的快速 CPU 测试。
6. 测试通过后，用户在本地 `main` 创建一个或少量紧密相关的原子 Commit。
7. 用户在待验收 Commit 上创建 candidate 标签，只将该候选标签推送至 GitHub，暂不推送 `main`。
8. A100 服务器从 GitHub 获取 candidate 标签，并以 detached HEAD 检出该标签。
9. 用户在服务器运行工作包规定的验收命令；大型训练、多随机种子实验和 GPU 任务仅在这里由用户启动。
10. 服务器验收通过后，用户从 Mac 推送 `main`。
11. 用户检查 GitHub Actions 的实际运行结果。
12. Mac、服务器和 GitHub Actions 全部通过后，用户为该已验收阶段创建并推送稳定标签。
13. 用户删除本地和远程临时候选标签。
14. 用户将 Mac 和 A100 服务器同步到最新 `main`；服务器保持只读验收用途。

## 失败处理与历史保护

- 禁止 force push，禁止对远程 `main` 使用 `git reset` 或任何历史重写。
- 已推送的 `main` 出现问题时，只能追加修复 Commit 或使用 `git revert`。
- candidate 标签仅标识服务器验收候选，不代表稳定版本。
- 每个已验收的稳定阶段必须有稳定标签，作为可追溯和可回退的基线。
- 服务器验收失败时，不得直接在服务器修改源码；应将命令、错误日志和必要的脱敏环境信息返回 Mac 端，由 Codex 在 Mac 工作目录修复。
- 失败后的修复形成新的本地 Commit 和新的 candidate 标签，再完整执行候选验收流程。
- 服务器日志不得包含或回传 Token、SSH 配置及其他敏感信息。
