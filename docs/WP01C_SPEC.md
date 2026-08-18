# WP-01C 规范：配置、轨迹 Artifact、CLI 与统计汇总

状态：已验收冻结协议。

```text
Commit：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
标签：wp01c-stable
```

## 配置

- schema：`fura-mappo.demand-generation`
- version：1
- 小写 `.yaml`
- strict schema，无别名和隐藏默认
- SafeLoader 基础；拒绝 duplicate key、anchor/alias、merge、对象标签、非字符串 key
- 1 MiB 文件、10,000 nodes、depth 64
- YAML 内容错误在公共加载边界统一为 `ValueError`

## 配置哈希

- 带类型标记 canonical tree
- Mapping key 稳定排序
- int/float/string 类型区分
- finite float64 + `float.hex()`
- SHA-256

## Artifact

- schema：`fura-mappo.demand-trace`
- version：1
- 单文件 `.npz`
- 固定 little-endian int64/float64 成员
- manifest 为 strict UTF-8 JSON uint8
- 不使用 pickle/object array
- config hash + `sha256-logical-v1`
- provenance 不记录主机名、IP、SSH、Token 或绝对 Conda 路径
- loader 拒绝 path-like `conda_environment`

## 安全读取与写入

- ZIP/NPY header 在分配前验证
- 文件 2 GiB、manifest 4 MiB、声明总解压 4 GiB 上限
- `ZipExtFile` 流式传给 `np.load(..., allow_pickle=False)`
- 默认拒绝覆盖
- symlink 始终拒绝
- 临时文件与目标同目录
- `os.link` 无覆盖发布，`os.replace` 覆盖发布
- artifact 内容错误统一为 `ValueError`

## Summary

- schema：`fura-mappo.demand-summary`
- version：1
- counts/intensity/event 属性统计
- 方差 `ddof=0`
- 零事件属性返回 count=0，其余 null

## CLI

```text
fura-demand generate
fura-demand summarize
python -m fura_mappo.demand
```

退出码：

```text
0 success
1 internal
2 argparse
3 config
4 artifact
5 exists
6 filesystem
7 dirty git
```

## 验收

- 最终批准 patch：`bea26147f19ed6db311040ae54a4192e0e82731a0b17c65296e5dfd2c79b917d`
- Mac：421 passed
- GitHub Actions：CPU checks run #7 success
- A100：421 passed
- 稳定标签：`wp01c-stable`

后续工作包不得改变 v1 协议或固定 seed 轨迹，除非显式版本升级。
