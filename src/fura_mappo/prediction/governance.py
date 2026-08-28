"""WP-03B Layer-A PRE-TRAINING DATA/SEARCH FREEZE identity core。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from fura_mappo.demand import compute_config_hash
from fura_mappo.prediction.dataset import (
    DatasetProtocolSpec,
    DatasetSplitManifest,
    PredictionSource,
    SplitLabel,
    VerifiedPredictionArtifact,
    validate_split_manifest_artifacts,
)
from fura_mappo.prediction.model_selection import HistoryTransformKind, PointObjectiveKind

_PRE_TRAINING_FREEZE_SCHEMA = "fura-mappo.prediction-pre-training-freeze"
_PRE_TRAINING_FREEZE_VERSION = 1
_PRE_TRAINING_FREEZE_FAILURE_STATUS = "PRE_TRAINING_DATA_FREEZE_FAILURE"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_REQUIRED_SPLITS = (
    SplitLabel.TRAIN,
    SplitLabel.VALIDATION,
    SplitLabel.TEST_ID,
    SplitLabel.TEST_OOD,
)


class PreTrainingFreezeFailure(ValueError):
    """表示 Layer-A freeze construction 或 authoritative binding 无法成立。"""

    @property
    def status(self) -> str:
        """返回独立于训练、选择、评估和 Formal H1 的稳定状态。"""

        return _PRE_TRAINING_FREEZE_FAILURE_STATUS


def _freeze_failure(message: str) -> PreTrainingFreezeFailure:
    """构造稳定 namespace 的 Layer-A hard failure。"""

    return PreTrainingFreezeFailure(message)


def _normalize_sha256(value: object, name: str) -> str:
    """验证 64-char lowercase SHA-256 identity。"""

    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} 必须是 64 位小写 SHA-256")
    return value


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """验证 non-bool nonnegative integer identity。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 必须是非 bool 整数")
    if value < 0:
        raise ValueError(f"{name} 必须大于或等于 0")
    return value


class CalibrationDisposition(str, Enum):
    """Layer-A calibration split 的精确预留状态。"""

    EMPTY = "EMPTY"
    SEALED = "SEALED"


class PredictionOODKind(str, Enum):
    """evaluation trace 的冻结 scientific taxonomy。"""

    ID = "ID"
    NEAR_OOD = "NEAR_OOD"
    STRUCTURAL_OOD = "STRUCTURAL_OOD"


@dataclass(frozen=True, slots=True)
class TraceOODAssignment:
    """一条 TEST_ID/TEST_OOD trace 的预注册 taxonomy identity。"""

    trace_id: str
    kind: PredictionOODKind
    cell_id: str

    def __post_init__(self) -> None:
        """验证与 PredictionSource 兼容的安全标识和 taxonomy 类型。"""

        if not isinstance(self.trace_id, str) or _SAFE_ID_PATTERN.fullmatch(self.trace_id) is None:
            raise ValueError("trace_id 必须是安全的 1..255 字符标识符")
        if not isinstance(self.kind, PredictionOODKind):
            raise TypeError("kind 必须是 PredictionOODKind")
        if not isinstance(self.cell_id, str) or _SAFE_ID_PATTERN.fullmatch(self.cell_id) is None:
            raise ValueError("cell_id 必须是安全的 1..255 字符标识符")


@dataclass(frozen=True, slots=True)
class LearnedConfigFreezeIdentity:
    """进入训练前的 learned candidate identity，不含结果或 checkpoint。"""

    config_sha256: str
    protocol_sha256: str
    objective: PointObjectiveKind
    transform: HistoryTransformKind
    model_complexity_key: tuple[int, ...]
    canonical_order: int

    def __post_init__(self) -> None:
        """验证 candidate 的纯 identity 字段。"""

        config_sha256 = _normalize_sha256(self.config_sha256, "config_sha256")
        protocol_sha256 = _normalize_sha256(self.protocol_sha256, "protocol_sha256")
        if not isinstance(self.objective, PointObjectiveKind):
            raise TypeError("objective 必须是 PointObjectiveKind")
        if not isinstance(self.transform, HistoryTransformKind):
            raise TypeError("transform 必须是 HistoryTransformKind")
        if not isinstance(self.model_complexity_key, tuple):
            raise TypeError("model_complexity_key 必须是 tuple[int, ...]")
        if not self.model_complexity_key:
            raise ValueError("model_complexity_key 必须非空")
        complexity_key = tuple(
            _normalize_nonnegative_integer(component, "model_complexity_key component")
            for component in self.model_complexity_key
        )
        canonical_order = _normalize_nonnegative_integer(
            self.canonical_order,
            "canonical_order",
        )
        object.__setattr__(self, "config_sha256", config_sha256)
        object.__setattr__(self, "protocol_sha256", protocol_sha256)
        object.__setattr__(self, "model_complexity_key", complexity_key)
        object.__setattr__(self, "canonical_order", canonical_order)


def _normalize_secondary_protocols(
    value: object,
    primary_protocol: DatasetProtocolSpec,
) -> tuple[DatasetProtocolSpec, ...]:
    """验证 secondary protocols 并按 SHA canonicalize。"""

    try:
        protocols = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("secondary_protocols 必须是有限 iterable") from error
    if any(not isinstance(protocol, DatasetProtocolSpec) for protocol in protocols):
        raise TypeError("secondary_protocols 必须全部是 DatasetProtocolSpec")
    hashes = [protocol.sha256 for protocol in protocols]
    if len(hashes) != len(set(hashes)):
        raise _freeze_failure("secondary protocol SHA 必须全部唯一")
    if primary_protocol.sha256 in hashes:
        raise _freeze_failure("primary protocol 不得在 secondary_protocols 中重复")
    if any(
        protocol.zone_schema_sha256 != primary_protocol.zone_schema_sha256 for protocol in protocols
    ):
        raise _freeze_failure("全部 dataset protocols 必须共享同一 zone schema")
    return tuple(sorted(protocols, key=lambda protocol: protocol.sha256))


def _validate_manifest(
    manifest: DatasetSplitManifest,
    primary_protocol: DatasetProtocolSpec,
    calibration_disposition: CalibrationDisposition,
) -> None:
    """验证 required roles、calibration disposition 与统一 zone geometry。"""

    labels = tuple(entry.split for entry in manifest.entries)
    for required in _REQUIRED_SPLITS:
        if required not in labels:
            raise _freeze_failure(f"split manifest 缺少 required role {required.value}")
    if any(
        entry.source.zone_schema_sha256 != primary_protocol.zone_schema_sha256
        for entry in manifest.entries
    ):
        raise _freeze_failure("manifest source zone schema 与 primary protocol 不一致")
    calibration_count = labels.count(SplitLabel.CALIBRATION)
    if calibration_disposition is CalibrationDisposition.EMPTY and calibration_count != 0:
        raise _freeze_failure("EMPTY calibration disposition 要求零条 calibration trace")
    if calibration_disposition is CalibrationDisposition.SEALED and calibration_count < 1:
        raise _freeze_failure("SEALED calibration disposition 要求至少一条 calibration trace")


def _normalize_ood_assignments(
    value: object,
    manifest: DatasetSplitManifest,
) -> tuple[TraceOODAssignment, ...]:
    """验证 evaluation trace taxonomy 的 exact one-to-one coverage。"""

    try:
        assignments = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("ood_assignments 必须是有限 iterable") from error
    if any(not isinstance(assignment, TraceOODAssignment) for assignment in assignments):
        raise TypeError("ood_assignments 必须全部是 TraceOODAssignment")
    trace_ids = [assignment.trace_id for assignment in assignments]
    if len(trace_ids) != len(set(trace_ids)):
        raise _freeze_failure("每条 evaluation trace 必须恰有一个 OOD assignment")

    evaluation_entries = {
        entry.source.trace_id: entry.split
        for entry in manifest.entries
        if entry.split in (SplitLabel.TEST_ID, SplitLabel.TEST_OOD)
    }
    if set(trace_ids) != set(evaluation_entries):
        raise _freeze_failure("OOD assignments 必须精确覆盖 TEST_ID/TEST_OOD traces")
    for assignment in assignments:
        split = evaluation_entries[assignment.trace_id]
        if split is SplitLabel.TEST_ID and assignment.kind is not PredictionOODKind.ID:
            raise _freeze_failure("TEST_ID trace 必须分配 PredictionOODKind.ID")
        if split is SplitLabel.TEST_OOD and assignment.kind not in (
            PredictionOODKind.NEAR_OOD,
            PredictionOODKind.STRUCTURAL_OOD,
        ):
            raise _freeze_failure("TEST_OOD trace 必须分配 near/structural OOD kind")
    return tuple(sorted(assignments, key=lambda assignment: assignment.trace_id))


def _normalize_fixed_training_seeds(value: object) -> tuple[int, ...]:
    """验证并 canonicalize 至少三个 distinct training-seed identities。"""

    try:
        raw_seeds = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("fixed_training_seeds 必须是有限 iterable") from error
    try:
        seeds = tuple(
            _normalize_nonnegative_integer(seed, "fixed training seed") for seed in raw_seeds
        )
    except (TypeError, ValueError) as error:
        raise _freeze_failure(str(error)) from error
    if len(seeds) < 3:
        raise _freeze_failure("fixed_training_seeds 必须至少包含三个 seeds")
    if len(seeds) != len(set(seeds)):
        raise _freeze_failure("fixed_training_seeds 必须全部唯一")
    return tuple(sorted(seeds))


def _normalize_learned_config_identities(
    value: object,
    protocol_hashes: set[str],
) -> tuple[LearnedConfigFreezeIdentity, ...]:
    """验证 learned search-space identities 并按 canonical_order 排序。"""

    try:
        identities = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("learned_config_identities 必须是有限 iterable") from error
    if any(not isinstance(identity, LearnedConfigFreezeIdentity) for identity in identities):
        raise TypeError("learned_config_identities 必须全部是 LearnedConfigFreezeIdentity")
    if not identities:
        raise _freeze_failure("learned candidate identity set 必须非空")
    config_hashes = [identity.config_sha256 for identity in identities]
    if len(config_hashes) != len(set(config_hashes)):
        raise _freeze_failure("learned candidate config_sha256 必须全部唯一")
    canonical_orders = [identity.canonical_order for identity in identities]
    if len(canonical_orders) != len(set(canonical_orders)):
        raise _freeze_failure("learned candidate canonical_order 必须全部唯一")
    if any(identity.protocol_sha256 not in protocol_hashes for identity in identities):
        raise _freeze_failure("learned candidate 引用了 unknown dataset protocol SHA")
    return tuple(sorted(identities, key=lambda identity: identity.canonical_order))


def _assignment_identity(assignment: TraceOODAssignment) -> dict[str, object]:
    """返回 OOD assignment canonical identity tree。"""

    return {
        "trace_id": assignment.trace_id,
        "kind": assignment.kind.value,
        "cell_id": assignment.cell_id,
    }


def _candidate_identity(candidate: LearnedConfigFreezeIdentity) -> dict[str, object]:
    """返回 learned candidate canonical identity tree。"""

    return {
        "config_sha256": candidate.config_sha256,
        "protocol_sha256": candidate.protocol_sha256,
        "objective": candidate.objective.value,
        "transform": candidate.transform.value,
        "model_complexity_key": list(candidate.model_complexity_key),
        "canonical_order": candidate.canonical_order,
    }


def _pretraining_freeze_identity(freeze: PreTrainingFreeze) -> dict[str, object]:
    """返回不含 self hash 的 canonical Layer-A identity tree。"""

    return {
        "schema": freeze.schema,
        "version": freeze.version,
        "zone_schema_sha256": freeze.zone_schema_sha256,
        "primary_protocol_sha256": freeze.primary_protocol.sha256,
        "secondary_protocol_sha256s": [protocol.sha256 for protocol in freeze.secondary_protocols],
        "split_manifest_sha256": freeze.split_manifest.sha256,
        "calibration_disposition": freeze.calibration_disposition.value,
        "ood_assignments": [
            _assignment_identity(assignment) for assignment in freeze.ood_assignments
        ],
        "fixed_training_seeds": list(freeze.fixed_training_seeds),
        "learned_config_identities": [
            _candidate_identity(identity) for identity in freeze.learned_config_identities
        ],
        "rng_namespace_plan_sha256": freeze.rng_namespace_plan_sha256,
        "training_plan_sha256": freeze.training_plan_sha256,
        "baseline_plan_sha256": freeze.baseline_plan_sha256,
    }


@dataclass(frozen=True, slots=True)
class PreTrainingFreeze:
    """Layer-A PRE-TRAINING DATA/SEARCH FREEZE 的 immutable identity record。

    直接构造只证明 structural identity consistency，不能证明 manifest 来源于 safe-loaded
    artifacts。scientific/official construction path 必须使用 :func:`build_pretraining_freeze`
    与 WP-03A ``VerifiedPredictionArtifact`` binding。本对象不授权训练、选择、测试或 Layer B。
    """

    primary_protocol: DatasetProtocolSpec
    secondary_protocols: tuple[DatasetProtocolSpec, ...]
    split_manifest: DatasetSplitManifest
    calibration_disposition: CalibrationDisposition
    ood_assignments: tuple[TraceOODAssignment, ...]
    fixed_training_seeds: tuple[int, ...]
    learned_config_identities: tuple[LearnedConfigFreezeIdentity, ...]
    rng_namespace_plan_sha256: str
    training_plan_sha256: str
    baseline_plan_sha256: str
    schema: str = _PRE_TRAINING_FREEZE_SCHEMA
    version: int = _PRE_TRAINING_FREEZE_VERSION
    zone_schema_sha256: str = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """验证并 canonicalize 完整 Layer-A structural identity。"""

        if not isinstance(self.primary_protocol, DatasetProtocolSpec):
            raise TypeError("primary_protocol 必须是 DatasetProtocolSpec")
        if not isinstance(self.split_manifest, DatasetSplitManifest):
            raise TypeError("split_manifest 必须是 DatasetSplitManifest")
        if not isinstance(self.calibration_disposition, CalibrationDisposition):
            raise TypeError("calibration_disposition 必须是 CalibrationDisposition")
        if (
            type(self.schema) is not str
            or self.schema != _PRE_TRAINING_FREEZE_SCHEMA
            or type(self.version) is not int
            or self.version != _PRE_TRAINING_FREEZE_VERSION
        ):
            raise _freeze_failure("pre-training freeze schema/version 不受支持")

        secondary_protocols = _normalize_secondary_protocols(
            self.secondary_protocols,
            self.primary_protocol,
        )
        _validate_manifest(
            self.split_manifest,
            self.primary_protocol,
            self.calibration_disposition,
        )
        ood_assignments = _normalize_ood_assignments(
            self.ood_assignments,
            self.split_manifest,
        )
        fixed_training_seeds = _normalize_fixed_training_seeds(self.fixed_training_seeds)
        protocol_hashes = {
            self.primary_protocol.sha256,
            *(protocol.sha256 for protocol in secondary_protocols),
        }
        learned_config_identities = _normalize_learned_config_identities(
            self.learned_config_identities,
            protocol_hashes,
        )
        try:
            rng_namespace_plan_sha256 = _normalize_sha256(
                self.rng_namespace_plan_sha256,
                "rng_namespace_plan_sha256",
            )
            training_plan_sha256 = _normalize_sha256(
                self.training_plan_sha256,
                "training_plan_sha256",
            )
            baseline_plan_sha256 = _normalize_sha256(
                self.baseline_plan_sha256,
                "baseline_plan_sha256",
            )
        except ValueError as error:
            raise _freeze_failure(str(error)) from error

        object.__setattr__(self, "secondary_protocols", secondary_protocols)
        object.__setattr__(self, "ood_assignments", ood_assignments)
        object.__setattr__(self, "fixed_training_seeds", fixed_training_seeds)
        object.__setattr__(
            self,
            "learned_config_identities",
            learned_config_identities,
        )
        object.__setattr__(self, "rng_namespace_plan_sha256", rng_namespace_plan_sha256)
        object.__setattr__(self, "training_plan_sha256", training_plan_sha256)
        object.__setattr__(self, "baseline_plan_sha256", baseline_plan_sha256)
        object.__setattr__(
            self,
            "zone_schema_sha256",
            self.primary_protocol.zone_schema_sha256,
        )
        object.__setattr__(self, "sha256", compute_config_hash(_pretraining_freeze_identity(self)))

    @property
    def primary_prediction_horizon(self) -> int:
        """返回 generic primary protocol 的 prediction horizon P。"""

        return self.primary_protocol.prediction_horizon

    @property
    def source_inventory(self) -> tuple[PredictionSource, ...]:
        """按 manifest canonical order 唯一派生 immutable source inventory。"""

        return tuple(entry.source for entry in self.split_manifest.entries)

    def trace_ids_for_split(self, split_label: SplitLabel) -> tuple[str, ...]:
        """按 manifest canonical order 返回指定 split 的 trace identities。"""

        if not isinstance(split_label, SplitLabel):
            raise TypeError("split_label 必须是 SplitLabel")
        return tuple(
            entry.source.trace_id
            for entry in self.split_manifest.entries
            if entry.split is split_label
        )


def build_pretraining_freeze(
    *,
    primary_protocol: DatasetProtocolSpec,
    secondary_protocols: Iterable[DatasetProtocolSpec],
    split_manifest: DatasetSplitManifest,
    verified_artifacts: Iterable[VerifiedPredictionArtifact],
    calibration_disposition: CalibrationDisposition,
    ood_assignments: Iterable[TraceOODAssignment],
    fixed_training_seeds: Iterable[int],
    learned_config_identities: Iterable[LearnedConfigFreezeIdentity],
    rng_namespace_plan_sha256: str,
    training_plan_sha256: str,
    baseline_plan_sha256: str,
) -> PreTrainingFreeze:
    """经 WP-03A authoritative artifact binding 构造 Layer-A freeze。"""

    if not isinstance(primary_protocol, DatasetProtocolSpec):
        raise TypeError("primary_protocol 必须是 DatasetProtocolSpec")
    if not isinstance(split_manifest, DatasetSplitManifest):
        raise TypeError("split_manifest 必须是 DatasetSplitManifest")
    try:
        artifacts = tuple(verified_artifacts)
    except TypeError as error:
        raise TypeError("verified_artifacts 必须是有限 iterable") from error
    if any(not isinstance(artifact, VerifiedPredictionArtifact) for artifact in artifacts):
        raise TypeError("verified_artifacts 必须全部是 VerifiedPredictionArtifact")

    artifacts_by_trace_id: dict[str, VerifiedPredictionArtifact] = {}
    for artifact in artifacts:
        trace_id = artifact.source.trace_id
        if trace_id in artifacts_by_trace_id:
            raise _freeze_failure("verified_artifacts 不允许重复 trace_id")
        artifacts_by_trace_id[trace_id] = artifact
    try:
        validate_split_manifest_artifacts(
            split_manifest,
            primary_protocol,
            artifacts_by_trace_id,
        )
    except (TypeError, ValueError, KeyError) as error:
        raise _freeze_failure(f"authoritative manifest/artifact binding 失败: {error}") from error

    return PreTrainingFreeze(
        primary_protocol=primary_protocol,
        secondary_protocols=tuple(secondary_protocols),
        split_manifest=split_manifest,
        calibration_disposition=calibration_disposition,
        ood_assignments=tuple(ood_assignments),
        fixed_training_seeds=tuple(fixed_training_seeds),
        learned_config_identities=tuple(learned_config_identities),
        rng_namespace_plan_sha256=rng_namespace_plan_sha256,
        training_plan_sha256=training_plan_sha256,
        baseline_plan_sha256=baseline_plan_sha256,
    )


__all__ = [
    "CalibrationDisposition",
    "LearnedConfigFreezeIdentity",
    "PredictionOODKind",
    "PreTrainingFreeze",
    "PreTrainingFreezeFailure",
    "TraceOODAssignment",
    "build_pretraining_freeze",
]
