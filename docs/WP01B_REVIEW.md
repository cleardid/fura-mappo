# WP-01B 独立审查与验收记录

## 1. 结论

**WP-01B 已通过独立补丁审查、Mac 验收、GitHub Actions 和 A100 服务器验收。**

稳定实现：

```text
Commit：d67f71b5d75ee47adb120686914d32572ea7d6d1
标签：wp01b-stable
```

## 2. 审查输入

```text
基线 Commit：6558da920e10c61497fb34ba2fa5f22f9dd162f3
补丁：wp01b-review.patch
补丁 SHA-256：04f2e705d05deafbb3d14bfd9e031dd58ddb7f98c57bb456a45dde39ac713449
Diff 段数：9
行数：2,628
字节数：105,717
```

补丁只涉及批准的 demand 源码和测试文件。

## 3. Mac 正式结果

```text
专项测试：214 passed
完整测试：293 passed
Ruff：通过
Ruff format：通过
git diff --check：通过
Python：3.11.15
```

## 4. 独立复测

独立环境使用 Python 3.13.5、NumPy 2.3.5 和 Pytest 9.0.2，只作为跨版本补充证据：

```text
专项测试：214 passed
完整测试：293 passed
compileall：通过
Python 3.10 grammar 解析：通过
```

额外检查：

- 150/150 Stationary 随机配置与 WP-01A 原实现轨迹完全一致；
- 100,000 组热点反射输入与独立参考一致；
- 1,000 组 Drifting 随机配置满足有限性、非负性和总增量守恒；
- 三状态 Markov 长期占用率与理论稳定分布一致；
- duration>1 的多组 Burst 长期活动率符合 `p*d/(1-p+p*d)`；
- Poisson 安全边界、配置不变性、RNG 隔离和退化配置随机消耗检查通过。

## 5. 代码审查结论

通过的关键点：

- reset 候选 Generator 和隐状态重建具有公共状态失败原子性；
- 内部 `_PoissonDemandProcess` 未扩大公共 API；
- Stationary 随机序列兼容；
- Drifting 的 log-space 核和反射数值稳定；
- Markov 当前状态先发射、确定性行不消费 RNG；
- Burst 启动步、持续时间和非重叠语义无 off-by-one；
- 四类型严格 schema 和防御性复制正确；
- 未夹带 WP-01C、环境、预测或 RL 功能。

## 6. 非阻断观察

1. 工厂在前三种类型分支后直接返回 Burst；当前四类型 schema 下正确，WP-01C 可改为显式 burst 分支和不可达保护。
2. Drifting 的 `_reflection_periods` 主要用于构造期安全验证，运行期未直接读取；不影响正确性。

## 7. GitHub 与服务器

- GitHub `main`：`d67f71b5d75ee47adb120686914d32572ea7d6d1`；
- GitHub Actions `CPU checks` run #5：成功；
- A100 返回：Commit 匹配、Python 3.11.15、Conda 环境 `fura-mappo`；
- 用户确认服务器端全部测试通过。

服务器摘要未包含逐项测试数量，因此本记录不补造该数量。

## 8. 最终判断

WP-01B 无待处理阻断问题。四类需求过程及其工厂行为成为 WP-01C 的冻结输入基线。
