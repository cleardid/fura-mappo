# 项目状态

## 项目

- 名称：FURA-MAPPO
- 当前工作包：WP-00 仓库初始化与服务器审计
- 当前状态：待在目标服务器执行
- 最新稳定Commit：待填写

## 已完成

- [x] 建立Python包骨架
- [x] 建立基础Conda环境文件
- [x] 建立服务器只读审计脚本
- [x] 建立随机种子工具和单元测试
- [x] 建立Ruff、Pytest和GitHub Actions
- [x] 建立跨会话交接文件

## 待完成

- [ ] 创建私有GitHub仓库
- [ ] 在服务器克隆仓库
- [ ] 执行服务器审计
- [ ] 创建`fura-mappo` Conda环境
- [ ] 通过服务器烟雾测试
- [ ] 通过GitHub Actions
- [ ] 记录GPU驱动、CUDA、Python和磁盘摘要

## 服务器审计摘要

执行后填写：

```text
OS：
CPU：
内存：
GPU：
NVIDIA驱动：
CUDA Toolkit：
Conda：
Python：
项目分区可用空间：
tmux：
```

## 当前已知风险

1. 尚未确认目标服务器的NVIDIA驱动版本，因此暂不选择PyTorch CUDA发行版。
2. 尚未确认磁盘容量；后续多种子实验可能产生大量检查点和日志。
3. 当前代码仅验证基础工程，不包含研究环境和算法。

## 下一工作包

WP-01：实现可参数化、可复现、可统计验证的非平稳需求生成器。
