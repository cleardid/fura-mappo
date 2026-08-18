# 会话交接

更新日期：2026-08-18

## 当前任务

WP-02：资源服务环境与反应式/Oracle 控制基线。

当前阶段严格为只读设计分析。

## 稳定基线

```text
WP-01C 实现：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
标签：wp01c-stable
```

当前 docs-only HEAD 必须由下一会话真实读取，不预设 SHA。

## WP-01C 完成结论

- YAML/config hash/NPZ artifact/CLI/summary 已实现并冻结
- Mac 421 passed
- GitHub Actions run #7 success
- A100 421 passed
- WP-01 接口和文件协议视为冻结

## WP-02 只读分析必须解决

1. DemandStep/DemandTrace 如何进入环境
2. 时间步内 arrival/observe/action/move/service/complete/deadline/metric 顺序
3. 资源数量、容量、位置和可用性
4. 连续二维 vs zone-level 位置抽象
5. 移动速度/耗时/成本
6. service_time、并发和完成规则
7. queue、deadline miss、丢弃
8. 冲突和 tie-breaking
9. episode/reset
10. observation/action，但不实现 RL
11. 组成指标，不冻结最终 reward
12. Reactive baseline
13. Oracle horizon 与信息边界
14. 配对 DemandTrace/artifact
15. H1 门槛实验
16. WP-02 子工作包拆分

## 非目标

预测器、不确定性模型、MAPPO、PyTorch/GPU、正式 ID/OOD 主实验、最终 reward、大规模优化器、多进程。
