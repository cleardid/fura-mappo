"""WP-03 learned point predictor 的安全 checkpoint directory core。"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import sys
import tempfile
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO

import numpy as np

from fura_mappo.prediction.model_selection import HistoryTransformKind, PointObjectiveKind
from fura_mappo.prediction.official_spec import (
    EXPECTED_WP03_POINT_PRIMARY_V1_SPEC_SHA256,
    OfficialLearnedTrainingConfig,
    OfficialTrainingPlan,
    compute_official_model_complexity_key,
)

_CHECKPOINT_SCHEMA = "fura-mappo.wp03-point-checkpoint"
_CHECKPOINT_VERSION = 1
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_WEIGHTS_BYTES = 512 * 1024 * 1024
_MAX_NPY_HEADER_BYTES = 10_000
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x00000004
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_TRAINING_SEEDS = frozenset({610001, 610002, 610003})
_WEIGHT_NAMES = (
    "linear1.weight",
    "linear1.bias",
    "linear2.weight",
    "linear2.bias",
    "output.weight",
    "output.bias",
)
_MEMBER_NAMES = tuple(f"{name}.npy" for name in _WEIGHT_NAMES)
_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "version",
        "official_spec_sha256",
        "config_sha256",
        "protocol_sha256",
        "training_plan_sha256",
        "rng_namespace_plan_sha256",
        "objective",
        "transform",
        "learning_rate",
        "canonical_order",
        "feature_encoding_sha256",
        "architecture_sha256",
        "model_complexity_key",
        "training_seed",
        "epoch",
        "validation_primary_rmse",
        "history_length",
        "hidden_width",
        "input_dimension",
        "output_dimension",
        "runtime_provenance_sha256",
        "checkpoint_content_sha256",
    }
)


def _normalize_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} 必须是 64 位小写 SHA-256")
    return value


def _normalize_integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} 必须是非 bool 整数")
    normalized = int(value)
    if normalized < minimum:
        raise ValueError(f"{name} 必须大于或等于 {minimum}")
    return normalized


def _normalize_finite_nonnegative_float(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise TypeError(f"{name} 必须是非 bool 实数")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise ValueError(f"{name} 必须是有限非负值")
    if normalized == 0.0:
        normalized = 0.0
    return normalized


def _normalize_model_complexity_key(value: object) -> tuple[int]:
    if not isinstance(value, (list, tuple)) or len(value) != 1:
        raise TypeError("model_complexity_key 必须是单元素 list/tuple")
    return (_normalize_integer(value[0], "model_complexity_key[0]", 1),)


def _authoritative_training_max_epochs(
    official_spec_sha256: str,
    recorded_training_plan_sha256: str,
) -> int:
    """从 hash-bound OfficialTrainingPlan 读取唯一 max_epochs。"""

    training_plan = OfficialTrainingPlan(official_spec_sha256)
    if training_plan.sha256 != recorded_training_plan_sha256:
        raise ValueError("training_plan_sha256 与 authoritative frozen plan 不一致")
    training = training_plan.to_plain_tree().get("training")
    if not isinstance(training, Mapping):
        raise RuntimeError("authoritative training plan 缺少 training section")
    max_epochs = training.get("max_epochs")
    if isinstance(max_epochs, bool) or not isinstance(max_epochs, int) or max_epochs < 1:
        raise RuntimeError("authoritative training plan max_epochs 无效")
    return max_epochs


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _strict_json_loads(payload: bytes) -> dict[str, object]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("checkpoint manifest 必须是有效 UTF-8") from error

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"checkpoint manifest 包含重复键 {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"checkpoint manifest 不允许常量 {value}")

    try:
        loaded = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ValueError("checkpoint manifest JSON 语法无效") from error
    if not isinstance(loaded, dict):
        raise ValueError("checkpoint manifest 顶层必须是 object")
    return loaded


def _hash_length_prefixed(hasher: hashlib._Hash, payload: bytes) -> None:
    hasher.update(struct.pack(">Q", len(payload)))
    hasher.update(payload)


def _weight_shapes(history_length: int, hidden_width: int) -> dict[str, tuple[int, ...]]:
    input_dimension = 5 * history_length + 1
    return {
        "linear1.weight": (hidden_width, input_dimension),
        "linear1.bias": (hidden_width,),
        "linear2.weight": (hidden_width, hidden_width),
        "linear2.bias": (hidden_width,),
        "output.weight": (8, hidden_width),
        "output.bias": (8,),
    }


def _normalize_weights(
    weights: Mapping[str, np.ndarray],
    *,
    history_length: int,
    hidden_width: int,
) -> Mapping[str, np.ndarray]:
    if not isinstance(weights, Mapping):
        raise TypeError("weights 必须是 Mapping[str, ndarray]")
    if set(weights) != set(_WEIGHT_NAMES):
        raise ValueError("weights 必须精确包含 six frozen array members")
    shapes = _weight_shapes(history_length, hidden_width)
    normalized: dict[str, np.ndarray] = {}
    for name in _WEIGHT_NAMES:
        value = weights[name]
        if not isinstance(value, np.ndarray):
            raise TypeError(f"weights[{name!r}] 必须是 ndarray")
        if value.dtype != np.dtype(np.float32):
            raise ValueError(f"weights[{name!r}] dtype 必须精确为 float32")
        if value.shape != shapes[name]:
            raise ValueError(f"weights[{name!r}] shape 必须精确为 {shapes[name]!r}")
        if not np.all(np.isfinite(value)):
            raise ValueError(f"weights[{name!r}] 必须全部 finite")
        array = np.array(value, dtype="<f4", order="C", copy=True)
        if not array.flags.c_contiguous:
            raise RuntimeError("canonical checkpoint array 必须 C contiguous")
        array.setflags(write=False)
        normalized[name] = array
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class OfficialCheckpointManifest:
    """绑定 config/protocol/plan/runtime 与 logical content 的 checkpoint manifest。"""

    official_spec_sha256: str
    config_sha256: str
    protocol_sha256: str
    training_plan_sha256: str
    rng_namespace_plan_sha256: str
    objective: str
    transform: str
    learning_rate: float
    canonical_order: int
    feature_encoding_sha256: str
    architecture_sha256: str
    model_complexity_key: tuple[int]
    training_seed: int
    epoch: int
    validation_primary_rmse: float
    history_length: int
    hidden_width: int
    input_dimension: int
    output_dimension: int
    runtime_provenance_sha256: str
    checkpoint_content_sha256: str
    schema: str = _CHECKPOINT_SCHEMA
    version: int = _CHECKPOINT_VERSION

    def __post_init__(self) -> None:
        if (
            self.schema != _CHECKPOINT_SCHEMA
            or type(self.version) is not int
            or self.version != _CHECKPOINT_VERSION
        ):
            raise ValueError("checkpoint manifest schema/version 不受支持")
        official_sha = _normalize_sha256(self.official_spec_sha256, "official_spec_sha256")
        if official_sha != EXPECTED_WP03_POINT_PRIMARY_V1_SPEC_SHA256:
            raise ValueError("official_spec_sha256 不是 frozen WP-03 v1")
        normalized_sha256: dict[str, str] = {}
        for value, name in (
            (self.config_sha256, "config_sha256"),
            (self.protocol_sha256, "protocol_sha256"),
            (self.training_plan_sha256, "training_plan_sha256"),
            (self.rng_namespace_plan_sha256, "rng_namespace_plan_sha256"),
            (self.feature_encoding_sha256, "feature_encoding_sha256"),
            (self.architecture_sha256, "architecture_sha256"),
            (self.runtime_provenance_sha256, "runtime_provenance_sha256"),
            (self.checkpoint_content_sha256, "checkpoint_content_sha256"),
        ):
            normalized_sha256[name] = _normalize_sha256(value, name)
        max_epochs = _authoritative_training_max_epochs(
            official_sha,
            normalized_sha256["training_plan_sha256"],
        )
        if not isinstance(self.objective, str):
            raise TypeError("objective 必须是 frozen string identity")
        if not isinstance(self.transform, str):
            raise TypeError("transform 必须是 frozen string identity")
        try:
            objective = PointObjectiveKind(self.objective)
        except ValueError as error:
            raise ValueError("objective 不属于 frozen official set") from error
        try:
            transform = HistoryTransformKind(self.transform)
        except ValueError as error:
            raise ValueError("transform 不属于 frozen official set") from error
        learning_rate = _normalize_finite_nonnegative_float(
            self.learning_rate,
            "learning_rate",
        )
        canonical_order = _normalize_integer(self.canonical_order, "canonical_order", 0)
        model_complexity_key = _normalize_model_complexity_key(self.model_complexity_key)
        training_seed = _normalize_integer(self.training_seed, "training_seed", 0)
        if training_seed not in _TRAINING_SEEDS:
            raise ValueError("training_seed 不属于 frozen official seed set")
        epoch = _normalize_integer(self.epoch, "epoch", 1)
        if epoch > max_epochs:
            raise ValueError("epoch 超过 authoritative training plan max_epochs")
        validation_rmse = _normalize_finite_nonnegative_float(
            self.validation_primary_rmse,
            "validation_primary_rmse",
        )
        history_length = _normalize_integer(self.history_length, "history_length", 1)
        hidden_width = _normalize_integer(self.hidden_width, "hidden_width", 1)
        expected_complexity_key = compute_official_model_complexity_key(
            history_length,
            hidden_width,
        )
        expected_input = 5 * history_length + 1
        input_dimension = _normalize_integer(self.input_dimension, "input_dimension", 1)
        output_dimension = _normalize_integer(self.output_dimension, "output_dimension", 1)
        if input_dimension != expected_input or output_dimension != 8:
            raise ValueError("checkpoint dimensions 与 frozen MLP config 不一致")
        reconstructed = OfficialLearnedTrainingConfig(
            official_spec_sha256=official_sha,
            protocol_sha256=normalized_sha256["protocol_sha256"],
            history_length=history_length,
            objective=objective,
            transform=transform,
            hidden_width=hidden_width,
            learning_rate=learning_rate,
            training_plan_sha256=normalized_sha256["training_plan_sha256"],
            rng_namespace_plan_sha256=normalized_sha256["rng_namespace_plan_sha256"],
            feature_encoding_sha256=normalized_sha256["feature_encoding_sha256"],
            architecture_sha256=normalized_sha256["architecture_sha256"],
            canonical_order=canonical_order,
        )
        if reconstructed.config_sha256 != normalized_sha256["config_sha256"]:
            raise ValueError("config_sha256 与 reconstructed frozen config 不一致")
        if reconstructed.protocol_sha256 != normalized_sha256["protocol_sha256"]:
            raise ValueError("protocol_sha256 与 reconstructed frozen config 不一致")
        if reconstructed.training_plan_sha256 != normalized_sha256["training_plan_sha256"]:
            raise ValueError("training_plan_sha256 与 reconstructed frozen config 不一致")
        if (
            reconstructed.rng_namespace_plan_sha256
            != normalized_sha256["rng_namespace_plan_sha256"]
        ):
            raise ValueError("rng_namespace_plan_sha256 与 reconstructed frozen config 不一致")
        if reconstructed.model_complexity_key != model_complexity_key:
            raise ValueError("model_complexity_key 与 reconstructed frozen config 不一致")
        if expected_complexity_key != model_complexity_key:
            raise ValueError("model_complexity_key 与 manifest dimensions 不一致")
        object.__setattr__(self, "official_spec_sha256", official_sha)
        for name, value in normalized_sha256.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "objective", objective.value)
        object.__setattr__(self, "transform", transform.value)
        object.__setattr__(self, "learning_rate", learning_rate)
        object.__setattr__(self, "canonical_order", canonical_order)
        object.__setattr__(self, "model_complexity_key", model_complexity_key)
        object.__setattr__(self, "training_seed", training_seed)
        object.__setattr__(self, "epoch", epoch)
        object.__setattr__(self, "validation_primary_rmse", validation_rmse)
        object.__setattr__(self, "history_length", history_length)
        object.__setattr__(self, "hidden_width", hidden_width)
        object.__setattr__(self, "input_dimension", input_dimension)
        object.__setattr__(self, "output_dimension", output_dimension)


def _manifest_identity(manifest: OfficialCheckpointManifest) -> dict[str, object]:
    return {
        "schema": manifest.schema,
        "version": manifest.version,
        "official_spec_sha256": manifest.official_spec_sha256,
        "config_sha256": manifest.config_sha256,
        "protocol_sha256": manifest.protocol_sha256,
        "training_plan_sha256": manifest.training_plan_sha256,
        "rng_namespace_plan_sha256": manifest.rng_namespace_plan_sha256,
        "objective": manifest.objective,
        "transform": manifest.transform,
        "learning_rate": manifest.learning_rate,
        "canonical_order": manifest.canonical_order,
        "feature_encoding_sha256": manifest.feature_encoding_sha256,
        "architecture_sha256": manifest.architecture_sha256,
        "model_complexity_key": list(manifest.model_complexity_key),
        "training_seed": manifest.training_seed,
        "epoch": manifest.epoch,
        "validation_primary_rmse": manifest.validation_primary_rmse,
        "history_length": manifest.history_length,
        "hidden_width": manifest.hidden_width,
        "input_dimension": manifest.input_dimension,
        "output_dimension": manifest.output_dimension,
        "runtime_provenance_sha256": manifest.runtime_provenance_sha256,
    }


def _checkpoint_manifest_to_dict(manifest: OfficialCheckpointManifest) -> dict[str, object]:
    """返回包含 logical content digest 的 canonical manifest tree。"""

    if not isinstance(manifest, OfficialCheckpointManifest):
        raise TypeError("manifest 必须是 OfficialCheckpointManifest")
    value = _manifest_identity(manifest)
    value["checkpoint_content_sha256"] = manifest.checkpoint_content_sha256
    return value


def _logical_content_sha256(
    manifest_identity: Mapping[str, object],
    weights: Mapping[str, np.ndarray],
) -> str:
    """Hash canonical manifest identity + ordered logical array content。"""

    hasher = hashlib.sha256()
    hasher.update(b"fura-mappo:wp03-point-checkpoint-logical-content-v1\x00")
    _hash_length_prefixed(hasher, _canonical_json_bytes(manifest_identity))
    for name in _WEIGHT_NAMES:
        array = weights[name]
        _hash_length_prefixed(hasher, name.encode("ascii"))
        _hash_length_prefixed(hasher, array.dtype.str.encode("ascii"))
        _hash_length_prefixed(
            hasher,
            json.dumps(list(array.shape), separators=(",", ":")).encode("ascii"),
        )
        _hash_length_prefixed(hasher, array.tobytes(order="C"))
    return hasher.hexdigest()


@dataclass(frozen=True, slots=True)
class OfficialCheckpoint:
    """严格回读的 manifest 与递归防御性只读 arrays。"""

    manifest: OfficialCheckpointManifest
    weights: Mapping[str, np.ndarray]

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, OfficialCheckpointManifest):
            raise TypeError("manifest 必须是 OfficialCheckpointManifest")
        normalized = _normalize_weights(
            self.weights,
            history_length=self.manifest.history_length,
            hidden_width=self.manifest.hidden_width,
        )
        if _logical_content_sha256(_manifest_identity(self.manifest), normalized) != (
            self.manifest.checkpoint_content_sha256
        ):
            raise ValueError("checkpoint logical content SHA 校验失败")
        object.__setattr__(self, "weights", normalized)


def _coerce_checkpoint_path(path: str | os.PathLike[str]) -> Path:
    if isinstance(path, bytes):
        raise TypeError("path 不能是 bytes")
    try:
        raw = os.fspath(path)
    except TypeError as error:
        raise TypeError("path 必须是 str 或 os.PathLike[str]") from error
    if isinstance(raw, bytes):
        raise TypeError("path 不能是 bytes")
    target = Path(raw)
    if target.suffix != ".ckpt":
        raise ValueError("checkpoint directory 后缀必须精确为 .ckpt")
    return target


def _require_regular_member(path: Path, name: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"checkpoint 缺少 {name}") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"checkpoint member {name} 不能是符号链接")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"checkpoint member {name} 必须是普通文件")


def _read_manifest(path: Path) -> OfficialCheckpointManifest:
    _require_regular_member(path, "manifest.json")
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("checkpoint manifest 超出 1 MiB 上限")
    with path.open("rb") as stream:
        payload = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(payload) > _MAX_MANIFEST_BYTES:
        raise ValueError("checkpoint manifest 超出 1 MiB 上限")
    if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        raise ValueError("checkpoint manifest 必须恰好以一个换行结束")
    value = _strict_json_loads(payload[:-1])
    if set(value) != set(_MANIFEST_FIELDS):
        raise ValueError("checkpoint manifest field set 与 schema 不一致")
    if payload != _canonical_json_bytes(value) + b"\n":
        raise ValueError("checkpoint manifest 不是 canonical JSON representation")
    return OfficialCheckpointManifest(
        official_spec_sha256=value["official_spec_sha256"],  # type: ignore[arg-type]
        config_sha256=value["config_sha256"],  # type: ignore[arg-type]
        protocol_sha256=value["protocol_sha256"],  # type: ignore[arg-type]
        training_plan_sha256=value["training_plan_sha256"],  # type: ignore[arg-type]
        rng_namespace_plan_sha256=value["rng_namespace_plan_sha256"],  # type: ignore[arg-type]
        objective=value["objective"],  # type: ignore[arg-type]
        transform=value["transform"],  # type: ignore[arg-type]
        learning_rate=value["learning_rate"],  # type: ignore[arg-type]
        canonical_order=value["canonical_order"],  # type: ignore[arg-type]
        feature_encoding_sha256=value["feature_encoding_sha256"],  # type: ignore[arg-type]
        architecture_sha256=value["architecture_sha256"],  # type: ignore[arg-type]
        model_complexity_key=value["model_complexity_key"],  # type: ignore[arg-type]
        training_seed=value["training_seed"],  # type: ignore[arg-type]
        epoch=value["epoch"],  # type: ignore[arg-type]
        validation_primary_rmse=value["validation_primary_rmse"],  # type: ignore[arg-type]
        history_length=value["history_length"],  # type: ignore[arg-type]
        hidden_width=value["hidden_width"],  # type: ignore[arg-type]
        input_dimension=value["input_dimension"],  # type: ignore[arg-type]
        output_dimension=value["output_dimension"],  # type: ignore[arg-type]
        runtime_provenance_sha256=value["runtime_provenance_sha256"],  # type: ignore[arg-type]
        checkpoint_content_sha256=value["checkpoint_content_sha256"],  # type: ignore[arg-type]
        schema=value["schema"],  # type: ignore[arg-type]
        version=value["version"],  # type: ignore[arg-type]
    )


def _read_npy_header(stream: BinaryIO) -> tuple[tuple[int, ...], bool, np.dtype[object]]:
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        return np.lib.format.read_array_header_1_0(stream, max_header_size=_MAX_NPY_HEADER_BYTES)
    if version in {(2, 0), (3, 0)}:
        return np.lib.format.read_array_header_2_0(stream, max_header_size=_MAX_NPY_HEADER_BYTES)
    raise ValueError("checkpoint NPY member version 不受支持")


def _inspect_npz_members(
    archive: zipfile.ZipFile,
    expected_shapes: Mapping[str, tuple[int, ...]],
) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValueError("weights.npz 包含重复 member")
    if set(names) != set(_MEMBER_NAMES) or len(names) != len(_MEMBER_NAMES):
        raise ValueError("weights.npz members 必须精确等于 frozen six-array schema")
    by_name = {info.filename: info for info in infos}
    for weight_name, member_name in zip(_WEIGHT_NAMES, _MEMBER_NAMES, strict=True):
        info = by_name[member_name]
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode) or info.is_dir():
            raise ValueError("weights.npz 不允许 symlink/directory member")
        if info.file_size > _MAX_WEIGHTS_BYTES:
            raise ValueError("weights.npz member 超出安全大小上限")
        with archive.open(info, "r") as stream:
            shape, fortran_order, dtype = _read_npy_header(stream)
            header_end_offset = stream.tell()
        if dtype.hasobject:
            raise ValueError("weights.npz 不允许 object dtype")
        if dtype != np.dtype("<f4"):
            raise ValueError("weights.npz member dtype 必须精确为 canonical little-endian float32")
        if fortran_order:
            raise ValueError("weights.npz member 必须是 C-order representation")
        if shape != expected_shapes[weight_name]:
            raise ValueError(f"weights.npz member {weight_name!r} shape 错误")
        expected_array_bytes = math.prod(shape) * dtype.itemsize
        expected_member_size = header_end_offset + expected_array_bytes
        if info.file_size != expected_member_size:
            raise ValueError(f"weights.npz member {weight_name!r} 含 trailing 或缺失 bytes")
    return by_name


def _read_weights(
    path: Path,
    *,
    history_length: int,
    hidden_width: int,
) -> Mapping[str, np.ndarray]:
    _require_regular_member(path, "weights.npz")
    if path.stat().st_size > _MAX_WEIGHTS_BYTES:
        raise ValueError("weights.npz 超出 512 MiB 上限")
    shapes = _weight_shapes(history_length, hidden_width)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = _inspect_npz_members(archive, shapes)
            loaded: dict[str, np.ndarray] = {}
            for weight_name, member_name in zip(_WEIGHT_NAMES, _MEMBER_NAMES, strict=True):
                with archive.open(infos[member_name], "r") as stream:
                    array = np.load(stream, allow_pickle=False)
                    if stream.read(1) != b"":
                        raise ValueError(f"weights.npz member {weight_name!r} 含 trailing bytes")
                if not isinstance(array, np.ndarray):
                    raise ValueError("weights.npz member 不是 ndarray")
                loaded[weight_name] = array
    except (zipfile.BadZipFile, EOFError, zlib.error) as error:
        raise ValueError("weights.npz 损坏或不是有效 NPZ") from error
    return _normalize_weights(
        loaded,
        history_length=history_length,
        hidden_width=hidden_width,
    )


def _load_checkpoint_directory(path: Path, *, require_suffix: bool) -> OfficialCheckpoint:
    if require_suffix and path.suffix != ".ckpt":
        raise ValueError("checkpoint directory 后缀必须精确为 .ckpt")
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError("checkpoint directory 不存在") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("checkpoint directory 不能是符号链接")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("checkpoint path 必须是目录")
    names = {entry.name for entry in path.iterdir()}
    if names != {"manifest.json", "weights.npz"}:
        raise ValueError("checkpoint directory 必须精确包含 manifest.json 与 weights.npz")
    manifest = _read_manifest(path / "manifest.json")
    weights = _read_weights(
        path / "weights.npz",
        history_length=manifest.history_length,
        hidden_width=manifest.hidden_width,
    )
    return OfficialCheckpoint(manifest=manifest, weights=weights)


def load_official_checkpoint(path: str | os.PathLike[str]) -> OfficialCheckpoint:
    """Strict-load 一个 no-pickle official checkpoint directory。"""

    return _load_checkpoint_directory(_coerce_checkpoint_path(path), require_suffix=True)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
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


def _write_file(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _current_platform() -> str:
    """返回 atomic publication dispatch 使用的 Python platform identity。"""

    return sys.platform


def _load_process_libc() -> ctypes.CDLL:
    """加载当前进程 libc；不可用时对 atomic publication fail closed。"""

    try:
        return ctypes.CDLL(None, use_errno=True)
    except OSError as error:
        raise OSError(
            errno.ENOTSUP,
            "atomic no-replace directory publication is unsupported",
        ) from error


def _encoded_path(path: Path) -> bytes:
    encoded = os.fsencode(os.fspath(path))
    if b"\x00" in encoded:
        raise ValueError("checkpoint publication path 不能包含 NUL")
    return encoded


def _raise_atomic_rename_error(error_number: int, source: Path, destination: Path) -> None:
    if error_number == errno.EEXIST:
        raise FileExistsError(
            error_number,
            "checkpoint destination already exists at atomic publication",
            os.fspath(destination),
        )
    if error_number == 0:
        error_number = errno.EIO
    raise OSError(
        error_number,
        f"atomic no-replace directory publication failed: {os.strerror(error_number)}",
        os.fspath(source),
    )


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    """使用单次 platform-native atomic NO-REPLACE directory rename。"""

    source_bytes = _encoded_path(source)
    destination_bytes = _encoded_path(destination)
    libc = _load_process_libc()
    platform_name = _current_platform()
    if platform_name.startswith("linux"):
        try:
            renameat2 = libc.renameat2
        except AttributeError as error:
            raise OSError(
                errno.ENOTSUP,
                "atomic no-replace directory publication is unsupported",
            ) from error
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = renameat2(
            _AT_FDCWD,
            source_bytes,
            _AT_FDCWD,
            destination_bytes,
            _RENAME_NOREPLACE,
        )
    elif platform_name == "darwin":
        try:
            renamex_np = libc.renamex_np
        except AttributeError as error:
            raise OSError(
                errno.ENOTSUP,
                "atomic no-replace directory publication is unsupported",
            ) from error
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = renamex_np(source_bytes, destination_bytes, _RENAME_EXCL)
    else:
        raise OSError(
            errno.ENOTSUP,
            "atomic no-replace directory publication is unsupported",
        )
    if result != 0:
        _raise_atomic_rename_error(ctypes.get_errno(), source, destination)


def _check_checkpoint_target_absent(target: Path) -> None:
    """仅提供快速失败；最终正确性由 atomic NO-REPLACE primitive 保证。"""

    if target.is_symlink():
        raise ValueError("checkpoint target 不能是符号链接")
    if os.path.lexists(target):
        raise FileExistsError("checkpoint target 已存在")


def write_official_checkpoint(
    path: str | os.PathLike[str],
    *,
    learned_config: OfficialLearnedTrainingConfig,
    training_seed: int,
    epoch: int,
    validation_primary_rmse: float,
    runtime_provenance_sha256: str,
    weights: Mapping[str, np.ndarray],
) -> Path:
    """从唯一 frozen learned config 派生 identity 并原子发布 checkpoint。"""

    target = _coerce_checkpoint_path(path)
    if not target.parent.exists() or not target.parent.is_dir():
        raise FileNotFoundError("checkpoint parent 必须是已存在目录")
    _check_checkpoint_target_absent(target)

    if not isinstance(learned_config, OfficialLearnedTrainingConfig):
        raise TypeError("learned_config 必须是 OfficialLearnedTrainingConfig")
    history = learned_config.history_length
    width = learned_config.hidden_width
    normalized_weights = _normalize_weights(
        weights,
        history_length=history,
        hidden_width=width,
    )
    identity = {
        "schema": _CHECKPOINT_SCHEMA,
        "version": _CHECKPOINT_VERSION,
        "official_spec_sha256": learned_config.official_spec_sha256,
        "config_sha256": learned_config.config_sha256,
        "protocol_sha256": learned_config.protocol_sha256,
        "training_plan_sha256": learned_config.training_plan_sha256,
        "rng_namespace_plan_sha256": learned_config.rng_namespace_plan_sha256,
        "objective": learned_config.objective.value,
        "transform": learned_config.transform.value,
        "learning_rate": learned_config.learning_rate,
        "canonical_order": learned_config.canonical_order,
        "feature_encoding_sha256": learned_config.feature_encoding_sha256,
        "architecture_sha256": learned_config.architecture_sha256,
        "model_complexity_key": list(learned_config.model_complexity_key),
        "training_seed": _normalize_integer(training_seed, "training_seed", 0),
        "epoch": _normalize_integer(epoch, "epoch", 1),
        "validation_primary_rmse": _normalize_finite_nonnegative_float(
            validation_primary_rmse,
            "validation_primary_rmse",
        ),
        "history_length": history,
        "hidden_width": width,
        "input_dimension": 5 * history + 1,
        "output_dimension": 8,
        "runtime_provenance_sha256": _normalize_sha256(
            runtime_provenance_sha256,
            "runtime_provenance_sha256",
        ),
    }
    digest = _logical_content_sha256(identity, normalized_weights)
    manifest = OfficialCheckpointManifest(
        **identity,  # type: ignore[arg-type]
        checkpoint_content_sha256=digest,
    )

    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
    )
    published = False
    try:
        weights_path = temporary / "weights.npz"
        with weights_path.open("xb") as stream:
            np.savez(stream, **{name: normalized_weights[name] for name in _WEIGHT_NAMES})
            stream.flush()
            os.fsync(stream.fileno())
        manifest_payload = _canonical_json_bytes(_checkpoint_manifest_to_dict(manifest)) + b"\n"
        if len(manifest_payload) > _MAX_MANIFEST_BYTES:
            raise ValueError("checkpoint manifest 超出 1 MiB 上限")
        _write_file(temporary / "manifest.json", manifest_payload)
        _fsync_directory(temporary)

        readback = _load_checkpoint_directory(temporary, require_suffix=False)
        if readback.manifest != manifest:
            raise RuntimeError("checkpoint strict readback manifest 不一致")
        for name in _WEIGHT_NAMES:
            if not np.array_equal(readback.weights[name], normalized_weights[name]):
                raise RuntimeError("checkpoint strict readback weights 不一致")
        _rename_directory_noreplace(temporary, target)
        published = True
        _fsync_directory(target.parent)
        return target
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)


__all__ = [
    "OfficialCheckpoint",
    "OfficialCheckpointManifest",
    "load_official_checkpoint",
    "write_official_checkpoint",
]
