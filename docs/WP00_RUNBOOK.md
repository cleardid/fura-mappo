# WP-00 运行手册：仓库初始化与服务器审计

## 1. 本会话边界

本会话只处理：

- GitHub仓库初始化；
- 服务器软硬件审计；
- 基础Conda环境；
- 包导入、随机种子、测试和CI；
- 跨会话状态文件。

本会话不处理：

- PyTorch GPU安装；
- PettingZoo或Gymnasium环境；
- 需求生成器；
- MAPPO；
- 实验训练。

这样做是为了先消除驱动、磁盘、Python版本和工程复现方面的风险。

## 2. 本地端操作

### 2.1 创建私有仓库

仓库建议命名为：

```text
fura-mappo
```

保持私有，至少到代码、数据和论文公开策略确定之后。

### 2.2 上传初始代码

在解压目录执行：

```bash
git init
git add .
git commit -m "chore: initialize WP-00 project skeleton"
git branch -M main
git remote add origin <仓库地址>
git push -u origin main
```

确认 GitHub 的 `Actions` 页面中 `CPU checks` 通过。

## 3. 服务器端操作

### 3.1 克隆

```bash
cd ~
git clone <仓库地址>
cd fura-mappo
```

私有仓库建议使用 SSH deploy key 或个人 SSH key。不要把私钥复制到仓库。

### 3.2 只读审计

```bash
bash scripts/collect_system_info.sh
sed -n '1,260p' artifacts/system_audit/system_info.txt
```

重点检查：

- CPU逻辑核数是否约为80；
-内存是否约为512GB；
- 两块GPU是否均为A100 80GB；
- NVIDIA驱动版本；
- `nvcc`是否存在及其版本；
- 用户目录和项目目录的剩余磁盘空间；
- Conda是否能够在非交互SSH shell中使用；
- Python版本；
- `tmux`是否存在。

`nvcc`不存在并不表示PyTorch不能使用GPU。PyTorch二进制包通常携带所需CUDA运行时；最终安装方案以驱动兼容性和项目测试为准。

### 3.3 创建WP-00环境

```bash
bash scripts/bootstrap_conda_env.sh
conda activate fura-mappo
python -m pip install -e ".[dev]"
```

如果非交互shell无法识别`conda activate`，可先执行：

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate fura-mappo
```

### 3.4 验收

```bash
bash scripts/smoke_test.sh 2>&1 | tee artifacts/wp00_smoke_test.log
```

预期结果：

- Ruff无错误；
- 6个测试通过；
- 生成`artifacts/runtime_info.json`；
- 终端输出“WP-00 基础烟雾测试通过”。

## 4. Git提交策略

建议分为两个Commit：

```text
chore: initialize WP-00 project skeleton
docs: record server audit and WP-00 handoff
```

默认不要提交`artifacts/`中的审计原始文件。建议把经人工脱敏后的关键结论写入`docs/PROJECT_STATE.md`。如确需保存原始审计信息，只能在私有仓库中单独确认后使用强制添加：

```bash
git add -f artifacts/system_audit/system_info.txt
```

通常没有必要这么做。

## 5. 交回下一会话的信息

请保存以下信息：

```text
仓库URL：
当前Commit：
GitHub Actions状态：
服务器审计摘要：
pytest结果：
ruff结果：
磁盘可用空间：
NVIDIA驱动版本：
Conda/Python版本：
已知异常：
```

并更新：

- `docs/PROJECT_STATE.md`
- `docs/SESSION_HANDOFF.md`

完成后，下一会话进入WP-01：非平稳需求生成器。
