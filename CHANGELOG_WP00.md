# WP-00 变更记录

状态：已完成。

- 稳定标签：`wp00-stable`
- 稳定 Commit：`427b231f73f3194ab9420130744e9ee075998c68`
- 后续 OPS-01 验收 Commit：`62675e43d17726adde3696f7fd5e5ab4208b6a2a`

## 新增

- Python 项目骨架与可编辑安装配置；
- Python 3.11 基础 Conda 环境；
- 服务器软硬件只读审计脚本；
- 最小运行时元数据采集工具；
- Python 和 NumPy 全局随机种子工具；
- Pytest 单元测试；
- Ruff 静态检查；
- GitHub Actions CPU 检查；
- 项目状态、决策和跨会话交接文档。

## 验收结果

WP-00 已完成 Mac、GitHub 和 A100 服务器基础验收。OPS-01 随后补充 main-only 协作规范和统一 CPU 验收脚本。当前事实以 `docs/PROJECT_STATE.md` 为准。

## 明确未包含

- PyTorch 和 CUDA 安装；
- 多智能体环境；
- 需求生成器；
- MAPPO；
- 训练和评估代码。

本文件保留 WP-00 历史范围，不用于描述当前 WP-01A 进度。
