"""严格需求配置加载与稳定配置哈希。"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import yaml
from yaml.events import (
    AliasEvent,
    CollectionEndEvent,
    CollectionStartEvent,
    NodeEvent,
    ScalarEvent,
)
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken

from fura_mappo.demand.factory import create_demand_process

_CONFIG_SCHEMA = "fura-mappo.demand-generation"
_CONFIG_VERSION = 1
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_YAML_NODES = 10_000
_MAX_YAML_DEPTH = 64
_TOP_LEVEL_FIELDS = frozenset({"schema", "version", "demand", "generation"})
_GENERATION_FIELDS = frozenset({"num_steps"})
_ALLOWED_NODE_TAGS = frozenset(
    {
        "tag:yaml.org,2002:map",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
    }
)


def _format_fields(fields: set[object]) -> str:
    """稳定格式化字段集合。"""

    return ", ".join(sorted(repr(field) for field in fields))


def _validate_exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    name: str,
) -> None:
    """同时报告 Mapping 中缺失和多余的字段。"""

    actual = set(value)
    missing = set(expected) - actual
    extra = actual - set(expected)
    problems: list[str] = []
    if missing:
        problems.append(f"{name} 缺少必需字段: {_format_fields(missing)}")
    if extra:
        problems.append(f"{name} 包含多余字段: {_format_fields(extra)}")
    if problems:
        raise ValueError("；".join(problems))


def _scan_yaml_tokens(text: str) -> None:
    """在构造对象前拒绝 anchor 与 alias。"""

    for token in yaml.scan(text, Loader=yaml.SafeLoader):
        if isinstance(token, AnchorToken):
            raise ValueError("YAML 配置不允许 anchor")
        if isinstance(token, AliasToken):
            raise ValueError("YAML 配置不允许 alias")


def _scan_yaml_events(text: str) -> None:
    """在 compose 前限制节点数、集合深度、anchor、alias 和显式标签。"""

    node_count = 0
    depth = 0
    for event in yaml.parse(text, Loader=yaml.SafeLoader):
        if isinstance(event, AliasEvent):
            raise ValueError("YAML 配置不允许 alias")
        if isinstance(event, NodeEvent) and event.anchor is not None:
            raise ValueError("YAML 配置不允许 anchor")
        if isinstance(event, (CollectionStartEvent, ScalarEvent)):
            node_count += 1
            if node_count > _MAX_YAML_NODES:
                raise ValueError(f"YAML 节点数不能超过 {_MAX_YAML_NODES}")
            if event.tag is not None and event.tag not in _ALLOWED_NODE_TAGS:
                raise ValueError("YAML 配置包含不支持或不安全的类型标签")
        if isinstance(event, CollectionStartEvent):
            depth += 1
            if depth > _MAX_YAML_DEPTH:
                raise ValueError(f"YAML 嵌套深度不能超过 {_MAX_YAML_DEPTH}")
        elif isinstance(event, CollectionEndEvent):
            depth -= 1


def _validate_yaml_node_tree(root: Node | None) -> None:
    """在构造对象前限制节点类型、数量、深度、键和重复键。"""

    if root is None:
        raise ValueError("YAML 配置不能为空")
    node_count = 0
    stack: list[tuple[Node, int]] = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        node_count += 1
        if node_count > _MAX_YAML_NODES:
            raise ValueError(f"YAML 节点数不能超过 {_MAX_YAML_NODES}")
        if depth > _MAX_YAML_DEPTH:
            raise ValueError(f"YAML 嵌套深度不能超过 {_MAX_YAML_DEPTH}")
        if node.tag not in _ALLOWED_NODE_TAGS:
            raise ValueError("YAML 配置包含不支持或不安全的类型标签")

        if isinstance(node, MappingNode):
            seen_keys: set[str] = set()
            for key_node, value_node in node.value:
                if isinstance(key_node, ScalarNode) and key_node.value == "<<":
                    raise ValueError("YAML 配置不允许 merge key")
                if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                    raise ValueError("YAML Mapping 的键必须是字符串")
                if key_node.value in seen_keys:
                    raise ValueError(f"YAML Mapping 包含重复键 {key_node.value!r}")
                seen_keys.add(key_node.value)
                stack.append((value_node, depth + 1))
                stack.append((key_node, depth + 1))
        elif isinstance(node, SequenceNode):
            stack.extend((item, depth + 1) for item in reversed(node.value))
        elif not isinstance(node, ScalarNode):
            raise ValueError("YAML 配置包含不支持的节点类型")


def _copy_plain_tree(value: object, name: str = "配置") -> object:
    """复制并限制为 JSON 风格普通 Python tree。"""

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
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{name} 的 Mapping 键必须是字符串")
            result[key] = _copy_plain_tree(item, name)
        return result
    if isinstance(value, list):
        return [_copy_plain_tree(item, name) for item in value]
    raise TypeError(f"{name} 包含不支持的值类型")


def _validate_demand_config(config: Mapping[str, object]) -> dict[str, object]:
    """验证顶层协议并返回完全独立的普通配置树。"""

    copied = _copy_plain_tree(config)
    if not isinstance(copied, dict):
        raise TypeError("配置顶层必须是 Mapping")
    _validate_exact_fields(copied, _TOP_LEVEL_FIELDS, "配置顶层")

    if copied["schema"] != _CONFIG_SCHEMA:
        raise ValueError(f"schema 必须精确等于 {_CONFIG_SCHEMA!r}")
    version = copied["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError("version 必须是整数且不能是布尔值")
    if version != _CONFIG_VERSION:
        raise ValueError(f"version 必须精确等于 {_CONFIG_VERSION}")

    demand = copied["demand"]
    if not isinstance(demand, dict):
        raise TypeError("demand 必须是 Mapping")
    generation = copied["generation"]
    if not isinstance(generation, dict):
        raise TypeError("generation 必须是 Mapping")
    _validate_exact_fields(generation, _GENERATION_FIELDS, "generation")
    num_steps = generation["num_steps"]
    if isinstance(num_steps, bool) or not isinstance(num_steps, int):
        raise TypeError("generation.num_steps 必须是整数且不能是布尔值")
    if num_steps <= 0:
        raise ValueError("generation.num_steps 必须是正整数")

    create_demand_process(demand)
    return copied


def load_demand_config(path: str | os.PathLike[str]) -> dict[str, object]:
    """安全加载并严格验证需求生成 YAML 配置。

    Args:
        path: 小写 ``.yaml`` 配置路径；拒绝 bytes 路径。

    Returns:
        仅含普通 ``dict/list/str/int/float`` 的全新配置树。

    Raises:
        TypeError: 路径对象类型不受支持时抛出。
        ValueError: 后缀、YAML 安全规则或文件内容协议不满足时抛出。
        OSError: 文件不存在、权限不足或其他 I/O 失败时原样传播。
    """

    if isinstance(path, bytes):
        raise TypeError("path 不能是 bytes")
    try:
        raw_path = os.fspath(path)
    except TypeError as error:
        raise TypeError("path 必须是 str 或 os.PathLike[str]") from error
    if isinstance(raw_path, bytes):
        raise TypeError("path 不能是 bytes")
    config_path = Path(raw_path)
    if config_path.suffix != ".yaml":
        raise ValueError("配置文件后缀必须精确为 .yaml")

    with config_path.open("rb") as stream:
        payload = stream.read(_MAX_CONFIG_BYTES + 1)
    if len(payload) > _MAX_CONFIG_BYTES:
        raise ValueError(f"YAML 配置文件不能超过 {_MAX_CONFIG_BYTES} 字节")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("YAML 配置必须使用有效 UTF-8 编码") from error

    try:
        _scan_yaml_tokens(text)
        _scan_yaml_events(text)
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        _validate_yaml_node_tree(node)
        loaded = yaml.load(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise ValueError("YAML 配置语法或安全校验失败") from error
    try:
        if not isinstance(loaded, Mapping):
            raise TypeError("配置顶层必须是 Mapping")
        return _validate_demand_config(loaded)
    except TypeError as error:
        raise ValueError(f"YAML 配置内容错误：{error}") from error


def _normalize_hash_value(value: object) -> list[object]:
    """构造带类型标记且无歧义的配置规范化表示。"""

    if isinstance(value, (bool, np.bool_)):
        raise TypeError("配置哈希不允许布尔值")
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, (int, np.integer)):
        return ["int", str(int(value))]
    if isinstance(value, (float, np.floating)):
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError("配置哈希不允许 NaN 或无穷值")
        if normalized == 0.0:
            normalized = 0.0
        return ["float", normalized.hex()]
    if isinstance(value, Mapping):
        items: list[list[object]] = []
        keys = list(value)
        if not all(isinstance(key, str) for key in keys):
            raise TypeError("配置哈希的 Mapping 键必须是字符串")
        for key in sorted(keys):
            if not isinstance(key, str):
                raise TypeError("配置哈希的 Mapping 键必须是字符串")
            items.append([key, _normalize_hash_value(value[key])])
        return ["mapping", items]
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return _normalize_hash_value(value.item())
        return ["sequence", [_normalize_hash_value(item) for item in value.tolist()]]
    if isinstance(value, (list, tuple)):
        return ["sequence", [_normalize_hash_value(item) for item in value]]
    raise TypeError("配置哈希包含不支持的值类型")


def compute_config_hash(config: Mapping[str, object]) -> str:
    """返回完整配置的稳定小写 SHA-256。

    Mapping 使用 Unicode 码点排序；序列、字符串、整数与 float64 浮点值均带有
    独立类型标签，因此 ``1``、``1.0`` 和字符串表示不会相互碰撞。

    Args:
        config: 仅含字符串键和受支持标量、序列或 NumPy 数组的配置。

    Returns:
        64 位小写十六进制 SHA-256 字符串。
    """

    if not isinstance(config, Mapping):
        raise TypeError("config 必须是 Mapping")
    normalized = _normalize_hash_value(config)
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__: list[str] = ["compute_config_hash", "load_demand_config"]
