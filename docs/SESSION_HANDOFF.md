# 会话交接

更新日期：2026-08-17

## 当前任务

完成 WP-01A 的最后交付阶段：合并文档、Mac Python 3.11 验收、用户提交和推送、A100 服务器验收。

不得开始 WP-01B。

## 远程基线

```text
仓库：https://github.com/cleardid/fura-mappo
分支：main
远程 Commit：62675e43d17726adde3696f7fd5e5ab4208b6a2a
稳定标签：wp00-stable
稳定标签 Commit：427b231f73f3194ab9420130744e9ee075998c68
```

## WP-01A 审查状态

最新完整补丁：

```text
wp01a-review.patch
SHA-256: 97fe150926f746708b662126233553621595e1e234151fe40b98fa1ec4600195
```

独立审查已经完成：

- 9 个预期 Diff 文件齐全；
- 修复混合 bool 静默转换；
- 修复 set/generator 范围输入；
- generator 被拒绝后不消费；
- 专项测试 164 passed；
- 重建完整基线测试 166 passed；
- 额外多种子、状态、边界和配置不变性检查通过；
- 无新的阻断性缺陷。

独立复测使用 Python 3.13，只能作为补充证据。正式验收必须使用 Mac 和服务器的 Python 3.11。

## 下一步操作

### 1. 合并文档包

把文档压缩包中的文件按原有相对路径覆盖或新增到 Mac 仓库。不要提交压缩包本身。

### 2. Mac 验收

```bash
cd /Users/tianjia/Code/Python/fura-mappo-wp00

git diff --check
git status --short

conda run --no-capture-output \
  -n fura-mappo-mac \
  python -m pytest -q \
  tests/test_seeding.py \
  tests/test_demand_models.py \
  tests/test_stationary_demand.py \
  tests/test_demand_factory.py

conda run --no-capture-output \
  -n fura-mappo-mac \
  bash scripts/verify_cpu.sh
```

预期专项测试：164 passed。预期完整 Pytest：166 passed。实际结果必须以终端输出为准。

### 3. 人工检查和提交

确认没有补丁、ZIP、缓存、日志或大型产物进入暂存区。然后明确添加代码、测试和文档文件，检查：

```bash
git diff --cached
git diff --cached --check
```

建议提交说明：

```text
feat: add WP-01A stationary demand core
```

用户手工执行：

```bash
git commit -m "feat: add WP-01A stationary demand core"
git push origin main
```

Codex 不得执行上述命令。

### 4. A100 服务器验收

```bash
cd ~/fura-mappo
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate fura-mappo
git pull --ff-only origin main
python -m pip install -e ".[dev]"
bash scripts/verify_cpu.sh
python -m pytest -q \
  tests/test_seeding.py \
  tests/test_demand_models.py \
  tests/test_stationary_demand.py \
  tests/test_demand_factory.py
```

服务器失败时不修改源码，返回完整命令、退出码和脱敏日志到 Mac 修复。

## 验收后必须补录

- WP-01A 实际 Commit；
- Mac Python、专项测试和完整验收结果；
- 服务器 Python、专项测试和完整验收结果；
- GitHub Actions 结果；
- 是否创建稳定标签；
- `docs/PROJECT_STATE.md` 和本文件的最终状态。

## 下一会话开场信息

```text
项目：FURA-MAPPO
远程 main Commit：<WP-01A 实际 SHA>
Mac 验收：<实际结果>
A100 服务器验收：<实际结果>
GitHub Actions：<实际结果>
当前目标：完成 WP-01A 状态收尾；通过后再设计 WP-01B。
```
