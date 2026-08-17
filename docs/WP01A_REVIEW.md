# WP-01A 补丁独立审查记录

## 1. 审查对象

- 远程基线 Commit：`62675e43d17726adde3696f7fd5e5ab4208b6a2a`
- 补丁文件：`wp01a-review.patch`
- 补丁 SHA-256：`97fe150926f746708b662126233553621595e1e234151fe40b98fa1ec4600195`
- 补丁规模：9 个 Diff 段，1588 行，59167 字节
- 审查日期：2026-08-17

涉及文件：

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

## 2. 前一轮审查问题及修复

前一轮发现两个输入校验问题组：

1. bool 与普通数值混合后可能被 `np.asarray` 静默转换；
2. 属性范围可能接受无序 set 或消耗一次性 generator。

最新补丁已修复：

- 在普通数值 dtype 转换前递归识别 Python `bool` 和 `numpy.bool_`；
- Step、Trace、intensities 和 zone bounds 的混合 bool 均被明确拒绝；
- 范围只接受非字符串、非 Mapping 的 `Sequence`；
- set、frozenset 和 generator 被拒绝；
- generator 被拒绝后保持未消费；
- list 和 tuple 继续可用。

## 3. 独立检查结果

在隔离审查副本中执行：

- 补丁完整性：9 个预期文件全部存在；
- `git apply --check`：通过；
- `git diff --check`：通过；
- WP-01A 专项测试：`164 passed`；
- 补入远程基线原有 `test_import.py` 和 `test_system_info.py` 后：`166 passed`；
- Python 字节码编译：通过；
- 额外多种子、重放、实例隔离、半开坐标、事件连续编号、配置不变性、混合 bool、generator 不消费和全局随机状态检查：通过。

审查环境使用 Python 3.13，超出仓库声明的 `<3.13` 支持范围，因此这些结果只作为独立行为审查证据，不能替代 Mac 和服务器的 Python 3.11 正式验收。

## 4. 代码审查结论

未发现新的阻断性缺陷。以下设计符合 WP-01A 约束：

- 外生需求与策略完全解耦；
- 实例私有 `numpy.random.Generator`；
- `reset`、`step` 和 `generate` 语义明确；
- event ID 由基类验证连续分配；
- 输入数组和输出数组不与内部状态共享可变内存；
- Step 和 Trace 对事件计数进行区域及时间一致性验证；
- 工厂不修改调用方配置；
- Poisson 均值统计测试使用固定 seed 和八个标准误；
- 未引入 WP-01B、WP-01C、PyTorch、GPU、环境或强化学习内容。

## 5. 审查决定

状态：**通过代码审查，可进入 Mac Python 3.11 最终验收。**

这不等于 WP-01A 已完成。以下门槛仍未完成：

1. 在 `fura-mappo-mac` 环境运行最新补丁的专项测试和 `scripts/verify_cpu.sh`；
2. 用户人工检查完整 Diff 和状态；
3. 用户手工 Commit 并 Push 到 `origin/main`；
4. A100 服务器 `git pull --ff-only` 后执行 CPU 验收；
5. 记录实际 Commit、服务器结果和 GitHub Actions 状态。

## 6. 正式验收预期

最新补丁新增专项测试总数为 164；加上远程基线原有两项测试，完整 Pytest 预期为 166。若 Mac 或服务器结果不同，应先检查工作树、安装状态、Python 版本和补丁完整性，不得直接修改预期数字或放宽测试。
