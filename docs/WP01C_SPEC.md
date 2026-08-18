# WP-01C 规范：配置、轨迹 Artifact、CLI 与统计汇总

状态：候选实现协议。WP-01C 不改变 WP-01A/WP-01B 的四类需求过程、固定 seed 轨迹、
公共状态语义或数据字段。

## 1. 范围与非目标

本工作包只增加严格 YAML 配置、稳定配置哈希、单文件 NPZ artifact、`generate` /
`summarize` CLI 和 JSON 统计汇总。第一版不实现可视化、Matplotlib、sidecar、pickle、
YAML include/继承、streaming、远程存储、环境、预测、强化学习、PyTorch 或 GPU。

## 2. 需求生成配置 v1

文件后缀必须精确为小写 `.yaml`，顶层字段必须恰好为：

```yaml
schema: fura-mappo.demand-generation
version: 1
demand: {}
generation:
  num_steps: 5
```

`version` 和 `num_steps` 是非 bool 整数，且 `num_steps > 0`。`demand` 直接遵循严格内存
工厂的四种规范 schema：

- `stationary_poisson`：共享字段加 `intensities`；
- `drifting_hotspot`：共享字段加 `base_intensities`、`hotspot_amplitudes`、
  `hotspot_scales`、`initial_hotspot_positions`、`hotspot_velocities`；
- `markov_switching`：共享字段加 `state_intensities`、`transition_matrix`、
  `initial_state`；
- `burst`：共享字段加 `base_intensities`、`burst_probability`、
  `burst_duration_range`、`burst_amplitude_range`、`burst_zone_weights`。

共享字段为 `type`、`seed`、`zone_bounds`、`priority_range`、`service_time_range` 和
`deadline_offset_range`。不提供别名、隐藏默认值或兼容层。

加载器以 `yaml.SafeLoader` 为基础，在构造前扫描 token 和 node，拒绝 anchor、alias、
merge key、重复键、未知/对象标签和非字符串键。文件上限 1 MiB，节点上限 10,000，
嵌套深度上限 64。最终树只允许普通 `dict/list/str`、非 bool `int` 和有限 `float`。

CLI 覆盖优先于文件且只有两项：`--seed` 覆盖 `demand.seed`，`--num-steps` 覆盖
`generation.num_steps`。覆盖作用于深复制，artifact 保存覆盖后的完整配置。

## 3. 配置哈希

`compute_config_hash()` 对完整 resolved config 计算小写 SHA-256。规范化结构为带类型标签
的 mapping、sequence、str、int 和 float；Mapping 键按 Unicode 码点排序。list、tuple
和 NumPy 数组等价，NumPy 标量转为相应标量。整数用十进制字符串，有限浮点先转
float64 再用 `float.hex()`，`-0.0` 规范为 `0.0`。类型标签保证整数、浮点和真实 hex
字符串不碰撞。不做 Unicode normalization。输出路径、Git、时间和运行环境不参与配置哈希。

## 4. NPZ artifact v1

文件为单个小写 `.npz`，不使用 sidecar 或 pickle。逻辑成员精确为：

| 成员 | dtype | 形状 |
|---|---|---|
| `counts` | little-endian int64 | `[num_steps, num_zones]` |
| `intensities` | little-endian float64 | `[num_steps, num_zones]` |
| `event_id` | little-endian int64 | `[num_events]` |
| `arrival_step` | little-endian int64 | `[num_events]` |
| `zone_id` | little-endian int64 | `[num_events]` |
| `positions` | little-endian float64 | `[num_events, 2]` |
| `priority` | little-endian float64 | `[num_events]` |
| `service_time` | little-endian int64 | `[num_events]` |
| `deadline` | little-endian int64 | `[num_events]` |
| `manifest` | uint8 | `[manifest_bytes]` |

零事件时所有事件列形状为 `[0]`，`positions` 为 `[0, 2]`。manifest 是 strict UTF-8
canonical JSON，不使用 object 或 Unicode ndarray。

### 4.1 Manifest

顶层字段精确为 `schema`、`version`、`start_step`、`num_steps`、`num_zones`、
`num_events`、`process_type`、`seed`、`resolved_config`、`config_sha256`、
`git_commit`、`git_dirty`、`package_version`、`created_at_utc`、`runtime`、
`content_hash_algorithm` 和 `content_sha256`。

- schema 为 `fura-mappo.demand-trace`，version 为 1；
- 数量、开始步、过程类型和 seed 与数组及 resolved config 交叉核对；
- `git_commit` 不可用时为 null，`git_dirty` 为 bool 或 null；
- 时间使用 UTC 秒精度 `Z`；
- runtime 只含 Python 版本/实现、系统/版本/架构、NumPy、PyYAML 和 Conda 环境名；
  `runtime.conda_environment` 只保存环境名，prefix 环境会去除 POSIX/Windows 路径，
  不保存 Conda 环境绝对路径；loader 只接受 null 或不含 `/`、`\` 的非空环境名，
  对外部 artifact 中的空字符串或 path-like 值直接拒绝，不自动清洗；
- 不记录 GPU、Python 绝对路径、主机名、IP、SSH、Token 或环境变量列表。

### 4.2 逻辑内容哈希

`content_hash_algorithm` 固定为 `sha256-logical-v1`。算法按固定成员顺序纳入每个数值
成员的长度前缀名称、dtype、shape 和 C-order 原始字节，再纳入删除
`content_sha256` 后的 canonical manifest。所有边界均有明确长度前缀。

该哈希覆盖 provenance，因此同一轨迹在不同创建时间或环境保存时可以得到不同值。它用于
完整性检查，不是数字签名，也不宣称抵御能够重写 manifest 和哈希的恶意重签名。CLI 另行
输出整个 NPZ 文件 SHA-256，该文件哈希不自嵌入 artifact。

## 5. 文件安全与原子写入

保存要求 parent 已存在，默认拒绝已有目标，`overwrite=True`/`--force` 只替换普通文件；
目标为 symlink（包括 dangling symlink）始终拒绝。临时文件位于目标同目录，依次完成
写入、flush、文件 fsync、完整回读校验，再以 `os.link` 无覆盖发布或 `os.replace` 覆盖
发布，最后尝试目录 fsync。成功和失败均清理临时文件。

读取先检查 ZIP；header 门禁通过后，将 `ZipExtFile` 流直接交给
`np.load(..., allow_pickle=False)`，不把完整成员额外复制到 bytes。文件上限 2 GiB，manifest
成员上限 4 MiB，声明总解压大小上限 4 GiB；不使用压缩比阈值。成员名/数量必须精确，
重复、目录、加密和未知压缩方法被拒绝。每个 NPY header 在分配前验证 dtype、维度、shape
和预计字节数。strict JSON 拒绝无效 UTF-8、重复键、NaN/Infinity、未知字段和版本。
成员不会解压到文件系统。

## 6. 统计汇总 v1

`summarize_demand_trace()` 返回 schema `fura-mappo.demand-summary` version 1 的普通 JSON
tree，包括开始步、步数、区域数、事件数；逐区域 counts 的 total/mean/variance/min/max/
zero_fraction；逐步总 counts 的同类统计；逐区域 intensity 的 mean/min/max；以及 priority、
service_time、deadline_offset 的 count/mean/variance/min/max。

方差均为总体方差 `ddof=0`，单样本方差为 0。counts 使用 Python 任意精度整数累计，均值
和方差采用稳定在线算法。零事件时三个事件属性的 count 为 0，其余统计为 null。summary
不包含过程隐状态或 provenance，也不返回逐步数组。

## 7. CLI

入口为 `python -m fura_mappo.demand` 或安装后的 `fura-demand`：

```text
fura-demand generate --config CONFIG.yaml [--seed SEED] [--num-steps N]
  [--output TRACE.npz] [--force] [--allow-dirty]

fura-demand summarize --input TRACE.npz [--output SUMMARY.json] [--force]
```

generate 默认输出为
`artifacts/demand/<type>-s<seed>-n<num_steps>-<config_hash前12位>.npz`，只有使用该默认
路径时自动创建目录。默认拒绝 dirty Git 工作树，`--allow-dirty` 才放行并记录真实状态；
Git 不可用时警告并记录 null。summarize 无 output 时 stdout 是 summary 本身；有 output 时
使用同目录原子 JSON 写入。所有成功 stdout 是单个严格 JSON。

退出码：0 成功，1 未预期内部错误，2 argparse 用法错误，3 配置/覆盖错误，4 artifact
损坏或版本不兼容，5 目标已存在，6 文件系统/权限错误，7 dirty policy 拒绝。默认 stderr
不含 traceback 或敏感绝对路径；顶层 `--debug` 才显示 traceback。CLI 无交互且不读取策略、
智能体或服务状态。
