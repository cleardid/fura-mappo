"""Prediction protocol 与 split manifest 的最小严格 JSON serialization。"""

from __future__ import annotations

import errno
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from fura_mappo.prediction.dataset import (
    DatasetProtocolSpec,
    DatasetSplitManifest,
    PredictionSource,
    SplitEntry,
    dataset_protocol_identity,
    split_manifest_identity,
)

_MAX_JSON_BYTES = 8 * 1024 * 1024
_PROTOCOL_FIELDS = frozenset(
    {
        "schema",
        "version",
        "history_length",
        "prediction_horizon",
        "zone_schema_sha256",
        "target_kind",
        "history_kind",
        "history_padding",
        "target_padding",
        "anchor_rule",
        "zone_ordering",
        "sha256",
    }
)
_MANIFEST_FIELDS = frozenset({"schema", "version", "entries", "sha256"})
_ENTRY_FIELDS = frozenset({"split", "source"})
_SOURCE_FIELDS = frozenset(
    {
        "trace_id",
        "seed",
        "process_type",
        "config_sha256",
        "content_sha256",
        "realized_trace_sha256",
        "condition_sha256",
        "zone_schema_sha256",
        "start_step",
        "num_steps",
        "num_zones",
    }
)


def _canonical_json_bytes(value: object) -> bytes:
    """编码 sorted-key、无 NaN/Inf 的 canonical UTF-8 JSON。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _strict_json_loads(payload: bytes) -> dict[str, object]:
    """拒绝重复键、非有限常量和非 object 顶层。"""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("protocol JSON 必须是有效 UTF-8") from error

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"protocol JSON 包含重复键 {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"protocol JSON 不允许常量 {value}")

    try:
        value = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ValueError("protocol JSON 语法无效") from error
    if not isinstance(value, dict):
        raise ValueError("protocol JSON 顶层必须是 object")
    return value


def _require_exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    name: str,
) -> None:
    """拒绝 schema 未声明的缺失或未知字段。"""

    if set(value) != set(expected):
        raise ValueError(f"{name} 字段集合与 schema 不一致")


def _coerce_json_path(path: str | os.PathLike[str]) -> Path:
    """规范化非 bytes、小写 ``.json`` 路径。"""

    if isinstance(path, bytes):
        raise TypeError("path 不能是 bytes")
    try:
        raw = os.fspath(path)
    except TypeError as error:
        raise TypeError("path 必须是 str 或 os.PathLike[str]") from error
    if isinstance(raw, bytes):
        raise TypeError("path 不能是 bytes")
    target = Path(raw)
    if target.suffix != ".json":
        raise ValueError("protocol 文件后缀必须精确为 .json")
    return target


def _fsync_parent(parent: Path) -> None:
    """持久化新目录项；仅忽略平台明确不支持 directory fsync 的错误。"""

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
    """同目录临时文件 + hard link 原子 no-overwrite 发布。"""

    if not path.parent.exists() or not path.parent.is_dir():
        raise FileNotFoundError("输出目录不存在或不是目录")
    if path.is_symlink():
        raise ValueError("输出目标不能是符号链接")
    if os.path.lexists(path):
        raise FileExistsError("输出目标已存在")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    consumed = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
        consumed = True
        _fsync_parent(path.parent)
        return path
    finally:
        if not consumed:
            try:
                temporary.unlink()
            except OSError:
                pass


def _read_canonical_json(path: str | os.PathLike[str]) -> dict[str, object]:
    """安全读取、严格解析并验证 canonical writer representation。"""

    target = _coerce_json_path(path)
    if target.is_symlink():
        raise ValueError("protocol 文件不能是符号链接")
    if not target.is_file():
        raise ValueError("protocol path 必须是普通文件")
    if target.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError("protocol JSON 超出 8 MiB 上限")
    with target.open("rb") as stream:
        payload = stream.read(_MAX_JSON_BYTES + 1)
    if len(payload) > _MAX_JSON_BYTES:
        raise ValueError("protocol JSON 超出 8 MiB 上限")
    if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        raise ValueError("protocol JSON 必须恰好以一个换行结束")
    value = _strict_json_loads(payload[:-1])
    try:
        canonical = _canonical_json_bytes(value) + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError("protocol JSON 包含不可规范编码的值") from error
    if payload != canonical:
        raise ValueError("protocol JSON 不是 canonical writer representation")
    return value


def dataset_protocol_to_dict(spec: DatasetProtocolSpec) -> dict[str, object]:
    """返回含 protocol self hash 的 canonical tree。"""

    value = dataset_protocol_identity(spec)
    value["sha256"] = spec.sha256
    return value


def split_manifest_to_dict(manifest: DatasetSplitManifest) -> dict[str, object]:
    """返回含 manifest self hash 的 canonical tree。"""

    value = split_manifest_identity(manifest)
    value["sha256"] = manifest.sha256
    return value


def write_dataset_protocol(
    path: str | os.PathLike[str],
    spec: DatasetProtocolSpec,
) -> Path:
    """no-overwrite 写入并严格回读一个 dataset protocol JSON。"""

    if not isinstance(spec, DatasetProtocolSpec):
        raise TypeError("spec 必须是 DatasetProtocolSpec")
    target = _coerce_json_path(path)
    _atomic_write_new(target, _canonical_json_bytes(dataset_protocol_to_dict(spec)) + b"\n")
    if read_dataset_protocol(target) != spec:
        raise RuntimeError("dataset protocol strict readback 不一致")
    return target


def read_dataset_protocol(path: str | os.PathLike[str]) -> DatasetProtocolSpec:
    """严格读取并重算 dataset protocol identity。"""

    value = _read_canonical_json(path)
    _require_exact_fields(value, _PROTOCOL_FIELDS, "dataset protocol")
    stored_sha = value["sha256"]
    spec = DatasetProtocolSpec(
        history_length=value["history_length"],  # type: ignore[arg-type]
        prediction_horizon=value["prediction_horizon"],  # type: ignore[arg-type]
        zone_schema_sha256=value["zone_schema_sha256"],  # type: ignore[arg-type]
        target_kind=value["target_kind"],  # type: ignore[arg-type]
        history_kind=value["history_kind"],  # type: ignore[arg-type]
        history_padding=value["history_padding"],  # type: ignore[arg-type]
        target_padding=value["target_padding"],  # type: ignore[arg-type]
        anchor_rule=value["anchor_rule"],  # type: ignore[arg-type]
        zone_ordering=value["zone_ordering"],  # type: ignore[arg-type]
        schema=value["schema"],  # type: ignore[arg-type]
        version=value["version"],  # type: ignore[arg-type]
    )
    if stored_sha != spec.sha256 or value != dataset_protocol_to_dict(spec):
        raise ValueError("dataset protocol SHA 或 canonical content 校验失败")
    return spec


def _source_from_dict(value: object) -> PredictionSource:
    """严格重建 source descriptor。"""

    if not isinstance(value, Mapping):
        raise ValueError("split entry source 必须是 object")
    _require_exact_fields(value, _SOURCE_FIELDS, "prediction source")
    return PredictionSource(
        trace_id=value["trace_id"],  # type: ignore[arg-type]
        seed=value["seed"],  # type: ignore[arg-type]
        process_type=value["process_type"],  # type: ignore[arg-type]
        config_sha256=value["config_sha256"],  # type: ignore[arg-type]
        content_sha256=value["content_sha256"],  # type: ignore[arg-type]
        realized_trace_sha256=value["realized_trace_sha256"],  # type: ignore[arg-type]
        condition_sha256=value["condition_sha256"],  # type: ignore[arg-type]
        zone_schema_sha256=value["zone_schema_sha256"],  # type: ignore[arg-type]
        start_step=value["start_step"],  # type: ignore[arg-type]
        num_steps=value["num_steps"],  # type: ignore[arg-type]
        num_zones=value["num_zones"],  # type: ignore[arg-type]
    )


def write_split_manifest(
    path: str | os.PathLike[str],
    manifest: DatasetSplitManifest,
) -> Path:
    """no-overwrite 写入并严格回读 explicit trace split manifest。"""

    if not isinstance(manifest, DatasetSplitManifest):
        raise TypeError("manifest 必须是 DatasetSplitManifest")
    target = _coerce_json_path(path)
    _atomic_write_new(target, _canonical_json_bytes(split_manifest_to_dict(manifest)) + b"\n")
    if read_split_manifest(target) != manifest:
        raise RuntimeError("split manifest strict readback 不一致")
    return target


def read_split_manifest(path: str | os.PathLike[str]) -> DatasetSplitManifest:
    """严格读取、规范排序并重算 split manifest identity。"""

    value = _read_canonical_json(path)
    _require_exact_fields(value, _MANIFEST_FIELDS, "split manifest")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list):
        raise ValueError("split manifest entries 必须是 array")
    entries: list[SplitEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("split manifest entry 必须是 object")
        _require_exact_fields(raw_entry, _ENTRY_FIELDS, "split entry")
        entries.append(
            SplitEntry(
                split=raw_entry["split"],  # type: ignore[arg-type]
                source=_source_from_dict(raw_entry["source"]),
            )
        )
    manifest = DatasetSplitManifest(
        entries=tuple(entries),
        schema=value["schema"],  # type: ignore[arg-type]
        version=value["version"],  # type: ignore[arg-type]
    )
    if value["sha256"] != manifest.sha256 or value != split_manifest_to_dict(manifest):
        raise ValueError("split manifest SHA、ordering 或 canonical content 校验失败")
    return manifest


__all__ = [
    "dataset_protocol_to_dict",
    "read_dataset_protocol",
    "read_split_manifest",
    "split_manifest_to_dict",
    "write_dataset_protocol",
    "write_split_manifest",
]
