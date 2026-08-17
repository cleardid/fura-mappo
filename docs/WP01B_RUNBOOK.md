# WP-01B 运行手册：三类非平稳需求

状态：历史验收手册。WP-01B 已完成；当前事实以 `docs/PROJECT_STATE.md` 为准。

## 1. 工作包边界

WP-01B 只实现：

- Drifting Hotspot；
- Markov Switching；
- Burst Demand；
- 四类型内存工厂扩展；
- 必要的内部 Poisson 复用和 reset 隐状态钩子；
- 单元、边界、状态、随机和统计测试。

不实现文件配置、序列化、CLI、可视化、环境、预测或强化学习。

## 2. 基线

```text
远程基线：6558da920e10c61497fb34ba2fa5f22f9dd162f3
前序稳定标签：wp01a-stable
前序实现：b7b48bb394bd4613652b4d1ff4158cb8503f52a5
```

## 3. 实现文件

修改：

```text
src/fura_mappo/demand/__init__.py
src/fura_mappo/demand/factory.py
src/fura_mappo/demand/processes.py
tests/test_demand_factory.py
tests/test_stationary_demand.py
```

新增：

```text
src/fura_mappo/demand/nonstationary.py
tests/test_drifting_hotspot.py
tests/test_markov_switching.py
tests/test_burst_demand.py
```

## 4. Mac 验收

聚焦命令覆盖 Stationary、三类非平稳过程和工厂，结果：

```text
214 passed
```

完整命令：

```bash
conda run --no-capture-output   -n fura-mappo-mac   bash scripts/verify_cpu.sh
```

结果：

```text
Python 3.11.15
Ruff：通过
格式检查：通过
Pytest：293 passed
CPU 验收：通过
```

## 5. 完整补丁审查

```text
补丁路径：$HOME/Downloads/wp01b-review.patch
SHA-256：04f2e705d05deafbb3d14bfd9e031dd58ddb7f98c57bb456a45dde39ac713449
Diff 段数：9
```

用户上传补丁和实现报告后，独立环境执行应用检查、源码审查、专项/完整测试和额外科学检查。结论：通过。

## 6. 发布

一键发布脚本重新运行 Mac 验收并精确核对批准补丁 SHA。用户输入 `PUBLISH` 后创建：

```text
Commit：d67f71b5d75ee47adb120686914d32572ea7d6d1
说明：feat: add WP-01B nonstationary demand processes
```

禁止 force push。

## 7. GitHub Actions

```text
工作流：CPU checks
Run：#5
Commit：d67f71b5d75ee47adb120686914d32572ea7d6d1
结论：success
```

## 8. A100 验收

服务器一键脚本绑定完整 Commit SHA，执行 fast-forward 同步、可编辑安装和 `scripts/verify_cpu.sh`。

返回摘要：

```text
Commit：d67f71b5d75ee47adb120686914d32572ea7d6d1
Python：Python 3.11.15
Conda 环境：fura-mappo
```

用户确认全部测试通过。服务器不直接修改源码。

## 9. 稳定收尾

稳定标签：

```text
wp01b-stable → d67f71b5d75ee47adb120686914d32572ea7d6d1
```

文档收尾 Commit 只记录状态，不改变稳定实现标签目标。

## 10. 失败处理

- 标签已存在但目标不符：停止，不覆盖；
- 本地/远程 Commit 不一致：停止，先人工核对；
- 工作树不干净：停止，不自动 clean/reset；
- Mac 或服务器测试失败：返回日志，在 Mac 追加修复并重新生成完整补丁；
- 已推送错误：追加修复 Commit 或 `git revert`，禁止历史重写。
