# WP-01A 实现、审查与验收手册

状态：**已完成，转为历史运行手册。**

- 实现 Commit：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`
- 稳定标签：`wp01a-stable`
- GitHub Actions：`CPU checks` run #3 成功
- A100 验收：用户确认全部通过

本文件保留 WP-01A 的实际流程和复验方法。除勘误外不再按候选状态更新。

## 1. 完成范围

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

详细科学与接口规范见 `docs/WP01A_SPEC.md` 和 `docs/WP01_DEMAND_GENERATION.md`。

## 2. 实际审查流程

1. Codex 在 Mac 本地 `main` 修改和测试，不执行 Git 写操作；
2. Codex 在 Downloads 生成覆盖 tracked 与 untracked 文件的完整 patch；
3. 用户上传 patch；
4. ChatGPT 在精确远程基线上独立应用、审查并复测；
5. 第一轮发现混合 bool 与一次性范围迭代器问题；
6. Codex 局部修复并重新生成完整 patch；
7. 独立复审通过；
8. 用户手工 Commit、Push；
9. GitHub Actions 和 A100 正式验收通过；
10. 形成稳定实现基线。

审查文件使用 Desktop 或 Downloads，不使用 `/tmp`。

## 3. 独立审查证据

```text
Patch SHA-256：97fe150926f746708b662126233553621595e1e234151fe40b98fa1ec4600195
专项测试：164 passed
隔离完整测试：166 passed
git apply --check：通过
git diff --check：通过
```

Poisson 检验：固定 seed `314159`、20,000 步、强度 `[0.2, 0.8, 2.0]`，逐区域使用八个标准误容差。

## 4. 正式验收结果

- `main` 实现 Commit：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`；
- GitHub Actions：成功；
- A100 `git pull --ff-only` 后 CPU 验收：通过；
- A100 WP-01A 专项验收：通过；
- 服务器源码未直接修改。

逐行 A100 输出未写入本文件；仓库只记录通过结论，避免提交大型日志或环境敏感信息。

## 5. 复验命令

Mac：

```bash
conda run --no-capture-output   -n fura-mappo-mac   python -m pytest -q   tests/test_seeding.py   tests/test_demand_models.py   tests/test_stationary_demand.py   tests/test_demand_factory.py
```

```bash
conda run --no-capture-output   -n fura-mappo-mac   bash scripts/verify_cpu.sh
```

A100：

```bash
cd ~/fura-mappo
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate fura-mappo
git pull --ff-only origin main
python -m pip install -e ".[dev]"
bash scripts/verify_cpu.sh
python -m pytest -q   tests/test_seeding.py   tests/test_demand_models.py   tests/test_stationary_demand.py   tests/test_demand_factory.py
```

## 6. 完成清单

- [x] 唯一目标已实现；
- [x] 修改范围受控；
- [x] 完整 patch 独立审查通过；
- [x] 实现已由用户手工提交；本记录不补造未提供的最终 Mac 逐项输出；
- [x] 实现 Commit 已推送；
- [x] GitHub Actions 通过；
- [x] A100 CPU 与专项验收通过；
- [x] 稳定实现 Commit 已记录；
- [x] WP-01A 正式关闭；
- [x] 下一阶段限定为 WP-01B 只读设计分析。

## 7. 历史保护

- 不重写已推送历史；
- 后续回归问题使用追加修复 Commit 或 `git revert`；
- 任何 WP-01A 公共接口变更都需要单独决策、兼容性分析和完整审查；
- 不把后续 WP-01B/01C 内容补写成 WP-01A 原始范围。
