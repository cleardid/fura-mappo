# WP-01A 实现、审查与验收手册

## 1. 当前基线

```text
分支：main
origin/main：62675e43d17726adde3696f7fd5e5ab4208b6a2a
初始稳定标签：wp00-stable
标签 Commit：427b231f73f3194ab9420130744e9ee075998c68
```

OPS-01 已在基线 Commit 完成 CPU 验收。WP-01A 候选代码已经独立审查，但尚未 Commit、Push 或在 A100 服务器验收。

## 2. 唯一目标

实现外生需求核心数据结构、统一需求过程状态接口和逐区域平稳 Poisson 需求过程，不提前实现 WP-01B、WP-01C、环境、预测或强化学习功能。

## 3. 候选代码文件

```text
src/fura_mappo/utils/seeding.py
src/fura_mappo/demand/__init__.py
src/fura_mappo/demand/models.py
src/fura_mappo/demand/processes.py
src/fura_mappo/demand/factory.py

tests/test_seeding.py
tests/test_demand_models.py
tests/test_stationary_demand.py
tests/test_demand_factory.py
```

WP-01 总体需求规范见 `docs/WP01_DEMAND_GENERATION.md`；WP-01A 冻结接口见 `docs/WP01A_SPEC.md`。

## 4. 固定审查流程

1. Codex 在 Mac 本地 `main` 修改和测试，不执行 Git 写操作；
2. Codex 将完整 patch 写到 Desktop 或 Downloads；
3. 用户上传 patch；
4. ChatGPT 核对 `origin/main` 精确 Commit，在隔离副本应用 patch，执行独立审查和可运行测试；
5. 有问题时由 ChatGPT 给出有限范围修复任务，Codex 修复后覆盖生成 patch；
6. 无阻断问题后，用户把文档更新合入本地工作树并执行最终 Mac 验收；
7. 用户手工 Commit 和 Push；
8. A100 服务器只从 GitHub 同步并验收。

审查文件不得写入 `/tmp`。规范路径：

```text
$HOME/Downloads/wp01a-review.patch
```

或：

```text
$HOME/Desktop/wp01a-review.patch
```

patch 必须包含已跟踪修改和未跟踪新增文件。

## 5. 已完成的独立审查

截至 2026-08-17：

- patch 包含 9 个代码/测试 Diff 段；
- 已核查 RNG、状态管理、数据一致性、数组隔离、工厂和统计测试；
- 早期发现的混合布尔数组与一次性范围迭代器问题已修复；
- 隔离审查环境专项测试：`164 passed`；
- 补入远程基线原有两项测试后的完整测试：`166 passed`；
- `git diff --check`：通过；
- Poisson 测试参数：seed `314159`、20,000 步、强度 `[0.2, 0.8, 2.0]`；
- 经验均值：`[0.19765, 0.78630, 1.99605]`；
- 八个标准误容差：`[0.02529822, 0.05059644, 0.08000000]`；
- 未发现新的阻断性缺陷。

独立审查环境使用 Python 3.13，且未安装 Ruff；测试结果只作为补充证据。最终 Mac Python 3.11 `scripts/verify_cpu.sh` 仍是提交前必需检查。

## 6. 合入文档包后检查工作树

在仓库根目录执行：

```bash
git status --short
git diff --check
git diff --stat
git diff
```

确认只出现 WP-01A 代码、测试和本次文档更新。不得出现 patch、缓存、日志、模型或大型生成文件。

## 7. Mac 最终验收

```bash
conda run --no-capture-output \
  -n fura-mappo-mac \
  python -m pytest -q \
  tests/test_seeding.py \
  tests/test_demand_models.py \
  tests/test_stationary_demand.py \
  tests/test_demand_factory.py
```

然后执行完整 CPU 验收：

```bash
conda run --no-capture-output \
  -n fura-mappo-mac \
  bash scripts/verify_cpu.sh
```

最后再次执行：

```bash
git diff --check
git status --short
git diff --stat
```

必须记录 Python 版本、专项测试数量、完整测试数量、Ruff 结果和任何警告。不得根据预期推测结果。

## 8. 提交与推送

仅在独立审查和 Mac 最终验收均通过后，由用户手工暂存明确文件。可先检查：

```bash
git add -n \
  .github/ISSUE_TEMPLATE/work-package.md \
  AGENTS.md README.md README_zh.md SECURITY.md \
  CHANGELOG_WP00.md CHANGELOG_WP01A.md \
  configs/README.md docs/*.md \
  src/fura_mappo/utils/seeding.py \
  src/fura_mappo/demand/__init__.py \
  src/fura_mappo/demand/models.py \
  src/fura_mappo/demand/processes.py \
  src/fura_mappo/demand/factory.py \
  tests/test_seeding.py \
  tests/test_demand_models.py \
  tests/test_stationary_demand.py \
  tests/test_demand_factory.py
```

确认后去掉 `-n` 执行暂存，再检查：

```bash
git diff --cached --check
git diff --cached --stat
git diff --cached
```

建议 Commit：

```bash
git commit -m "feat: add WP-01A stationary demand core"
git push origin main
```

禁止 force push。GitHub Actions 是被动附加检查，不是服务器验收前置条件。

## 9. A100 服务器验收

```bash
cd ~/fura-mappo
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate fura-mappo

git pull --ff-only origin main
python -m pip install -e ".[dev]"
bash scripts/verify_cpu.sh
```

专项测试：

```bash
python -m pytest -q \
  tests/test_seeding.py \
  tests/test_demand_models.py \
  tests/test_stationary_demand.py \
  tests/test_demand_factory.py
```

服务器不得直接修改源码。若失败，返回以下脱敏信息：

```text
Commit：
Python：
pip check：
Ruff：
Pytest：
失败测试：
完整异常摘要：
git status --short：
```

修复必须回到 Mac，由 Codex 产生追加修改；已推送错误使用追加修复 Commit 或 `git revert`，不得重写历史。

## 10. 完成标准

- [ ] 文档更新已合入工作树；
- [ ] Mac 专项测试通过；
- [ ] Mac `scripts/verify_cpu.sh` 通过；
- [ ] `git diff --cached --check` 通过；
- [ ] 用户完成 Commit 和 Push；
- [ ] A100 `git pull --ff-only` 成功；
- [ ] A100 专项测试和完整 CPU 验收通过；
- [ ] GitHub Actions 结果已记录；
- [ ] `PROJECT_STATE.md` 和 `SESSION_HANDOFF.md` 更新为实际稳定 Commit；
- [ ] WP-01A 才能标记为正式完成并开始 WP-01B。
