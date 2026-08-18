"""需求轨迹 NPZ artifact 的安全保存与读取。"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import platform
import re
import struct
import subprocess
import tempfile
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO

import numpy as np
import yaml

from fura_mappo import __version__
from fura_mappo.demand.config import _validate_demand_config, compute_config_hash
from fura_mappo.demand.models import DemandEvent, DemandTrace

_ARTIFACT_SCHEMA = "fura-mappo.demand-trace"
_ARTIFACT_VERSION = 1
_CONTENT_HASH_ALGORITHM = "sha256-logical-v1"
_MAX_FILE_BYTES = 2 * 1024**3
_MAX_MANIFEST_MEMBER_BYTES = 4 * 1024**2
_MAX_TOTAL_UNCOMPRESSED_BYTES = 4 * 1024**3
_ARRAY_ORDER = (
    "counts",
    "intensities",
    "event_id",
    "arrival_step",
    "zone_id",
    "positions",
    "priority",
    "service_time",
    "deadline",
)
_MEMBER_ORDER = _ARRAY_ORDER + ("manifest",)
_EXPECTED_MEMBER_NAMES = tuple(f"{name}.npy" for name in _MEMBER_ORDER)
_EXPECTED_DTYPES = {
    "counts": np.dtype("<i8"),
    "intensities": np.dtype("<f8"),
    "event_id": np.dtype("<i8"),
    "arrival_step": np.dtype("<i8"),
    "zone_id": np.dtype("<i8"),
    "positions": np.dtype("<f8"),
    "priority": np.dtype("<f8"),
    "service_time": np.dtype("<i8"),
    "deadline": np.dtype("<i8"),
    "manifest": np.dtype("u1"),
}
_EXPECTED_NDIMS = {
    "counts": 2,
    "intensities": 2,
    "event_id": 1,
    "arrival_step": 1,
    "zone_id": 1,
    "positions": 2,
    "priority": 1,
    "service_time": 1,
    "deadline": 1,
    "manifest": 1,
}
_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "version",
        "start_step",
        "num_steps",
        "num_zones",
        "num_events",
        "process_type",
        "seed",
        "resolved_config",
        "config_sha256",
        "git_commit",
        "git_dirty",
        "package_version",
        "created_at_utc",
        "runtime",
        "content_hash_algorithm",
        "content_sha256",
    }
)
_RUNTIME_FIELDS = frozenset({"python", "platform", "numpy", "pyyaml", "conda_environment"})
_PYTHON_FIELDS = frozenset({"version", "implementation"})
_PLATFORM_FIELDS = frozenset({"system", "release", "machine"})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


def _freeze_json_tree(value: object, name: str = "manifest") -> object:
    """防御性复制并递归冻结 JSON tree。"""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} 不允许 NaN 或无穷值")
        return float(value)
    if isinstance(value, Mapping):
        copied: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{name} 的 Mapping 键必须是字符串")
            copied[key] = _freeze_json_tree(item, name)
        return MappingProxyType(copied)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json_tree(item, name) for item in value)
    raise TypeError(f"{name} 包含不支持的值类型")


@dataclass(frozen=True, slots=True)
class DemandTraceArtifact:
    """保存需求轨迹及递归只读 provenance manifest。"""

    trace: DemandTrace
    manifest: Mapping[str, object]

    def __post_init__(self) -> None:
        """验证轨迹类型并冻结 manifest 的防御性副本。"""

        if not isinstance(self.trace, DemandTrace):
            raise TypeError("trace 必须是 DemandTrace")
        if not isinstance(self.manifest, Mapping):
            raise TypeError("manifest 必须是 Mapping")
        frozen = _freeze_json_tree(self.manifest)
        object.__setattr__(self, "manifest", frozen)


def _canonical_json_bytes(value: object) -> bytes:
    """编码无 NaN、键稳定的 UTF-8 canonical JSON。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _run_git(command: list[str]) -> str | None:
    """运行短时只读 Git 探针；不可用时返回 ``None``。"""

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip()


def _collect_git_state() -> tuple[str | None, bool | None]:
    """返回当前完整 Commit 与 dirty 状态；Git 不可用时使用 null。"""

    commit = _run_git(["git", "rev-parse", "HEAD"])
    if commit is None or _GIT_SHA_PATTERN.fullmatch(commit) is None:
        return None, None
    status = _run_git(["git", "status", "--porcelain"])
    if status is None:
        return commit, None
    return commit, bool(status)


def _runtime_manifest() -> dict[str, object]:
    """采集不含主机名、绝对路径、GPU 或环境变量列表的运行时字段。"""

    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "numpy": np.__version__,
        "pyyaml": yaml.__version__,
        "conda_environment": _normalize_conda_environment(os.environ.get("CONDA_DEFAULT_ENV")),
    }


def _normalize_conda_environment(value: str | None) -> str | None:
    """只保留 Conda 环境名，避免 prefix 环境泄露绝对路径。"""

    if value is None or value == "":
        return None
    if "/" not in value and "\\" not in value:
        return value
    components = [component for component in re.split(r"[/\\]+", value) if component]
    return components[-1] if components else None


def _int64_array(values: Sequence[int], name: str) -> np.ndarray:
    """验证整数序列可无损保存为 little-endian int64。"""

    minimum = int(np.iinfo(np.int64).min)
    maximum = int(np.iinfo(np.int64).max)
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} 必须全部为整数且不能包含布尔值")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} 包含无法表示为 int64 的值")
        normalized.append(value)
    return np.asarray(normalized, dtype="<i8")


def _trace_arrays(trace: DemandTrace) -> dict[str, np.ndarray]:
    """按固定列顺序把 Trace 编码为 C-order little-endian 数组。"""

    events = trace.events
    positions = np.empty((len(events), 2), dtype="<f8")
    if events:
        positions[:, :] = [event.position for event in events]
    arrays = {
        "counts": np.ascontiguousarray(trace.counts, dtype="<i8"),
        "intensities": np.ascontiguousarray(trace.intensities, dtype="<f8"),
        "event_id": _int64_array([event.event_id for event in events], "event_id"),
        "arrival_step": _int64_array([event.arrival_step for event in events], "arrival_step"),
        "zone_id": _int64_array([event.zone_id for event in events], "zone_id"),
        "positions": positions,
        "priority": np.asarray([event.priority for event in events], dtype="<f8"),
        "service_time": _int64_array([event.service_time for event in events], "service_time"),
        "deadline": _int64_array([event.deadline for event in events], "deadline"),
    }
    return arrays


def _hash_field(hasher: hashlib._Hash, payload: bytes) -> None:
    """用无符号 64 位长度前缀纳入一个逻辑字段。"""

    hasher.update(struct.pack(">Q", len(payload)))
    hasher.update(payload)


def _logical_content_hash(arrays: Mapping[str, np.ndarray], manifest: Mapping[str, object]) -> str:
    """计算 sha256-logical-v1 数组与 provenance manifest 哈希。"""

    hasher = hashlib.sha256()
    hasher.update(b"fura-mappo:sha256-logical-v1\x00")
    for name in _ARRAY_ORDER:
        array = arrays[name]
        _hash_field(hasher, name.encode("ascii"))
        _hash_field(hasher, array.dtype.str.encode("ascii"))
        _hash_field(hasher, _canonical_json_bytes(list(array.shape)))
        _hash_field(hasher, array.tobytes(order="C"))
    without_hash = dict(manifest)
    without_hash.pop("content_sha256", None)
    _hash_field(hasher, b"manifest")
    _hash_field(hasher, _canonical_json_bytes(without_hash))
    return hasher.hexdigest()


def _build_manifest(
    trace: DemandTrace,
    resolved_config: Mapping[str, object],
    arrays: Mapping[str, np.ndarray],
) -> dict[str, object]:
    """由验证后的配置、Trace 和当前 provenance 构造 manifest。"""

    config = _validate_demand_config(resolved_config)
    num_steps, num_zones = trace.counts.shape
    configured_steps = config["generation"]["num_steps"]  # type: ignore[index]
    if configured_steps != num_steps:
        raise ValueError("resolved_config 的 num_steps 必须等于 trace 时间步数")
    demand = config["demand"]
    if not isinstance(demand, dict):
        raise TypeError("resolved_config.demand 必须是 Mapping")
    process_type = demand["type"]
    seed = demand["seed"]
    if not isinstance(process_type, str):
        raise TypeError("resolved_config.demand.type 必须是字符串")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("resolved_config.demand.seed 必须是非 bool 整数")

    commit, dirty = _collect_git_state()
    created_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    manifest: dict[str, object] = {
        "schema": _ARTIFACT_SCHEMA,
        "version": _ARTIFACT_VERSION,
        "start_step": trace.start_step,
        "num_steps": num_steps,
        "num_zones": num_zones,
        "num_events": len(trace.events),
        "process_type": process_type,
        "seed": seed,
        "resolved_config": config,
        "config_sha256": compute_config_hash(config),
        "git_commit": commit,
        "git_dirty": dirty,
        "package_version": __version__,
        "created_at_utc": created_at,
        "runtime": _runtime_manifest(),
        "content_hash_algorithm": _CONTENT_HASH_ALGORITHM,
    }
    manifest["content_sha256"] = _logical_content_hash(arrays, manifest)
    return manifest


def _coerce_path(path: str | os.PathLike[str], suffix: str) -> Path:
    """规范化非 bytes 路径并检查精确小写后缀。"""

    if isinstance(path, bytes):
        raise TypeError("path 不能是 bytes")
    try:
        raw_path = os.fspath(path)
    except TypeError as error:
        raise TypeError("path 必须是 str 或 os.PathLike[str]") from error
    if isinstance(raw_path, bytes):
        raise TypeError("path 不能是 bytes")
    normalized = Path(raw_path)
    if normalized.suffix != suffix:
        raise ValueError(f"文件后缀必须精确为 {suffix}")
    return normalized


def _validate_save_target(path: Path, overwrite: bool) -> None:
    """验证保存 parent、目标 symlink 与覆盖策略。"""

    if not path.parent.exists() or not path.parent.is_dir():
        raise FileNotFoundError("输出目录不存在或不是目录")
    if path.is_symlink():
        raise ValueError("输出目标不能是符号链接")
    if os.path.lexists(path) and not overwrite:
        raise FileExistsError("输出目标已存在")


def _write_npz(stream: BinaryIO, arrays: Mapping[str, np.ndarray]) -> None:
    """按固定成员顺序写入压缩 NPZ。"""

    np.savez_compressed(stream, **{name: arrays[name] for name in _MEMBER_ORDER})


def _fsync_parent(parent: Path) -> None:
    """同步目录项，仅忽略平台明确不支持目录 fsync 的错误。"""

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


def save_demand_trace(
    path: str | os.PathLike[str],
    trace: DemandTrace,
    *,
    resolved_config: Mapping[str, object],
    overwrite: bool = False,
) -> Path:
    """原子保存单文件 NPZ 需求轨迹 artifact。

    Args:
        path: 精确小写 ``.npz`` 目标；parent 必须已存在。
        trace: 计数形状 ``[num_steps, num_zones]`` 的需求轨迹。
        resolved_config: 完整、已解析的 WP-01C 顶层配置。
        overwrite: 为真时原子替换已有普通文件，仍拒绝符号链接。

    Returns:
        成功发布的目标 ``Path``。
    """

    target = _coerce_path(path, ".npz")
    if not isinstance(trace, DemandTrace):
        raise TypeError("trace 必须是 DemandTrace")
    if not isinstance(resolved_config, Mapping):
        raise TypeError("resolved_config 必须是 Mapping")
    if not isinstance(overwrite, bool):
        raise TypeError("overwrite 必须是 bool")
    _validate_save_target(target, overwrite)

    arrays = _trace_arrays(trace)
    manifest = _build_manifest(trace, resolved_config, arrays)
    manifest_bytes = _canonical_json_bytes(manifest)
    if len(manifest_bytes) > _MAX_MANIFEST_MEMBER_BYTES:
        raise ValueError("manifest 超出安全大小上限")
    complete_arrays = dict(arrays)
    complete_arrays["manifest"] = np.frombuffer(manifest_bytes, dtype=np.uint8).copy()

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w+b") as stream:
            _write_npz(stream, complete_arrays)
            stream.flush()
            os.fsync(stream.fileno())

        _load_demand_trace_path(temporary)
        if overwrite:
            if target.is_symlink():
                raise ValueError("输出目标不能是符号链接")
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
        _fsync_parent(target.parent)
        return target
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_npy_header(stream: BinaryIO) -> tuple[tuple[int, ...], bool, np.dtype[object]]:
    """只读 NPY header，不分配声明的数据数组。"""

    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        return np.lib.format.read_array_header_1_0(stream, max_header_size=10_000)
    if version in {(2, 0), (3, 0)}:
        return np.lib.format.read_array_header_2_0(stream, max_header_size=10_000)
    raise ValueError("NPY 成员使用不支持的版本")


def _inspect_zip_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """验证 ZIP 目录及每个 NPY header，避免不可信预分配。"""

    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValueError("NPZ 包含重复成员")
    if tuple(sorted(names)) != tuple(sorted(_EXPECTED_MEMBER_NAMES)):
        raise ValueError("NPZ 成员必须与 artifact v1 schema 精确一致")
    allowed_compression = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
    total_uncompressed = 0
    result: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        if info.is_dir() or info.filename.endswith("/"):
            raise ValueError("NPZ 不允许目录成员")
        if info.flag_bits & 0x1:
            raise ValueError("NPZ 不允许加密成员")
        if info.compress_type not in allowed_compression:
            raise ValueError("NPZ 使用不支持的压缩方法")
        total_uncompressed += info.file_size
        if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("NPZ 声明的总解压大小超出安全上限")
        logical_name = info.filename.removesuffix(".npy")
        if logical_name == "manifest" and info.file_size > _MAX_MANIFEST_MEMBER_BYTES:
            raise ValueError("manifest 成员超出安全大小上限")

        with archive.open(info, "r") as stream:
            shape, fortran_order, dtype = _read_npy_header(stream)
            header_size = stream.tell()
        expected_dtype = _EXPECTED_DTYPES[logical_name]
        if dtype.str != expected_dtype.str:
            raise ValueError(f"NPZ 成员 {logical_name!r} 的 dtype 错误")
        if len(shape) != _EXPECTED_NDIMS[logical_name]:
            raise ValueError(f"NPZ 成员 {logical_name!r} 的维度错误")
        if fortran_order:
            raise ValueError(f"NPZ 成员 {logical_name!r} 必须使用 C-order")
        element_count = math.prod(shape)
        expected_size = element_count * dtype.itemsize
        if expected_size > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError(f"NPZ 成员 {logical_name!r} 声明数组过大")
        if header_size + expected_size != info.file_size:
            raise ValueError(f"NPZ 成员 {logical_name!r} 的 header 与数据大小不一致")
        result[logical_name] = info
    return result


def _strict_json_loads(payload: bytes) -> dict[str, object]:
    """严格读取 manifest JSON，拒绝重复键和非有限常量。"""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("manifest 必须是有效 UTF-8") from error

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"manifest JSON 包含重复键 {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"manifest JSON 不允许常量 {value}")

    try:
        value = json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)
    except json.JSONDecodeError as error:
        raise ValueError("manifest 不是有效严格 JSON") from error
    if not isinstance(value, dict):
        raise ValueError("manifest 顶层必须是 JSON object")
    return value


def _require_exact_fields(value: Mapping[str, object], expected: frozenset[str], name: str) -> None:
    """验证 JSON object 精确字段集合。"""

    actual = set(value)
    missing = set(expected) - actual
    extra = actual - set(expected)
    if missing or extra:
        raise ValueError(f"{name} 字段与 artifact v1 schema 不一致")


def _require_integer(value: object, name: str, minimum: int = 0) -> int:
    """读取非 bool JSON 整数并检查下界。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"manifest.{name} 必须是整数且不能是布尔值")
    if value < minimum:
        raise ValueError(f"manifest.{name} 必须大于或等于 {minimum}")
    return value


def _require_string(value: object, name: str) -> str:
    """读取非空 JSON 字符串。"""

    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest.{name} 必须是非空字符串")
    return value


def _validate_runtime(value: object) -> None:
    """严格验证不含敏感字段的 runtime 子 schema。"""

    if not isinstance(value, Mapping):
        raise ValueError("manifest.runtime 必须是 object")
    _require_exact_fields(value, _RUNTIME_FIELDS, "manifest.runtime")
    python = value["python"]
    platform_value = value["platform"]
    if not isinstance(python, Mapping) or not isinstance(platform_value, Mapping):
        raise ValueError("manifest.runtime 的 python/platform 必须是 object")
    _require_exact_fields(python, _PYTHON_FIELDS, "manifest.runtime.python")
    _require_exact_fields(platform_value, _PLATFORM_FIELDS, "manifest.runtime.platform")
    for key in _PYTHON_FIELDS:
        _require_string(python[key], f"runtime.python.{key}")
    for key in _PLATFORM_FIELDS:
        _require_string(platform_value[key], f"runtime.platform.{key}")
    _require_string(value["numpy"], "runtime.numpy")
    _require_string(value["pyyaml"], "runtime.pyyaml")
    conda_environment = value["conda_environment"]
    if conda_environment is None:
        return
    if not isinstance(conda_environment, str):
        raise ValueError("manifest.runtime.conda_environment 必须是字符串或 null")
    if not conda_environment:
        raise ValueError("manifest.runtime.conda_environment 必须是非空环境名或 null")
    if "/" in conda_environment or "\\" in conda_environment:
        raise ValueError("manifest.runtime.conda_environment 必须是环境名，不能包含路径分隔符")


def _validate_manifest(
    manifest: dict[str, object], arrays: Mapping[str, np.ndarray]
) -> dict[str, object]:
    """交叉验证 manifest、数组形状、配置哈希和逻辑内容哈希。"""

    _require_exact_fields(manifest, _MANIFEST_FIELDS, "manifest")
    if manifest["schema"] != _ARTIFACT_SCHEMA:
        raise ValueError("artifact schema 不受支持")
    if _require_integer(manifest["version"], "version") != _ARTIFACT_VERSION:
        raise ValueError("artifact version 不受支持")
    start_step = _require_integer(manifest["start_step"], "start_step")
    num_steps = _require_integer(manifest["num_steps"], "num_steps", 1)
    num_zones = _require_integer(manifest["num_zones"], "num_zones", 1)
    num_events = _require_integer(manifest["num_events"], "num_events")
    process_type = _require_string(manifest["process_type"], "process_type")
    seed = _require_integer(manifest["seed"], "seed")
    config_hash = _require_string(manifest["config_sha256"], "config_sha256")
    content_hash = _require_string(manifest["content_sha256"], "content_sha256")
    if (
        _SHA256_PATTERN.fullmatch(config_hash) is None
        or _SHA256_PATTERN.fullmatch(content_hash) is None
    ):
        raise ValueError("manifest SHA-256 字段格式错误")
    commit = manifest["git_commit"]
    if commit is not None and (
        not isinstance(commit, str) or _GIT_SHA_PATTERN.fullmatch(commit) is None
    ):
        raise ValueError("manifest.git_commit 必须是完整 Commit SHA 或 null")
    if manifest["git_dirty"] is not None and not isinstance(manifest["git_dirty"], bool):
        raise ValueError("manifest.git_dirty 必须是 bool 或 null")
    _require_string(manifest["package_version"], "package_version")
    created_at = _require_string(manifest["created_at_utc"], "created_at_utc")
    try:
        datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError("manifest.created_at_utc 必须是 UTC 秒精度 Z 时间") from error
    _validate_runtime(manifest["runtime"])
    if manifest["content_hash_algorithm"] != _CONTENT_HASH_ALGORITHM:
        raise ValueError("manifest.content_hash_algorithm 不受支持")

    resolved = manifest["resolved_config"]
    if not isinstance(resolved, Mapping):
        raise ValueError("manifest.resolved_config 必须是 object")
    try:
        validated_config = _validate_demand_config(resolved)
    except TypeError as error:
        raise ValueError(f"manifest.resolved_config 内容类型错误：{error}") from error
    manifest["resolved_config"] = validated_config
    if compute_config_hash(validated_config) != config_hash:
        raise ValueError("manifest.config_sha256 校验失败")
    demand = validated_config["demand"]
    generation = validated_config["generation"]
    if not isinstance(demand, dict) or not isinstance(generation, dict):
        raise ValueError("manifest.resolved_config 子结构错误")
    if demand["type"] != process_type or demand["seed"] != seed:
        raise ValueError("manifest process_type/seed 与 resolved_config 不一致")
    if generation["num_steps"] != num_steps:
        raise ValueError("manifest num_steps 与 resolved_config 不一致")

    if arrays["counts"].shape != (num_steps, num_zones):
        raise ValueError("counts 形状与 manifest 不一致")
    if arrays["intensities"].shape != (num_steps, num_zones):
        raise ValueError("intensities 形状与 manifest 不一致")
    for name in ("event_id", "arrival_step", "zone_id", "priority", "service_time", "deadline"):
        if arrays[name].shape != (num_events,):
            raise ValueError(f"{name} 形状与 manifest 不一致")
    if arrays["positions"].shape != (num_events, 2):
        raise ValueError("positions 形状与 manifest 不一致")
    if start_step > int(np.iinfo(np.int64).max):
        raise ValueError("manifest.start_step 无法由事件 int64 列表示")
    if _logical_content_hash(arrays, manifest) != content_hash:
        raise ValueError("manifest.content_sha256 校验失败")
    return manifest


def _load_arrays(
    archive: zipfile.ZipFile,
    infos: Mapping[str, zipfile.ZipInfo],
) -> dict[str, np.ndarray]:
    """在 header 检查通过后以 allow_pickle=False 加载所有成员。"""

    arrays: dict[str, np.ndarray] = {}
    for name in _MEMBER_ORDER:
        with archive.open(infos[name], "r") as stream:
            array = np.load(stream, allow_pickle=False)
        if not isinstance(array, np.ndarray):
            raise ValueError(f"NPZ 成员 {name!r} 不是 ndarray")
        arrays[name] = array
    return arrays


def _load_demand_trace_path(artifact_path: Path) -> DemandTraceArtifact:
    """从已规范化路径读取并验证 artifact。"""

    if artifact_path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError("NPZ 文件超出 2 GiB 安全上限")
    try:
        with zipfile.ZipFile(artifact_path, "r") as archive:
            infos = _inspect_zip_members(archive)
            arrays = _load_arrays(archive, infos)
    except (zipfile.BadZipFile, EOFError, zlib.error) as error:
        raise ValueError("NPZ 文件损坏或不是有效 artifact") from error

    manifest_payload = arrays.pop("manifest").tobytes(order="C")
    manifest = _strict_json_loads(manifest_payload)
    manifest = _validate_manifest(manifest, arrays)
    num_events = int(manifest["num_events"])
    events = tuple(
        DemandEvent(
            event_id=int(arrays["event_id"][index]),
            arrival_step=int(arrays["arrival_step"][index]),
            zone_id=int(arrays["zone_id"][index]),
            position=(
                float(arrays["positions"][index, 0]),
                float(arrays["positions"][index, 1]),
            ),
            priority=float(arrays["priority"][index]),
            service_time=int(arrays["service_time"][index]),
            deadline=int(arrays["deadline"][index]),
        )
        for index in range(num_events)
    )
    trace = DemandTrace(
        start_step=int(manifest["start_step"]),
        counts=arrays["counts"],
        intensities=arrays["intensities"],
        events=events,
    )
    return DemandTraceArtifact(trace=trace, manifest=manifest)


def load_demand_trace(path: str | os.PathLike[str]) -> DemandTraceArtifact:
    """安全读取并完整验证单文件 NPZ 需求轨迹 artifact。

    Args:
        path: 精确小写 ``.npz`` artifact 路径。

    Returns:
        含只读 ``DemandTrace`` 与递归冻结 manifest 的 artifact。
    """

    return _load_demand_trace_path(_coerce_path(path, ".npz"))


__all__ = ["DemandTraceArtifact", "load_demand_trace", "save_demand_trace"]
