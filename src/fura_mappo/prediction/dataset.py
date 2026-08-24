"""WP-03A deterministic dataset protocol、source identity 与 split manifest。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import InitVar, dataclass, field
from enum import Enum

import numpy as np

from fura_mappo.demand import (
    DemandTrace,
    DemandTraceArtifact,
    compute_config_hash,
    load_demand_trace,
)
from fura_mappo.prediction.models import (
    PredictionContext,
    PredictionSample,
    PredictionTarget,
    ZoneSchema,
    _normalize_integer,
    _normalize_sha256,
)

_DATASET_PROTOCOL_SCHEMA = "fura-mappo.prediction-dataset-protocol"
_DATASET_PROTOCOL_VERSION = 1
_SPLIT_MANIFEST_SCHEMA = "fura-mappo.prediction-split-manifest"
_SPLIT_MANIFEST_VERSION = 1
_TARGET_KIND = "realized_zone_arrival_counts"
_HISTORY_KIND = "realized_zone_arrival_counts"
_HISTORY_PADDING = "zero_left_with_boolean_mask"
_TARGET_PADDING = "zero_right_with_boolean_mask"
_ANCHOR_RULE = "start_step_le_anchor_lt_stop_step_minus_one"
_ZONE_ORDERING = "zero_based_zone_id_ascending"
_TRACE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_REALIZED_TRACE_HASH_SCHEMA = "fura-mappo.prediction-realized-trace"
_REALIZED_TRACE_HASH_VERSION = 1


def _copy_plain_tree(value: object, name: str = "resolved_config") -> object:
    """复制有限 JSON-style tree，不接受 NumPy/global-state 特殊对象。"""

    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} 不允许布尔值")
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
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_copy_plain_tree(item, name) for item in value]
    raise TypeError(f"{name} 包含不支持的值类型")


def _normalize_nonempty_string(value: object, name: str) -> str:
    """验证不含路径分隔符的非空标识字符串。"""

    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} 必须是非空字符串")
    if "/" in value or "\\" in value:
        raise ValueError(f"{name} 不能包含路径分隔符")
    return value


def _hash_length_prefixed(hasher: hashlib._Hash, payload: bytes) -> None:
    """把单个 logical field 以大端 uint64 长度前缀纳入 hash。"""

    hasher.update(struct.pack(">Q", len(payload)))
    hasher.update(payload)


def _hash_realized_array(
    hasher: hashlib._Hash,
    name: str,
    array: np.ndarray,
) -> None:
    """按 name/dtype/shape/C-order bytes 纳入一个 canonical realized array。"""

    _hash_length_prefixed(hasher, name.encode("ascii"))
    _hash_length_prefixed(hasher, array.dtype.str.encode("ascii"))
    shape = json.dumps(list(array.shape), separators=(",", ":")).encode("ascii")
    _hash_length_prefixed(hasher, shape)
    _hash_length_prefixed(hasher, array.tobytes(order="C"))


def _realized_int64_array(values: Sequence[int], name: str) -> np.ndarray:
    """把 artifact-realizable event 整数列规范化为 C-order little-endian int64。"""

    minimum = int(np.iinfo(np.int64).min)
    maximum = int(np.iinfo(np.int64).max)
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} 必须全部是非 bool 整数")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} 包含无法表示为 artifact int64 的值")
        normalized.append(value)
    return np.ascontiguousarray(normalized, dtype="<i8")


def _realized_float64_array(value: object, name: str) -> np.ndarray:
    """规范化 realized float 列，并把 IEEE signed zero 统一为正零。"""

    normalized = np.array(value, dtype="<f8", order="C", copy=True)
    if not np.all(np.isfinite(normalized)):
        raise ValueError(f"{name} 必须全部为有限值")
    normalized[normalized == 0.0] = 0.0
    return normalized


def compute_realized_trace_sha256(trace: DemandTrace) -> str:
    """计算只绑定 realized demand content 的 intrinsic trace identity。

    v1 logical content 依次包含 schema/version domain separator、typed ``start_step``、canonical
    little-endian ``counts``，以及按 ``DemandTrace.events`` 规范顺序排列的 event_id、arrival_step、
    zone_id、positions、priority、service_time、deadline 列。每个数组均绑定 name、dtype、shape 与
    C-order bytes。``positions`` 与 ``priority`` 中数值相等的 ``+0.0``/``-0.0`` 在 hash 前统一
    canonicalize 为 ``+0.0``。明确不读取 ``intensities`` 或任何 artifact/config/runtime/path
    metadata。
    """

    if not isinstance(trace, DemandTrace):
        raise TypeError("trace 必须是 DemandTrace")
    hasher = hashlib.sha256()
    hasher.update(b"fura-mappo:prediction-realized-trace-sha256-v1\x00")
    _hash_length_prefixed(hasher, _REALIZED_TRACE_HASH_SCHEMA.encode("ascii"))
    _hash_length_prefixed(hasher, str(_REALIZED_TRACE_HASH_VERSION).encode("ascii"))
    _hash_length_prefixed(hasher, b"start_step")
    _hash_length_prefixed(hasher, b"int")
    _hash_length_prefixed(hasher, str(trace.start_step).encode("ascii"))

    events = trace.events
    positions = np.empty((len(events), 2), dtype="<f8")
    if events:
        positions[:, :] = [event.position for event in events]
    positions = _realized_float64_array(positions, "positions")
    priorities = _realized_float64_array(
        [event.priority for event in events],
        "priority",
    )
    arrays = (
        ("counts", np.ascontiguousarray(trace.counts, dtype="<i8")),
        ("event_id", _realized_int64_array([event.event_id for event in events], "event_id")),
        (
            "arrival_step",
            _realized_int64_array([event.arrival_step for event in events], "arrival_step"),
        ),
        ("zone_id", _realized_int64_array([event.zone_id for event in events], "zone_id")),
        ("positions", positions),
        ("priority", priorities),
        (
            "service_time",
            _realized_int64_array([event.service_time for event in events], "service_time"),
        ),
        ("deadline", _realized_int64_array([event.deadline for event in events], "deadline")),
    )
    for name, array in arrays:
        _hash_realized_array(hasher, name, array)
    return hasher.hexdigest()


def dataset_protocol_identity(spec: DatasetProtocolSpec) -> dict[str, object]:
    """返回不含 self hash 的 dataset derivation 科学身份树。"""

    if not isinstance(spec, DatasetProtocolSpec):
        raise TypeError("spec 必须是 DatasetProtocolSpec")
    return {
        "schema": spec.schema,
        "version": spec.version,
        "history_length": spec.history_length,
        "prediction_horizon": spec.prediction_horizon,
        "zone_schema_sha256": spec.zone_schema_sha256,
        "target_kind": spec.target_kind,
        "history_kind": spec.history_kind,
        "history_padding": spec.history_padding,
        "target_padding": spec.target_padding,
        "anchor_rule": spec.anchor_rule,
        "zone_ordering": spec.zone_ordering,
    }


@dataclass(frozen=True, slots=True)
class DatasetProtocolSpec:
    """参数化但 versioned 的 WP-03A dataset derivation 规范。"""

    history_length: int
    prediction_horizon: int
    zone_schema_sha256: str
    target_kind: str = _TARGET_KIND
    history_kind: str = _HISTORY_KIND
    history_padding: str = _HISTORY_PADDING
    target_padding: str = _TARGET_PADDING
    anchor_rule: str = _ANCHOR_RULE
    zone_ordering: str = _ZONE_ORDERING
    schema: str = _DATASET_PROTOCOL_SCHEMA
    version: int = _DATASET_PROTOCOL_VERSION
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """验证冻结语义常量并计算 deterministic protocol hash。"""

        history_length = _normalize_integer(self.history_length, "history_length", 1)
        horizon = _normalize_integer(self.prediction_horizon, "prediction_horizon", 1)
        zone_hash = _normalize_sha256(self.zone_schema_sha256, "zone_schema_sha256")
        expected = {
            "target_kind": _TARGET_KIND,
            "history_kind": _HISTORY_KIND,
            "history_padding": _HISTORY_PADDING,
            "target_padding": _TARGET_PADDING,
            "anchor_rule": _ANCHOR_RULE,
            "zone_ordering": _ZONE_ORDERING,
            "schema": _DATASET_PROTOCOL_SCHEMA,
            "version": _DATASET_PROTOCOL_VERSION,
        }
        for name, value in expected.items():
            actual = getattr(self, name)
            if type(actual) is not type(value) or actual != value:
                raise ValueError(f"{name} 必须精确等于冻结值 {value!r}")
        object.__setattr__(self, "history_length", history_length)
        object.__setattr__(self, "prediction_horizon", horizon)
        object.__setattr__(self, "zone_schema_sha256", zone_hash)
        object.__setattr__(
            self,
            "sha256",
            compute_config_hash(dataset_protocol_identity(self)),
        )


def compute_condition_sha256(resolved_config: Mapping[str, object]) -> str:
    """计算去除 realization seed 后的 demand condition identity。

    精确规则是：防御性复制完整 WP-01 ``resolved_config``，要求其含 ``demand`` 与
    ``generation``，只删除 ``demand.seed``，保留 schema/version、全部 demand dynamics、
    zone geometry 和 generation protocol，再对所得完整 tree 调用现有
    :func:`compute_config_hash`。
    """

    if not isinstance(resolved_config, Mapping):
        raise TypeError("resolved_config 必须是 Mapping")
    copied = _copy_plain_tree(resolved_config)
    if not isinstance(copied, dict):
        raise TypeError("resolved_config 顶层必须是 Mapping")
    expected_top = {"schema", "version", "demand", "generation"}
    if set(copied) != expected_top:
        raise ValueError("resolved_config 顶层字段必须与 WP-01 config schema 一致")
    if (
        copied["schema"] != "fura-mappo.demand-generation"
        or isinstance(copied["version"], bool)
        or not isinstance(copied["version"], int)
        or copied["version"] != 1
    ):
        raise ValueError("resolved_config schema/version 不受支持")
    demand = copied.get("demand")
    generation = copied.get("generation")
    if not isinstance(demand, dict):
        raise ValueError("resolved_config.demand 必须是 Mapping")
    if not isinstance(generation, dict):
        raise ValueError("resolved_config.generation 必须是 Mapping")
    if "seed" not in demand:
        raise ValueError("resolved_config.demand 必须包含 seed")
    seed = demand.pop("seed")
    _normalize_integer(seed, "resolved_config.demand.seed", 0)
    return compute_config_hash(copied)


@dataclass(frozen=True, slots=True)
class PredictionSource:
    """一条 dataset trace 的可序列化审计描述符。

    该 dataclass 本身只验证字段结构，不证明字段来自真实 artifact。科学数据路径必须通过
    :func:`load_verified_prediction_artifact` 建立 authoritative binding；直接构造仅用于
    synthetic unit fixtures 或 strict manifest readback。
    """

    trace_id: str
    seed: int
    process_type: str
    config_sha256: str
    content_sha256: str
    realized_trace_sha256: str
    condition_sha256: str
    zone_schema_sha256: str
    start_step: int
    num_steps: int
    num_zones: int

    def __post_init__(self) -> None:
        """验证 scalar identity；该对象不得进入 PredictionContext。"""

        if not isinstance(self.trace_id, str) or _TRACE_ID_PATTERN.fullmatch(self.trace_id) is None:
            raise ValueError("trace_id 必须是安全的 1..255 字符标识符")
        object.__setattr__(self, "seed", _normalize_integer(self.seed, "seed", 0))
        object.__setattr__(
            self,
            "process_type",
            _normalize_nonempty_string(self.process_type, "process_type"),
        )
        for name in (
            "config_sha256",
            "content_sha256",
            "realized_trace_sha256",
            "condition_sha256",
            "zone_schema_sha256",
        ):
            object.__setattr__(self, name, _normalize_sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "start_step",
            _normalize_integer(self.start_step, "start_step", 0),
        )
        object.__setattr__(self, "num_steps", _normalize_integer(self.num_steps, "num_steps", 1))
        object.__setattr__(self, "num_zones", _normalize_integer(self.num_zones, "num_zones", 1))


def prediction_source_to_dict(source: PredictionSource) -> dict[str, object]:
    """返回 source descriptor 的 canonical JSON-style tree。"""

    if not isinstance(source, PredictionSource):
        raise TypeError("source 必须是 PredictionSource")
    return {
        "trace_id": source.trace_id,
        "seed": source.seed,
        "process_type": source.process_type,
        "config_sha256": source.config_sha256,
        "content_sha256": source.content_sha256,
        "realized_trace_sha256": source.realized_trace_sha256,
        "condition_sha256": source.condition_sha256,
        "zone_schema_sha256": source.zone_schema_sha256,
        "start_step": source.start_step,
        "num_steps": source.num_steps,
        "num_zones": source.num_zones,
    }


def _prediction_source_from_validated_artifact(
    artifact: DemandTraceArtifact,
    trace_id: str,
) -> PredictionSource:
    """由 WP-01 safe loader 已完整验证的 artifact 构造 source descriptor。"""

    if not isinstance(artifact, DemandTraceArtifact):
        raise TypeError("artifact 必须是 DemandTraceArtifact")
    manifest = artifact.manifest
    required = (
        "seed",
        "process_type",
        "config_sha256",
        "content_sha256",
        "resolved_config",
        "start_step",
        "num_steps",
        "num_zones",
    )
    if any(name not in manifest for name in required):
        raise ValueError("artifact manifest 缺少 prediction source 必需字段")
    resolved = manifest["resolved_config"]
    if not isinstance(resolved, Mapping):
        raise ValueError("artifact manifest.resolved_config 必须是 Mapping")
    config_sha = _normalize_sha256(manifest["config_sha256"], "manifest.config_sha256")
    if compute_config_hash(resolved) != config_sha:
        raise ValueError("artifact manifest config_sha256 与 resolved_config 不一致")
    demand = resolved.get("demand")
    if not isinstance(demand, Mapping):
        raise ValueError("artifact resolved_config.demand 必须是 Mapping")
    if demand.get("seed") != manifest["seed"]:
        raise ValueError("artifact manifest seed 与 resolved_config 不一致")
    if demand.get("type") != manifest["process_type"]:
        raise ValueError("artifact manifest process_type 与 resolved_config 不一致")
    trace = artifact.trace
    num_steps, num_zones = trace.counts.shape
    if "zone_bounds" not in demand:
        raise ValueError("artifact resolved_config.demand 缺少 zone_bounds")
    zone_schema = ZoneSchema(demand["zone_bounds"])
    if zone_schema.num_zones != num_zones:
        raise ValueError("artifact zone_bounds 与 DemandTrace zone 数量不一致")
    comparisons = {
        "start_step": trace.start_step,
        "num_steps": num_steps,
        "num_zones": num_zones,
    }
    for name, expected in comparisons.items():
        if manifest[name] != expected:
            raise ValueError(f"artifact manifest.{name} 与 DemandTrace 不一致")
    return PredictionSource(
        trace_id=trace_id,
        seed=manifest["seed"],  # type: ignore[arg-type]
        process_type=manifest["process_type"],  # type: ignore[arg-type]
        config_sha256=config_sha,
        content_sha256=manifest["content_sha256"],  # type: ignore[arg-type]
        realized_trace_sha256=compute_realized_trace_sha256(trace),
        condition_sha256=compute_condition_sha256(resolved),
        zone_schema_sha256=zone_schema.sha256,
        start_step=trace.start_step,
        num_steps=num_steps,
        num_zones=num_zones,
    )


_VERIFIED_ARTIFACT_TOKEN = object()


@dataclass(frozen=True, slots=True)
class VerifiedPredictionArtifact:
    """由 WP-01 safe loader 建立的 authoritative offline artifact/source binding。

    该对象可在 offline dataset/manifest construction 中持有完整 ``DemandTraceArtifact``；它绝不
    是 predictor 或 controller 输入。普通 caller 不能用自填 metadata 构造合法实例。
    """

    artifact: DemandTraceArtifact
    source: PredictionSource
    _verification_token: InitVar[object]

    def __post_init__(self, _verification_token: object) -> None:
        """只允许本模块的 safe-loader factory 建立 verified binding。"""

        if _verification_token is not _VERIFIED_ARTIFACT_TOKEN:
            raise TypeError(
                "VerifiedPredictionArtifact 必须由 load_verified_prediction_artifact 构造"
            )
        if not isinstance(self.artifact, DemandTraceArtifact):
            raise TypeError("artifact 必须是 DemandTraceArtifact")
        if not isinstance(self.source, PredictionSource):
            raise TypeError("source 必须是 PredictionSource")


def load_verified_prediction_artifact(
    path: str | os.PathLike[str],
    trace_id: str,
) -> VerifiedPredictionArtifact:
    """经 WP-01 strict NPZ loader 建立唯一 authoritative source descriptor。

    WP-01 loader 负责 NPZ member/schema/dtype/shape、resolved config、config SHA、logical content
    SHA、seed、process type 与 trace reconstruction 的完整交叉验证；本层只从该验证结果派生
    condition 与 zone schema identity。
    """

    artifact = load_demand_trace(path)
    source = _prediction_source_from_validated_artifact(artifact, trace_id)
    return VerifiedPredictionArtifact(artifact, source, _VERIFIED_ARTIFACT_TOKEN)


_SOURCE_BINDING_FIELDS = (
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
)


def validate_prediction_source_for_artifact(
    verified: VerifiedPredictionArtifact,
    source: PredictionSource,
) -> None:
    """拒绝与 authoritative safe-loaded artifact 不完全一致的 descriptor。"""

    if not isinstance(verified, VerifiedPredictionArtifact):
        raise TypeError("verified 必须是 VerifiedPredictionArtifact")
    if not isinstance(source, PredictionSource):
        raise TypeError("source 必须是 PredictionSource")
    mismatches = tuple(
        name
        for name in _SOURCE_BINDING_FIELDS
        if getattr(source, name) != getattr(verified.source, name)
    )
    if mismatches:
        raise ValueError("PredictionSource 与 verified artifact 不一致: " + ", ".join(mismatches))


def _validate_source_zone_schema(
    source: PredictionSource,
    spec: DatasetProtocolSpec,
) -> None:
    """把 authoritative/synthetic source zone geometry hard-bind 到 dataset protocol。"""

    if source.zone_schema_sha256 != spec.zone_schema_sha256:
        raise ValueError("source.zone_schema_sha256 必须等于 dataset protocol zone schema")


class SplitLabel(str, Enum):
    """WP-03A 预留的完整 trace split labels。"""

    TRAIN = "train"
    VALIDATION = "validation"
    CALIBRATION = "calibration"
    TEST_ID = "test_id"
    TEST_OOD = "test_ood"


_SPLIT_ORDER = {label: index for index, label in enumerate(SplitLabel)}


@dataclass(frozen=True, slots=True)
class SplitEntry:
    """把完整 source trace 分配给唯一 split。"""

    split: SplitLabel
    source: PredictionSource

    def __post_init__(self) -> None:
        """规范化 label 并验证 source 类型。"""

        try:
            split = self.split if isinstance(self.split, SplitLabel) else SplitLabel(self.split)
        except (TypeError, ValueError) as error:
            raise ValueError("split 必须是 WP-03A 预留 label") from error
        if not isinstance(self.source, PredictionSource):
            raise TypeError("source 必须是 PredictionSource")
        object.__setattr__(self, "split", split)


def _split_entry_sort_key(entry: SplitEntry) -> tuple[object, ...]:
    """返回跨文件系统和调用方输入顺序稳定的 manifest ordering key。"""

    return (
        _SPLIT_ORDER[entry.split],
        entry.source.condition_sha256,
        entry.source.seed,
        entry.source.trace_id,
        entry.source.content_sha256,
    )


def split_entry_to_dict(entry: SplitEntry) -> dict[str, object]:
    """返回 split entry 的 canonical JSON-style tree。"""

    if not isinstance(entry, SplitEntry):
        raise TypeError("entry 必须是 SplitEntry")
    return {"split": entry.split.value, "source": prediction_source_to_dict(entry.source)}


def split_manifest_identity(manifest: DatasetSplitManifest) -> dict[str, object]:
    """返回不含 self hash 的 explicit split manifest identity。"""

    if not isinstance(manifest, DatasetSplitManifest):
        raise TypeError("manifest 必须是 DatasetSplitManifest")
    return {
        "schema": manifest.schema,
        "version": manifest.version,
        "entries": [split_entry_to_dict(entry) for entry in manifest.entries],
    }


@dataclass(frozen=True, slots=True)
class DatasetSplitManifest:
    """以完整 trace 为 unit 的显式、泄漏防护 split declaration。

    构造函数验证 descriptor-level 结构与 global identities。Scientific provenance 还必须经
    ``build_split_manifest_from_artifacts`` 构造，或在 readback 后执行
    ``validate_split_manifest_artifacts``。
    """

    entries: tuple[SplitEntry, ...]
    schema: str = _SPLIT_MANIFEST_SCHEMA
    version: int = _SPLIT_MANIFEST_VERSION
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """规范排序、拒绝 identity/seed 重复并检查 OOD condition 隔离。"""

        if (
            not isinstance(self.schema, str)
            or self.schema != _SPLIT_MANIFEST_SCHEMA
            or isinstance(self.version, bool)
            or not isinstance(self.version, (int, np.integer))
            or int(self.version) != _SPLIT_MANIFEST_VERSION
        ):
            raise ValueError("split manifest schema/version 不受支持")
        object.__setattr__(self, "version", int(self.version))
        try:
            entries = tuple(self.entries)
        except TypeError as error:
            raise TypeError("entries 必须是 SplitEntry 序列") from error
        if not entries:
            raise ValueError("split manifest 必须至少包含一个 source")
        if not all(isinstance(entry, SplitEntry) for entry in entries):
            raise TypeError("entries 中每一项都必须是 SplitEntry")
        entries = tuple(sorted(entries, key=_split_entry_sort_key))

        identity_fields = (
            "trace_id",
            "content_sha256",
            "realized_trace_sha256",
            "seed",
        )
        for name in identity_fields:
            values = [getattr(entry.source, name) for entry in entries]
            if len(values) != len(set(values)):
                raise ValueError(f"split manifest 不允许重复 source {name}")

        development_labels = {
            SplitLabel.TRAIN,
            SplitLabel.VALIDATION,
            SplitLabel.CALIBRATION,
            SplitLabel.TEST_ID,
        }
        development_conditions = {
            entry.source.condition_sha256 for entry in entries if entry.split in development_labels
        }
        ood_conditions = {
            entry.source.condition_sha256 for entry in entries if entry.split is SplitLabel.TEST_OOD
        }
        overlap = development_conditions & ood_conditions
        if overlap:
            raise ValueError("test_ood condition 必须与 train/validation/calibration/test_id 隔离")

        object.__setattr__(self, "entries", entries)
        object.__setattr__(
            self,
            "sha256",
            compute_config_hash(split_manifest_identity(self)),
        )


def _validate_trace_and_anchor(
    trace: DemandTrace,
    spec: DatasetProtocolSpec,
    anchor_absolute_step: object,
) -> tuple[int, int, int, int]:
    """返回规范 anchor、stop、num_steps、num_zones。"""

    if not isinstance(trace, DemandTrace):
        raise TypeError("trace 必须是 DemandTrace")
    if not isinstance(spec, DatasetProtocolSpec):
        raise TypeError("spec 必须是 DatasetProtocolSpec")
    anchor = _normalize_integer(anchor_absolute_step, "anchor_absolute_step", 0)
    num_steps, num_zones = trace.counts.shape
    stop_step = trace.start_step + num_steps
    if not trace.start_step <= anchor < stop_step:
        raise ValueError("anchor_absolute_step 必须位于 DemandTrace 时间范围内")
    return anchor, stop_step, num_steps, num_zones


def derive_prediction_context(
    trace: DemandTrace,
    spec: DatasetProtocolSpec,
    anchor_absolute_step: int,
) -> PredictionContext:
    """只从 ``counts[:t+1]`` 显式复制构造 boundary ``t`` 的离线 context。"""

    anchor, stop_step, _, num_zones = _validate_trace_and_anchor(
        trace,
        spec,
        anchor_absolute_step,
    )
    history = np.zeros((spec.history_length, num_zones), dtype=np.int64)
    mask = np.zeros(spec.history_length, dtype=np.bool_)
    first_observed = max(trace.start_step, anchor - spec.history_length + 1)
    observed_count = anchor - first_observed + 1
    source_start = first_observed - trace.start_step
    source_stop = anchor - trace.start_step + 1
    history[-observed_count:, :] = trace.counts[source_start:source_stop, :]
    mask[-observed_count:] = True
    return PredictionContext(
        absolute_step=anchor,
        steps_remaining=stop_step - anchor,
        history_counts=history,
        history_mask=mask,
        zone_schema_sha256=spec.zone_schema_sha256,
        prediction_horizon=spec.prediction_horizon,
    )


def derive_prediction_target(
    trace: DemandTrace,
    spec: DatasetProtocolSpec,
    anchor_absolute_step: int,
) -> PredictionTarget:
    """由 realized future counts 构造 lead 1..P 标签并在 episode end 右填充。"""

    anchor, stop_step, _, num_zones = _validate_trace_and_anchor(
        trace,
        spec,
        anchor_absolute_step,
    )
    target = np.zeros((spec.prediction_horizon, num_zones), dtype=np.int64)
    mask = np.zeros(spec.prediction_horizon, dtype=np.bool_)
    future_start = anchor + 1
    future_stop = min(stop_step, future_start + spec.prediction_horizon)
    valid_count = max(0, future_stop - future_start)
    if valid_count:
        source_start = future_start - trace.start_step
        source_stop = future_stop - trace.start_step
        target[:valid_count, :] = trace.counts[source_start:source_stop, :]
        mask[:valid_count] = True
    return PredictionTarget(counts=target, valid_mask=mask)


def compute_sample_id(
    spec: DatasetProtocolSpec,
    source: PredictionSource,
    anchor_absolute_step: int,
) -> str:
    """计算与 filesystem traversal order 无关的 sample logical identity。"""

    if not isinstance(spec, DatasetProtocolSpec):
        raise TypeError("spec 必须是 DatasetProtocolSpec")
    if not isinstance(source, PredictionSource):
        raise TypeError("source 必须是 PredictionSource")
    anchor = _normalize_integer(anchor_absolute_step, "anchor_absolute_step", 0)
    return compute_config_hash(
        {
            "dataset_protocol_sha256": spec.sha256,
            "source_artifact_content_sha256": source.content_sha256,
            "anchor_absolute_step": anchor,
        }
    )


def derive_synthetic_prediction_samples(
    trace: DemandTrace,
    source: PredictionSource,
    spec: DatasetProtocolSpec,
) -> tuple[PredictionSample, ...]:
    """按 anchor 升序派生 synthetic/unit-fixture samples 的低层 helper。

    Anchor 精确为 ``start_step <= t < stop_step - 1``；因此一时间步 trace 合法返回空
    tuple，且每个返回 sample 至少含一个 ``valid_mask=True`` 的 target row。该接口接受 caller
    descriptor，因此不是 scientific provenance trust root；authoritative 数据必须使用
    :func:`derive_prediction_samples_from_artifact`。
    """

    if not isinstance(trace, DemandTrace):
        raise TypeError("trace 必须是 DemandTrace")
    if not isinstance(source, PredictionSource):
        raise TypeError("source 必须是 PredictionSource")
    if not isinstance(spec, DatasetProtocolSpec):
        raise TypeError("spec 必须是 DatasetProtocolSpec")
    _validate_source_zone_schema(source, spec)
    num_steps, num_zones = trace.counts.shape
    comparisons = {
        "start_step": trace.start_step,
        "num_steps": num_steps,
        "num_zones": num_zones,
    }
    for name, expected in comparisons.items():
        if getattr(source, name) != expected:
            raise ValueError(f"source.{name} 与 DemandTrace 不一致")
    stop_step = trace.start_step + num_steps
    return tuple(
        PredictionSample(
            sample_id=compute_sample_id(spec, source, anchor),
            context=derive_prediction_context(trace, spec, anchor),
            target=derive_prediction_target(trace, spec, anchor),
        )
        for anchor in range(trace.start_step, stop_step - 1)
    )


def derive_prediction_samples_from_artifact(
    verified: VerifiedPredictionArtifact,
    spec: DatasetProtocolSpec,
) -> tuple[PredictionSample, ...]:
    """从 safe-loaded authoritative artifact 派生 deterministic supervised samples。"""

    if not isinstance(verified, VerifiedPredictionArtifact):
        raise TypeError("verified 必须是 VerifiedPredictionArtifact")
    if not isinstance(spec, DatasetProtocolSpec):
        raise TypeError("spec 必须是 DatasetProtocolSpec")
    validate_prediction_source_for_artifact(verified, verified.source)
    _validate_source_zone_schema(verified.source, spec)
    return derive_synthetic_prediction_samples(
        verified.artifact.trace,
        verified.source,
        spec,
    )


def build_split_manifest_from_artifacts(
    assignments: Sequence[tuple[SplitLabel | str, VerifiedPredictionArtifact]],
    spec: DatasetProtocolSpec,
) -> DatasetSplitManifest:
    """只从 verified artifacts 构造 scientific split manifest。

    Caller 只能提供 split label 与 safe-loaded binding，不能自填 seed/config/content/condition/zone
    provenance。``DatasetSplitManifest`` 的 global identity guards 随后拒绝同一 artifact/seed 被
    多次分配。
    """

    if not isinstance(spec, DatasetProtocolSpec):
        raise TypeError("spec 必须是 DatasetProtocolSpec")
    try:
        normalized = tuple(assignments)
    except TypeError as error:
        raise TypeError("assignments 必须是 (split, VerifiedPredictionArtifact) 序列") from error
    entries: list[SplitEntry] = []
    for assignment in normalized:
        if not isinstance(assignment, tuple) or len(assignment) != 2:
            raise TypeError("每个 assignment 必须是长度为 2 的 tuple")
        split, verified = assignment
        if not isinstance(verified, VerifiedPredictionArtifact):
            raise TypeError("assignment artifact 必须是 VerifiedPredictionArtifact")
        validate_prediction_source_for_artifact(verified, verified.source)
        _validate_source_zone_schema(verified.source, spec)
        entries.append(SplitEntry(split, verified.source))
    return DatasetSplitManifest(tuple(entries))


def validate_split_manifest_artifacts(
    manifest: DatasetSplitManifest,
    spec: DatasetProtocolSpec,
    artifacts_by_trace_id: Mapping[str, VerifiedPredictionArtifact],
) -> None:
    """把 read-back manifest 的每个 descriptor 重新绑定到 safe-loaded artifacts。

    只有此校验成功的 manifest 才能作为 scientific split provenance 使用；单独反序列化得到的
    manifest 仍只是结构合法的 declaration。
    """

    if not isinstance(manifest, DatasetSplitManifest):
        raise TypeError("manifest 必须是 DatasetSplitManifest")
    if not isinstance(spec, DatasetProtocolSpec):
        raise TypeError("spec 必须是 DatasetProtocolSpec")
    if not isinstance(artifacts_by_trace_id, Mapping):
        raise TypeError("artifacts_by_trace_id 必须是 Mapping")
    expected_ids = {entry.source.trace_id for entry in manifest.entries}
    if set(artifacts_by_trace_id) != expected_ids:
        raise ValueError("artifacts_by_trace_id 必须与 manifest trace_id 集合精确一致")
    for entry in manifest.entries:
        verified = artifacts_by_trace_id[entry.source.trace_id]
        if not isinstance(verified, VerifiedPredictionArtifact):
            raise TypeError("artifacts_by_trace_id 的值必须是 VerifiedPredictionArtifact")
        validate_prediction_source_for_artifact(verified, entry.source)
        _validate_source_zone_schema(entry.source, spec)


__all__ = [
    "DatasetProtocolSpec",
    "DatasetSplitManifest",
    "PredictionSource",
    "SplitEntry",
    "SplitLabel",
    "VerifiedPredictionArtifact",
    "build_split_manifest_from_artifacts",
    "compute_condition_sha256",
    "compute_realized_trace_sha256",
    "compute_sample_id",
    "dataset_protocol_identity",
    "derive_prediction_context",
    "derive_prediction_samples_from_artifact",
    "derive_synthetic_prediction_samples",
    "derive_prediction_target",
    "prediction_source_to_dict",
    "split_entry_to_dict",
    "split_manifest_identity",
    "load_verified_prediction_artifact",
    "validate_prediction_source_for_artifact",
    "validate_split_manifest_artifacts",
]
