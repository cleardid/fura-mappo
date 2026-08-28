"""Official point-forecast records 的 immutable provenance binding core。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from fura_mappo.prediction.dataset import (
    DatasetProtocolSpec,
    PredictionSource,
    SplitLabel,
    VerifiedPredictionArtifact,
    derive_prediction_samples_from_artifact,
    validate_prediction_source_for_artifact,
)
from fura_mappo.prediction.governance import (
    PreTestFreeze,
    SealedEvaluationState,
    TestSetDisposition,
)
from fura_mappo.prediction.metrics import PointForecastRecord
from fura_mappo.prediction.models import ForecastProvenance, ForecastRecord, PredictionSample
from fura_mappo.prediction.selection import BaselineKind

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_TRACE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_TEST_SPLITS = (SplitLabel.TEST_ID, SplitLabel.TEST_OOD)


def _normalize_sha256(value: object, name: str) -> str:
    """验证 exact lowercase SHA-256 identity。"""

    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} 必须是 64 位小写 SHA-256")
    return value


def _normalize_git_commit(value: object) -> str:
    """验证 exact lowercase Git commit identity。"""

    if not isinstance(value, str) or _GIT_SHA_PATTERN.fullmatch(value) is None:
        raise ValueError("execution_git_commit 必须是 40 位小写 Git commit SHA")
    return value


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """验证 non-bool nonnegative integer。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 必须是非 bool 整数")
    if value < 0:
        raise ValueError(f"{name} 必须大于或等于 0")
    return value


def _normalize_positive_integer(value: object, name: str) -> int:
    """验证 non-bool positive integer。"""

    normalized = _normalize_nonnegative_integer(value, name)
    if normalized < 1:
        raise ValueError(f"{name} 必须大于或等于 1")
    return normalized


def _normalize_trace_ids(value: object) -> tuple[str, ...]:
    """规范化非空、唯一的 frozen trace inventory。"""

    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError("trace_ids 必须是有限 iterable")
    try:
        trace_ids = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("trace_ids 必须是有限 iterable") from error
    if not trace_ids:
        raise ValueError("trace_ids 必须非空")
    if any(
        not isinstance(trace_id, str) or _TRACE_ID_PATTERN.fullmatch(trace_id) is None
        for trace_id in trace_ids
    ):
        raise ValueError("trace_ids 必须全部是安全的 1..255 字符标识符")
    if len(trace_ids) != len(set(trace_ids)):
        raise ValueError("trace_ids 不得重复")
    return trace_ids


@dataclass(frozen=True, slots=True)
class OfficialPointForecastRecord:
    """一个 authoritative sample/forecast 与其 hidden provenance 的 immutable binding。

    直接构造只验证结构。official path 必须由本模块 factory 使用 authoritative sample 与同一
    :class:`ForecastRecord` 的 forecast/provenance 成对构造。
    """

    point_record: PointForecastRecord
    provenance: ForecastProvenance

    def __post_init__(self) -> None:
        """验证 record 类型与 sample identity binding。"""

        if not isinstance(self.point_record, PointForecastRecord):
            raise TypeError("point_record 必须是 PointForecastRecord")
        if not isinstance(self.provenance, ForecastProvenance):
            raise TypeError("provenance 必须是 ForecastProvenance")
        if self.provenance.sample_id != self.point_record.sample.sample_id:
            raise ValueError("provenance.sample_id 必须等于 authoritative sample_id")


@dataclass(frozen=True, slots=True)
class OfficialPredictorSplitForecasts:
    """一个 locked predictor 在 exact test split 上的 immutable point-record bundle。

    本对象只保存 numerical forecast records 与 frozen identity snapshot，不定义 persistence
    schema，也不表示 scientific evaluation success。
    """

    sealed_evaluation_state_sha256: str
    pretraining_freeze_sha256: str
    pretest_freeze_sha256: str
    split: SplitLabel
    baseline: BaselineKind | None
    training_seed: int | None
    predictor_artifact_sha256: str
    prediction_config_sha256: str
    protocol_sha256: str
    split_manifest_sha256: str
    execution_git_commit: str
    prediction_horizon: int
    num_zones: int
    zone_schema_sha256: str
    trace_ids: tuple[str, ...]
    records: tuple[OfficialPointForecastRecord, ...]

    def __post_init__(self) -> None:
        """验证 identity-only bundle、one-of predictor kind 与 canonical record order。"""

        sealed_state_sha256 = _normalize_sha256(
            self.sealed_evaluation_state_sha256,
            "sealed_evaluation_state_sha256",
        )
        pretraining_freeze_sha256 = _normalize_sha256(
            self.pretraining_freeze_sha256,
            "pretraining_freeze_sha256",
        )
        pretest_freeze_sha256 = _normalize_sha256(
            self.pretest_freeze_sha256,
            "pretest_freeze_sha256",
        )
        predictor_artifact_sha256 = _normalize_sha256(
            self.predictor_artifact_sha256,
            "predictor_artifact_sha256",
        )
        prediction_config_sha256 = _normalize_sha256(
            self.prediction_config_sha256,
            "prediction_config_sha256",
        )
        protocol_sha256 = _normalize_sha256(self.protocol_sha256, "protocol_sha256")
        split_manifest_sha256 = _normalize_sha256(
            self.split_manifest_sha256,
            "split_manifest_sha256",
        )
        zone_schema_sha256 = _normalize_sha256(
            self.zone_schema_sha256,
            "zone_schema_sha256",
        )
        execution_git_commit = _normalize_git_commit(self.execution_git_commit)
        prediction_horizon = _normalize_positive_integer(
            self.prediction_horizon,
            "prediction_horizon",
        )
        num_zones = _normalize_positive_integer(self.num_zones, "num_zones")
        if not isinstance(self.split, SplitLabel):
            raise TypeError("split 必须是 SplitLabel")
        if self.split not in _TEST_SPLITS:
            raise ValueError("split 必须是 TEST_ID 或 TEST_OOD")
        if self.baseline is not None and not isinstance(self.baseline, BaselineKind):
            raise TypeError("baseline 必须是 BaselineKind 或 None")
        training_seed = self.training_seed
        if training_seed is not None:
            training_seed = _normalize_nonnegative_integer(training_seed, "training_seed")
        if (self.baseline is None) == (training_seed is None):
            raise ValueError("baseline 与 training_seed 必须精确 one-of")
        trace_ids = _normalize_trace_ids(self.trace_ids)
        if isinstance(self.records, (str, bytes, bytearray)):
            raise TypeError("records 必须是有限 iterable")
        try:
            records = tuple(self.records)
        except TypeError as error:
            raise TypeError("records 必须是有限 iterable") from error
        if any(not isinstance(record, OfficialPointForecastRecord) for record in records):
            raise TypeError("records 必须全部是 OfficialPointForecastRecord")
        sample_ids = tuple(record.provenance.sample_id for record in records)
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("records 不得重复 sample_id")
        trace_order = {trace_id: index for index, trace_id in enumerate(trace_ids)}
        if any(record.point_record.trace_id not in trace_order for record in records):
            raise ValueError("record trace_id 必须属于 frozen trace_ids")
        order_keys = tuple(
            (
                trace_order[record.point_record.trace_id],
                record.point_record.sample.context.absolute_step,
            )
            for record in records
        )
        if order_keys != tuple(sorted(order_keys)):
            raise ValueError("records 必须按 frozen trace order 与 anchor ascending 排列")
        for record in records:
            provenance = record.provenance
            if provenance.predictor_artifact_sha256 != predictor_artifact_sha256:
                raise ValueError("record predictor artifact SHA 与 bundle 不一致")
            if provenance.prediction_config_sha256 != prediction_config_sha256:
                raise ValueError("record prediction config SHA 与 bundle 不一致")
            if provenance.dataset_protocol_sha256 != protocol_sha256:
                raise ValueError("record dataset protocol SHA 与 bundle 不一致")
            if provenance.split_manifest_sha256 != split_manifest_sha256:
                raise ValueError("record split manifest SHA 与 bundle 不一致")
            if provenance.execution_git_commit != execution_git_commit:
                raise ValueError("record execution Git commit 与 bundle 不一致")
            context = record.point_record.sample.context
            if context.prediction_horizon != prediction_horizon:
                raise ValueError("record prediction horizon 与 bundle 不一致")
            if context.num_zones != num_zones:
                raise ValueError("record num_zones 与 bundle 不一致")
            if context.zone_schema_sha256 != zone_schema_sha256:
                raise ValueError("record zone schema SHA 与 bundle 不一致")

        object.__setattr__(self, "sealed_evaluation_state_sha256", sealed_state_sha256)
        object.__setattr__(self, "pretraining_freeze_sha256", pretraining_freeze_sha256)
        object.__setattr__(self, "pretest_freeze_sha256", pretest_freeze_sha256)
        object.__setattr__(self, "training_seed", training_seed)
        object.__setattr__(self, "predictor_artifact_sha256", predictor_artifact_sha256)
        object.__setattr__(self, "prediction_config_sha256", prediction_config_sha256)
        object.__setattr__(self, "protocol_sha256", protocol_sha256)
        object.__setattr__(self, "split_manifest_sha256", split_manifest_sha256)
        object.__setattr__(self, "execution_git_commit", execution_git_commit)
        object.__setattr__(self, "prediction_horizon", prediction_horizon)
        object.__setattr__(self, "num_zones", num_zones)
        object.__setattr__(self, "zone_schema_sha256", zone_schema_sha256)
        object.__setattr__(self, "trace_ids", trace_ids)
        object.__setattr__(self, "records", records)

    @property
    def point_records(self) -> tuple[PointForecastRecord, ...]:
        """返回 future metrics orchestration 可消费的 immutable point records。"""

        return tuple(record.point_record for record in self.records)


def _validate_spent_state_binding(
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
) -> None:
    """在任何 test artifact/forecast access 前验证 already-SPENT authoritative identity。"""

    if not isinstance(state, SealedEvaluationState):
        raise TypeError("state 必须是 SealedEvaluationState")
    if not isinstance(pretest_freeze, PreTestFreeze):
        raise TypeError("pretest_freeze 必须是 PreTestFreeze")
    if state.disposition is not TestSetDisposition.SPENT:
        raise ValueError("official forecast binding 要求 already-SPENT state")
    if state.first_official_test_execution is None:
        raise ValueError("SPENT state 必须保留 first official execution")
    if pretest_freeze.sha256 not in state.registered_pretest_freeze_sha256s:
        raise ValueError("pretest_freeze 必须属于 state registered Layer-B freezes")
    if pretest_freeze.pretraining_freeze_sha256 != state.pretraining_freeze_sha256:
        raise ValueError("pretest_freeze Layer-A SHA 与 sealed state 不一致")
    if pretest_freeze.test_id_trace_ids != state.test_id_trace_ids:
        raise ValueError("pretest_freeze TEST_ID identities 与 sealed state 不一致")
    if pretest_freeze.test_ood_trace_ids != state.test_ood_trace_ids:
        raise ValueError("pretest_freeze TEST_OOD identities 与 sealed state 不一致")


def _validate_test_split(split: SplitLabel) -> SplitLabel:
    """验证 official binding 只允许 TEST_ID/TEST_OOD。"""

    if not isinstance(split, SplitLabel):
        raise TypeError("split 必须是 SplitLabel")
    if split not in _TEST_SPLITS:
        raise ValueError("split 必须是 TEST_ID 或 TEST_OOD")
    return split


def _resolve_protocol(
    pretest_freeze: PreTestFreeze,
    protocol_sha256: str,
) -> DatasetProtocolSpec:
    """从 frozen Layer-A protocols 唯一解析 exact protocol identity。"""

    matches = tuple(
        protocol
        for protocol in (
            pretest_freeze.pretraining_freeze.primary_protocol,
            *pretest_freeze.pretraining_freeze.secondary_protocols,
        )
        if protocol.sha256 == protocol_sha256
    )
    if len(matches) != 1:
        raise ValueError("protocol SHA 未唯一解析到 frozen DatasetProtocolSpec")
    return matches[0]


def _expected_sources(
    pretest_freeze: PreTestFreeze,
    split: SplitLabel,
    trace_ids: tuple[str, ...],
) -> tuple[PredictionSource, ...]:
    """按 frozen test order 解析 exact manifest PredictionSource inventory。"""

    source_by_trace_id = {
        entry.source.trace_id: entry.source
        for entry in pretest_freeze.pretraining_freeze.split_manifest.entries
        if entry.split is split
    }
    if len(source_by_trace_id) != len(trace_ids) or set(source_by_trace_id) != set(trace_ids):
        raise ValueError("PreTestFreeze test inventory 与 Layer-A split manifest 不一致")
    return tuple(source_by_trace_id[trace_id] for trace_id in trace_ids)


def _bind_artifacts_and_samples(
    *,
    expected_sources: tuple[PredictionSource, ...],
    verified_artifacts: Iterable[VerifiedPredictionArtifact],
    protocol: DatasetProtocolSpec,
) -> tuple[tuple[PredictionSource, PredictionSample], ...]:
    """执行 exact artifact coverage/source rebind 并派生 authoritative samples。"""

    try:
        artifacts = tuple(verified_artifacts)
    except TypeError as error:
        raise TypeError("verified_artifacts 必须是有限 iterable") from error
    if any(not isinstance(artifact, VerifiedPredictionArtifact) for artifact in artifacts):
        raise TypeError("verified_artifacts 必须全部是 VerifiedPredictionArtifact")
    artifact_trace_ids = tuple(artifact.source.trace_id for artifact in artifacts)
    if len(artifact_trace_ids) != len(set(artifact_trace_ids)):
        raise ValueError("verified_artifacts 不得重复 trace_id")
    expected_trace_ids = tuple(source.trace_id for source in expected_sources)
    if set(artifact_trace_ids) != set(expected_trace_ids):
        raise ValueError("verified_artifacts 必须精确覆盖 requested frozen test split")
    artifact_by_trace_id = {artifact.source.trace_id: artifact for artifact in artifacts}

    source_sample_pairs: list[tuple[PredictionSource, PredictionSample]] = []
    sample_ids: set[str] = set()
    for source in expected_sources:
        artifact = artifact_by_trace_id[source.trace_id]
        validate_prediction_source_for_artifact(artifact, source)
        samples = tuple(
            sorted(
                derive_prediction_samples_from_artifact(artifact, protocol),
                key=lambda sample: sample.context.absolute_step,
            )
        )
        for sample in samples:
            if sample.sample_id in sample_ids:
                raise ValueError("authoritative samples 不得重复 sample_id")
            sample_ids.add(sample.sample_id)
            source_sample_pairs.append((source, sample))
    return tuple(source_sample_pairs)


def _materialize_forecast_records(
    forecast_records: Iterable[ForecastRecord],
) -> dict[str, ForecastRecord]:
    """物化 caller records并拒绝 type/duplicate sample identity。"""

    try:
        records = tuple(forecast_records)
    except TypeError as error:
        raise TypeError("forecast_records 必须是有限 iterable") from error
    if any(not isinstance(record, ForecastRecord) for record in records):
        raise TypeError("forecast_records 必须全部是 ForecastRecord")
    sample_ids = tuple(record.provenance.sample_id for record in records)
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("forecast_records 不得重复 provenance.sample_id")
    return {record.provenance.sample_id: record for record in records}


def _validate_point_forecast_provenance(
    *,
    forecast_record: ForecastRecord,
    sample: PredictionSample,
    predictor_artifact_sha256: str,
    prediction_config_sha256: str,
    protocol_sha256: str,
    split_manifest_sha256: str,
    execution_git_commit: str,
) -> None:
    """验证 exact locked provenance 与 WP-03B point-only surface。"""

    provenance = forecast_record.provenance
    if provenance.sample_id != sample.sample_id:
        raise ValueError("forecast provenance sample_id 与 authoritative sample 不一致")
    if provenance.predictor_artifact_sha256 != predictor_artifact_sha256:
        raise ValueError("forecast predictor artifact SHA 与 locked predictor 不一致")
    if provenance.prediction_config_sha256 != prediction_config_sha256:
        raise ValueError("forecast prediction config SHA 与 frozen config 不一致")
    if provenance.dataset_protocol_sha256 != protocol_sha256:
        raise ValueError("forecast dataset protocol SHA 与 frozen protocol 不一致")
    if provenance.split_manifest_sha256 != split_manifest_sha256:
        raise ValueError("forecast split manifest SHA 与 frozen manifest 不一致")
    if provenance.execution_git_commit != execution_git_commit:
        raise ValueError("forecast execution Git commit 与 PreTestFreeze 不一致")
    if provenance.normalization_sha256 is not None:
        raise ValueError("point-only official forecast normalization_sha256 必须为 None")
    if provenance.inference_rng_id is not None:
        raise ValueError("point-only official forecast inference_rng_id 必须为 None")
    forecast = forecast_record.forecast
    if forecast.variance is not None:
        raise ValueError("point-only official forecast 不得包含 variance")
    if forecast.quantile_levels is not None or forecast.quantiles is not None:
        raise ValueError("point-only official forecast 不得包含 quantiles")
    if forecast.scenarios is not None:
        raise ValueError("point-only official forecast 不得包含 scenarios")


def _bind_official_split_forecasts(
    *,
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
    split: SplitLabel,
    baseline: BaselineKind | None,
    training_seed: int | None,
    predictor_artifact_sha256: str,
    prediction_config_sha256: str,
    protocol: DatasetProtocolSpec,
    verified_artifacts: Iterable[VerifiedPredictionArtifact],
    forecast_records: Iterable[ForecastRecord],
) -> OfficialPredictorSplitForecasts:
    """绑定 exact split inventory、authoritative samples 与 caller forecast records。"""

    trace_ids = (
        pretest_freeze.test_id_trace_ids
        if split is SplitLabel.TEST_ID
        else pretest_freeze.test_ood_trace_ids
    )
    sources = _expected_sources(pretest_freeze, split, trace_ids)
    source_sample_pairs = _bind_artifacts_and_samples(
        expected_sources=sources,
        verified_artifacts=verified_artifacts,
        protocol=protocol,
    )
    forecast_by_sample_id = _materialize_forecast_records(forecast_records)
    expected_sample_ids = {sample.sample_id for _, sample in source_sample_pairs}
    if set(forecast_by_sample_id) != expected_sample_ids:
        raise ValueError("forecast_records 必须精确覆盖 authoritative sample IDs")

    split_manifest_sha256 = pretest_freeze.pretraining_freeze.split_manifest.sha256
    bound_records: list[OfficialPointForecastRecord] = []
    for source, sample in source_sample_pairs:
        forecast_record = forecast_by_sample_id[sample.sample_id]
        _validate_point_forecast_provenance(
            forecast_record=forecast_record,
            sample=sample,
            predictor_artifact_sha256=predictor_artifact_sha256,
            prediction_config_sha256=prediction_config_sha256,
            protocol_sha256=protocol.sha256,
            split_manifest_sha256=split_manifest_sha256,
            execution_git_commit=pretest_freeze.git_commit_sha,
        )
        point_record = PointForecastRecord(
            trace_id=source.trace_id,
            trace_start_step=source.start_step,
            trace_num_steps=source.num_steps,
            sample=sample,
            forecast=forecast_record.forecast,
        )
        bound_records.append(
            OfficialPointForecastRecord(
                point_record=point_record,
                provenance=forecast_record.provenance,
            )
        )

    return OfficialPredictorSplitForecasts(
        sealed_evaluation_state_sha256=state.sha256,
        pretraining_freeze_sha256=state.pretraining_freeze_sha256,
        pretest_freeze_sha256=pretest_freeze.sha256,
        split=split,
        baseline=baseline,
        training_seed=training_seed,
        predictor_artifact_sha256=predictor_artifact_sha256,
        prediction_config_sha256=prediction_config_sha256,
        protocol_sha256=protocol.sha256,
        split_manifest_sha256=split_manifest_sha256,
        execution_git_commit=pretest_freeze.git_commit_sha,
        prediction_horizon=protocol.prediction_horizon,
        num_zones=pretest_freeze.num_zones,
        zone_schema_sha256=pretest_freeze.zone_schema_sha256,
        trace_ids=trace_ids,
        records=tuple(bound_records),
    )


def bind_official_baseline_split_forecasts(
    *,
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
    split: SplitLabel,
    baseline: BaselineKind,
    verified_artifacts: Iterable[VerifiedPredictionArtifact],
    forecast_records: Iterable[ForecastRecord],
) -> OfficialPredictorSplitForecasts:
    """绑定一个 locked B0--B5 的 official point forecasts，不执行 forecast 或 metrics。

    任何 real official binding failure必须由上层 orchestration记录为
    ``PREDICTION_EVALUATION_FAILURE``；不得继续 smaller-n evaluation。
    """

    _validate_spent_state_binding(state, pretest_freeze)
    split = _validate_test_split(split)
    if not isinstance(baseline, BaselineKind):
        raise TypeError("baseline 必须是 BaselineKind")
    matches = tuple(
        identity for identity in pretest_freeze.locked_baselines if identity.baseline is baseline
    )
    if len(matches) != 1:
        raise ValueError("baseline 未唯一匹配 locked baseline identity")
    locked_identity = matches[0]
    protocol = _resolve_protocol(pretest_freeze, locked_identity.protocol_sha256)
    return _bind_official_split_forecasts(
        state=state,
        pretest_freeze=pretest_freeze,
        split=split,
        baseline=baseline,
        training_seed=None,
        predictor_artifact_sha256=locked_identity.predictor_sha256,
        prediction_config_sha256=pretest_freeze.pretraining_freeze.baseline_plan_sha256,
        protocol=protocol,
        verified_artifacts=verified_artifacts,
        forecast_records=forecast_records,
    )


def bind_official_learned_split_forecasts(
    *,
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
    split: SplitLabel,
    training_seed: int,
    verified_artifacts: Iterable[VerifiedPredictionArtifact],
    forecast_records: Iterable[ForecastRecord],
) -> OfficialPredictorSplitForecasts:
    """绑定一个 fixed-seed learned predictor 的 official point forecasts，不执行 inference。

    任何 real official binding failure必须由上层 orchestration记录为
    ``PREDICTION_EVALUATION_FAILURE``；不得继续 smaller-n evaluation。
    """

    _validate_spent_state_binding(state, pretest_freeze)
    split = _validate_test_split(split)
    training_seed = _normalize_nonnegative_integer(training_seed, "training_seed")
    matches = tuple(
        identity
        for identity in pretest_freeze.learned_predictor_identities
        if identity.training_seed == training_seed
    )
    if len(matches) != 1:
        raise ValueError("training_seed 未唯一匹配 locked learned predictor identity")
    locked_identity = matches[0]
    learned_config = pretest_freeze.selected_learned_config_identity
    protocol = _resolve_protocol(pretest_freeze, learned_config.protocol_sha256)
    return _bind_official_split_forecasts(
        state=state,
        pretest_freeze=pretest_freeze,
        split=split,
        baseline=None,
        training_seed=training_seed,
        predictor_artifact_sha256=locked_identity.predictor_sha256,
        prediction_config_sha256=learned_config.config_sha256,
        protocol=protocol,
        verified_artifacts=verified_artifacts,
        forecast_records=forecast_records,
    )


__all__ = [
    "OfficialPointForecastRecord",
    "OfficialPredictorSplitForecasts",
    "bind_official_baseline_split_forecasts",
    "bind_official_learned_split_forecasts",
]
