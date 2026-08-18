# 统计分析计划

状态：研究设计草案。WP-01 已完成；WP-02 将冻结控制环境指标和 Oracle 门槛比较。

## 第一科学门槛

```text
Reactive baseline
vs
True-future Oracle
```

要求：

- 使用相同 DemandTrace/artifact 配对
- 仅信息集不同
- 资源、移动、服务规则相同
- Oracle horizon 预先冻结
- 同时报告服务质量和资源成本组成项
- 若 Oracle 无稳定优势，暂停预测/MAPPO 主线并检查问题设定

## 候选环境指标

- served / unserved
- service rate
- deadline miss rate
- waiting / response time
- completions
- utilization / idle
- travel / relocation
- capacity shortfall
- 综合成本
- 相对 Reactive 改善
- 相对 Oracle gap

不得只报告单一 reward。

## 随机性与比较

- 方法间使用相同需求 artifact
- 控制器随机性与需求 RNG 分离
- train/validation/ID/OOD 集合分离
- 不因结果删除 seed
- 异常排除规则预先定义

## WP-01C 验收

- Mac 421 tests
- A100 421 tests
- GitHub Actions run #7 success
- config/hash/artifact/security/summary/CLI 机制测试全部通过

## WP-02 必须定义

- 指标分母与边界行为
- episode 结束未完成任务的计分
- deadline miss 与 unserved 是否重复
- 移动成本与服务收益分开报告
- Oracle horizon 和动作约束
- Reactive/Oracle 配对单位
- H1 小规模机制测试和方差估计
