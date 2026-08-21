"""WP-02D1 H1 门槛的冻结协议、配对运行与统计工具。"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import cast

import numpy as np
import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken

from fura_mappo.baselines import (
    ReactiveController,
    RollingTrueFutureOracle,
    build_true_future_view,
)
from fura_mappo.baselines.oracle import _Candidate, _evaluate_pair
from fura_mappo.demand import (
    DemandEvent,
    DemandTrace,
    DemandTraceArtifact,
    compute_config_hash,
    create_demand_process,
    load_demand_trace,
)
from fura_mappo.envs import (
    EnvironmentSnapshot,
    EpisodeMetrics,
    MoveAction,
    ResourceAction,
    ResourceServiceConfig,
    ResourceServiceEnvironment,
    ResourceStatus,
    ServeAction,
    StepResult,
)

_SPEC_SCHEMA = "fura-mappo.wp02d-h1"
_SPEC_VERSION = 1
_INVENTORY_SCHEMA = "fura-mappo.wp02d-artifact-inventory"
_INVENTORY_VERSION = 1
_RESULT_SCHEMA = "fura-mappo.wp02d-paired-trace"
_RESULT_VERSION = 1
_SUMMARY_SCHEMA = "fura-mappo.wp02d-h1-summary"
_SUMMARY_VERSION = 1
_VERDICT_SCHEMA = "fura-mappo.wp02d-primary-verdict"
_VERDICT_VERSION = 1
_MAX_SPEC_BYTES = 1024 * 1024
_MAX_PROTOCOL_JSON_BYTES = 8 * 1024 * 1024
_MAX_YAML_NODES = 10_000
_MAX_YAML_DEPTH = 64
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


def _frozen_config() -> dict[str, object]:
    """返回一份新的 preregistration 常量树，避免隐藏的全局可变状态。"""

    return {
        "schema": _SPEC_SCHEMA,
        "version": _SPEC_VERSION,
        "primary": {
            "demand": {
                "type": "drifting_hotspot",
                "base_intensities": [0.025, 0.025, 0.025, 0.025],
                "hotspot_amplitudes": [0.55],
                "hotspot_scales": [0.45],
                "initial_hotspot_positions": [[0.5, 0.5]],
                "hotspot_velocities": [[0.25, 0.0]],
                "zone_bounds": [
                    [0.0, 1.0, 0.0, 1.0],
                    [1.0, 2.0, 0.0, 1.0],
                    [2.0, 3.0, 0.0, 1.0],
                    [3.0, 4.0, 0.0, 1.0],
                ],
                "priority_range": [0.5, 0.5],
                "service_time_range": [1, 2],
                "deadline_offset_range": [2, 3],
            },
            "generation": {"num_steps": 256},
            "environment": {
                "initial_resource_positions": [[0.5, 0.5], [3.5, 0.5]],
                "movement_speed": 0.75,
            },
            "horizon": 2,
        },
        "seed_protocol": {
            "rule": "consecutive",
            "base_seed": 20_260_819,
            "count": 256,
        },
        "bootstrap": {
            "resamples": 50_000,
            "seed": 90_260_819,
            "generator": "PCG64",
            "method": "percentile",
            "quantile_method": "linear",
        },
        "gate": {
            "delta_min": 0.02,
            "lower_quantile": 0.05,
            "upper_quantile": 0.95,
            "two_sided_quantiles": [0.025, 0.975],
        },
        "provenance": {"wp02c_stable_sha": "9159c841af4f605d6e32cca4b37940f0116a19cf"},
        "sensitivity": {
            "horizons": [0, 1, 2, 3, 4],
            "priority_range": [0.25, 0.75],
        },
    }


class H1ProtocolError(ValueError):
    """表示不能进入科学推断的 WP-02D 协议错误。"""


class H1Verdict(str, Enum):
    """WP-02D H1 的科学结论或协议失败状态。"""

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    PROTOCOL_FAIL = "PROTOCOL_FAIL"


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """规范化非负整数，并明确拒绝 Python/NumPy 布尔值。"""

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} 必须是整数且不能是布尔值")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} 必须是非负整数")
    return normalized


def _normalize_positive_integer(value: object, name: str) -> int:
    """规范化正整数，并明确拒绝布尔值。"""

    normalized = _normalize_nonnegative_integer(value, name)
    if normalized == 0:
        raise ValueError(f"{name} 必须严格大于零")
    return normalized


def _normalize_finite_float(value: object, name: str) -> float:
    """规范化有限实数，并明确拒绝布尔值和复数。"""

    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise TypeError(f"{name} 必须是实数且不能是布尔值")
    try:
        normalized = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} 必须能安全转换为 Python float") from error
    if not math.isfinite(normalized):
        raise ValueError(f"{name} 必须是有限值")
    return normalized


def _copy_plain_tree(value: object, name: str = "H1 配置") -> object:
    """复制 JSON 风格树，并拒绝 bool、非有限数值和不支持类型。"""

    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} 不允许布尔值")
    if isinstance(value, str):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError(f"{name} 不允许 NaN 或无穷值")
        return normalized
    if isinstance(value, Mapping):
        copied: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{name} 的 Mapping 键必须是字符串")
            copied[key] = _copy_plain_tree(item, name)
        return copied
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_copy_plain_tree(item, name) for item in value]
    raise TypeError(f"{name} 包含不支持的值类型")


def _freeze_tree(value: object) -> object:
    """把普通 JSON 树递归冻结为 MappingProxyType 和 tuple。"""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_tree(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_tree(item) for item in value)
    return value


def _plain_tree(value: object) -> object:
    """把冻结 JSON 树递归转换为普通 dict/list。"""

    if isinstance(value, Mapping):
        return {str(key): _plain_tree(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain_tree(item) for item in value]
    return value


def _validate_frozen_value(actual: object, expected: object, path: str = "配置") -> None:
    """逐类型、逐字段验证 preregistration 配置与冻结常量完全一致。"""

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise ValueError(f"{path} 必须是 Mapping")
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing or extra:
            raise ValueError(f"{path} 字段不匹配；missing={missing!r}, extra={extra!r}")
        for key, expected_item in expected.items():
            _validate_frozen_value(actual[key], expected_item, f"{path}.{key}")
        return
    if isinstance(expected, list):
        if not isinstance(actual, list):
            raise ValueError(f"{path} 必须是 Sequence")
        if len(actual) != len(expected):
            raise ValueError(f"{path} 长度必须精确等于 {len(expected)}")
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected, strict=True)):
            _validate_frozen_value(actual_item, expected_item, f"{path}[{index}]")
        return
    if type(actual) is not type(expected) or actual != expected:
        raise ValueError(f"{path} 必须精确等于冻结值 {expected!r}")


class _StrictSafeLoader(yaml.SafeLoader):
    """拒绝重复 Mapping 键的 SafeLoader。"""


def _construct_unique_mapping(
    loader: _StrictSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    """构造无重复键的 Mapping。"""

    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"YAML Mapping 包含重复键 {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _validate_yaml_nodes(root: Node | None) -> None:
    """限制 YAML 节点、标签、深度、数量与 merge key。"""

    if root is None:
        raise ValueError("H1 YAML 配置不能为空")
    allowed_tags = {
        "tag:yaml.org,2002:map",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
    }
    stack: list[tuple[Node, int]] = [(root, 1)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > _MAX_YAML_NODES:
            raise ValueError(f"YAML 节点数不能超过 {_MAX_YAML_NODES}")
        if depth > _MAX_YAML_DEPTH:
            raise ValueError(f"YAML 嵌套深度不能超过 {_MAX_YAML_DEPTH}")
        if node.tag not in allowed_tags:
            raise ValueError("YAML 配置包含不支持或不安全的类型标签")
        if isinstance(node, MappingNode):
            seen: set[str] = set()
            for key_node, value_node in node.value:
                if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                    raise ValueError("YAML Mapping 的键必须是字符串")
                if key_node.value == "<<":
                    raise ValueError("YAML 配置不允许 merge key")
                if key_node.value in seen:
                    raise ValueError(f"YAML Mapping 包含重复键 {key_node.value!r}")
                seen.add(key_node.value)
                stack.extend(((value_node, depth + 1), (key_node, depth + 1)))
        elif isinstance(node, SequenceNode):
            stack.extend((item, depth + 1) for item in node.value)
        elif not isinstance(node, ScalarNode):
            raise ValueError("YAML 配置包含不支持的节点类型")


@dataclass(frozen=True, slots=True)
class H1GateSpec:
    """递归只读的 WP-02D v1 preregistration 配置。"""

    config: Mapping[str, object]
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """验证完整冻结常量并保存稳定配置哈希。"""

        copied = _copy_plain_tree(self.config)
        if not isinstance(copied, dict):
            raise TypeError("config 必须是 Mapping")
        _validate_frozen_value(copied, _frozen_config())
        frozen = _freeze_tree(copied)
        if not isinstance(frozen, Mapping):
            raise RuntimeError("冻结 H1 配置必须保持 Mapping")
        object.__setattr__(self, "config", frozen)
        object.__setattr__(self, "sha256", compute_config_hash(copied))

    @property
    def primary_horizon(self) -> int:
        """返回冻结 primary horizon。"""

        primary = cast(Mapping[str, object], self.config["primary"])
        return cast(int, primary["horizon"])

    @property
    def num_steps(self) -> int:
        """返回冻结轨迹步数。"""

        primary = cast(Mapping[str, object], self.config["primary"])
        generation = cast(Mapping[str, object], primary["generation"])
        return cast(int, generation["num_steps"])

    @property
    def planned_seed_count(self) -> int:
        """返回冻结正式 seed 数。"""

        protocol = cast(Mapping[str, object], self.config["seed_protocol"])
        return cast(int, protocol["count"])

    @property
    def wp02c_stable_sha(self) -> str:
        """返回冻结 WP-02C stable Commit。"""

        provenance = cast(Mapping[str, object], self.config["provenance"])
        return cast(str, provenance["wp02c_stable_sha"])


def load_h1_gate_spec(path: str | os.PathLike[str]) -> H1GateSpec:
    """安全加载并严格验证冻结 WP-02D H1 YAML。"""

    if isinstance(path, bytes):
        raise TypeError("path 不能是 bytes")
    try:
        raw_path = os.fspath(path)
    except TypeError as error:
        raise TypeError("path 必须是 str 或 os.PathLike[str]") from error
    if isinstance(raw_path, bytes):
        raise TypeError("path 不能是 bytes")
    spec_path = Path(raw_path)
    if spec_path.suffix != ".yaml":
        raise ValueError("H1 配置文件后缀必须精确为 .yaml")
    with spec_path.open("rb") as stream:
        payload = stream.read(_MAX_SPEC_BYTES + 1)
    if len(payload) > _MAX_SPEC_BYTES:
        raise ValueError(f"H1 YAML 配置文件不能超过 {_MAX_SPEC_BYTES} 字节")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("H1 YAML 配置必须使用有效 UTF-8") from error
    try:
        for token in yaml.scan(text, Loader=_StrictSafeLoader):
            if isinstance(token, AnchorToken):
                raise ValueError("YAML 配置不允许 anchor")
            if isinstance(token, AliasToken):
                raise ValueError("YAML 配置不允许 alias")
        root = yaml.compose(text, Loader=_StrictSafeLoader)
        _validate_yaml_nodes(root)
        loaded = yaml.load(text, Loader=_StrictSafeLoader)
    except yaml.YAMLError as error:
        raise ValueError("H1 YAML 配置语法或安全校验失败") from error
    try:
        if not isinstance(loaded, Mapping):
            raise TypeError("H1 配置顶层必须是 Mapping")
        return H1GateSpec(cast(Mapping[str, object], loaded))
    except TypeError as error:
        raise ValueError(f"H1 YAML 配置内容错误：{error}") from error


def compute_h1_spec_hash(spec: H1GateSpec) -> str:
    """使用现有 demand 配置哈希协议返回完整 experiment spec 哈希。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    return compute_config_hash(cast(Mapping[str, object], _plain_tree(spec.config)))


def primary_seeds(spec: H1GateSpec) -> tuple[int, ...]:
    """返回冻结、无 replacement 的 256 个连续正式 seed。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    protocol = cast(Mapping[str, object], spec.config["seed_protocol"])
    base_seed = cast(int, protocol["base_seed"])
    count = cast(int, protocol["count"])
    return tuple(base_seed + index for index in range(count))


def build_primary_demand_config(spec: H1GateSpec, seed: int) -> dict[str, object]:
    """为一个 seed 构造合法且独立的 demand-generation v1 配置。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    normalized_seed = _normalize_nonnegative_integer(seed, "seed")
    primary = cast(Mapping[str, object], spec.config["primary"])
    demand = cast(dict[str, object], _plain_tree(primary["demand"]))
    generation = cast(dict[str, object], _plain_tree(primary["generation"]))
    demand["seed"] = normalized_seed
    create_demand_process(demand)
    return {
        "schema": "fura-mappo.demand-generation",
        "version": 1,
        "demand": demand,
        "generation": generation,
    }


def build_primary_environment_config(spec: H1GateSpec) -> ResourceServiceConfig:
    """由冻结 spec 构造 WP-02A 环境配置。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    primary = cast(Mapping[str, object], spec.config["primary"])
    environment = cast(Mapping[str, object], primary["environment"])
    positions = cast(Sequence[Sequence[float]], environment["initial_resource_positions"])
    return ResourceServiceConfig(
        initial_resource_positions=tuple(tuple(position) for position in positions),
        movement_speed=cast(float, environment["movement_speed"]),
    )


def compute_environment_config_hash(config: ResourceServiceConfig) -> str:
    """对规范环境普通树复用现有配置哈希协议。"""

    if not isinstance(config, ResourceServiceConfig):
        raise TypeError("config 必须是 ResourceServiceConfig")
    plain_config: dict[str, object] = {
        "initial_resource_positions": [
            [float(coordinate) for coordinate in position]
            for position in config.initial_resource_positions
        ],
        "movement_speed": float(config.movement_speed),
    }
    return compute_config_hash(plain_config)


@dataclass(frozen=True, slots=True)
class ArtifactPlanEntry:
    """一个正式 seed 的确定性 artifact 相对路径计划。"""

    seed: int
    relative_path: str

    def __post_init__(self) -> None:
        """规范化 seed 并冻结确定性文件名。"""

        seed = _normalize_nonnegative_integer(self.seed, "seed")
        _validate_relative_artifact_path(self.relative_path)
        if self.relative_path != f"trace_{seed}.npz":
            raise ValueError("artifact plan 文件名必须精确为 trace_<seed>.npz")
        object.__setattr__(self, "seed", seed)


def plan_primary_artifacts(spec: H1GateSpec) -> tuple[ArtifactPlanEntry, ...]:
    """只构造 artifact 计划，不生成任何需求轨迹。"""

    return tuple(
        ArtifactPlanEntry(seed=seed, relative_path=f"trace_{seed}.npz")
        for seed in primary_seeds(spec)
    )


@dataclass(frozen=True, slots=True)
class ArtifactInventoryEntry:
    """一个已冻结 DemandTrace artifact 的审计记录。"""

    seed: int
    relative_path: str
    process_type: str
    config_sha256: str
    content_sha256: str
    start_step: int
    num_steps: int
    num_events: int

    def __post_init__(self) -> None:
        """验证单条 inventory 记录的局部类型和值域。"""

        seed = _normalize_nonnegative_integer(self.seed, "seed")
        _validate_relative_artifact_path(self.relative_path)
        if not isinstance(self.process_type, str) or not self.process_type:
            raise TypeError("process_type 必须是非空字符串")
        for value, name in (
            (self.config_sha256, "config_sha256"),
            (self.content_sha256, "content_sha256"),
        ):
            if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} 必须是小写完整 SHA-256")
        start_step = _normalize_nonnegative_integer(self.start_step, "start_step")
        num_steps = _normalize_positive_integer(self.num_steps, "num_steps")
        num_events = _normalize_nonnegative_integer(self.num_events, "num_events")
        object.__setattr__(self, "seed", seed)
        object.__setattr__(self, "start_step", start_step)
        object.__setattr__(self, "num_steps", num_steps)
        object.__setattr__(self, "num_events", num_events)


@dataclass(frozen=True, slots=True)
class ArtifactInventory:
    """按正式 seed 顺序排列的 artifact inventory。"""

    experiment_spec_sha256: str
    wp02c_stable_sha: str
    planned_seed_count: int
    entries: tuple[ArtifactInventoryEntry, ...]
    schema: str = _INVENTORY_SCHEMA
    version: int = _INVENTORY_VERSION

    def __post_init__(self) -> None:
        """防御性复制 entries 并验证顶层协议字段。"""

        if (
            not isinstance(self.experiment_spec_sha256, str)
            or _SHA256_PATTERN.fullmatch(self.experiment_spec_sha256) is None
        ):
            raise ValueError("experiment_spec_sha256 必须是小写完整 SHA-256")
        if (
            not isinstance(self.wp02c_stable_sha, str)
            or _GIT_SHA_PATTERN.fullmatch(self.wp02c_stable_sha) is None
        ):
            raise ValueError("wp02c_stable_sha 必须是小写完整 Commit SHA")
        planned = _normalize_positive_integer(self.planned_seed_count, "planned_seed_count")
        try:
            entries = tuple(self.entries)
        except TypeError as error:
            raise TypeError("entries 必须是 ArtifactInventoryEntry 序列") from error
        if not all(isinstance(entry, ArtifactInventoryEntry) for entry in entries):
            raise TypeError("entries 中每一项都必须是 ArtifactInventoryEntry")
        if len(entries) != planned:
            raise ValueError("entries 数量必须等于 planned_seed_count")
        if self.schema != _INVENTORY_SCHEMA or self.version != _INVENTORY_VERSION:
            raise ValueError("inventory schema/version 不受支持")
        object.__setattr__(self, "planned_seed_count", planned)
        object.__setattr__(self, "entries", entries)


def _validate_relative_artifact_path(value: str) -> None:
    """拒绝绝对、父目录和非规范 NPZ 路径。"""

    if not isinstance(value, str) or not value:
        raise H1ProtocolError("artifact relative_path 必须是非空字符串")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".npz":
        raise H1ProtocolError("artifact path 必须是安全的相对 .npz 路径")


def _validate_inventory_entries(
    inventory: ArtifactInventory,
    *,
    expected_seeds: tuple[int, ...],
    expected_num_steps: int,
) -> None:
    """验证 inventory 自身与 artifact manifest 的确定性一致性。"""

    seeds = tuple(entry.seed for entry in inventory.entries)
    if seeds != expected_seeds:
        raise H1ProtocolError("inventory seed 集或顺序与计划不一致")
    paths = tuple(entry.relative_path for entry in inventory.entries)
    if len(paths) != len(set(paths)):
        raise H1ProtocolError("inventory 不允许重复 artifact path")
    for entry in inventory.entries:
        _validate_relative_artifact_path(entry.relative_path)
        if entry.relative_path != f"trace_{entry.seed}.npz":
            raise H1ProtocolError("artifact filename 必须精确为 trace_<seed>.npz")
        if entry.process_type != "drifting_hotspot":
            raise H1ProtocolError("inventory process_type 必须是 drifting_hotspot")
        if _SHA256_PATTERN.fullmatch(entry.config_sha256) is None:
            raise H1ProtocolError("inventory config_sha256 格式错误")
        if _SHA256_PATTERN.fullmatch(entry.content_sha256) is None:
            raise H1ProtocolError("inventory content_sha256 格式错误")
        if entry.start_step < 0 or entry.num_steps != expected_num_steps or entry.num_events < 0:
            raise H1ProtocolError("inventory trace shape/count 字段错误")


def validate_primary_artifact_inventory(
    spec: H1GateSpec,
    inventory: ArtifactInventory,
    artifact_root: str | os.PathLike[str],
) -> None:
    """安全回读并完整交叉验证正式 primary artifact inventory。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    if not isinstance(inventory, ArtifactInventory):
        raise TypeError("inventory 必须是 ArtifactInventory")
    if inventory.schema != _INVENTORY_SCHEMA or inventory.version != _INVENTORY_VERSION:
        raise H1ProtocolError("inventory schema/version 不受支持")
    if inventory.experiment_spec_sha256 != spec.sha256:
        raise H1ProtocolError("inventory experiment spec hash 不匹配")
    if inventory.wp02c_stable_sha != spec.wp02c_stable_sha:
        raise H1ProtocolError("inventory WP-02C stable SHA 不匹配")
    if inventory.planned_seed_count != spec.planned_seed_count:
        raise H1ProtocolError("inventory planned seed count 不匹配")
    _validate_inventory_entries(
        inventory,
        expected_seeds=primary_seeds(spec),
        expected_num_steps=spec.num_steps,
    )
    root = Path(artifact_root)
    for entry in inventory.entries:
        _validate_primary_inventory_entry_identity(spec, entry)
        _validate_artifact_entry(root / entry.relative_path, entry, spec.num_steps)


def build_primary_artifact_inventory(
    spec: H1GateSpec,
    entries: Sequence[ArtifactInventoryEntry],
) -> ArtifactInventory:
    """由完整、按 seed 排序的 entries 构造冻结 primary inventory。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    try:
        normalized_entries = tuple(entries)
    except TypeError as error:
        raise TypeError("entries 必须是 ArtifactInventoryEntry 序列") from error
    inventory = ArtifactInventory(
        experiment_spec_sha256=spec.sha256,
        wp02c_stable_sha=spec.wp02c_stable_sha,
        planned_seed_count=spec.planned_seed_count,
        entries=normalized_entries,
    )
    _validate_inventory_entries(
        inventory,
        expected_seeds=primary_seeds(spec),
        expected_num_steps=spec.num_steps,
    )
    for entry in inventory.entries:
        _validate_primary_inventory_entry_identity(spec, entry)
    return inventory


def _validate_primary_inventory_entry_identity(
    spec: H1GateSpec,
    entry: ArtifactInventoryEntry,
) -> None:
    """把一个 entry 的 seed、路径和配置身份绑定到冻结 primary spec。"""

    if entry.seed not in primary_seeds(spec):
        raise H1ProtocolError("artifact seed 不属于冻结 primary seed 集")
    if entry.relative_path != f"trace_{entry.seed}.npz":
        raise H1ProtocolError("artifact filename 必须精确为 trace_<seed>.npz")
    if entry.process_type != "drifting_hotspot":
        raise H1ProtocolError("inventory process_type 必须是 drifting_hotspot")
    expected_config_sha256 = compute_config_hash(build_primary_demand_config(spec, entry.seed))
    if entry.config_sha256 != expected_config_sha256:
        raise H1ProtocolError(f"seed {entry.seed} config_sha256 与冻结 primary spec 不一致")
    if entry.start_step != 0:
        raise H1ProtocolError("primary artifact start_step 必须精确为零")
    if entry.num_steps != spec.num_steps:
        raise H1ProtocolError("primary artifact num_steps 与冻结 spec 不一致")


def _validate_artifact_entry(
    path: Path,
    entry: ArtifactInventoryEntry,
    expected_num_steps: int,
) -> None:
    """回读一个 artifact 并与 inventory entry 交叉验证。"""

    _load_validated_artifact_entry(path, entry, expected_num_steps)


def _load_validated_artifact_entry(
    path: Path,
    entry: ArtifactInventoryEntry,
    expected_num_steps: int,
) -> DemandTraceArtifact:
    """严格回读并返回与 inventory entry 完全一致的 artifact。"""

    if path.is_symlink():
        raise H1ProtocolError("artifact 不能是符号链接")
    artifact = load_demand_trace(path)
    manifest = artifact.manifest
    comparisons = {
        "seed": entry.seed,
        "process_type": entry.process_type,
        "config_sha256": entry.config_sha256,
        "content_sha256": entry.content_sha256,
        "start_step": entry.start_step,
        "num_steps": entry.num_steps,
        "num_events": entry.num_events,
    }
    for key, expected in comparisons.items():
        if manifest[key] != expected:
            raise H1ProtocolError(f"artifact manifest.{key} 与 inventory 不一致")
    if artifact.trace.counts.shape[0] != expected_num_steps:
        raise H1ProtocolError("artifact trace num_steps 与 protocol 不一致")
    return artifact


def build_provenance_bound_artifact_entry(
    spec: H1GateSpec,
    plan: ArtifactPlanEntry,
    artifact_path: str | os.PathLike[str],
    formal_provenance: FormalProvenance,
) -> ArtifactInventoryEntry:
    """从已回读 artifact 构造与正式 spec/Git provenance 绑定的 inventory entry。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    if not isinstance(plan, ArtifactPlanEntry):
        raise TypeError("plan 必须是 ArtifactPlanEntry")
    if plan not in plan_primary_artifacts(spec):
        raise H1ProtocolError("artifact plan entry 不属于冻结 primary plan")
    _validate_verdict_formal_provenance(formal_provenance, spec.sha256)
    if formal_provenance.wp02c_stable_sha != spec.wp02c_stable_sha:
        raise H1ProtocolError("formal provenance WP-02C stable SHA 不匹配")

    target = _coerce_output_path(artifact_path)
    if target.name != plan.relative_path:
        raise H1ProtocolError("artifact path 与冻结 plan filename 不匹配")
    if target.is_symlink():
        raise H1ProtocolError("artifact 不能是符号链接")
    try:
        artifact = load_demand_trace(target)
    except (OSError, TypeError, ValueError) as error:
        raise H1ProtocolError(f"artifact 严格回读失败：{error}") from error

    manifest = artifact.manifest
    expected_config = build_primary_demand_config(spec, plan.seed)
    if _plain_tree(manifest["resolved_config"]) != expected_config:
        raise H1ProtocolError("artifact resolved_config 与冻结 primary config 不一致")
    expected_config_sha256 = compute_config_hash(expected_config)
    if manifest["config_sha256"] != expected_config_sha256:
        raise H1ProtocolError("artifact config SHA 与冻结 primary config 不一致")
    if manifest["seed"] != plan.seed:
        raise H1ProtocolError("artifact manifest seed 与冻结 plan 不一致")
    if manifest["process_type"] != "drifting_hotspot":
        raise H1ProtocolError("artifact process_type 必须是 drifting_hotspot")
    if manifest["git_commit"] != formal_provenance.actual_head:
        raise H1ProtocolError("artifact manifest git_commit 与 formal execution HEAD 不一致")
    if manifest["git_dirty"] is not False:
        raise H1ProtocolError("artifact manifest 必须记录 clean Git 状态")
    if artifact.trace.start_step != 0 or manifest["start_step"] != 0:
        raise H1ProtocolError("primary artifact start_step 必须精确为零")
    if artifact.trace.counts.shape[0] != spec.num_steps or manifest["num_steps"] != spec.num_steps:
        raise H1ProtocolError("primary artifact num_steps 与冻结 spec 不一致")
    if manifest["num_events"] != len(artifact.trace.events):
        raise H1ProtocolError("artifact num_events 与 trace 不一致")

    entry = ArtifactInventoryEntry(
        seed=plan.seed,
        relative_path=plan.relative_path,
        process_type=cast(str, manifest["process_type"]),
        config_sha256=cast(str, manifest["config_sha256"]),
        content_sha256=cast(str, manifest["content_sha256"]),
        start_step=cast(int, manifest["start_step"]),
        num_steps=cast(int, manifest["num_steps"]),
        num_events=cast(int, manifest["num_events"]),
    )
    _validate_primary_inventory_entry_identity(spec, entry)
    _load_validated_artifact_entry(target, entry, spec.num_steps)
    return entry


def inventory_to_dict(inventory: ArtifactInventory) -> dict[str, object]:
    """返回 artifact inventory 的 JSON-compatible 普通树。"""

    if not isinstance(inventory, ArtifactInventory):
        raise TypeError("inventory 必须是 ArtifactInventory")
    return cast(dict[str, object], asdict(inventory))


def compute_artifact_inventory_hash(inventory: ArtifactInventory) -> str:
    """对完整 inventory 普通树复用现有配置哈希协议。"""

    return compute_config_hash({"artifact_inventory": inventory_to_dict(inventory)})


def _validate_episode_metrics(metrics: EpisodeMetrics, name: str) -> None:
    """验证 formal result 中 EpisodeMetrics 的核心账本与有限性约束。"""

    if not isinstance(metrics, EpisodeMetrics):
        raise TypeError(f"{name} 必须是 EpisodeMetrics")
    integer_fields = (
        "arrived",
        "completed",
        "expired",
        "truncated",
        "demanded_service_work",
        "service_slots",
        "movement_slots",
        "idle_slots",
        "completed_service_work",
        "expired_service_work",
        "truncated_service_work",
        "expired_remaining_work",
        "truncated_remaining_work",
        "service_start_wait_sum",
        "service_start_count",
        "completed_response_sum",
        "completed_response_count",
        "duplicate_assignment_conflicts",
        "zero_distance_moves",
    )
    for field_name in integer_fields:
        _normalize_nonnegative_integer(getattr(metrics, field_name), f"{name}.{field_name}")
    finite_fields = (
        "arrived_priority_sum",
        "completed_priority_sum",
        "expired_priority_sum",
        "truncated_priority_sum",
        "movement_distance",
    )
    for field_name in finite_fields:
        value = _normalize_finite_float(getattr(metrics, field_name), f"{name}.{field_name}")
        if value < 0.0:
            raise ValueError(f"{name}.{field_name} 必须非负")
    if metrics.completed + metrics.expired + metrics.truncated != metrics.arrived:
        raise ValueError(f"{name} terminal task counts 必须精确分解 arrived")

    zone_fields = (
        ("per_zone_arrived", metrics.arrived),
        ("per_zone_completed", metrics.completed),
        ("per_zone_expired", metrics.expired),
        ("per_zone_truncated", metrics.truncated),
    )
    zone_count: int | None = None
    for field_name, expected_total in zone_fields:
        values = getattr(metrics, field_name)
        if not isinstance(values, tuple):
            raise TypeError(f"{name}.{field_name} 必须是 tuple")
        if zone_count is None:
            zone_count = len(values)
            if zone_count == 0:
                raise ValueError(f"{name} per-zone metrics 不能为空")
        elif len(values) != zone_count:
            raise ValueError(f"{name} per-zone metrics 长度必须一致")
        normalized = tuple(
            _normalize_nonnegative_integer(value, f"{name}.{field_name}") for value in values
        )
        if sum(normalized) != expected_total:
            raise ValueError(f"{name}.{field_name} 总和与 aggregate 不一致")

    rate_fields = (
        ("completion_rate", metrics.completed),
        ("expiration_rate", metrics.expired),
        ("truncation_rate", metrics.truncated),
    )
    for field_name, numerator in rate_fields:
        value = getattr(metrics, field_name)
        expected = None if metrics.arrived == 0 else numerator / metrics.arrived
        if value is None:
            if expected is not None:
                raise ValueError(f"{name}.{field_name} 缺失")
        elif _normalize_finite_float(value, f"{name}.{field_name}") != expected:
            raise ValueError(f"{name}.{field_name} 与账本不一致")

    mean_fields = (
        (
            "mean_service_start_wait",
            metrics.service_start_wait_sum,
            metrics.service_start_count,
        ),
        (
            "mean_completed_response",
            metrics.completed_response_sum,
            metrics.completed_response_count,
        ),
    )
    for field_name, total, count in mean_fields:
        value = getattr(metrics, field_name)
        expected = None if count == 0 else total / count
        if value is None:
            if expected is not None:
                raise ValueError(f"{name}.{field_name} 缺失")
        elif _normalize_finite_float(value, f"{name}.{field_name}") != expected:
            raise ValueError(f"{name}.{field_name} 与组成量不一致")


@dataclass(frozen=True, slots=True)
class PairedTraceResult:
    """一条 DemandTrace 的完整 Reactive/Oracle 配对结果。"""

    seed: int
    trace_id: str
    horizon: int
    experiment_spec_sha256: str
    artifact_config_sha256: str
    artifact_content_sha256: str
    environment_config_sha256: str
    reactive_metrics: EpisodeMetrics
    oracle_metrics: EpisodeMetrics
    primary_difference: float
    reference_nonempty_view_steps: int
    reference_feasible_future_pair_steps: int
    reference_oracle_would_differ_steps: int
    reference_oracle_would_preposition_steps: int
    actionable_steps: int
    has_reference_feasible_future_pair: bool
    has_reference_oracle_action_difference: bool
    realized_oracle_prearrival_move_steps: int
    oracle_actionable_steps: int
    protocol_failure: str | None = None
    schema: str = _RESULT_SCHEMA
    version: int = _RESULT_VERSION

    def __post_init__(self) -> None:
        """验证配对结果的局部 schema、账本和诊断分母。"""

        seed = _normalize_nonnegative_integer(self.seed, "seed")
        horizon = _normalize_nonnegative_integer(self.horizon, "horizon")
        if not isinstance(self.trace_id, str) or not self.trace_id:
            raise TypeError("trace_id 必须是非空字符串")
        if "/" in self.trace_id or "\\" in self.trace_id:
            raise ValueError("trace_id 必须是标识符，不能包含路径分隔符")
        for value, name in (
            (self.experiment_spec_sha256, "experiment_spec_sha256"),
            (self.artifact_config_sha256, "artifact_config_sha256"),
            (self.artifact_content_sha256, "artifact_content_sha256"),
            (self.environment_config_sha256, "environment_config_sha256"),
        ):
            if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} 必须是小写完整 SHA-256")
        _validate_episode_metrics(self.reactive_metrics, "reactive_metrics")
        _validate_episode_metrics(self.oracle_metrics, "oracle_metrics")
        difference = _normalize_finite_float(self.primary_difference, "primary_difference")
        diagnostic_counts = (
            "reference_nonempty_view_steps",
            "reference_feasible_future_pair_steps",
            "reference_oracle_would_differ_steps",
            "reference_oracle_would_preposition_steps",
            "actionable_steps",
            "realized_oracle_prearrival_move_steps",
            "oracle_actionable_steps",
        )
        normalized_counts = {
            name: _normalize_nonnegative_integer(getattr(self, name), name)
            for name in diagnostic_counts
        }
        for name in diagnostic_counts[:4]:
            if normalized_counts[name] > normalized_counts["actionable_steps"]:
                raise ValueError(f"{name} 不能超过 actionable_steps")
        if (
            normalized_counts["reference_oracle_would_preposition_steps"]
            > normalized_counts["reference_oracle_would_differ_steps"]
        ):
            raise ValueError("preposition difference count 不能超过 action difference count")
        if (
            normalized_counts["realized_oracle_prearrival_move_steps"]
            > normalized_counts["oracle_actionable_steps"]
        ):
            raise ValueError("realized Oracle prearrival count 不能超过 denominator")
        for value, name in (
            (self.has_reference_feasible_future_pair, "has_reference_feasible_future_pair"),
            (self.has_reference_oracle_action_difference, "has_reference_oracle_action_difference"),
        ):
            if type(value) is not bool:
                raise TypeError(f"{name} 必须是 bool")
        if self.has_reference_feasible_future_pair != bool(
            normalized_counts["reference_feasible_future_pair_steps"]
        ):
            raise ValueError("feasible future pair bool 与 count 不一致")
        if self.has_reference_oracle_action_difference != bool(
            normalized_counts["reference_oracle_would_differ_steps"]
        ):
            raise ValueError("Oracle action difference bool 与 count 不一致")
        if self.protocol_failure is not None and (
            not isinstance(self.protocol_failure, str) or not self.protocol_failure
        ):
            raise TypeError("protocol_failure 必须是非空字符串或 None")
        if self.schema != _RESULT_SCHEMA or self.version != _RESULT_VERSION:
            raise ValueError("paired result schema/version 不受支持")
        object.__setattr__(self, "seed", seed)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "primary_difference", difference)
        for name, value in normalized_counts.items():
            object.__setattr__(self, name, value)


def _terminal_metrics(results: Sequence[StepResult]) -> EpisodeMetrics:
    """读取 rollout 唯一 terminal EpisodeMetrics。"""

    if not results or not results[-1].is_terminal or results[-1].episode_metrics is None:
        raise H1ProtocolError("rollout 未产生 terminal EpisodeMetrics")
    if any(result.episode_metrics is not None for result in results[:-1]):
        raise H1ProtocolError("非 terminal step 不得提前包含 EpisodeMetrics")
    return results[-1].episode_metrics


def _has_feasible_future_pair(
    snapshot: EnvironmentSnapshot,
    future_events: tuple[DemandEvent, ...],
    movement_speed: float,
) -> bool:
    """直接复用 WP-02C 冻结 pair helper 判断未来可行性。"""

    stop_step = snapshot.absolute_step + snapshot.steps_remaining
    available = tuple(
        resource for resource in snapshot.resources if resource.status is ResourceStatus.AVAILABLE
    )
    for event in future_events:
        candidate = _Candidate(event=event, work=event.service_time, is_future=True)
        for resource in available:
            if (
                _evaluate_pair(
                    resource,
                    candidate,
                    absolute_step=snapshot.absolute_step,
                    stop_step=stop_step,
                    movement_speed=movement_speed,
                )
                is not None
            ):
                return True
    return False


def _contains_future_target_move(
    actions: tuple[ResourceAction, ...],
    snapshot: EnvironmentSnapshot,
    future_events: tuple[DemandEvent, ...],
) -> bool:
    """判断动作 tuple 是否包含指向尚未到达事件的精确 Move。"""

    targets = {
        event.position for event in future_events if event.arrival_step > snapshot.absolute_step
    }
    return any(
        isinstance(action, MoveAction) and action.target_position in targets for action in actions
    )


def run_paired_trace(
    trace: DemandTrace,
    environment_config: ResourceServiceConfig,
    horizon: int,
    *,
    seed: int,
    trace_id: str,
    experiment_spec_sha256: str,
    artifact_config_sha256: str,
    artifact_content_sha256: str,
) -> PairedTraceResult:
    """在两个独立环境中运行同一 Trace；这是 tiny test 使用的低层非正式入口。

    该函数允许调用方提供测试 provenance，因此不能作为 formal artifact 入口。正式运行必须
    使用 ``run_primary_artifact()``，由冻结 spec 和已验证 artifact 自动绑定身份。
    """

    if not isinstance(trace, DemandTrace):
        raise TypeError("trace 必须是 DemandTrace")
    if not isinstance(environment_config, ResourceServiceConfig):
        raise TypeError("environment_config 必须是 ResourceServiceConfig")
    normalized_seed = _normalize_nonnegative_integer(seed, "seed")
    if not isinstance(trace_id, str) or not trace_id:
        raise TypeError("trace_id 必须是非空字符串")
    if "/" in trace_id or "\\" in trace_id:
        raise ValueError("trace_id 必须是标识符，不能包含路径分隔符")
    for value, name in (
        (experiment_spec_sha256, "experiment_spec_sha256"),
        (artifact_config_sha256, "artifact_config_sha256"),
        (artifact_content_sha256, "artifact_content_sha256"),
    ):
        if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{name} 必须是小写完整 SHA-256")
    environment_config_sha256 = compute_environment_config_hash(environment_config)

    reactive_environment = ResourceServiceEnvironment(environment_config)
    oracle_environment = ResourceServiceEnvironment(environment_config)
    reactive = ReactiveController(environment_config.movement_speed)
    counterfactual_oracle = RollingTrueFutureOracle(
        environment_config.movement_speed,
        horizon,
    )
    oracle = RollingTrueFutureOracle(environment_config.movement_speed, horizon)

    reactive_snapshot: EnvironmentSnapshot | None = reactive_environment.reset(trace)
    reactive_results: list[StepResult] = []
    nonempty = 0
    feasible = 0
    differs = 0
    prepositions = 0
    actionable = 0
    while reactive_snapshot is not None:
        reactive_actions = reactive.act(reactive_snapshot)
        view = build_true_future_view(trace, reactive_snapshot, horizon)
        counterfactual_actions = counterfactual_oracle.act(reactive_snapshot, view)
        actionable += 1
        nonempty += bool(view.future_events)
        feasible += _has_feasible_future_pair(
            reactive_snapshot,
            view.future_events,
            environment_config.movement_speed,
        )
        actions_differ = counterfactual_actions != reactive_actions
        differs += actions_differ
        prepositions += actions_differ and _contains_future_target_move(
            counterfactual_actions,
            reactive_snapshot,
            view.future_events,
        )
        result = reactive_environment.step(reactive_actions)
        reactive_results.append(result)
        reactive_snapshot = result.next_snapshot

    oracle_snapshot: EnvironmentSnapshot | None = oracle_environment.reset(trace)
    oracle_results: list[StepResult] = []
    realized_prepositions = 0
    oracle_actionable = 0
    while oracle_snapshot is not None:
        view = build_true_future_view(trace, oracle_snapshot, horizon)
        oracle_actions = oracle.act(oracle_snapshot, view)
        oracle_actionable += 1
        realized_prepositions += _contains_future_target_move(
            oracle_actions,
            oracle_snapshot,
            view.future_events,
        )
        result = oracle_environment.step(oracle_actions)
        oracle_results.append(result)
        oracle_snapshot = result.next_snapshot

    reactive_metrics = _terminal_metrics(reactive_results)
    oracle_metrics = _terminal_metrics(oracle_results)
    if reactive_metrics.arrived != oracle_metrics.arrived:
        raise H1ProtocolError("Reactive/Oracle arrived denominator 必须完全一致")
    arrived = reactive_metrics.arrived
    difference = (
        0.0 if arrived == 0 else (oracle_metrics.completed - reactive_metrics.completed) / arrived
    )
    return PairedTraceResult(
        seed=normalized_seed,
        trace_id=trace_id,
        horizon=horizon,
        experiment_spec_sha256=experiment_spec_sha256,
        artifact_config_sha256=artifact_config_sha256,
        artifact_content_sha256=artifact_content_sha256,
        environment_config_sha256=environment_config_sha256,
        reactive_metrics=reactive_metrics,
        oracle_metrics=oracle_metrics,
        primary_difference=difference,
        reference_nonempty_view_steps=nonempty,
        reference_feasible_future_pair_steps=feasible,
        reference_oracle_would_differ_steps=differs,
        reference_oracle_would_preposition_steps=prepositions,
        actionable_steps=actionable,
        has_reference_feasible_future_pair=bool(feasible),
        has_reference_oracle_action_difference=bool(differs),
        realized_oracle_prearrival_move_steps=realized_prepositions,
        oracle_actionable_steps=oracle_actionable,
    )


def run_primary_artifact(
    spec: H1GateSpec,
    inventory_entry: ArtifactInventoryEntry,
    artifact_root: str | os.PathLike[str],
) -> PairedTraceResult:
    """从冻结 inventory entry 运行唯一 formal primary paired rollout。

    调用方不能覆盖 trace、seed、环境、horizon 或 provenance；这些值全部由严格验证后的
    artifact、entry 与 H1 spec 推导。
    """

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    if not isinstance(inventory_entry, ArtifactInventoryEntry):
        raise TypeError("inventory_entry 必须是 ArtifactInventoryEntry")
    _validate_primary_inventory_entry_identity(spec, inventory_entry)
    root = Path(artifact_root)
    artifact = _load_validated_artifact_entry(
        root / inventory_entry.relative_path,
        inventory_entry,
        spec.num_steps,
    )
    environment_config = build_primary_environment_config(spec)
    manifest = artifact.manifest
    return run_paired_trace(
        artifact.trace,
        environment_config,
        spec.primary_horizon,
        seed=inventory_entry.seed,
        trace_id=inventory_entry.relative_path,
        experiment_spec_sha256=spec.sha256,
        artifact_config_sha256=cast(str, manifest["config_sha256"]),
        artifact_content_sha256=cast(str, manifest["content_sha256"]),
    )


def validate_h0_invariant(trace: DemandTrace, config: ResourceServiceConfig) -> None:
    """逐步验证 Oracle(H=0) 与 Reactive 的严格协议等价。"""

    reactive_environment = ResourceServiceEnvironment(config)
    oracle_environment = ResourceServiceEnvironment(config)
    reactive = ReactiveController(config.movement_speed)
    oracle = RollingTrueFutureOracle(config.movement_speed, 0)
    reactive_snapshot: EnvironmentSnapshot | None = reactive_environment.reset(trace)
    oracle_snapshot: EnvironmentSnapshot | None = oracle_environment.reset(trace)
    while reactive_snapshot is not None and oracle_snapshot is not None:
        reactive_actions = reactive.act(reactive_snapshot)
        view = build_true_future_view(trace, oracle_snapshot, 0)
        oracle_actions = oracle.act(oracle_snapshot, view)
        if reactive_actions != oracle_actions:
            raise H1ProtocolError("H=0 action sequence 与 Reactive 不一致")
        reactive_result = reactive_environment.step(reactive_actions)
        oracle_result = oracle_environment.step(oracle_actions)
        if reactive_result != oracle_result:
            raise H1ProtocolError("H=0 StepResult sequence 与 Reactive 不一致")
        reactive_snapshot = reactive_result.next_snapshot
        oracle_snapshot = oracle_result.next_snapshot
    if reactive_snapshot is not None or oracle_snapshot is not None:
        raise H1ProtocolError("H=0 与 Reactive terminal 时序不一致")


def validate_canonical_mechanism() -> None:
    """验证 WP-02C Move/Move/Serve 机制，但不生成正式 H1 证据。"""

    event = DemandEvent(
        event_id=0,
        arrival_step=2,
        zone_id=0,
        position=(2.0, 0.0),
        priority=0.5,
        service_time=1,
        deadline=3,
    )
    counts = np.zeros((4, 1), dtype=np.int64)
    counts[2, 0] = 1
    trace = DemandTrace(
        start_step=0,
        counts=counts,
        intensities=np.zeros((4, 1), dtype=np.float64),
        events=(event,),
    )
    config = ResourceServiceConfig(initial_resource_positions=((0.0, 0.0),), movement_speed=1.0)
    oracle_environment = ResourceServiceEnvironment(config)
    oracle = RollingTrueFutureOracle(config.movement_speed, 2)
    oracle_snapshot: EnvironmentSnapshot | None = oracle_environment.reset(trace)
    oracle_actions: list[tuple[ResourceAction, ...]] = []
    oracle_results: list[StepResult] = []
    while oracle_snapshot is not None:
        view = build_true_future_view(trace, oracle_snapshot, 2)
        actions = oracle.act(oracle_snapshot, view)
        oracle_actions.append(actions)
        result = oracle_environment.step(actions)
        oracle_results.append(result)
        oracle_snapshot = result.next_snapshot
    expected_prefix = (
        (MoveAction((2.0, 0.0)),),
        (MoveAction((2.0, 0.0)),),
        (ServeAction(0),),
    )
    if tuple(oracle_actions[:3]) != expected_prefix:
        raise H1ProtocolError("WP-02C canonical Oracle 必须精确执行 Move/Move/Serve")
    if oracle_results[2].step_metrics.completed != 1:
        raise H1ProtocolError("WP-02C canonical event 必须在 boundary 3 完成")

    reactive_environment = ResourceServiceEnvironment(config)
    reactive = ReactiveController(config.movement_speed)
    reactive_snapshot: EnvironmentSnapshot | None = reactive_environment.reset(trace)
    reactive_results: list[StepResult] = []
    while reactive_snapshot is not None:
        actions = reactive.act(reactive_snapshot)
        result = reactive_environment.step(actions)
        reactive_results.append(result)
        reactive_snapshot = result.next_snapshot
    if (
        _terminal_metrics(oracle_results).completed != 1
        or _terminal_metrics(reactive_results).completed != 0
    ):
        raise H1ProtocolError("WP-02C canonical mechanism preflight 失败")


_SECONDARY_FIELDS = (
    "completed",
    "completion_rate",
    "expired",
    "expiration_rate",
    "truncated",
    "truncation_rate",
    "completed_priority_sum",
    "service_slots",
    "movement_slots",
    "idle_slots",
    "movement_distance",
    "mean_service_start_wait",
    "mean_completed_response",
    "duplicate_assignment_conflicts",
    "zero_distance_moves",
)
_DIAGNOSTIC_SUMMARY_FIELDS = (
    "reference_nonempty_view_step_fraction",
    "reference_feasible_future_pair_step_fraction",
    "reference_oracle_would_differ_step_fraction",
    "reference_oracle_would_preposition_step_fraction",
    "traces_with_reference_feasible_future_pair_fraction",
    "traces_with_reference_oracle_action_difference_fraction",
    "realized_oracle_prearrival_move_step_fraction",
)


def _mean_optional(values: Sequence[float | int | None]) -> float | None:
    """返回有限非空值的算术均值。"""

    finite = [float(value) for value in values if value is not None]
    return None if not finite else math.fsum(finite) / len(finite)


def summarize_paired_results(results: Sequence[PairedTraceResult]) -> dict[str, object]:
    """汇总组成指标和诊断量，不构造综合 reward。"""

    result_tuple = tuple(results)
    if not result_tuple:
        raise ValueError("results 不能为空")
    secondary: dict[str, object] = {}
    for name in _SECONDARY_FIELDS:
        reactive_values = [getattr(item.reactive_metrics, name) for item in result_tuple]
        oracle_values = [getattr(item.oracle_metrics, name) for item in result_tuple]
        secondary[name] = {
            "reactive_mean": _mean_optional(reactive_values),
            "oracle_mean": _mean_optional(oracle_values),
        }
    actionable = sum(item.actionable_steps for item in result_tuple)
    oracle_actionable = sum(item.oracle_actionable_steps for item in result_tuple)

    def fraction(numerator: int, denominator: int) -> float | None:
        return None if denominator == 0 else numerator / denominator

    diagnostics = {
        "reference_nonempty_view_step_fraction": fraction(
            sum(item.reference_nonempty_view_steps for item in result_tuple), actionable
        ),
        "reference_feasible_future_pair_step_fraction": fraction(
            sum(item.reference_feasible_future_pair_steps for item in result_tuple), actionable
        ),
        "reference_oracle_would_differ_step_fraction": fraction(
            sum(item.reference_oracle_would_differ_steps for item in result_tuple), actionable
        ),
        "reference_oracle_would_preposition_step_fraction": fraction(
            sum(item.reference_oracle_would_preposition_steps for item in result_tuple), actionable
        ),
        "traces_with_reference_feasible_future_pair_fraction": fraction(
            sum(item.has_reference_feasible_future_pair for item in result_tuple),
            len(result_tuple),
        ),
        "traces_with_reference_oracle_action_difference_fraction": fraction(
            sum(item.has_reference_oracle_action_difference for item in result_tuple),
            len(result_tuple),
        ),
        "realized_oracle_prearrival_move_step_fraction": fraction(
            sum(item.realized_oracle_prearrival_move_steps for item in result_tuple),
            oracle_actionable,
        ),
    }
    return {"secondary": secondary, "diagnostics": diagnostics}


@dataclass(frozen=True, slots=True)
class H1GateSummary:
    """Primary paired inference、verdict 与组成指标汇总。"""

    verdict: H1Verdict
    n_planned: int
    n_valid: int
    point_estimate: float | None
    one_sided_lcb: float | None
    one_sided_ucb: float | None
    two_sided_interval: tuple[float, float] | None
    delta_min: float
    bootstrap_resamples: int
    bootstrap_seed: int
    secondary: Mapping[str, object]
    diagnostics: Mapping[str, object]
    protocol_errors: tuple[str, ...] = ()
    schema: str = _SUMMARY_SCHEMA
    version: int = _SUMMARY_VERSION

    def __post_init__(self) -> None:
        """冻结嵌套汇总并验证 scientific/protocol 两类状态。"""

        if not isinstance(self.verdict, H1Verdict):
            raise TypeError("verdict 必须是 H1Verdict")
        n_planned = _normalize_positive_integer(self.n_planned, "n_planned")
        n_valid = _normalize_nonnegative_integer(self.n_valid, "n_valid")
        if n_valid > n_planned:
            raise ValueError("n_valid 不能超过 n_planned")
        delta_min = _normalize_finite_float(self.delta_min, "delta_min")
        if delta_min <= 0.0:
            raise ValueError("delta_min 必须严格大于零")
        resamples = _normalize_positive_integer(
            self.bootstrap_resamples,
            "bootstrap_resamples",
        )
        bootstrap_seed = _normalize_nonnegative_integer(
            self.bootstrap_seed,
            "bootstrap_seed",
        )
        estimates = (
            self.point_estimate,
            self.one_sided_lcb,
            self.one_sided_ucb,
        )
        if self.verdict is H1Verdict.PROTOCOL_FAIL:
            if any(value is not None for value in estimates) or self.two_sided_interval is not None:
                raise ValueError("PROTOCOL_FAIL 不得包含 scientific estimate")
            if not self.protocol_errors:
                raise ValueError("PROTOCOL_FAIL 必须记录 protocol_errors")
        else:
            if any(value is None for value in estimates) or self.two_sided_interval is None:
                raise ValueError("scientific verdict 必须包含完整 bootstrap estimates")
            normalized_estimates = tuple(
                _normalize_finite_float(value, name)
                for value, name in zip(
                    estimates,
                    ("point_estimate", "one_sided_lcb", "one_sided_ucb"),
                    strict=True,
                )
            )
            interval = tuple(self.two_sided_interval)
            if len(interval) != 2:
                raise ValueError("two_sided_interval 必须包含两个端点")
            normalized_interval = (
                _normalize_finite_float(interval[0], "two_sided_interval[0]"),
                _normalize_finite_float(interval[1], "two_sided_interval[1]"),
            )
            if not (
                normalized_interval[0]
                <= normalized_estimates[1]
                <= normalized_estimates[2]
                <= normalized_interval[1]
            ):
                raise ValueError("bootstrap quantile 顺序错误")
            object.__setattr__(self, "point_estimate", normalized_estimates[0])
            object.__setattr__(self, "one_sided_lcb", normalized_estimates[1])
            object.__setattr__(self, "one_sided_ucb", normalized_estimates[2])
            object.__setattr__(self, "two_sided_interval", normalized_interval)
            if self.protocol_errors:
                raise ValueError("scientific verdict 不得包含 protocol_errors")
        if not all(isinstance(error, str) and error for error in self.protocol_errors):
            raise TypeError("protocol_errors 必须是非空字符串 tuple")
        if self.schema != _SUMMARY_SCHEMA or self.version != _SUMMARY_VERSION:
            raise ValueError("H1 summary schema/version 不受支持")
        secondary = _freeze_tree(_plain_tree(self.secondary))
        diagnostics = _freeze_tree(_plain_tree(self.diagnostics))
        if not isinstance(secondary, Mapping) or not isinstance(diagnostics, Mapping):
            raise TypeError("secondary 和 diagnostics 必须是 Mapping")
        object.__setattr__(self, "n_planned", n_planned)
        object.__setattr__(self, "n_valid", n_valid)
        object.__setattr__(self, "delta_min", delta_min)
        object.__setattr__(self, "bootstrap_resamples", resamples)
        object.__setattr__(self, "bootstrap_seed", bootstrap_seed)
        object.__setattr__(self, "secondary", secondary)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "protocol_errors", tuple(self.protocol_errors))


def _bootstrap_mean_interval(
    values: np.ndarray,
    *,
    resamples: int,
    seed: int,
    chunk_size: int = 1024,
) -> tuple[float, float, tuple[float, float]]:
    """以独立 PCG64 对完整 trace units 做确定性 percentile bootstrap。"""

    if not isinstance(values, np.ndarray):
        raise TypeError("bootstrap values 必须是 NumPy ndarray")
    if values.ndim != 1 or values.size == 0 or not np.all(np.isfinite(values)):
        raise ValueError("bootstrap values 必须是一维非空有限数组")
    normalized_resamples = _normalize_positive_integer(resamples, "resamples")
    normalized_seed = _normalize_nonnegative_integer(seed, "seed")
    normalized_chunk_size = _normalize_positive_integer(chunk_size, "chunk_size")
    generator = np.random.Generator(np.random.PCG64(normalized_seed))
    bootstrap_means = np.empty(normalized_resamples, dtype=np.float64)
    offset = 0
    while offset < normalized_resamples:
        size = min(normalized_chunk_size, normalized_resamples - offset)
        indices = generator.integers(0, values.size, size=(size, values.size))
        bootstrap_means[offset : offset + size] = np.mean(values[indices], axis=1)
        offset += size
    lower, upper, two_lower, two_upper = np.quantile(
        bootstrap_means,
        [0.05, 0.95, 0.025, 0.975],
        method="linear",
    )
    return float(lower), float(upper), (float(two_lower), float(two_upper))


def _scientific_summary(
    results: tuple[PairedTraceResult, ...],
    *,
    delta_min: float,
    resamples: int,
    bootstrap_seed: int,
    n_planned: int,
) -> H1GateSummary:
    """在已完成协议校验的 records 上计算唯一科学结论。"""

    values = np.asarray([item.primary_difference for item in results], dtype=np.float64)
    point = float(np.mean(values))
    lower, upper, two_sided = _bootstrap_mean_interval(
        values,
        resamples=resamples,
        seed=bootstrap_seed,
    )
    if point >= delta_min and lower > 0.0:
        verdict = H1Verdict.PASS
    elif upper < delta_min:
        verdict = H1Verdict.FAIL
    else:
        verdict = H1Verdict.INCONCLUSIVE
    components = summarize_paired_results(results)
    return H1GateSummary(
        verdict=verdict,
        n_planned=n_planned,
        n_valid=len(results),
        point_estimate=point,
        one_sided_lcb=lower,
        one_sided_ucb=upper,
        two_sided_interval=two_sided,
        delta_min=delta_min,
        bootstrap_resamples=resamples,
        bootstrap_seed=bootstrap_seed,
        secondary=cast(Mapping[str, object], components["secondary"]),
        diagnostics=cast(Mapping[str, object], components["diagnostics"]),
    )


def _protocol_fail_summary(spec: H1GateSpec, errors: Sequence[str]) -> H1GateSummary:
    """返回不包含科学估计的 PROTOCOL_FAIL summary。"""

    bootstrap = cast(Mapping[str, object], spec.config["bootstrap"])
    gate = cast(Mapping[str, object], spec.config["gate"])
    return H1GateSummary(
        verdict=H1Verdict.PROTOCOL_FAIL,
        n_planned=spec.planned_seed_count,
        n_valid=0,
        point_estimate=None,
        one_sided_lcb=None,
        one_sided_ucb=None,
        two_sided_interval=None,
        delta_min=cast(float, gate["delta_min"]),
        bootstrap_resamples=cast(int, bootstrap["resamples"]),
        bootstrap_seed=cast(int, bootstrap["seed"]),
        secondary=MappingProxyType({}),
        diagnostics=MappingProxyType({}),
        protocol_errors=tuple(errors),
    )


def _primary_protocol_errors(
    results: Sequence[PairedTraceResult],
    spec: H1GateSpec,
    inventory: ArtifactInventory,
) -> tuple[str, ...]:
    """返回 primary records 相对 spec/inventory 的唯一协议校验错误集合。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    if not isinstance(inventory, ArtifactInventory):
        raise TypeError("inventory 必须是 ArtifactInventory")
    result_tuple = tuple(results)
    errors: list[str] = []
    if inventory.experiment_spec_sha256 != spec.sha256:
        errors.append("inventory experiment spec hash 不匹配")
    if inventory.wp02c_stable_sha != spec.wp02c_stable_sha:
        errors.append("inventory WP-02C stable SHA 不匹配")
    if inventory.planned_seed_count != spec.planned_seed_count:
        errors.append("inventory planned seed count 不匹配")
    try:
        _validate_inventory_entries(
            inventory,
            expected_seeds=primary_seeds(spec),
            expected_num_steps=spec.num_steps,
        )
    except H1ProtocolError as error:
        errors.append(str(error))
    for entry in inventory.entries:
        try:
            _validate_primary_inventory_entry_identity(spec, entry)
        except H1ProtocolError as error:
            errors.append(str(error))
    entries_by_seed = {entry.seed: entry for entry in inventory.entries}
    expected_environment_sha256 = compute_environment_config_hash(
        build_primary_environment_config(spec)
    )
    if len(result_tuple) != spec.planned_seed_count:
        errors.append("primary results 数量必须精确等于 planned seed count")
    if not all(isinstance(item, PairedTraceResult) for item in result_tuple):
        errors.append("primary results 中包含非法 record 类型")
    else:
        seeds = tuple(item.seed for item in result_tuple)
        if seeds != primary_seeds(spec):
            errors.append("primary results seed 集或顺序不匹配")
        if len(seeds) != len(set(seeds)):
            errors.append("primary results 不允许重复 seed")
        trace_ids = tuple(item.trace_id for item in result_tuple)
        if len(trace_ids) != len(set(trace_ids)):
            errors.append("primary results 不允许重复 trace_id")
        for item in result_tuple:
            entry = entries_by_seed.get(item.seed)
            if item.schema != _RESULT_SCHEMA or item.version != _RESULT_VERSION:
                errors.append(f"seed {item.seed} result schema/version 错误")
            if item.horizon != spec.primary_horizon:
                errors.append(f"seed {item.seed} horizon 不是 primary H")
            if item.experiment_spec_sha256 != spec.sha256:
                errors.append(f"seed {item.seed} experiment spec hash 不匹配")
            if item.environment_config_sha256 != expected_environment_sha256:
                errors.append(f"seed {item.seed} environment config hash 不匹配")
            if entry is None:
                errors.append(f"seed {item.seed} 在 inventory 中不存在")
            else:
                if item.trace_id != entry.relative_path:
                    errors.append(f"seed {item.seed} trace/artifact identity 不匹配")
                if item.artifact_config_sha256 != entry.config_sha256:
                    errors.append(f"seed {item.seed} artifact config hash 不匹配")
                if item.artifact_content_sha256 != entry.content_sha256:
                    errors.append(f"seed {item.seed} artifact content hash 不匹配")
            if item.protocol_failure is not None:
                errors.append(f"seed {item.seed} 包含 protocol failure")
            if item.reactive_metrics.arrived != item.oracle_metrics.arrived:
                errors.append(f"seed {item.seed} arrived denominator 不一致")
            if not math.isfinite(item.primary_difference):
                errors.append(f"seed {item.seed} primary difference 非有限")
            elif item.reactive_metrics.arrived == item.oracle_metrics.arrived:
                arrived = item.reactive_metrics.arrived
                expected_difference = (
                    0.0
                    if arrived == 0
                    else (item.oracle_metrics.completed - item.reactive_metrics.completed) / arrived
                )
                if item.primary_difference != expected_difference:
                    errors.append(f"seed {item.seed} primary difference 与 metrics 不一致")
    return tuple(errors)


def validate_primary_paired_results(
    results: Sequence[PairedTraceResult],
    spec: H1GateSpec,
    inventory: ArtifactInventory,
) -> None:
    """严格验证完整 formal paired results，不执行 bootstrap。"""

    errors = _primary_protocol_errors(results, spec, inventory)
    if errors:
        raise H1ProtocolError("primary paired results 协议校验失败：" + "; ".join(errors))


def evaluate_primary_gate(
    results: Sequence[PairedTraceResult],
    spec: H1GateSpec,
    inventory: ArtifactInventory,
) -> H1GateSummary:
    """绑定 spec、validated inventory 和 256 条 results 后执行唯一 gate rule。"""

    result_tuple = tuple(results)
    errors = _primary_protocol_errors(result_tuple, spec, inventory)
    if errors:
        return _protocol_fail_summary(spec, errors)
    bootstrap = cast(Mapping[str, object], spec.config["bootstrap"])
    gate = cast(Mapping[str, object], spec.config["gate"])
    return _scientific_summary(
        result_tuple,
        delta_min=cast(float, gate["delta_min"]),
        resamples=cast(int, bootstrap["resamples"]),
        bootstrap_seed=cast(int, bootstrap["seed"]),
        n_planned=spec.planned_seed_count,
    )


def paired_result_to_dict(result: PairedTraceResult) -> dict[str, object]:
    """返回一条 paired result 的 JSON-compatible 普通树。"""

    if not isinstance(result, PairedTraceResult):
        raise TypeError("result 必须是 PairedTraceResult")
    return cast(dict[str, object], asdict(result))


def compute_paired_results_hash(results: Sequence[PairedTraceResult]) -> str:
    """对完整、按 formal seed 顺序排列的 paired results 计算规范哈希。"""

    result_tuple = tuple(results)
    if not all(isinstance(result, PairedTraceResult) for result in result_tuple):
        raise TypeError("results 中每一项都必须是 PairedTraceResult")
    seed_protocol = cast(Mapping[str, object], _frozen_config()["seed_protocol"])
    base_seed = cast(int, seed_protocol["base_seed"])
    count = cast(int, seed_protocol["count"])
    expected_seeds = tuple(base_seed + index for index in range(count))
    if tuple(result.seed for result in result_tuple) != expected_seeds:
        raise H1ProtocolError("results 必须按完整 formal seed 顺序排列")
    payload: dict[str, object] = {
        "schema": "fura-mappo.wp02d-paired-results",
        "version": 1,
        "results": [paired_result_to_dict(result) for result in result_tuple],
    }
    canonical_payload = _canonical_json_bytes(payload).decode("utf-8")
    return compute_config_hash({"canonical_paired_results_json": canonical_payload})


def summary_to_dict(summary: H1GateSummary) -> dict[str, object]:
    """返回 H1 summary 的 JSON-compatible 普通树。"""

    if not isinstance(summary, H1GateSummary):
        raise TypeError("summary 必须是 H1GateSummary")
    return {
        "verdict": summary.verdict.value,
        "n_planned": summary.n_planned,
        "n_valid": summary.n_valid,
        "point_estimate": summary.point_estimate,
        "one_sided_lcb": summary.one_sided_lcb,
        "one_sided_ucb": summary.one_sided_ucb,
        "two_sided_interval": summary.two_sided_interval,
        "delta_min": summary.delta_min,
        "bootstrap_resamples": summary.bootstrap_resamples,
        "bootstrap_seed": summary.bootstrap_seed,
        "secondary": _plain_tree(summary.secondary),
        "diagnostics": _plain_tree(summary.diagnostics),
        "protocol_errors": summary.protocol_errors,
        "schema": summary.schema,
        "version": summary.version,
    }


def _canonical_json_bytes(value: object) -> bytes:
    """编码无 NaN、稳定键序的 canonical UTF-8 JSON。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_protocol_bytes(value: object, name: str) -> bytes:
    """在 reader 边界把任何 canonical 编码失败统一为协议错误。"""

    try:
        return _canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        raise H1ProtocolError(f"{name} 包含无法 canonical 编码的 JSON 值") from error


def _read_protocol_bytes(path: Path, name: str) -> bytes:
    """限长读取 protocol 文件。"""

    with path.open("rb") as stream:
        payload = stream.read(_MAX_PROTOCOL_JSON_BYTES + 1)
    if len(payload) > _MAX_PROTOCOL_JSON_BYTES:
        raise H1ProtocolError(f"{name} 超出安全大小上限")
    return payload


def _strict_json_object(payload: bytes, name: str) -> dict[str, object]:
    """解析一个严格 JSON object，并拒绝重复键与非有限常量。"""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise H1ProtocolError(f"{name} 必须是有效 UTF-8 JSON") from error

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise H1ProtocolError(f"{name} JSON 包含重复键 {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise H1ProtocolError(f"{name} JSON 不允许常量 {value}")

    try:
        loaded = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as error:
        raise H1ProtocolError(f"{name} 不是有效严格 JSON") from error
    if not isinstance(loaded, dict):
        raise H1ProtocolError(f"{name} 顶层必须是 JSON object")
    return loaded


def _read_protocol_json_object(
    path: Path,
    name: str,
    *,
    require_canonical: bool = False,
) -> dict[str, object]:
    """限长读取严格 JSON object，可要求 writer 的 canonical bytes。"""

    payload = _read_protocol_bytes(path, name)
    loaded = _strict_json_object(payload, name)
    if require_canonical and payload != _canonical_protocol_bytes(loaded, name) + b"\n":
        raise H1ProtocolError(f"{name} 不是 canonical JSON representation")
    return loaded


def _require_json_integer(value: object, name: str, *, minimum: int = 0) -> int:
    """在 artifact/protocol 边界读取非 bool JSON 整数。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise H1ProtocolError(f"{name} 必须是整数且不能是布尔值")
    if value < minimum:
        raise H1ProtocolError(f"{name} 必须大于或等于 {minimum}")
    return value


def _require_json_finite(value: object, name: str) -> float:
    """在 artifact/protocol 边界读取有限 JSON 实数。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise H1ProtocolError(f"{name} 必须是有限实数")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise H1ProtocolError(f"{name} 必须是有限实数")
    return normalized


_EPISODE_INTEGER_FIELDS = frozenset(
    {
        "arrived",
        "completed",
        "expired",
        "truncated",
        "demanded_service_work",
        "service_slots",
        "movement_slots",
        "idle_slots",
        "completed_service_work",
        "expired_service_work",
        "truncated_service_work",
        "expired_remaining_work",
        "truncated_remaining_work",
        "service_start_wait_sum",
        "service_start_count",
        "completed_response_sum",
        "completed_response_count",
        "duplicate_assignment_conflicts",
        "zero_distance_moves",
    }
)
_EPISODE_FINITE_FIELDS = frozenset(
    {
        "arrived_priority_sum",
        "completed_priority_sum",
        "expired_priority_sum",
        "truncated_priority_sum",
        "movement_distance",
    }
)
_EPISODE_ZONE_FIELDS = frozenset(
    {
        "per_zone_arrived",
        "per_zone_completed",
        "per_zone_expired",
        "per_zone_truncated",
    }
)
_EPISODE_OPTIONAL_FINITE_FIELDS = frozenset(
    {
        "completion_rate",
        "expiration_rate",
        "truncation_rate",
        "mean_service_start_wait",
        "mean_completed_response",
    }
)


def _episode_metrics_from_json(value: object, name: str) -> EpisodeMetrics:
    """从 exact JSON schema 重建并验证 EpisodeMetrics。"""

    expected_fields = {item.name for item in fields(EpisodeMetrics)}
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise H1ProtocolError(f"{name} 字段集合错误")
    normalized: dict[str, object] = {}
    for field_name in _EPISODE_INTEGER_FIELDS:
        normalized[field_name] = _require_json_integer(
            value[field_name],
            f"{name}.{field_name}",
        )
    for field_name in _EPISODE_FINITE_FIELDS:
        normalized[field_name] = _require_json_finite(
            value[field_name],
            f"{name}.{field_name}",
        )
    for field_name in _EPISODE_ZONE_FIELDS:
        items = value[field_name]
        if not isinstance(items, list) or not items:
            raise H1ProtocolError(f"{name}.{field_name} 必须是非空数组")
        normalized[field_name] = tuple(
            _require_json_integer(item, f"{name}.{field_name}[{index}]")
            for index, item in enumerate(items)
        )
    for field_name in _EPISODE_OPTIONAL_FINITE_FIELDS:
        item = value[field_name]
        normalized[field_name] = (
            None if item is None else _require_json_finite(item, f"{name}.{field_name}")
        )
    try:
        metrics = EpisodeMetrics(**normalized)  # type: ignore[arg-type]
        _validate_episode_metrics(metrics, name)
    except (TypeError, ValueError) as error:
        raise H1ProtocolError(f"{name} 内容错误：{error}") from error
    return metrics


def _paired_result_from_json(value: object, index: int) -> PairedTraceResult:
    """从 exact JSON schema 重建一条 PairedTraceResult。"""

    name = f"paired results line {index + 1}"
    expected_fields = {item.name for item in fields(PairedTraceResult)}
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise H1ProtocolError(f"{name} 字段集合错误")
    string_fields = (
        "trace_id",
        "experiment_spec_sha256",
        "artifact_config_sha256",
        "artifact_content_sha256",
        "environment_config_sha256",
        "schema",
    )
    for field_name in string_fields:
        if not isinstance(value[field_name], str):
            raise H1ProtocolError(f"{name}.{field_name} 必须是字符串")
    integer_fields = (
        "seed",
        "horizon",
        "reference_nonempty_view_steps",
        "reference_feasible_future_pair_steps",
        "reference_oracle_would_differ_steps",
        "reference_oracle_would_preposition_steps",
        "actionable_steps",
        "realized_oracle_prearrival_move_steps",
        "oracle_actionable_steps",
    )
    normalized: dict[str, object] = {
        field_name: _require_json_integer(value[field_name], f"{name}.{field_name}")
        for field_name in integer_fields
    }
    normalized["version"] = _require_json_integer(
        value["version"],
        f"{name}.version",
        minimum=1,
    )
    for field_name in (
        "has_reference_feasible_future_pair",
        "has_reference_oracle_action_difference",
    ):
        if type(value[field_name]) is not bool:
            raise H1ProtocolError(f"{name}.{field_name} 必须是 bool")
        normalized[field_name] = value[field_name]
    protocol_failure = value["protocol_failure"]
    if protocol_failure is not None and (
        not isinstance(protocol_failure, str) or not protocol_failure
    ):
        raise H1ProtocolError(f"{name}.protocol_failure 必须是非空字符串或 null")
    normalized.update({field_name: value[field_name] for field_name in string_fields})
    normalized["protocol_failure"] = protocol_failure
    normalized["primary_difference"] = _require_json_finite(
        value["primary_difference"],
        f"{name}.primary_difference",
    )
    normalized["reactive_metrics"] = _episode_metrics_from_json(
        value["reactive_metrics"],
        f"{name}.reactive_metrics",
    )
    normalized["oracle_metrics"] = _episode_metrics_from_json(
        value["oracle_metrics"],
        f"{name}.oracle_metrics",
    )
    try:
        return PairedTraceResult(**normalized)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise H1ProtocolError(f"{name} 内容错误：{error}") from error


def read_paired_jsonl(
    path: str | os.PathLike[str],
    spec: H1GateSpec,
    inventory: ArtifactInventory,
) -> tuple[PairedTraceResult, ...]:
    """严格回读 canonical formal paired JSONL 并复用 primary protocol validation。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    if not isinstance(inventory, ArtifactInventory):
        raise TypeError("inventory 必须是 ArtifactInventory")
    target = _coerce_output_path(path)
    if target.is_symlink():
        raise H1ProtocolError("paired results 不能是符号链接")
    payload = _read_protocol_bytes(target, "paired results")
    if not payload.endswith(b"\n"):
        raise H1ProtocolError("paired results 必须以单个 canonical newline 结束")
    raw_lines = payload[:-1].split(b"\n")
    if any(not line for line in raw_lines):
        raise H1ProtocolError("paired results 不允许 blank line")
    if len(raw_lines) != spec.planned_seed_count:
        raise H1ProtocolError("paired results 行数必须精确等于 planned seed count")
    results: list[PairedTraceResult] = []
    for index, line in enumerate(raw_lines):
        loaded = _strict_json_object(line, f"paired results line {index + 1}")
        line_name = f"paired results line {index + 1}"
        if line != _canonical_protocol_bytes(loaded, line_name):
            raise H1ProtocolError(
                f"paired results line {index + 1} 不是 canonical JSON representation"
            )
        result = _paired_result_from_json(loaded, index)
        if line != _canonical_protocol_bytes(paired_result_to_dict(result), line_name):
            raise H1ProtocolError(
                f"paired results line {index + 1} scalar types 不是 writer canonical representation"
            )
        results.append(result)
    result_tuple = tuple(results)
    validate_primary_paired_results(result_tuple, spec, inventory)
    compute_paired_results_hash(result_tuple)
    return result_tuple


def read_artifact_inventory(
    path: str | os.PathLike[str],
    spec: H1GateSpec,
    artifact_root: str | os.PathLike[str],
) -> ArtifactInventory:
    """严格回读 inventory JSON，并安全验证其全部 primary artifacts。"""

    if not isinstance(spec, H1GateSpec):
        raise TypeError("spec 必须是 H1GateSpec")
    inventory_path = _coerce_output_path(path)
    if inventory_path.is_symlink():
        raise H1ProtocolError("artifact inventory 不能是符号链接")
    loaded = _read_protocol_json_object(inventory_path, "artifact inventory")
    expected_fields = {
        "experiment_spec_sha256",
        "wp02c_stable_sha",
        "planned_seed_count",
        "entries",
        "schema",
        "version",
    }
    if set(loaded) != expected_fields:
        raise H1ProtocolError("artifact inventory 顶层字段集合错误")
    if (
        loaded["schema"] != _INVENTORY_SCHEMA
        or _require_json_integer(
            loaded["version"],
            "artifact inventory version",
            minimum=1,
        )
        != _INVENTORY_VERSION
    ):
        raise H1ProtocolError("artifact inventory schema/version 不受支持")
    entries_value = loaded["entries"]
    if not isinstance(entries_value, list):
        raise H1ProtocolError("artifact inventory entries 必须是数组")
    entry_fields = {
        "seed",
        "relative_path",
        "process_type",
        "config_sha256",
        "content_sha256",
        "start_step",
        "num_steps",
        "num_events",
    }
    entries: list[ArtifactInventoryEntry] = []
    for index, value in enumerate(entries_value):
        if not isinstance(value, dict) or set(value) != entry_fields:
            raise H1ProtocolError(f"artifact inventory entries[{index}] 字段集合错误")
        string_fields = (
            "relative_path",
            "process_type",
            "config_sha256",
            "content_sha256",
        )
        if any(not isinstance(value[name], str) for name in string_fields):
            raise H1ProtocolError(f"artifact inventory entries[{index}] 字符串字段类型错误")
        try:
            entry = ArtifactInventoryEntry(
                seed=_require_json_integer(value["seed"], f"entries[{index}].seed"),
                relative_path=cast(str, value["relative_path"]),
                process_type=cast(str, value["process_type"]),
                config_sha256=cast(str, value["config_sha256"]),
                content_sha256=cast(str, value["content_sha256"]),
                start_step=_require_json_integer(
                    value["start_step"],
                    f"entries[{index}].start_step",
                ),
                num_steps=_require_json_integer(
                    value["num_steps"],
                    f"entries[{index}].num_steps",
                    minimum=1,
                ),
                num_events=_require_json_integer(
                    value["num_events"],
                    f"entries[{index}].num_events",
                ),
            )
        except (TypeError, ValueError) as error:
            raise H1ProtocolError(
                f"artifact inventory entries[{index}] 内容错误：{error}"
            ) from error
        entries.append(entry)
    try:
        inventory = ArtifactInventory(
            experiment_spec_sha256=cast(str, loaded["experiment_spec_sha256"]),
            wp02c_stable_sha=cast(str, loaded["wp02c_stable_sha"]),
            planned_seed_count=_require_json_integer(
                loaded["planned_seed_count"],
                "artifact inventory planned_seed_count",
                minimum=1,
            ),
            entries=tuple(entries),
            schema=cast(str, loaded["schema"]),
            version=cast(int, loaded["version"]),
        )
    except (TypeError, ValueError) as error:
        raise H1ProtocolError(f"artifact inventory 内容错误：{error}") from error
    validate_primary_artifact_inventory(spec, inventory, artifact_root)
    return inventory


def _summary_from_payload(value: object, name: str) -> H1GateSummary:
    """从 exact JSON payload 重建所有合法 verdict 的 H1GateSummary。"""

    if not isinstance(value, dict):
        raise H1ProtocolError(f"{name} 必须是 object")
    expected_fields = {
        "verdict",
        "n_planned",
        "n_valid",
        "point_estimate",
        "one_sided_lcb",
        "one_sided_ucb",
        "two_sided_interval",
        "delta_min",
        "bootstrap_resamples",
        "bootstrap_seed",
        "secondary",
        "diagnostics",
        "protocol_errors",
        "schema",
        "version",
    }
    if set(value) != expected_fields:
        raise H1ProtocolError(f"{name} 字段集合错误")
    if (
        value["schema"] != _SUMMARY_SCHEMA
        or _require_json_integer(
            value["version"],
            "summary.version",
            minimum=1,
        )
        != _SUMMARY_VERSION
    ):
        raise H1ProtocolError(f"{name} schema/version 错误")
    try:
        verdict = H1Verdict(value["verdict"])
    except (TypeError, ValueError) as error:
        raise H1ProtocolError(f"{name} verdict 不受支持") from error
    n_planned = _require_json_integer(value["n_planned"], "summary.n_planned", minimum=1)
    if n_planned != 256:
        raise H1ProtocolError(f"{name} n_planned 必须精确为 256")
    n_valid = _require_json_integer(value["n_valid"], "summary.n_valid")
    if n_valid > n_planned:
        raise H1ProtocolError(f"{name} n_valid 不能超过 n_planned")
    if (
        _require_json_integer(
            value["bootstrap_resamples"],
            "summary.bootstrap_resamples",
            minimum=1,
        )
        != 50_000
    ):
        raise H1ProtocolError(f"{name} bootstrap_resamples 必须精确为 50000")
    if _require_json_integer(value["bootstrap_seed"], "summary.bootstrap_seed") != 90_260_819:
        raise H1ProtocolError(f"{name} bootstrap_seed 不匹配")
    delta_min = _require_json_finite(value["delta_min"], "summary.delta_min")
    if delta_min != 0.02:
        raise H1ProtocolError(f"{name} delta_min 不匹配")
    protocol_errors = value["protocol_errors"]
    if not isinstance(protocol_errors, list) or not all(
        isinstance(item, str) and item for item in protocol_errors
    ):
        raise H1ProtocolError(f"{name} protocol_errors 类型错误")

    secondary = value["secondary"]
    diagnostics = value["diagnostics"]
    point: float | None
    lower: float | None
    upper: float | None
    normalized_interval: tuple[float, float] | None
    normalized_secondary: dict[str, object] = {}
    normalized_diagnostics: dict[str, object] = {}
    if verdict is H1Verdict.PROTOCOL_FAIL:
        if n_valid > n_planned:
            raise H1ProtocolError(f"{name} n_valid 错误")
        if (
            any(
                value[field_name] is not None
                for field_name in ("point_estimate", "one_sided_lcb", "one_sided_ucb")
            )
            or value["two_sided_interval"] is not None
        ):
            raise H1ProtocolError(f"{name} PROTOCOL_FAIL 不得包含 scientific estimate")
        if not protocol_errors:
            raise H1ProtocolError(f"{name} PROTOCOL_FAIL 必须记录 protocol_errors")
        if secondary != {} or diagnostics != {}:
            raise H1ProtocolError(f"{name} PROTOCOL_FAIL summary components 必须为空")
        point = lower = upper = None
        normalized_interval = None
    else:
        if n_valid != 256:
            raise H1ProtocolError(f"{name} scientific n_valid 必须精确为 256")
        if protocol_errors:
            raise H1ProtocolError(f"{name} scientific verdict 不得包含 protocol_errors")
        point = _require_json_finite(value["point_estimate"], "summary.point_estimate")
        lower = _require_json_finite(value["one_sided_lcb"], "summary.one_sided_lcb")
        upper = _require_json_finite(value["one_sided_ucb"], "summary.one_sided_ucb")
        interval = value["two_sided_interval"]
        if not isinstance(interval, list) or len(interval) != 2:
            raise H1ProtocolError("summary.two_sided_interval 必须是两个端点的数组")
        two_lower = _require_json_finite(interval[0], "summary.two_sided_interval[0]")
        two_upper = _require_json_finite(interval[1], "summary.two_sided_interval[1]")
        normalized_interval = (two_lower, two_upper)
        if not (-1.0 <= two_lower <= lower <= upper <= two_upper <= 1.0):
            raise H1ProtocolError(f"{name} bootstrap quantile 顺序或范围错误")
        if not -1.0 <= point <= 1.0:
            raise H1ProtocolError(f"{name} point_estimate 超出合法范围")
        expected_verdict = (
            H1Verdict.PASS
            if point >= delta_min and lower > 0.0
            else H1Verdict.FAIL
            if upper < delta_min
            else H1Verdict.INCONCLUSIVE
        )
        if verdict is not expected_verdict:
            raise H1ProtocolError(f"{name} 与冻结 gate rule 不一致")
        if not isinstance(secondary, dict) or set(secondary) != set(_SECONDARY_FIELDS):
            raise H1ProtocolError(f"{name} secondary 字段集合错误")
        if not isinstance(diagnostics, dict) or set(diagnostics) != set(_DIAGNOSTIC_SUMMARY_FIELDS):
            raise H1ProtocolError(f"{name} diagnostics 字段集合错误")

    optional_secondary = {
        "completion_rate",
        "expiration_rate",
        "truncation_rate",
        "mean_service_start_wait",
        "mean_completed_response",
    }
    if verdict is not H1Verdict.PROTOCOL_FAIL:
        for metric, pair in secondary.items():
            if not isinstance(pair, dict) or set(pair) != {"reactive_mean", "oracle_mean"}:
                raise H1ProtocolError(f"secondary.{metric} 字段集合错误")
            normalized_pair: dict[str, float | None] = {}
            for controller in ("reactive_mean", "oracle_mean"):
                item = pair[controller]
                if item is None and metric in optional_secondary:
                    normalized_pair[controller] = None
                    continue
                normalized = _require_json_finite(item, f"secondary.{metric}.{controller}")
                if normalized < 0.0:
                    raise H1ProtocolError(f"secondary.{metric}.{controller} 必须非负")
                normalized_pair[controller] = normalized
            normalized_secondary[metric] = normalized_pair
        for diagnostic_name, item in diagnostics.items():
            if item is None:
                normalized_diagnostics[diagnostic_name] = None
                continue
            normalized = _require_json_finite(item, f"diagnostics.{diagnostic_name}")
            if not 0.0 <= normalized <= 1.0:
                raise H1ProtocolError(f"diagnostics.{diagnostic_name} 必须位于 [0, 1]")
            normalized_diagnostics[diagnostic_name] = normalized

    try:
        return H1GateSummary(
            verdict=verdict,
            n_planned=n_planned,
            n_valid=n_valid,
            point_estimate=point,
            one_sided_lcb=lower,
            one_sided_ucb=upper,
            two_sided_interval=normalized_interval,
            delta_min=delta_min,
            bootstrap_resamples=cast(int, value["bootstrap_resamples"]),
            bootstrap_seed=cast(int, value["bootstrap_seed"]),
            secondary=normalized_secondary,
            diagnostics=normalized_diagnostics,
            protocol_errors=tuple(protocol_errors),
            schema=cast(str, value["schema"]),
            version=cast(int, value["version"]),
        )
    except (TypeError, ValueError) as error:
        raise H1ProtocolError(f"{name} 内容错误：{error}") from error


def _validate_summary_payload(value: object) -> H1GateSummary:
    """严格验证 formal primary verdict 内嵌 summary，不执行 sensitivity unlock。"""

    return _summary_from_payload(value, "primary verdict summary")


def read_h1_summary(path: str | os.PathLike[str]) -> H1GateSummary:
    """严格回读 canonical aggregate，并支持所有合法 formal verdict。"""

    target = _coerce_output_path(path)
    if target.is_symlink():
        raise H1ProtocolError("H1 aggregate 不能是符号链接")
    loaded = _read_protocol_json_object(target, "H1 aggregate", require_canonical=True)
    summary = _summary_from_payload(loaded, "H1 aggregate")
    if _canonical_protocol_bytes(
        summary_to_dict(summary),
        "H1 aggregate normalized summary",
    ) != _canonical_protocol_bytes(loaded, "H1 aggregate"):
        raise H1ProtocolError("H1 aggregate canonical readback 不一致")
    return summary


def _coerce_output_path(path: str | os.PathLike[str]) -> Path:
    """规范化非 bytes 输出路径。"""

    if isinstance(path, bytes):
        raise TypeError("path 不能是 bytes")
    try:
        raw = os.fspath(path)
    except TypeError as error:
        raise TypeError("path 必须是 str 或 os.PathLike[str]") from error
    if isinstance(raw, bytes):
        raise TypeError("path 不能是 bytes")
    return Path(raw)


def _fsync_protocol_parent(parent: Path) -> None:
    """同步 protocol publication 目录项，仅忽略明确不支持目录 fsync 的平台错误。"""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(parent, flags)
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            unsupported = {errno.EINVAL, errno.ENOTSUP}
            if hasattr(errno, "EOPNOTSUPP"):
                unsupported.add(errno.EOPNOTSUPP)
            if error.errno not in unsupported:
                raise
    finally:
        os.close(descriptor)


def _atomic_write_new(path: Path, payload: bytes) -> Path:
    """原子创建新文件，默认拒绝覆盖与符号链接。"""

    if not path.parent.is_dir():
        raise FileNotFoundError("输出目录不存在或不是目录")
    if path.is_symlink() or os.path.lexists(path):
        raise FileExistsError("输出目标已存在或是符号链接")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    published = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        published = True
    finally:
        if not published:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    temporary.unlink()
    _fsync_protocol_parent(path.parent)
    return path


def write_canonical_json(path: str | os.PathLike[str], value: object) -> Path:
    """原子写入带末尾换行的 canonical JSON，且不覆盖。"""

    target = _coerce_output_path(path)
    return _atomic_write_new(target, _canonical_json_bytes(value) + b"\n")


def write_paired_jsonl(
    path: str | os.PathLike[str],
    results: Sequence[PairedTraceResult],
) -> Path:
    """按调用方确定顺序原子写入 paired JSONL。"""

    lines = [_canonical_json_bytes(paired_result_to_dict(result)) for result in results]
    payload = b"\n".join(lines) + (b"\n" if lines else b"")
    return _atomic_write_new(_coerce_output_path(path), payload)


def write_artifact_inventory(
    path: str | os.PathLike[str],
    inventory: ArtifactInventory,
) -> Path:
    """原子写入 schema-checked artifact inventory JSON。"""

    return write_canonical_json(path, inventory_to_dict(inventory))


def write_h1_summary(
    path: str | os.PathLike[str],
    summary: H1GateSummary,
) -> Path:
    """原子写入 schema-checked aggregate H1 summary JSON。"""

    return write_canonical_json(path, summary_to_dict(summary))


def write_primary_verdict(
    path: str | os.PathLike[str],
    summary: H1GateSummary,
    experiment_spec_sha256: str,
    artifact_inventory_sha256: str,
    paired_results_sha256: str,
    formal_provenance: FormalProvenance,
) -> Path:
    """原子锁定 primary verdict；PROTOCOL_FAIL 不允许进入 sensitivity。"""

    for value, name in (
        (experiment_spec_sha256, "experiment_spec_sha256"),
        (artifact_inventory_sha256, "artifact_inventory_sha256"),
        (paired_results_sha256, "paired_results_sha256"),
    ):
        if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{name} 格式错误")
    _validate_verdict_formal_provenance(formal_provenance, experiment_spec_sha256)
    payload: dict[str, object] = {
        "schema": _VERDICT_SCHEMA,
        "version": _VERDICT_VERSION,
        "experiment_spec_sha256": experiment_spec_sha256,
        "artifact_inventory_sha256": artifact_inventory_sha256,
        "paired_results_sha256": paired_results_sha256,
        "wp02d_accepted_implementation_sha": (formal_provenance.wp02d_accepted_implementation_sha),
        "actual_execution_head": formal_provenance.actual_head,
        "summary": summary_to_dict(summary),
    }
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    payload["payload_sha256"] = digest
    return write_canonical_json(path, payload)


def read_primary_verdict(
    path: str | os.PathLike[str],
    *,
    expected_spec_sha256: str,
    expected_artifact_inventory_sha256: str,
    expected_paired_results_sha256: str,
    expected_formal_provenance: FormalProvenance,
) -> Mapping[str, object]:
    """回读、校验并递归冻结 primary verdict 文件。"""

    for value, name in (
        (expected_spec_sha256, "expected_spec_sha256"),
        (expected_artifact_inventory_sha256, "expected_artifact_inventory_sha256"),
        (expected_paired_results_sha256, "expected_paired_results_sha256"),
    ):
        if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{name} 格式错误")
    _validate_verdict_formal_provenance(
        expected_formal_provenance,
        expected_spec_sha256,
    )
    target = _coerce_output_path(path)
    if target.is_symlink():
        raise H1ProtocolError("primary verdict 不能是符号链接")
    loaded = _read_protocol_json_object(
        target,
        "primary verdict",
        require_canonical=True,
    )
    if set(loaded) != {
        "schema",
        "version",
        "experiment_spec_sha256",
        "artifact_inventory_sha256",
        "paired_results_sha256",
        "wp02d_accepted_implementation_sha",
        "actual_execution_head",
        "summary",
        "payload_sha256",
    }:
        raise H1ProtocolError("primary verdict 字段集合错误")
    if (
        loaded["schema"] != _VERDICT_SCHEMA
        or _require_json_integer(
            loaded["version"],
            "primary verdict version",
            minimum=1,
        )
        != _VERDICT_VERSION
    ):
        raise H1ProtocolError("primary verdict schema/version 错误")
    if loaded["experiment_spec_sha256"] != expected_spec_sha256:
        raise H1ProtocolError("primary verdict experiment spec hash 不匹配")
    if loaded["artifact_inventory_sha256"] != expected_artifact_inventory_sha256:
        raise H1ProtocolError("primary verdict artifact inventory hash 不匹配")
    if loaded["paired_results_sha256"] != expected_paired_results_sha256:
        raise H1ProtocolError("primary verdict paired results hash 不匹配")
    if (
        loaded["wp02d_accepted_implementation_sha"]
        != expected_formal_provenance.wp02d_accepted_implementation_sha
    ):
        raise H1ProtocolError("primary verdict accepted implementation SHA 不匹配")
    if loaded["actual_execution_head"] != expected_formal_provenance.actual_head:
        raise H1ProtocolError("primary verdict actual execution HEAD 不匹配")
    recorded_hash = loaded.pop("payload_sha256")
    if not isinstance(recorded_hash, str) or _SHA256_PATTERN.fullmatch(recorded_hash) is None:
        raise H1ProtocolError("primary verdict payload_sha256 格式错误")
    actual_hash = hashlib.sha256(
        _canonical_protocol_bytes(loaded, "primary verdict payload")
    ).hexdigest()
    if recorded_hash != actual_hash:
        raise H1ProtocolError("primary verdict payload hash 校验失败")
    loaded["payload_sha256"] = recorded_hash
    summary = loaded.get("summary")
    normalized_summary = _validate_summary_payload(summary)
    if _canonical_protocol_bytes(
        summary_to_dict(normalized_summary),
        "primary verdict normalized summary",
    ) != _canonical_protocol_bytes(summary, "primary verdict embedded summary"):
        raise H1ProtocolError(
            "primary verdict embedded summary 不是 writer canonical representation"
        )
    frozen = _freeze_tree(loaded)
    if not isinstance(frozen, Mapping):
        raise RuntimeError("冻结 verdict 必须保持 Mapping")
    return frozen


def require_locked_primary_verdict(
    path: str | os.PathLike[str],
    spec: H1GateSpec,
    *,
    expected_artifact_inventory_sha256: str,
    expected_paired_results_sha256: str,
    expected_formal_provenance: FormalProvenance,
) -> None:
    """在任何 sensitivity execution 前强制验证已锁定 primary verdict。"""

    loaded = read_primary_verdict(
        path,
        expected_spec_sha256=spec.sha256,
        expected_artifact_inventory_sha256=expected_artifact_inventory_sha256,
        expected_paired_results_sha256=expected_paired_results_sha256,
        expected_formal_provenance=expected_formal_provenance,
    )
    summary = loaded["summary"]
    if not isinstance(summary, Mapping) or summary.get("verdict") == H1Verdict.PROTOCOL_FAIL.value:
        raise H1ProtocolError("PROTOCOL_FAIL verdict 不能解锁 sensitivity")


@dataclass(frozen=True, slots=True)
class FormalProvenance:
    """通过 formal hard gate 后的本地 Git provenance。"""

    actual_head: str
    origin_main: str
    wp02c_stable_sha: str
    wp02d_accepted_implementation_sha: str
    experiment_spec_sha256: str
    git_dirty: bool


def _validate_verdict_formal_provenance(
    provenance: FormalProvenance,
    expected_spec_sha256: str,
) -> None:
    """验证 verdict 中记录的 formal Git provenance 已通过 hard gate。"""

    if not isinstance(provenance, FormalProvenance):
        raise TypeError("formal_provenance 必须是 FormalProvenance")
    for value, name in (
        (provenance.actual_head, "actual_head"),
        (provenance.origin_main, "origin_main"),
        (provenance.wp02c_stable_sha, "wp02c_stable_sha"),
        (
            provenance.wp02d_accepted_implementation_sha,
            "wp02d_accepted_implementation_sha",
        ),
    ):
        if not isinstance(value, str) or _GIT_SHA_PATTERN.fullmatch(value) is None:
            raise ValueError(f"formal_provenance.{name} 格式错误")
    if provenance.actual_head != provenance.origin_main:
        raise H1ProtocolError("formal provenance 要求 actual HEAD == origin/main")
    if provenance.experiment_spec_sha256 != expected_spec_sha256:
        raise H1ProtocolError("formal provenance experiment spec hash 不匹配")
    if provenance.git_dirty is not False:
        raise H1ProtocolError("formal provenance 必须记录 clean Git 状态")


def _git(repository: Path, *arguments: str, allow_nonzero: bool = False) -> str:
    """在指定仓库执行无网络、只读 Git 命令。"""

    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0 and not allow_nonzero:
        raise H1ProtocolError(f"Git provenance 命令失败: git {' '.join(arguments)}")
    return result.stdout.strip() if result.returncode == 0 else ""


def validate_formal_provenance(
    repository: str | os.PathLike[str],
    spec: H1GateSpec,
    *,
    wp02d_accepted_implementation_sha: str,
) -> FormalProvenance:
    """验证 clean main lineage、origin identity 与 accepted-code 后续文件范围。"""

    if _GIT_SHA_PATTERN.fullmatch(wp02d_accepted_implementation_sha) is None:
        raise ValueError("wp02d_accepted_implementation_sha 必须是完整 Commit SHA")
    root = Path(repository)
    status = _git(root, "status", "--porcelain=v1")
    if status:
        raise H1ProtocolError("formal run 要求 working tree/index/untracked 全部干净")
    head = _git(root, "rev-parse", "HEAD")
    origin_main = _git(root, "rev-parse", "origin/main")
    if head != origin_main:
        raise H1ProtocolError("formal run 要求 actual HEAD == origin/main")
    for ancestor, name in (
        (spec.wp02c_stable_sha, "WP-02C stable SHA"),
        (wp02d_accepted_implementation_sha, "WP-02D accepted SHA"),
    ):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, head],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise H1ProtocolError(f"{name} 必须是 actual HEAD ancestor")
    if head != wp02d_accepted_implementation_sha:
        changed = _git(
            root,
            "diff",
            "--name-only",
            f"{wp02d_accepted_implementation_sha}..{head}",
        ).splitlines()
        forbidden = [
            path
            for path in changed
            if not (path.startswith("docs/") or path.startswith("CHANGELOG_"))
        ]
        if forbidden:
            raise H1ProtocolError(
                "accepted SHA 后仅允许 docs/changelog 变更；发现: " + ", ".join(forbidden)
            )
    return FormalProvenance(
        actual_head=head,
        origin_main=origin_main,
        wp02c_stable_sha=spec.wp02c_stable_sha,
        wp02d_accepted_implementation_sha=wp02d_accepted_implementation_sha,
        experiment_spec_sha256=spec.sha256,
        git_dirty=False,
    )


__all__ = [
    "ArtifactInventory",
    "ArtifactInventoryEntry",
    "ArtifactPlanEntry",
    "FormalProvenance",
    "H1GateSpec",
    "H1GateSummary",
    "H1ProtocolError",
    "H1Verdict",
    "PairedTraceResult",
    "build_primary_artifact_inventory",
    "build_primary_demand_config",
    "build_primary_environment_config",
    "build_provenance_bound_artifact_entry",
    "compute_artifact_inventory_hash",
    "compute_environment_config_hash",
    "compute_h1_spec_hash",
    "compute_paired_results_hash",
    "evaluate_primary_gate",
    "inventory_to_dict",
    "load_h1_gate_spec",
    "paired_result_to_dict",
    "plan_primary_artifacts",
    "primary_seeds",
    "read_artifact_inventory",
    "read_h1_summary",
    "read_paired_jsonl",
    "read_primary_verdict",
    "require_locked_primary_verdict",
    "run_paired_trace",
    "run_primary_artifact",
    "summary_to_dict",
    "summarize_paired_results",
    "validate_canonical_mechanism",
    "validate_formal_provenance",
    "validate_h0_invariant",
    "validate_primary_artifact_inventory",
    "validate_primary_paired_results",
    "write_canonical_json",
    "write_artifact_inventory",
    "write_h1_summary",
    "write_paired_jsonl",
    "write_primary_verdict",
]
