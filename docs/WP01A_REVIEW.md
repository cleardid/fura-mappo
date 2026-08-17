# WP-01A 补丁独立审查与最终验收记录

更新日期：2026-08-17

## 1. 审查对象

- 远程基线 Commit：`62675e43d17726adde3696f7fd5e5ab4208b6a2a`
- 最终补丁：`wp01a-review.patch`
- 补丁 SHA-256：`97fe150926f746708b662126233553621595e1e234151fe40b98fa1ec4600195`
- Diff 段：9 个代码与测试文件
- 最终实现 Commit：`b7b48bb394bd4613652b4d1ff4158cb8503f52a5`

## 2. 审查范围

重点检查：

- `DemandEvent`、`DemandStep`、`DemandTrace` 校验；
- `DemandProcess` 的 RNG、时间步和 event ID 状态机；
- `reset`、`step`、`generate` 语义；
- `StationaryPoissonDemand` 的计数、位置和属性采样；
- 防御性复制与只读数组；
- 工厂严格字段和输入不变性；
- NumPy 全局随机状态隔离；
- 长序列 Poisson 统计检验；
- 测试是否可能与实现共享错误假设。

## 3. 第一轮发现与修复

第一轮独立审查发现：

1. 混合数值数组中的 `bool` 会在 `np.asarray` 后被静默转换；
2. 属性范围错误接受 set、generator 和其他一次性 Iterator。

修复后：

- 在普通数值 dtype 转换前检查 Python `bool` 和 `numpy.bool_`；
- 范围只接受有序、可重复读取的非字符串 `Sequence`；
- 拒绝 set、frozenset、Mapping、generator 和 Iterator；
- 拒绝 generator 时不消费其内容；
- 新增对应回归测试。

## 4. 独立复测

```text
专项测试：164 passed
补入远程基线测试后的隔离完整测试：166 passed
git apply --check：通过
git diff --check：通过
```

统计测试：

```text
seed：314159
num_steps：20,000
理论强度：[0.2, 0.8, 2.0]
经验均值：[0.19765, 0.78630, 1.99605]
八个标准误容差：[0.02529822, 0.05059644, 0.08000000]
```

所有区域通过。零强度区域使用精确零断言。

独立审查环境使用 Python 3.13，未作为正式项目环境，只提供额外证据。

## 5. 最终交付验证

- 实现 Commit 已推送到 `main`；
- GitHub Actions `CPU checks` run #3：成功；
- A100 服务器 CPU 与 WP-01A 专项验收：用户确认全部通过；
- 稳定标签：`wp01a-stable` → `b7b48bb394bd4613652b4d1ff4158cb8503f52a5`；
- 服务器没有直接修改源码；
- 未发现新的阻断性缺陷。

本记录不虚构未提供的逐行 A100 日志或具体测试数量。正式通过结论以用户返回的服务器验收结果和 GitHub Actions 状态为依据。

## 6. 结论

WP-01A 已完成并形成稳定实现基线。以下内容在 WP-01B 中视为冻结：

- 数据模型字段和一致性约束；
- 实例独立 RNG；
- `reset`、`step`、`generate` 状态语义；
- event ID 连续分配；
- 工厂输入不变性和严格配置原则；
- 输出数组防御性复制和只读语义。

下一步仅启动 WP-01B 只读设计分析。
