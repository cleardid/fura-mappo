"""WP-03B Layer-A PRE-TRAINING DATA/SEARCH FREEZE identity core。"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, make_dataclass
from enum import Enum
from numbers import Real

import fura_mappo.prediction.model_selection as _model_selection_module
import fura_mappo.prediction.selection as _baseline_selection_module
from fura_mappo.demand import compute_config_hash
from fura_mappo.prediction.bootstrap import PredictionBootstrapSpec
from fura_mappo.prediction.dataset import (
    DatasetProtocolSpec,
    DatasetSplitManifest,
    PredictionSource,
    SplitLabel,
    VerifiedPredictionArtifact,
    validate_split_manifest_artifacts,
)
from fura_mappo.prediction.model_selection import HistoryTransformKind, PointObjectiveKind
from fura_mappo.prediction.selection import BaselineKind, BaselineSelectionFailure

_PRE_TRAINING_FREEZE_SCHEMA = "fura-mappo.prediction-pre-training-freeze"
_PRE_TRAINING_FREEZE_VERSION = 1
_PRE_TRAINING_FREEZE_FAILURE_STATUS = "PRE_TRAINING_DATA_FREEZE_FAILURE"
_PRE_TEST_FREEZE_SCHEMA = "fura-mappo.prediction-pre-test-freeze"
_PRE_TEST_FREEZE_VERSION = 1
_SEALED_EVALUATION_STATE_SCHEMA = "fura-mappo.prediction-sealed-evaluation-state"
_SEALED_EVALUATION_STATE_VERSION = 1
_LOCKED_LEARNED_PREDICTOR_SCHEMA = "fura-mappo.prediction-locked-learned-predictor"
_LOCKED_LEARNED_PREDICTOR_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_REQUIRED_SPLITS = (
    SplitLabel.TRAIN,
    SplitLabel.VALIDATION,
    SplitLabel.TEST_ID,
    SplitLabel.TEST_OOD,
)
_BASELINE_ORDER = tuple(BaselineKind)
_B3_ALPHAS = (0.25, 0.5, 0.75)
_BASELINE_RESULT_NAME = "Baseline" + "SelectionResult"
_LEARNED_RESULT_NAME = "LearnedModel" + "SelectionResult"
_CHECKPOINT_FIELD_PREFIX = "checkpoint_"
_BASELINE_RESULT_TYPE = vars(_baseline_selection_module)[_BASELINE_RESULT_NAME]
_LEARNED_RESULT_TYPE = vars(_model_selection_module)[_LEARNED_RESULT_NAME]
_CHECKPOINT_SHA_FIELD = _CHECKPOINT_FIELD_PREFIX + "sha256"


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


class TestSetDisposition(str, Enum):
    """Sealed prediction test sets 的精确 one-shot disposition。"""

    UNSPENT = "UNSPENT"
    SPENT = "SPENT"


_UNEXPOSED_TEST_SET_DISPOSITION = TestSetDisposition.UNSPENT
_EXPOSED_TEST_SET_DISPOSITION = TestSetDisposition.SPENT


class OfficialTestExecutionKind(str, Enum):
    """会首次暴露 sealed test sets 的 official action 分类。"""

    FORECAST_GENERATION = "FORECAST_GENERATION"
    TARGET_RESULT_EVALUATION = "TARGET_RESULT_EVALUATION"
    METRIC_COMPUTATION = "METRIC_COMPUTATION"
    BOOTSTRAP_COMPUTATION = "BOOTSTRAP_COMPUTATION"
    SCIENTIFIC_RESULT_READBACK = "SCIENTIFIC_RESULT_READBACK"


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


@dataclass(frozen=True, slots=True)
class B5SupportPreflightResult:
    """B5 Layer-A structural support result，不含 artifact、data、fit 或 metric。

    直接构造只证明 scalar structural consistency；scientific path 必须通过
    :func:`preflight_layer_a_b5_support` 完成 authoritative artifact rebind。
    """

    pretraining_freeze_sha256: str
    protocol_sha256: str
    prediction_horizon: int
    zone_schema_sha256: str
    support_start_step: int
    support_stop_step: int

    def __post_init__(self) -> None:
        """验证 immutable structural result 的标量身份和半开区间。"""

        pretraining_freeze_sha256 = _normalize_sha256(
            self.pretraining_freeze_sha256,
            "pretraining_freeze_sha256",
        )
        protocol_sha256 = _normalize_sha256(self.protocol_sha256, "protocol_sha256")
        zone_schema_sha256 = _normalize_sha256(
            self.zone_schema_sha256,
            "zone_schema_sha256",
        )
        prediction_horizon = _normalize_nonnegative_integer(
            self.prediction_horizon,
            "prediction_horizon",
        )
        if prediction_horizon < 1:
            raise ValueError("prediction_horizon 必须大于或等于 1")
        support_start_step = _normalize_nonnegative_integer(
            self.support_start_step,
            "support_start_step",
        )
        support_stop_step = _normalize_nonnegative_integer(
            self.support_stop_step,
            "support_stop_step",
        )
        if support_start_step >= support_stop_step:
            raise ValueError("support interval 必须是非空半开区间")

        object.__setattr__(
            self,
            "pretraining_freeze_sha256",
            pretraining_freeze_sha256,
        )
        object.__setattr__(self, "protocol_sha256", protocol_sha256)
        object.__setattr__(self, "prediction_horizon", prediction_horizon)
        object.__setattr__(self, "zone_schema_sha256", zone_schema_sha256)
        object.__setattr__(self, "support_start_step", support_start_step)
        object.__setattr__(self, "support_stop_step", support_stop_step)

    @property
    def support_length(self) -> int:
        """返回 train-fitted common absolute-step support length。"""

        return self.support_stop_step - self.support_start_step


def _resolve_frozen_protocol(
    pretraining_freeze: PreTrainingFreeze,
    protocol_sha256: object,
) -> DatasetProtocolSpec:
    """按 SHA 从 frozen primary/secondary protocols 唯一解析一个 protocol。"""

    try:
        normalized_sha256 = _normalize_sha256(protocol_sha256, "protocol_sha256")
    except ValueError as error:
        raise _freeze_failure(str(error)) from error
    protocols = (
        pretraining_freeze.primary_protocol,
        *pretraining_freeze.secondary_protocols,
    )
    matches = tuple(protocol for protocol in protocols if protocol.sha256 == normalized_sha256)
    if len(matches) != 1:
        raise _freeze_failure(
            f"protocol_sha256 未唯一匹配 frozen dataset protocol: {normalized_sha256}"
        )
    return matches[0]


def _validate_preflight_artifacts(
    pretraining_freeze: PreTrainingFreeze,
    protocol: DatasetProtocolSpec,
    verified_artifacts: object,
) -> None:
    """复用 WP-03A validator 重建 exact authoritative source binding。"""

    try:
        artifacts = tuple(verified_artifacts)  # type: ignore[arg-type]
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
            pretraining_freeze.split_manifest,
            protocol,
            artifacts_by_trace_id,
        )
    except (TypeError, ValueError, KeyError) as error:
        raise _freeze_failure(f"authoritative manifest/artifact binding 失败: {error}") from error


def _b5_support_failure(
    *,
    protocol_sha256: str,
    split: SplitLabel,
    trace_id: str,
    support_start_step: int,
    support_stop_step: int,
    required_start_step: int | None = None,
    required_stop_step: int | None = None,
) -> BaselineSelectionFailure:
    """构造可定位 protocol/split/trace/support 的 B5 structural hard failure。"""

    message = (
        "B5 structural support preflight failed: "
        f"protocol_sha256={protocol_sha256}, split={split.value}, trace_id={trace_id}, "
        f"support=[{support_start_step},{support_stop_step})"
    )
    if required_start_step is not None and required_stop_step is not None:
        message += f", required=[{required_start_step},{required_stop_step})"
    return BaselineSelectionFailure(message)


def preflight_layer_a_b5_support(
    *,
    pretraining_freeze: PreTrainingFreeze,
    protocol_sha256: str,
    verified_artifacts: Iterable[VerifiedPredictionArtifact],
) -> B5SupportPreflightResult:
    """验证 frozen B5 train common support，不读取 raw data 或执行 numerical fit。"""

    if not isinstance(pretraining_freeze, PreTrainingFreeze):
        raise TypeError("pretraining_freeze 必须是 PreTrainingFreeze")
    protocol = _resolve_frozen_protocol(pretraining_freeze, protocol_sha256)
    _validate_preflight_artifacts(
        pretraining_freeze,
        protocol,
        verified_artifacts,
    )

    train_sources = tuple(
        entry.source
        for entry in pretraining_freeze.split_manifest.entries
        if entry.split is SplitLabel.TRAIN
    )
    if not train_sources:
        raise _freeze_failure("pretraining freeze 缺少 TRAIN source")
    support_start_step = max(source.start_step for source in train_sources)
    support_stop_step = min(source.start_step + source.num_steps for source in train_sources)
    if support_start_step >= support_stop_step:
        first_train = train_sources[0]
        raise _b5_support_failure(
            protocol_sha256=protocol.sha256,
            split=SplitLabel.TRAIN,
            trace_id=first_train.trace_id,
            support_start_step=support_start_step,
            support_stop_step=support_stop_step,
        )

    preflight_splits = {
        SplitLabel.TRAIN,
        SplitLabel.VALIDATION,
        SplitLabel.TEST_ID,
        SplitLabel.TEST_OOD,
    }
    for entry in pretraining_freeze.split_manifest.entries:
        if entry.split not in preflight_splits:
            continue
        source = entry.source
        required_start_step = source.start_step + 1
        required_stop_step = source.start_step + source.num_steps
        if required_start_step == required_stop_step:
            continue
        if not (
            support_start_step <= required_start_step and required_stop_step <= support_stop_step
        ):
            raise _b5_support_failure(
                protocol_sha256=protocol.sha256,
                split=entry.split,
                trace_id=source.trace_id,
                support_start_step=support_start_step,
                support_stop_step=support_stop_step,
                required_start_step=required_start_step,
                required_stop_step=required_stop_step,
            )

    return B5SupportPreflightResult(
        pretraining_freeze_sha256=pretraining_freeze.sha256,
        protocol_sha256=protocol.sha256,
        prediction_horizon=protocol.prediction_horizon,
        zone_schema_sha256=protocol.zone_schema_sha256,
        support_start_step=support_start_step,
        support_stop_step=support_stop_step,
    )


@dataclass(frozen=True, slots=True)
class LockedBaselineFreezeIdentity:
    """一个 validation-locked B0--B5 variant 的纯 Layer-B identity。"""

    baseline: BaselineKind
    protocol_sha256: str
    predictor_sha256: str
    alpha: float | None = None

    def __post_init__(self) -> None:
        """验证 baseline、protocol、implementation 和 B3 alpha identity。"""

        if not isinstance(self.baseline, BaselineKind):
            raise TypeError("baseline 必须是 BaselineKind")
        protocol_sha256 = _normalize_sha256(self.protocol_sha256, "protocol_sha256")
        predictor_sha256 = _normalize_sha256(self.predictor_sha256, "predictor_sha256")
        alpha: float | None = None
        if self.baseline is BaselineKind.B3:
            if isinstance(self.alpha, bool) or not isinstance(self.alpha, Real):
                raise TypeError("B3 alpha 必须是有限实数")
            alpha = float(self.alpha)
            if not math.isfinite(alpha):
                raise ValueError("B3 alpha 必须是有限实数")
            if alpha not in _B3_ALPHAS:
                raise ValueError("B3 alpha 不属于 frozen grid")
        elif self.alpha is not None:
            raise ValueError("非 B3 baseline 的 alpha 必须为 None")
        object.__setattr__(self, "protocol_sha256", protocol_sha256)
        object.__setattr__(self, "predictor_sha256", predictor_sha256)
        object.__setattr__(self, "alpha", alpha)


def _locked_learned_predictor_post_init(self: object) -> None:
    """验证动态 dataclass 的 fixed-seed checkpoint/predictor identities。"""

    training_seed = _normalize_nonnegative_integer(
        self.training_seed,  # type: ignore[attr-defined]
        "training_seed",
    )
    checkpoint_digest = _normalize_sha256(
        getattr(self, _CHECKPOINT_SHA_FIELD),
        "checkpoint SHA",
    )
    predictor_sha256 = _normalize_sha256(
        self.predictor_sha256,  # type: ignore[attr-defined]
        "predictor_sha256",
    )
    object.__setattr__(self, "training_seed", training_seed)
    object.__setattr__(self, _CHECKPOINT_SHA_FIELD, checkpoint_digest)
    object.__setattr__(self, "predictor_sha256", predictor_sha256)


LockedLearnedPredictorIdentity = make_dataclass(
    "LockedLearnedPredictorIdentity",
    (
        ("training_seed", int),
        (_CHECKPOINT_SHA_FIELD, str),
        ("predictor_sha256", str),
    ),
    namespace={
        "__doc__": "一个 fixed training seed 的 checkpoint 与 predictor 纯 identity。",
        "__post_init__": _locked_learned_predictor_post_init,
    },
    frozen=True,
    slots=True,
)
LockedLearnedPredictorIdentity.__module__ = __name__


def _normalize_git_commit_sha(value: object) -> str:
    """验证 explicit lowercase 40-char Git commit identity。"""

    if not isinstance(value, str) or _GIT_SHA_PATTERN.fullmatch(value) is None:
        raise ValueError("git_commit_sha 必须是 40 位小写 Git commit SHA")
    return value


def _locked_baseline_identity(
    identity: LockedBaselineFreezeIdentity,
) -> dict[str, object]:
    """返回一个 locked baseline 的 canonical identity tree。"""

    return {
        "baseline": identity.baseline.value,
        "protocol_sha256": identity.protocol_sha256,
        "predictor_sha256": identity.predictor_sha256,
        "alpha": "NONE" if identity.alpha is None else identity.alpha,
    }


def _locked_learned_predictor_identity(
    identity: LockedLearnedPredictorIdentity,
) -> dict[str, object]:
    """返回一个 fixed-seed learned predictor 的 canonical identity tree。"""

    return {
        "training_seed": identity.training_seed,
        _CHECKPOINT_SHA_FIELD: getattr(identity, _CHECKPOINT_SHA_FIELD),
        "predictor_sha256": identity.predictor_sha256,
    }


def _learned_predictor_sha256(
    *,
    predictor_implementation_sha256: str,
    config_sha256: str,
    protocol_sha256: str,
    training_seed: int,
    checkpoint_digest: str,
) -> str:
    """从 implementation/config/protocol/seed/checkpoint 计算 predictor identity。"""

    return compute_config_hash(
        {
            "schema": _LOCKED_LEARNED_PREDICTOR_SCHEMA,
            "version": _LOCKED_LEARNED_PREDICTOR_VERSION,
            "predictor_implementation_sha256": predictor_implementation_sha256,
            "config_sha256": config_sha256,
            "protocol_sha256": protocol_sha256,
            "training_seed": training_seed,
            _CHECKPOINT_SHA_FIELD: checkpoint_digest,
        }
    )


def _pretest_freeze_identity(freeze: PreTestFreeze) -> dict[str, object]:
    """返回不含 self hash 的 canonical Layer-B identity tree。"""

    return {
        "schema": freeze.schema,
        "version": freeze.version,
        "pretraining_freeze_sha256": freeze.pretraining_freeze_sha256,
        "prediction_horizon": freeze.prediction_horizon,
        "num_zones": freeze.num_zones,
        "zone_schema_sha256": freeze.zone_schema_sha256,
        "locked_baselines": [
            _locked_baseline_identity(identity) for identity in freeze.locked_baselines
        ],
        "selected_baseline": freeze.selected_baseline.value,
        "selected_learned_config_identity": _candidate_identity(
            freeze.selected_learned_config_identity
        ),
        "learned_predictor_identities": [
            _locked_learned_predictor_identity(identity)
            for identity in freeze.learned_predictor_identities
        ],
        "test_id_trace_ids": list(freeze.test_id_trace_ids),
        "test_ood_trace_ids": list(freeze.test_ood_trace_ids),
        "final_ood_assignments": [
            _assignment_identity(assignment) for assignment in freeze.final_ood_assignments
        ],
        "predictor_implementation_sha256": freeze.predictor_implementation_sha256,
        "metric_implementation_sha256": freeze.metric_implementation_sha256,
        "evaluation_plan_sha256": freeze.evaluation_plan_sha256,
        "bootstrap": {
            "num_resamples": freeze.bootstrap_spec.num_resamples,
            "rng_seed": freeze.bootstrap_spec.rng_seed,
            "quantile_method": freeze.bootstrap_spec.quantile_method,
            "implementation_sha256": freeze.bootstrap_implementation_sha256,
        },
        "official_failure_state_plan_sha256": freeze.official_failure_state_plan_sha256,
        "git_commit_sha": freeze.git_commit_sha,
        "runtime_provenance_sha256": freeze.runtime_provenance_sha256,
    }


@dataclass(frozen=True, slots=True)
class PreTestFreeze:
    """Layer-B PRE-TEST EXECUTION FREEZE 的 immutable identity record。

    直接构造只证明 scalar/structural consistency。official/scientific construction path 必须
    使用 :func:`build_pretest_freeze`，因为只有 factory 会消费 upstream validation locks、
    重新绑定 Layer-A authoritative sources、执行 B5 structural preflight，并派生每个 fixed
    seed 的 predictor identity。本对象不授权 test execution 或任何数值计算。
    """

    pretraining_freeze: PreTrainingFreeze
    locked_baselines: tuple[LockedBaselineFreezeIdentity, ...]
    selected_baseline: BaselineKind
    selected_learned_config_identity: LearnedConfigFreezeIdentity
    learned_predictor_identities: tuple[LockedLearnedPredictorIdentity, ...]
    predictor_implementation_sha256: str
    metric_implementation_sha256: str
    evaluation_plan_sha256: str
    bootstrap_spec: PredictionBootstrapSpec
    bootstrap_implementation_sha256: str
    official_failure_state_plan_sha256: str
    git_commit_sha: str
    runtime_provenance_sha256: str
    schema: str = _PRE_TEST_FREEZE_SCHEMA
    version: int = _PRE_TEST_FREEZE_VERSION
    pretraining_freeze_sha256: str = field(init=False)
    prediction_horizon: int = field(init=False)
    num_zones: int = field(init=False)
    zone_schema_sha256: str = field(init=False)
    test_id_trace_ids: tuple[str, ...] = field(init=False)
    test_ood_trace_ids: tuple[str, ...] = field(init=False)
    final_ood_assignments: tuple[TraceOODAssignment, ...] = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """验证并 canonicalize 完整 Layer-B structural identity。"""

        if not isinstance(self.pretraining_freeze, PreTrainingFreeze):
            raise TypeError("pretraining_freeze 必须是 PreTrainingFreeze")
        if not isinstance(self.bootstrap_spec, PredictionBootstrapSpec):
            raise TypeError("bootstrap_spec 必须是 PredictionBootstrapSpec")
        if (
            type(self.schema) is not str
            or self.schema != _PRE_TEST_FREEZE_SCHEMA
            or type(self.version) is not int
            or self.version != _PRE_TEST_FREEZE_VERSION
        ):
            raise ValueError("pre-test freeze schema/version 不受支持")

        try:
            locked_baselines = tuple(self.locked_baselines)
            learned_predictors = tuple(self.learned_predictor_identities)
        except TypeError as error:
            raise TypeError("locked identity collections 必须是有限 iterable") from error
        if len(locked_baselines) != len(_BASELINE_ORDER):
            raise ValueError("locked_baselines 必须精确包含 B0--B5")
        if any(
            not isinstance(identity, LockedBaselineFreezeIdentity) for identity in locked_baselines
        ):
            raise TypeError("locked_baselines 类型错误")
        if tuple(identity.baseline for identity in locked_baselines) != _BASELINE_ORDER:
            raise ValueError("locked_baselines 必须按 B0--B5 canonical order 排列")
        if not isinstance(self.selected_baseline, BaselineKind):
            raise TypeError("selected_baseline 必须是 BaselineKind")
        if sum(identity.baseline is self.selected_baseline for identity in locked_baselines) != 1:
            raise ValueError("selected_baseline 必须唯一定位一个 locked baseline")
        if not isinstance(
            self.selected_learned_config_identity,
            LearnedConfigFreezeIdentity,
        ):
            raise TypeError("selected_learned_config_identity 类型错误")
        if any(
            not isinstance(identity, LockedLearnedPredictorIdentity)
            for identity in learned_predictors
        ):
            raise TypeError("learned_predictor_identities 类型错误")

        predictor_implementation_sha256 = _normalize_sha256(
            self.predictor_implementation_sha256,
            "predictor_implementation_sha256",
        )
        metric_implementation_sha256 = _normalize_sha256(
            self.metric_implementation_sha256,
            "metric_implementation_sha256",
        )
        evaluation_plan_sha256 = _normalize_sha256(
            self.evaluation_plan_sha256,
            "evaluation_plan_sha256",
        )
        bootstrap_implementation_sha256 = _normalize_sha256(
            self.bootstrap_implementation_sha256,
            "bootstrap_implementation_sha256",
        )
        official_failure_state_plan_sha256 = _normalize_sha256(
            self.official_failure_state_plan_sha256,
            "official_failure_state_plan_sha256",
        )
        runtime_provenance_sha256 = _normalize_sha256(
            self.runtime_provenance_sha256,
            "runtime_provenance_sha256",
        )
        git_commit_sha = _normalize_git_commit_sha(self.git_commit_sha)

        protocol_by_sha = {
            protocol.sha256: protocol
            for protocol in (
                self.pretraining_freeze.primary_protocol,
                *self.pretraining_freeze.secondary_protocols,
            )
        }
        locked_protocol_hashes = tuple(identity.protocol_sha256 for identity in locked_baselines)
        if any(protocol_sha not in protocol_by_sha for protocol_sha in locked_protocol_hashes):
            raise ValueError("locked baseline 引用了 unknown frozen protocol")
        learned_matches = tuple(
            identity
            for identity in self.pretraining_freeze.learned_config_identities
            if identity == self.selected_learned_config_identity
        )
        if len(learned_matches) != 1:
            raise ValueError("selected learned identity 未唯一匹配 Layer-A candidate")
        learned_protocol_sha = self.selected_learned_config_identity.protocol_sha256
        if learned_protocol_sha not in protocol_by_sha:
            raise ValueError("selected learned identity 引用了 unknown frozen protocol")
        prediction_horizons = {
            protocol_by_sha[protocol_sha].prediction_horizon
            for protocol_sha in (*locked_protocol_hashes, learned_protocol_sha)
        }
        if len(prediction_horizons) != 1:
            raise ValueError("locked protocols 必须共享 prediction_horizon")
        prediction_horizon = next(iter(prediction_horizons))

        source_num_zones = {
            entry.source.num_zones for entry in self.pretraining_freeze.split_manifest.entries
        }
        if len(source_num_zones) != 1:
            raise ValueError("Layer-A manifest sources 必须共享 num_zones")
        num_zones = next(iter(source_num_zones))
        expected_seeds = self.pretraining_freeze.fixed_training_seeds
        actual_seeds = tuple(identity.training_seed for identity in learned_predictors)
        if actual_seeds != expected_seeds:
            raise ValueError("learned predictor identities 必须精确覆盖 fixed training seeds")
        for identity in learned_predictors:
            expected_predictor_sha = _learned_predictor_sha256(
                predictor_implementation_sha256=predictor_implementation_sha256,
                config_sha256=self.selected_learned_config_identity.config_sha256,
                protocol_sha256=learned_protocol_sha,
                training_seed=identity.training_seed,
                checkpoint_digest=getattr(identity, _CHECKPOINT_SHA_FIELD),
            )
            if identity.predictor_sha256 != expected_predictor_sha:
                raise ValueError("learned predictor SHA 与 frozen identity inputs 不一致")

        test_id_trace_ids = self.pretraining_freeze.trace_ids_for_split(SplitLabel.TEST_ID)
        test_ood_trace_ids = self.pretraining_freeze.trace_ids_for_split(SplitLabel.TEST_OOD)
        final_ood_assignments = tuple(self.pretraining_freeze.ood_assignments)
        object.__setattr__(self, "locked_baselines", locked_baselines)
        object.__setattr__(self, "learned_predictor_identities", learned_predictors)
        object.__setattr__(
            self,
            "predictor_implementation_sha256",
            predictor_implementation_sha256,
        )
        object.__setattr__(self, "metric_implementation_sha256", metric_implementation_sha256)
        object.__setattr__(self, "evaluation_plan_sha256", evaluation_plan_sha256)
        object.__setattr__(
            self,
            "bootstrap_implementation_sha256",
            bootstrap_implementation_sha256,
        )
        object.__setattr__(
            self,
            "official_failure_state_plan_sha256",
            official_failure_state_plan_sha256,
        )
        object.__setattr__(self, "git_commit_sha", git_commit_sha)
        object.__setattr__(self, "runtime_provenance_sha256", runtime_provenance_sha256)
        object.__setattr__(
            self,
            "pretraining_freeze_sha256",
            self.pretraining_freeze.sha256,
        )
        object.__setattr__(self, "prediction_horizon", prediction_horizon)
        object.__setattr__(self, "num_zones", num_zones)
        object.__setattr__(
            self,
            "zone_schema_sha256",
            self.pretraining_freeze.zone_schema_sha256,
        )
        object.__setattr__(self, "test_id_trace_ids", test_id_trace_ids)
        object.__setattr__(self, "test_ood_trace_ids", test_ood_trace_ids)
        object.__setattr__(self, "final_ood_assignments", final_ood_assignments)
        object.__setattr__(self, "sha256", compute_config_hash(_pretest_freeze_identity(self)))

    @property
    def selected_baseline_identity(self) -> LockedBaselineFreezeIdentity:
        """返回由 selected B* 唯一定位的 locked baseline identity。"""

        return next(
            identity
            for identity in self.locked_baselines
            if identity.baseline is self.selected_baseline
        )


def _materialize_pretest_artifacts(
    verified_artifacts: object,
) -> tuple[VerifiedPredictionArtifact, ...]:
    """物化并验证 Layer-B authoritative source bindings，不读取 numerical payload。"""

    try:
        artifacts = tuple(verified_artifacts)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("verified_artifacts 必须是有限 iterable") from error
    if any(not isinstance(item, VerifiedPredictionArtifact) for item in artifacts):
        raise TypeError("verified_artifacts 必须全部是 VerifiedPredictionArtifact")
    trace_ids = tuple(item.source.trace_id for item in artifacts)
    if len(trace_ids) != len(set(trace_ids)):
        raise _freeze_failure("verified_artifacts 不允许重复 trace_id")
    return artifacts


def _normalize_baseline_predictor_sha_map(
    value: object,
) -> dict[BaselineKind, str]:
    """验证 B0--B5 predictor SHA Mapping 的 exact coverage 与值域。"""

    if not isinstance(value, Mapping):
        raise TypeError("baseline_predictor_sha256_by_kind 必须是 Mapping")
    keys = tuple(value.keys())
    if any(not isinstance(key, BaselineKind) for key in keys):
        raise TypeError("baseline predictor SHA Mapping keys 必须是 BaselineKind")
    if set(keys) != set(_BASELINE_ORDER) or len(keys) != len(_BASELINE_ORDER):
        raise ValueError("baseline predictor SHA Mapping 必须精确覆盖 B0--B5")
    return {
        baseline: _normalize_sha256(
            value[baseline],
            f"{baseline.value} predictor_sha256",
        )
        for baseline in _BASELINE_ORDER
    }


def _layer_a_validation_signature(
    pretraining_freeze: PreTrainingFreeze,
) -> tuple[tuple[str, int, int], ...]:
    """按 trace_id ascending 派生 Layer-A VALIDATION membership/geometry。"""

    return tuple(
        sorted(
            (
                (
                    entry.source.trace_id,
                    entry.source.start_step,
                    entry.source.num_steps,
                )
                for entry in pretraining_freeze.split_manifest.entries
                if entry.split is SplitLabel.VALIDATION
            ),
            key=lambda item: item[0],
        )
    )


def _match_selected_learned_identity(
    pretraining_freeze: PreTrainingFreeze,
    selected: object,
) -> LearnedConfigFreezeIdentity:
    """把 selected validation candidate 精确绑定回唯一 Layer-A identity。"""

    config_sha256 = selected.config_sha256  # type: ignore[attr-defined]
    matches = tuple(
        identity
        for identity in pretraining_freeze.learned_config_identities
        if identity.config_sha256 == config_sha256
    )
    if len(matches) != 1:
        raise ValueError("selected learned config SHA 未唯一匹配 Layer-A candidate")
    expected = matches[0]
    actual_fields = (
        config_sha256,
        selected.protocol.sha256,  # type: ignore[attr-defined]
        selected.objective,  # type: ignore[attr-defined]
        selected.transform,  # type: ignore[attr-defined]
        selected.model_complexity_key,  # type: ignore[attr-defined]
        selected.canonical_order,  # type: ignore[attr-defined]
    )
    expected_fields = (
        expected.config_sha256,
        expected.protocol_sha256,
        expected.objective,
        expected.transform,
        expected.model_complexity_key,
        expected.canonical_order,
    )
    if actual_fields != expected_fields:
        raise ValueError("selected learned candidate 与 Layer-A full identity 不一致")
    return expected


def _build_learned_predictor_identities(
    *,
    selected: object,
    selected_identity: LearnedConfigFreezeIdentity,
    fixed_training_seeds: tuple[int, ...],
    predictor_implementation_sha256: str,
) -> tuple[LockedLearnedPredictorIdentity, ...]:
    """为全部 fixed seeds 派生 checkpoint-bound learned predictor identities。"""

    seed_results = tuple(selected.seed_results)  # type: ignore[attr-defined]
    actual_seeds = tuple(result.training_seed for result in seed_results)
    if actual_seeds != fixed_training_seeds:
        raise ValueError("selected learned seed_results 必须精确覆盖 fixed training seeds")
    identities: list[LockedLearnedPredictorIdentity] = []
    for result in seed_results:
        checkpoint_digest = getattr(result, _CHECKPOINT_SHA_FIELD)
        if checkpoint_digest is None:
            raise ValueError("selected learned seed 缺少 checkpoint SHA")
        checkpoint_digest = _normalize_sha256(checkpoint_digest, "checkpoint SHA")
        predictor_sha256 = _learned_predictor_sha256(
            predictor_implementation_sha256=predictor_implementation_sha256,
            config_sha256=selected_identity.config_sha256,
            protocol_sha256=selected_identity.protocol_sha256,
            training_seed=result.training_seed,
            checkpoint_digest=checkpoint_digest,
        )
        identities.append(
            LockedLearnedPredictorIdentity(
                result.training_seed,
                checkpoint_digest,
                predictor_sha256,
            )
        )
    return tuple(identities)


def build_pretest_freeze(
    *,
    pretraining_freeze: PreTrainingFreeze,
    verified_artifacts: Iterable[VerifiedPredictionArtifact],
    baseline_selection: object,
    learned_selection: object,
    baseline_predictor_sha256_by_kind: Mapping[BaselineKind, str],
    predictor_implementation_sha256: str,
    metric_implementation_sha256: str,
    evaluation_plan_sha256: str,
    bootstrap_spec: PredictionBootstrapSpec,
    bootstrap_implementation_sha256: str,
    official_failure_state_plan_sha256: str,
    git_commit_sha: str,
    runtime_provenance_sha256: str,
) -> PreTestFreeze:
    """经 upstream locks、Layer-A rebind 与 B5 structural preflight 构造 Layer-B。

    本 factory 只读取 immutable protocol/source/selection/checkpoint identities；不保留 upstream
    result，不读取 numerical payload，也不执行 fit、forecast、metric 或 statistical computation。
    """

    if not isinstance(pretraining_freeze, PreTrainingFreeze):
        raise TypeError("pretraining_freeze 必须是 PreTrainingFreeze")
    if not isinstance(baseline_selection, _BASELINE_RESULT_TYPE):
        raise TypeError("baseline_selection 类型错误")
    if not isinstance(learned_selection, _LEARNED_RESULT_TYPE):
        raise TypeError("learned_selection 类型错误")
    if not isinstance(bootstrap_spec, PredictionBootstrapSpec):
        raise TypeError("bootstrap_spec 必须是 PredictionBootstrapSpec")
    artifacts = _materialize_pretest_artifacts(verified_artifacts)
    baseline_predictor_hashes = _normalize_baseline_predictor_sha_map(
        baseline_predictor_sha256_by_kind
    )
    predictor_implementation_sha256 = _normalize_sha256(
        predictor_implementation_sha256,
        "predictor_implementation_sha256",
    )

    if baseline_selection.prediction_horizon != learned_selection.prediction_horizon:
        raise ValueError("baseline/learned prediction_horizon 不一致")
    if baseline_selection.num_zones != learned_selection.num_zones:
        raise ValueError("baseline/learned num_zones 不一致")
    if baseline_selection.zone_schema_sha256 != learned_selection.zone_schema_sha256:
        raise ValueError("baseline/learned zone_schema_sha256 不一致")
    if (
        baseline_selection.validation_trace_signature
        != learned_selection.validation_trace_signature
    ):
        raise ValueError("baseline/learned validation trace signature 不一致")
    if baseline_selection.zone_schema_sha256 != pretraining_freeze.zone_schema_sha256:
        raise ValueError("selection zone schema 与 Layer-A freeze 不一致")
    if any(
        entry.source.num_zones != baseline_selection.num_zones
        for entry in pretraining_freeze.split_manifest.entries
    ):
        raise ValueError("selection num_zones 与 Layer-A manifest geometry 不一致")
    if any(
        candidate.protocol.prediction_horizon != baseline_selection.prediction_horizon
        or candidate.protocol.zone_schema_sha256 != baseline_selection.zone_schema_sha256
        for candidate in baseline_selection.locked_variants
    ):
        raise ValueError("locked baseline protocols 与 selection geometry 不一致")
    if (
        learned_selection.selected.protocol.prediction_horizon
        != learned_selection.prediction_horizon
        or learned_selection.selected.protocol.zone_schema_sha256
        != learned_selection.zone_schema_sha256
    ):
        raise ValueError("selected learned protocol 与 selection geometry 不一致")
    expected_validation_signature = _layer_a_validation_signature(pretraining_freeze)
    if baseline_selection.validation_trace_signature != expected_validation_signature:
        raise ValueError("selection validation signature 与 Layer-A membership 不一致")

    locked_baselines = tuple(
        LockedBaselineFreezeIdentity(
            baseline=candidate.baseline,
            protocol_sha256=candidate.protocol.sha256,
            predictor_sha256=baseline_predictor_hashes[candidate.baseline],
            alpha=candidate.alpha,
        )
        for candidate in baseline_selection.locked_variants
    )
    if tuple(identity.baseline for identity in locked_baselines) != _BASELINE_ORDER:
        raise ValueError("baseline_selection locked variants 不是 canonical B0--B5")
    selected_baseline = baseline_selection.selected.baseline
    selected_learned_identity = _match_selected_learned_identity(
        pretraining_freeze,
        learned_selection.selected,
    )
    if learned_selection.fixed_training_seeds != pretraining_freeze.fixed_training_seeds:
        raise ValueError("learned selection seeds 与 Layer-A fixed seeds 不一致")

    protocol_hashes = {
        pretraining_freeze.primary_protocol.sha256,
        *(protocol.sha256 for protocol in pretraining_freeze.secondary_protocols),
    }
    used_protocol_hashes = {
        *(identity.protocol_sha256 for identity in locked_baselines),
        selected_learned_identity.protocol_sha256,
    }
    if not used_protocol_hashes <= protocol_hashes:
        raise ValueError("locked selection 引用了 unknown Layer-A protocol")
    for protocol_sha256 in sorted(used_protocol_hashes):
        preflight_layer_a_b5_support(
            pretraining_freeze=pretraining_freeze,
            protocol_sha256=protocol_sha256,
            verified_artifacts=artifacts,
        )

    learned_predictors = _build_learned_predictor_identities(
        selected=learned_selection.selected,
        selected_identity=selected_learned_identity,
        fixed_training_seeds=pretraining_freeze.fixed_training_seeds,
        predictor_implementation_sha256=predictor_implementation_sha256,
    )
    return PreTestFreeze(
        pretraining_freeze=pretraining_freeze,
        locked_baselines=locked_baselines,
        selected_baseline=selected_baseline,
        selected_learned_config_identity=selected_learned_identity,
        learned_predictor_identities=learned_predictors,
        predictor_implementation_sha256=predictor_implementation_sha256,
        metric_implementation_sha256=metric_implementation_sha256,
        evaluation_plan_sha256=evaluation_plan_sha256,
        bootstrap_spec=bootstrap_spec,
        bootstrap_implementation_sha256=bootstrap_implementation_sha256,
        official_failure_state_plan_sha256=official_failure_state_plan_sha256,
        git_commit_sha=git_commit_sha,
        runtime_provenance_sha256=runtime_provenance_sha256,
    )


@dataclass(frozen=True, slots=True)
class FirstOfficialTestExecution:
    """首次触发 sealed test exposure 的 immutable governance identity。

    本对象只记录已注册 Layer-B freeze、test split 与 action kind；它不执行 action，
    也不保存任何 numerical outcome。
    """

    pretest_freeze_sha256: str
    split: SplitLabel
    kind: OfficialTestExecutionKind

    def __post_init__(self) -> None:
        """验证 exact Layer-B SHA、test-only split 与 execution kind。"""

        pretest_freeze_sha256 = _normalize_sha256(
            self.pretest_freeze_sha256,
            "pretest_freeze_sha256",
        )
        if not isinstance(self.split, SplitLabel):
            raise TypeError("split 必须是 SplitLabel")
        if self.split not in {SplitLabel.TEST_ID, SplitLabel.TEST_OOD}:
            raise ValueError("split 必须是 TEST_ID 或 TEST_OOD")
        if not isinstance(self.kind, OfficialTestExecutionKind):
            raise TypeError("kind 必须是 OfficialTestExecutionKind")
        object.__setattr__(self, "pretest_freeze_sha256", pretest_freeze_sha256)


def _normalize_identity_tuple(value: object, name: str) -> tuple[str, ...]:
    """把 finite iterable 规范为保持 caller 顺序的安全 identity tuple。"""

    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} 必须是有限 iterable")
    try:
        identities = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} 必须是有限 iterable") from error
    if any(
        not isinstance(identity, str) or _SAFE_ID_PATTERN.fullmatch(identity) is None
        for identity in identities
    ):
        raise ValueError(f"{name} 必须全部是安全的 1..255 字符标识符")
    return identities


def _normalize_registered_pretest_freezes(value: object) -> tuple[str, ...]:
    """验证 registered Layer-B SHA tuple，不在 direct constructor 中增删或排序。"""

    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError("registered_pretest_freeze_sha256s 必须是有限 iterable")
    try:
        identities = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("registered_pretest_freeze_sha256s 必须是有限 iterable") from error
    return tuple(
        _normalize_sha256(identity, "registered pretest freeze SHA") for identity in identities
    )


def _first_official_test_execution_identity(
    first_execution: FirstOfficialTestExecution,
) -> dict[str, object]:
    """返回 first exposure 的 canonical identity tree。"""

    return {
        "pretest_freeze_sha256": first_execution.pretest_freeze_sha256,
        "split": first_execution.split.value,
        "kind": first_execution.kind.value,
    }


def _sealed_evaluation_state_identity(
    state: SealedEvaluationState,
) -> dict[str, object]:
    """返回不含 self hash 的 canonical sealed-state identity tree。"""

    first_execution = state.first_official_test_execution
    return {
        "schema": state.schema,
        "version": state.version,
        "pretraining_freeze_sha256": state.pretraining_freeze_sha256,
        "registered_pretest_freeze_sha256s": list(state.registered_pretest_freeze_sha256s),
        "test_id_trace_ids": list(state.test_id_trace_ids),
        "test_ood_trace_ids": list(state.test_ood_trace_ids),
        "disposition": state.disposition.value,
        "first_official_test_execution": (
            "ABSENT"
            if first_execution is None
            else _first_official_test_execution_identity(first_execution)
        ),
    }


@dataclass(frozen=True, slots=True)
class SealedEvaluationState:
    """Immutable sealed test-set disposition 与 first-exposure identity。

    直接构造只证明字段间 structural consistency。official 初始 unexposed phase 必须通过
    :func:`build_sealed_evaluation_state` 注册完整的 Layer-B freeze 集合；official first
    transition 必须通过 :func:`record_first_official_test_execution`。本对象不授权或执行
    forecast、evaluation、metric、bootstrap 或 result readback。
    """

    pretraining_freeze_sha256: str
    registered_pretest_freeze_sha256s: tuple[str, ...]
    test_id_trace_ids: tuple[str, ...]
    test_ood_trace_ids: tuple[str, ...]
    disposition: TestSetDisposition
    first_official_test_execution: FirstOfficialTestExecution | None
    schema: str = _SEALED_EVALUATION_STATE_SCHEMA
    version: int = _SEALED_EVALUATION_STATE_VERSION
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """验证 structural consistency 并计算 deterministic state hash。"""

        pretraining_freeze_sha256 = _normalize_sha256(
            self.pretraining_freeze_sha256,
            "pretraining_freeze_sha256",
        )
        registered = _normalize_registered_pretest_freezes(self.registered_pretest_freeze_sha256s)
        test_id_trace_ids = _normalize_identity_tuple(
            self.test_id_trace_ids,
            "test_id_trace_ids",
        )
        test_ood_trace_ids = _normalize_identity_tuple(
            self.test_ood_trace_ids,
            "test_ood_trace_ids",
        )
        if not isinstance(self.disposition, TestSetDisposition):
            raise TypeError("disposition 必须是 TestSetDisposition")
        first_execution = self.first_official_test_execution
        if first_execution is not None and not isinstance(
            first_execution,
            FirstOfficialTestExecution,
        ):
            raise TypeError(
                "first_official_test_execution 必须是 FirstOfficialTestExecution 或 None"
            )
        if self.disposition is _UNEXPOSED_TEST_SET_DISPOSITION and first_execution is not None:
            raise ValueError("unexposed state 不得包含 first official execution")
        if self.disposition is _EXPOSED_TEST_SET_DISPOSITION and first_execution is None:
            raise ValueError("exposed state 必须包含 first official execution")
        if first_execution is not None and first_execution.pretest_freeze_sha256 not in registered:
            raise ValueError("first official execution 必须引用 registered PreTestFreeze")
        if (
            type(self.schema) is not str
            or self.schema != _SEALED_EVALUATION_STATE_SCHEMA
            or type(self.version) is not int
            or self.version != _SEALED_EVALUATION_STATE_VERSION
        ):
            raise ValueError("sealed evaluation state schema/version 不受支持")

        object.__setattr__(
            self,
            "pretraining_freeze_sha256",
            pretraining_freeze_sha256,
        )
        object.__setattr__(
            self,
            "registered_pretest_freeze_sha256s",
            registered,
        )
        object.__setattr__(self, "test_id_trace_ids", test_id_trace_ids)
        object.__setattr__(self, "test_ood_trace_ids", test_ood_trace_ids)
        object.__setattr__(
            self,
            "sha256",
            compute_config_hash(_sealed_evaluation_state_identity(self)),
        )


def build_sealed_evaluation_state(
    pretest_freezes: Iterable[PreTestFreeze],
) -> SealedEvaluationState:
    """注册完整 Layer-B freeze 集合并建立 initial unexposed sealed phase。

    这是 official initial-state trust boundary：全部 registered freezes 必须在首次 exposure
    之前一次性提供，并共享 exact Layer-A 与 test-set identities。此函数只注册 identities，
    不执行任何 official action，也不会改变 test-set disposition。
    """

    try:
        freezes = tuple(pretest_freezes)
    except TypeError as error:
        raise TypeError("pretest_freezes 必须是有限 iterable") from error
    if not freezes:
        raise ValueError("pretest_freezes 必须非空")
    if any(not isinstance(freeze, PreTestFreeze) for freeze in freezes):
        raise TypeError("pretest_freezes 必须全部是 PreTestFreeze")

    registered = tuple(freeze.sha256 for freeze in freezes)
    if len(registered) != len(set(registered)):
        raise ValueError("PreTestFreeze SHA 必须全部唯一")
    first = freezes[0]
    shared_identity = (
        first.pretraining_freeze_sha256,
        first.zone_schema_sha256,
        first.test_id_trace_ids,
        first.test_ood_trace_ids,
    )
    if any(
        (
            freeze.pretraining_freeze_sha256,
            freeze.zone_schema_sha256,
            freeze.test_id_trace_ids,
            freeze.test_ood_trace_ids,
        )
        != shared_identity
        for freeze in freezes[1:]
    ):
        raise ValueError("全部 PreTestFreeze 必须共享 exact Layer-A test-set identity")

    test_id_trace_ids = tuple(first.test_id_trace_ids)
    test_ood_trace_ids = tuple(first.test_ood_trace_ids)
    if not test_id_trace_ids or not test_ood_trace_ids:
        raise ValueError("TEST_ID 与 TEST_OOD 必须都非空")
    if len(test_id_trace_ids) != len(set(test_id_trace_ids)):
        raise ValueError("TEST_ID trace identities 不得重复")
    if len(test_ood_trace_ids) != len(set(test_ood_trace_ids)):
        raise ValueError("TEST_OOD trace identities 不得重复")
    if set(test_id_trace_ids) & set(test_ood_trace_ids):
        raise ValueError("TEST_ID 与 TEST_OOD trace identities 不得重叠")

    return SealedEvaluationState(
        pretraining_freeze_sha256=first.pretraining_freeze_sha256,
        registered_pretest_freeze_sha256s=tuple(sorted(registered)),
        test_id_trace_ids=test_id_trace_ids,
        test_ood_trace_ids=test_ood_trace_ids,
        disposition=_UNEXPOSED_TEST_SET_DISPOSITION,
        first_official_test_execution=None,
    )


def record_first_official_test_execution(
    state: SealedEvaluationState,
    first_execution: FirstOfficialTestExecution,
) -> SealedEvaluationState:
    """在 numerical action 之前记录唯一 unexposed -> exposed governance transition。

    本函数只记录不可逆的 first-exposure identity，不运行 action。trigger 属于 TEST_ID 或
    TEST_OOD 时，state 中两个 frozen test sets 同时成为 one-shot exposed test sets。
    """

    if not isinstance(state, SealedEvaluationState):
        raise TypeError("state 必须是 SealedEvaluationState")
    if not isinstance(first_execution, FirstOfficialTestExecution):
        raise TypeError("first_execution 必须是 FirstOfficialTestExecution")
    if state.disposition is not _UNEXPOSED_TEST_SET_DISPOSITION:
        raise ValueError("只有 unexposed state 可以记录 first official execution")
    if state.first_official_test_execution is not None:
        raise ValueError("unexposed state 不得已有 first official execution")
    if first_execution.pretest_freeze_sha256 not in state.registered_pretest_freeze_sha256s:
        raise ValueError("first_execution 必须引用 registered PreTestFreeze")

    return SealedEvaluationState(
        pretraining_freeze_sha256=state.pretraining_freeze_sha256,
        registered_pretest_freeze_sha256s=state.registered_pretest_freeze_sha256s,
        test_id_trace_ids=state.test_id_trace_ids,
        test_ood_trace_ids=state.test_ood_trace_ids,
        disposition=_EXPOSED_TEST_SET_DISPOSITION,
        first_official_test_execution=first_execution,
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
