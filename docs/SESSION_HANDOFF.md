# 会话交接

更新日期：2026-08-18

## 1. 当前任务

WP-01C：配置、工厂完善、轨迹序列化、CLI、统计汇总和可选可视化。

当前阶段仅为 **只读设计分析**。设计审查通过前不得修改源码、创建实现补丁、Commit 或 Push。

## 2. 稳定基线

```text
仓库：https://github.com/cleardid/fura-mappo
分支：main
WP-01B 实现 Commit：d67f71b5d75ee47adb120686914d32572ea7d6d1
稳定标签：wp01b-stable
标签目标：d67f71b5d75ee47adb120686914d32572ea7d6d1
前序稳定标签：wp01a-stable
```

文档收尾 Commit 以仓库当前 HEAD 为准，不在文档中自引用 SHA。

## 3. WP-01B 完成结论

- 已实现 Drifting Hotspot、Markov Switching 和 Burst Demand；
- 已提取内部共享 Poisson 生成层，Stationary 轨迹保持精确兼容；
- Mac 聚焦测试 `214 passed`，完整验收 `293 passed`；
- 独立补丁审查无阻断问题；
- GitHub Actions `CPU checks` run #5 成功；
- A100 Python 3.11.15、Conda 环境 `fura-mappo` 验收由用户确认全部通过；
- WP-01B 公共行为和工厂 schema 在 WP-01C 中视为冻结。

## 4. WP-01C 唯一范围

只设计和实现：

- 安全、严格、可复现的配置文件与加载；
- 四类型工厂维护性完善；
- `DemandTrace` 及必要配置/元数据的序列化和读取；
- 需求轨迹生成 CLI；
- 统计汇总 CLI 或公共函数；
- 可选、非核心的可视化。

必须继续满足：

- 外生性和实例 RNG 隔离；
- 四类过程科学语义不变；
- 不修改调用方配置；
- 文件格式有 schema/version；
- 输出可重放并记录 seed、过程类型、解析配置和 Commit；
- 默认不静默覆盖已有文件；
- 错误输入和损坏文件给出明确异常或非零退出码；
- CPU-only。

不得实现：

- PettingZoo/Gymnasium、智能体、服务、奖励或环境；
- 预测模型、MAPPO、PyTorch 或 GPU；
- 多进程和性能框架；
- 远程存储、数据库、实验追踪平台；
- ID/OOD 实验调度和正式实验运行。

## 5. WP-01C 只读分析必须读取

```text
AGENTS.md
pyproject.toml
configs/README.md
docs/PROJECT_REQUIREMENTS.md
docs/PROJECT_STATE.md
docs/DECISIONS.md
docs/SESSION_HANDOFF.md
docs/CODEX_WORKFLOW.md
docs/WP01_DEMAND_GENERATION.md
docs/WP01A_SPEC.md
docs/WP01B_SPEC.md
src/fura_mappo/demand/
src/fura_mappo/utils/system_info.py
tests/
scripts/verify_cpu.sh
```

## 6. WP-01C 只读分析必须报告

1. 当前 Commit、分支、工作树和标签；
2. 四类过程与工厂的冻结接口；
3. 配置文件格式、schema 版本、字段映射和安全加载方案；
4. 路径解析、CLI 覆盖、默认值和未知字段策略；
5. 轨迹序列化格式选择及其 dtype、形状、事件、metadata 和兼容性；
6. 原子写入、已有文件、损坏文件和部分写入的处理；
7. CLI 子命令、参数、退出码、stdout/stderr 和输出目录语义；
8. 统计汇总的字段、定义、数值稳定性和零事件行为；
9. 可视化是否实现、依赖放置和无显示环境行为；
10. 复现 manifest：seed、完整解析配置、Git Commit、版本和哈希；
11. 往返、配置安全、CLI 集成和错误路径测试；
12. 推荐文件范围、依赖变化、兼容性风险和需要 ChatGPT 决策的问题。

不得在只读阶段写实现代码、修改文件或创建补丁。

## 7. 固定协作流程

```text
Codex 只读分析
→ ChatGPT 设计审查
→ Codex 聚焦实现和 Mac 测试
→ Codex 在 Downloads/Desktop 生成完整 patch 和报告
→ 用户上传
→ ChatGPT 独立应用、审查和复测
→ 用户运行一键发布脚本并显式确认
→ A100 一键同步验收
→ 稳定标签和状态收尾
```

## 8. 下一会话开场模板

```text
项目：FURA-MAPPO
仓库：https://github.com/cleardid/fura-mappo
当前分支：main
当前 Commit：<git rev-parse HEAD>
稳定标签：wp01b-stable

请先读取：
- AGENTS.md
- docs/PROJECT_STATE.md
- docs/DECISIONS.md
- docs/SESSION_HANDOFF.md
- docs/WP01_DEMAND_GENERATION.md
- docs/WP01B_SPEC.md
- configs/README.md
- src/fura_mappo/demand/
- tests/

本会话目标：仅完成 WP-01C 只读设计分析，不修改文件。
```
