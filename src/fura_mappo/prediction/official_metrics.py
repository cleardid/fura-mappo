"""Official sealed point-metric completeness core。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from fura_mappo.prediction.dataset import (
    DatasetProtocolSpec,
    PredictionSource,
    SplitLabel,
    VerifiedPredictionArtifact,
    derive_prediction_samples_from_artifact,
    validate_prediction_source_for_artifact,
)
from fura_mappo.prediction.evaluation import (
    OfficialPointForecastRecord,
    OfficialPredictorSplitForecasts,
)
from fura_mappo.prediction.governance import (
    PreTestFreeze,
    SealedEvaluationState,
    TestSetDisposition,
)
from fura_mappo.prediction.metrics import PointMetricSummary, evaluate_point_forecasts
from fura_mappo.prediction.model_selection import (
    LearnedConfigStatus,
    LearnedModelSelectionResult,
)
from fura_mappo.prediction.models import PredictionSample
from fura_mappo.prediction.selection import BaselineKind, BaselineSelectionResult

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_BASELINE_ORDER = (
    BaselineKind.B0,
    BaselineKind.B1,
    BaselineKind.B2,
    BaselineKind.B3,
    BaselineKind.B4,
    BaselineKind.B5,
)
_TEST_SPLITS = (SplitLabel.TEST_ID, SplitLabel.TEST_OOD)


def _normalize_sha256(value: object, name: str) -> str:
    """验证 exact lowercase SHA-256 identity。"""

    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} 必须是 64 位小写 SHA-256")
    return value


def _materialize_tuple(value: object, name: str) -> tuple[object, ...]:
    """把 finite iterable 防御性物化为 tuple。"""

    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} 必须是有限 iterable")
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} 必须是有限 iterable") from error


def _validate_spent_state_binding(
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
) -> None:
    """在任何 bundle materialization 或 metric computation 前验证 sealed identities。"""

    if not isinstance(state, SealedEvaluationState):
        raise TypeError("state 必须是 SealedEvaluationState")
    if not isinstance(pretest_freeze, PreTestFreeze):
        raise TypeError("pretest_freeze 必须是 PreTestFreeze")
    if state.disposition is not TestSetDisposition.SPENT:
        raise ValueError("official point metrics 要求 already-SPENT state")
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


def _resolve_protocol(
    pretest_freeze: PreTestFreeze,
    protocol_sha256: str,
) -> DatasetProtocolSpec:
    """从 frozen Layer-A protocol inventory 唯一解析 identity。"""

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


def _expected_validation_signature(
    pretest_freeze: PreTestFreeze,
) -> tuple[tuple[str, int, int], ...]:
    """从 Layer-A manifest 派生 canonical validation trace geometry。"""

    signature = tuple(
        sorted(
            (
                (
                    entry.source.trace_id,
                    entry.source.start_step,
                    entry.source.num_steps,
                )
                for entry in pretest_freeze.pretraining_freeze.split_manifest.entries
                if entry.split is SplitLabel.VALIDATION
            ),
            key=lambda item: item[0],
        )
    )
    if not signature:
        raise ValueError("Layer-A manifest 必须包含 VALIDATION trace")
    return signature


def _validate_baseline_selection(
    pretest_freeze: PreTestFreeze,
    baseline_selection: BaselineSelectionResult,
    expected_validation_signature: tuple[tuple[str, int, int], ...],
) -> None:
    """把 validation-locked B0--B5 result 精确重绑定到 Layer-B freeze。"""

    if not isinstance(baseline_selection, BaselineSelectionResult):
        raise TypeError("baseline_selection 必须是 BaselineSelectionResult")
    locked_variants = tuple(baseline_selection.locked_variants)
    if tuple(candidate.baseline for candidate in locked_variants) != _BASELINE_ORDER:
        raise ValueError("baseline selection 必须精确包含 canonical B0--B5")
    if len(locked_variants) != len(pretest_freeze.locked_baselines):
        raise ValueError("baseline selection 与 PreTestFreeze baseline 数量不一致")
    for candidate, identity in zip(
        locked_variants,
        pretest_freeze.locked_baselines,
        strict=True,
    ):
        if candidate.baseline is not identity.baseline:
            raise ValueError("baseline selection kind 与 locked identity 不一致")
        if candidate.protocol.sha256 != identity.protocol_sha256:
            raise ValueError("baseline selection protocol SHA 与 locked identity 不一致")
        resolved_protocol = _resolve_protocol(pretest_freeze, identity.protocol_sha256)
        if candidate.protocol != resolved_protocol:
            raise ValueError("baseline selection protocol 未精确重绑定 frozen protocol")
        if candidate.alpha != identity.alpha:
            raise ValueError("baseline selection alpha 与 locked identity 不一致")
        if candidate.baseline is BaselineKind.B3:
            if candidate.alpha is None or identity.alpha is None:
                raise ValueError("B3 必须保留 frozen alpha")
        elif candidate.alpha is not None or identity.alpha is not None:
            raise ValueError("非 B3 baseline alpha 必须为 None")
    if baseline_selection.selected_kind is not pretest_freeze.selected_baseline:
        raise ValueError("validation-selected B* 与 PreTestFreeze 不一致")
    if baseline_selection.validation_trace_signature != expected_validation_signature:
        raise ValueError("baseline validation trace signature 与 Layer-A manifest 不一致")
    if baseline_selection.prediction_horizon != pretest_freeze.prediction_horizon:
        raise ValueError("baseline selection prediction_horizon 与 PreTestFreeze 不一致")
    if baseline_selection.num_zones != pretest_freeze.num_zones:
        raise ValueError("baseline selection num_zones 与 PreTestFreeze 不一致")
    if baseline_selection.zone_schema_sha256 != pretest_freeze.zone_schema_sha256:
        raise ValueError("baseline selection zone schema 与 PreTestFreeze 不一致")


def _validate_learned_selection(
    pretest_freeze: PreTestFreeze,
    learned_selection: LearnedModelSelectionResult,
    expected_validation_signature: tuple[tuple[str, int, int], ...],
) -> None:
    """把 selected learned config、fixed seeds 与 checkpoints 重绑定到 Layer-B。"""

    if not isinstance(learned_selection, LearnedModelSelectionResult):
        raise TypeError("learned_selection 必须是 LearnedModelSelectionResult")
    selected = learned_selection.selected
    if selected.status is not LearnedConfigStatus.VALID:
        raise ValueError("selected learned config 必须为 VALID")
    frozen = pretest_freeze.selected_learned_config_identity
    for actual, expected, name in (
        (selected.config_sha256, frozen.config_sha256, "config_sha256"),
        (selected.protocol.sha256, frozen.protocol_sha256, "protocol_sha256"),
        (selected.objective, frozen.objective, "objective"),
        (selected.transform, frozen.transform, "transform"),
        (selected.model_complexity_key, frozen.model_complexity_key, "model_complexity_key"),
        (selected.canonical_order, frozen.canonical_order, "canonical_order"),
    ):
        if actual != expected:
            raise ValueError(f"selected learned {name} 与 PreTestFreeze 不一致")
    resolved_protocol = _resolve_protocol(pretest_freeze, frozen.protocol_sha256)
    if selected.protocol != resolved_protocol:
        raise ValueError("selected learned protocol 未精确重绑定 frozen protocol")

    expected_seeds = pretest_freeze.pretraining_freeze.fixed_training_seeds
    if learned_selection.fixed_training_seeds != expected_seeds:
        raise ValueError("learned selection fixed training seeds 与 Layer-A 不一致")
    if learned_selection.validation_trace_signature != expected_validation_signature:
        raise ValueError("learned validation trace signature 与 Layer-A manifest 不一致")
    if learned_selection.prediction_horizon != pretest_freeze.prediction_horizon:
        raise ValueError("learned selection prediction_horizon 与 PreTestFreeze 不一致")
    if learned_selection.num_zones != pretest_freeze.num_zones:
        raise ValueError("learned selection num_zones 与 PreTestFreeze 不一致")
    if learned_selection.zone_schema_sha256 != pretest_freeze.zone_schema_sha256:
        raise ValueError("learned selection zone schema 与 PreTestFreeze 不一致")

    seed_results = tuple(selected.seed_results)
    actual_seeds = tuple(result.training_seed for result in seed_results)
    if actual_seeds != expected_seeds:
        raise ValueError("selected learned seed results 未精确覆盖 fixed seeds")
    locked_by_seed = {
        identity.training_seed: identity for identity in pretest_freeze.learned_predictor_identities
    }
    if set(locked_by_seed) != set(expected_seeds) or len(locked_by_seed) != len(expected_seeds):
        raise ValueError("PreTestFreeze learned predictor seed inventory 不一致")
    for result in seed_results:
        if not result.is_successful:
            raise ValueError("selected learned config 的全部 seeds 必须 successful")
        if result.checkpoint_sha256 is None:
            raise ValueError("successful learned seed 必须保留 checkpoint SHA")
        locked = locked_by_seed[result.training_seed]
        if result.checkpoint_sha256 != locked.checkpoint_sha256:
            raise ValueError("learned selection checkpoint 与 locked predictor 不一致")


def _materialize_baseline_bundles(
    value: object,
    name: str,
) -> tuple[OfficialPredictorSplitForecasts, ...]:
    """验证 exact B0--B5 coverage 并返回 canonical order。"""

    bundles = _materialize_tuple(value, name)
    if any(not isinstance(bundle, OfficialPredictorSplitForecasts) for bundle in bundles):
        raise TypeError(f"{name} 必须全部是 OfficialPredictorSplitForecasts")
    if len(bundles) != len(_BASELINE_ORDER):
        raise ValueError(f"{name} 必须精确包含 6 个 baseline bundles")
    baselines = tuple(bundle.baseline for bundle in bundles)
    if any(baseline is None for baseline in baselines):
        raise ValueError(f"{name} 不得包含 learned bundle")
    if any(bundle.training_seed is not None for bundle in bundles):
        raise ValueError(f"{name} baseline bundle 的 training_seed 必须为 None")
    if len(baselines) != len(set(baselines)):
        raise ValueError(f"{name} 不得重复 baseline identity")
    if set(baselines) != set(_BASELINE_ORDER):
        raise ValueError(f"{name} 必须精确覆盖 B0--B5")
    by_baseline = {bundle.baseline: bundle for bundle in bundles}
    return tuple(by_baseline[baseline] for baseline in _BASELINE_ORDER)


def _materialize_learned_bundles(
    value: object,
    name: str,
    expected_seeds: tuple[int, ...],
) -> tuple[OfficialPredictorSplitForecasts, ...]:
    """验证 exact fixed-seed coverage 并返回 ascending seed order。"""

    bundles = _materialize_tuple(value, name)
    if any(not isinstance(bundle, OfficialPredictorSplitForecasts) for bundle in bundles):
        raise TypeError(f"{name} 必须全部是 OfficialPredictorSplitForecasts")
    if any(bundle.baseline is not None for bundle in bundles):
        raise ValueError(f"{name} 不得包含 baseline bundle")
    seeds = tuple(bundle.training_seed for bundle in bundles)
    if any(seed is None for seed in seeds):
        raise ValueError(f"{name} learned bundle 必须提供 training_seed")
    if len(seeds) != len(set(seeds)):
        raise ValueError(f"{name} 不得重复 training_seed")
    if set(seeds) != set(expected_seeds) or len(seeds) != len(expected_seeds):
        raise ValueError(f"{name} 必须精确覆盖 frozen training seeds")
    by_seed = {bundle.training_seed: bundle for bundle in bundles}
    return tuple(by_seed[seed] for seed in expected_seeds)


def _expected_sources_for_split(
    pretest_freeze: PreTestFreeze,
    split: SplitLabel,
    trace_ids: tuple[str, ...],
) -> dict[str, PredictionSource]:
    """返回 requested split 的 exact Layer-A source geometry。"""

    sources = {
        entry.source.trace_id: entry.source
        for entry in pretest_freeze.pretraining_freeze.split_manifest.entries
        if entry.split is split
    }
    if set(sources) != set(trace_ids) or len(sources) != len(trace_ids):
        raise ValueError("frozen test trace inventory 与 Layer-A manifest 不一致")
    return sources


def _materialize_verified_artifacts(
    value: object,
    name: str,
    trace_ids: tuple[str, ...],
    expected_sources: dict[str, PredictionSource],
) -> tuple[VerifiedPredictionArtifact, ...]:
    """验证 split artifact exact coverage 并重绑定 authoritative source。"""

    artifacts = _materialize_tuple(value, name)
    if any(not isinstance(artifact, VerifiedPredictionArtifact) for artifact in artifacts):
        raise TypeError(f"{name} 必须全部是 VerifiedPredictionArtifact")
    actual_trace_ids = tuple(artifact.source.trace_id for artifact in artifacts)
    if len(actual_trace_ids) != len(set(actual_trace_ids)):
        raise ValueError(f"{name} 不得重复 trace_id")
    if set(actual_trace_ids) != set(trace_ids) or len(actual_trace_ids) != len(trace_ids):
        raise ValueError(f"{name} 必须精确覆盖 frozen split trace IDs")
    by_trace_id = {artifact.source.trace_id: artifact for artifact in artifacts}
    canonical = tuple(by_trace_id[trace_id] for trace_id in trace_ids)
    for trace_id, artifact in zip(trace_ids, canonical, strict=True):
        validate_prediction_source_for_artifact(artifact, expected_sources[trace_id])
    return canonical


def _build_authoritative_sample_cache(
    pretest_freeze: PreTestFreeze,
    test_id_artifacts: tuple[VerifiedPredictionArtifact, ...],
    test_ood_artifacts: tuple[VerifiedPredictionArtifact, ...],
) -> dict[tuple[SplitLabel, str, str], tuple[PredictionSample, ...]]:
    """按 split/protocol/trace 派生一次 authoritative samples。"""

    protocol_sha256s = tuple(
        dict.fromkeys(
            (
                *(identity.protocol_sha256 for identity in pretest_freeze.locked_baselines),
                pretest_freeze.selected_learned_config_identity.protocol_sha256,
            )
        )
    )
    cache: dict[tuple[SplitLabel, str, str], tuple[PredictionSample, ...]] = {}
    for split, artifacts in (
        (SplitLabel.TEST_ID, test_id_artifacts),
        (SplitLabel.TEST_OOD, test_ood_artifacts),
    ):
        for protocol_sha256 in protocol_sha256s:
            protocol = _resolve_protocol(pretest_freeze, protocol_sha256)
            for artifact in artifacts:
                trace_id = artifact.source.trace_id
                cache[(split, protocol_sha256, trace_id)] = derive_prediction_samples_from_artifact(
                    artifact, protocol
                )
    return cache


def _validate_authoritative_sample(
    actual: PredictionSample,
    expected: PredictionSample,
) -> None:
    """逐 scalar/array 证明 caller sample 等于 authoritative derived sample。"""

    if actual.sample_id != expected.sample_id:
        raise ValueError("forecast record sample_id 非 authoritative identity")
    actual_context = actual.context
    expected_context = expected.context
    if (
        actual_context.absolute_step != expected_context.absolute_step
        or actual_context.steps_remaining != expected_context.steps_remaining
        or actual_context.zone_schema_sha256 != expected_context.zone_schema_sha256
        or actual_context.prediction_horizon != expected_context.prediction_horizon
        or not np.array_equal(actual_context.history_counts, expected_context.history_counts)
        or not np.array_equal(actual_context.history_mask, expected_context.history_mask)
    ):
        raise ValueError("forecast record context 非 authoritative derived context")
    if not np.array_equal(actual.target.counts, expected.target.counts) or not np.array_equal(
        actual.target.valid_mask,
        expected.target.valid_mask,
    ):
        raise ValueError("forecast record target 非 authoritative derived target")


def _validate_complete_record_inventory(
    forecasts: OfficialPredictorSplitForecasts,
    expected_sources: dict[str, PredictionSource],
    authoritative_samples_by_trace: dict[str, tuple[PredictionSample, ...]],
) -> dict[str, tuple[int, int]]:
    """在 numerical phase 前验证每条 frozen trace 的完整 anchors 与 geometry。"""

    records_by_trace: dict[str, list[OfficialPointForecastRecord]] = {
        trace_id: [] for trace_id in forecasts.trace_ids
    }
    for record in forecasts.records:
        if not isinstance(record, OfficialPointForecastRecord):
            raise TypeError("forecast bundle records 类型错误")
        point_record = record.point_record
        if point_record.trace_id not in records_by_trace:
            raise ValueError("forecast record trace_id 不属于 frozen split")
        if record.provenance.sample_id != point_record.sample.sample_id:
            raise ValueError("forecast record sample provenance 不一致")
        if record.provenance.normalization_sha256 is not None:
            raise ValueError("official point forecast normalization_sha256 必须为 None")
        if record.provenance.inference_rng_id is not None:
            raise ValueError("official point forecast inference_rng_id 必须为 None")
        if record.provenance.predictor_artifact_sha256 != forecasts.predictor_artifact_sha256:
            raise ValueError("forecast record predictor SHA 与 bundle 不一致")
        if record.provenance.prediction_config_sha256 != forecasts.prediction_config_sha256:
            raise ValueError("forecast record prediction config 与 bundle 不一致")
        if record.provenance.dataset_protocol_sha256 != forecasts.protocol_sha256:
            raise ValueError("forecast record protocol 与 bundle 不一致")
        if record.provenance.split_manifest_sha256 != forecasts.split_manifest_sha256:
            raise ValueError("forecast record manifest 与 bundle 不一致")
        if record.provenance.execution_git_commit != forecasts.execution_git_commit:
            raise ValueError("forecast record Git commit 与 bundle 不一致")
        context = point_record.sample.context
        if context.prediction_horizon != forecasts.prediction_horizon:
            raise ValueError("forecast record prediction_horizon 与 bundle 不一致")
        if context.num_zones != forecasts.num_zones:
            raise ValueError("forecast record num_zones 与 bundle 不一致")
        if context.zone_schema_sha256 != forecasts.zone_schema_sha256:
            raise ValueError("forecast record zone schema 与 bundle 不一致")
        forecast = point_record.forecast
        if (
            forecast.variance is not None
            or forecast.quantile_levels is not None
            or forecast.quantiles is not None
            or forecast.scenarios is not None
        ):
            raise ValueError("official point forecast 不得包含 probabilistic surface")
        records_by_trace[point_record.trace_id].append(record)

    geometry_by_trace: dict[str, tuple[int, int]] = {}
    for trace_id in forecasts.trace_ids:
        records = records_by_trace[trace_id]
        if not records:
            raise ValueError("每条 frozen trace 必须包含完整 supervised records")
        source = expected_sources[trace_id]
        authoritative_samples = authoritative_samples_by_trace[trace_id]
        if source.num_steps < forecasts.prediction_horizon + 1:
            raise ValueError("official Primary metric trace 必须满足 num_steps >= P + 1")
        geometries = {
            (
                record.point_record.trace_start_step,
                record.point_record.trace_num_steps,
            )
            for record in records
        }
        expected_geometry = (source.start_step, source.num_steps)
        if geometries != {expected_geometry}:
            raise ValueError("forecast record geometry 与 frozen source 不一致")
        anchors = tuple(record.point_record.sample.context.absolute_step for record in records)
        expected_anchors = tuple(range(source.start_step, source.start_step + source.num_steps - 1))
        if len(anchors) != len(set(anchors)) or tuple(sorted(anchors)) != expected_anchors:
            raise ValueError("forecast records 必须完整且唯一覆盖 frozen supervised anchors")
        actual_sample_ids = tuple(record.point_record.sample.sample_id for record in records)
        expected_sample_ids = tuple(sample.sample_id for sample in authoritative_samples)
        if actual_sample_ids != expected_sample_ids:
            raise ValueError("forecast records 必须精确覆盖 authoritative sample IDs")
        for record, authoritative_sample in zip(records, authoritative_samples, strict=True):
            _validate_authoritative_sample(record.point_record.sample, authoritative_sample)
        geometry_by_trace[trace_id] = expected_geometry
    return geometry_by_trace


def _validate_common_bundle_identity(
    *,
    bundle: OfficialPredictorSplitForecasts,
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
    split: SplitLabel,
    authoritative_sample_cache: dict[tuple[SplitLabel, str, str], tuple[PredictionSample, ...]],
) -> None:
    """防御性重绑定一个 direct-constructible Slice 14 bundle。"""

    if bundle.split is not split:
        raise ValueError("forecast bundle split 与 requested split 不一致")
    expected_trace_ids = (
        pretest_freeze.test_id_trace_ids
        if split is SplitLabel.TEST_ID
        else pretest_freeze.test_ood_trace_ids
    )
    if bundle.sealed_evaluation_state_sha256 != state.sha256:
        raise ValueError("forecast bundle sealed state SHA 不一致")
    if bundle.pretraining_freeze_sha256 != state.pretraining_freeze_sha256:
        raise ValueError("forecast bundle Layer-A SHA 不一致")
    if bundle.pretest_freeze_sha256 != pretest_freeze.sha256:
        raise ValueError("forecast bundle PreTestFreeze SHA 不一致")
    if bundle.trace_ids != expected_trace_ids:
        raise ValueError("forecast bundle frozen trace tuple 不一致")
    if bundle.prediction_horizon != pretest_freeze.prediction_horizon:
        raise ValueError("forecast bundle prediction_horizon 不一致")
    if bundle.num_zones != pretest_freeze.num_zones:
        raise ValueError("forecast bundle num_zones 不一致")
    if bundle.zone_schema_sha256 != pretest_freeze.zone_schema_sha256:
        raise ValueError("forecast bundle zone schema 不一致")
    if bundle.split_manifest_sha256 != pretest_freeze.pretraining_freeze.split_manifest.sha256:
        raise ValueError("forecast bundle split manifest SHA 不一致")
    if bundle.execution_git_commit != pretest_freeze.git_commit_sha:
        raise ValueError("forecast bundle execution Git commit 不一致")
    expected_sources = _expected_sources_for_split(pretest_freeze, split, expected_trace_ids)
    authoritative_samples_by_trace = {
        trace_id: authoritative_sample_cache[(split, bundle.protocol_sha256, trace_id)]
        for trace_id in expected_trace_ids
    }
    _validate_complete_record_inventory(
        bundle,
        expected_sources,
        authoritative_samples_by_trace,
    )


def _validate_baseline_bundle_identity(
    *,
    bundle: OfficialPredictorSplitForecasts,
    expected_baseline: BaselineKind,
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
    split: SplitLabel,
    authoritative_sample_cache: dict[tuple[SplitLabel, str, str], tuple[PredictionSample, ...]],
) -> None:
    """精确重绑定一个 split/baseline bundle。"""

    if bundle.baseline is not expected_baseline or bundle.training_seed is not None:
        raise ValueError("baseline bundle predictor kind 不一致")
    identity = next(
        item for item in pretest_freeze.locked_baselines if item.baseline is expected_baseline
    )
    if bundle.predictor_artifact_sha256 != identity.predictor_sha256:
        raise ValueError("baseline bundle predictor artifact SHA 不一致")
    if bundle.protocol_sha256 != identity.protocol_sha256:
        raise ValueError("baseline bundle protocol SHA 不一致")
    if bundle.prediction_config_sha256 != pretest_freeze.pretraining_freeze.baseline_plan_sha256:
        raise ValueError("baseline bundle prediction config SHA 不一致")
    _validate_common_bundle_identity(
        bundle=bundle,
        state=state,
        pretest_freeze=pretest_freeze,
        split=split,
        authoritative_sample_cache=authoritative_sample_cache,
    )


def _validate_learned_bundle_identity(
    *,
    bundle: OfficialPredictorSplitForecasts,
    expected_seed: int,
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
    split: SplitLabel,
    authoritative_sample_cache: dict[tuple[SplitLabel, str, str], tuple[PredictionSample, ...]],
) -> None:
    """精确重绑定一个 split/fixed-seed learned bundle。"""

    if bundle.baseline is not None or bundle.training_seed != expected_seed:
        raise ValueError("learned bundle predictor kind/seed 不一致")
    identity = next(
        item
        for item in pretest_freeze.learned_predictor_identities
        if item.training_seed == expected_seed
    )
    selected = pretest_freeze.selected_learned_config_identity
    if bundle.predictor_artifact_sha256 != identity.predictor_sha256:
        raise ValueError("learned bundle predictor artifact SHA 不一致")
    if bundle.prediction_config_sha256 != selected.config_sha256:
        raise ValueError("learned bundle prediction config SHA 不一致")
    if bundle.protocol_sha256 != selected.protocol_sha256:
        raise ValueError("learned bundle protocol SHA 不一致")
    _validate_common_bundle_identity(
        bundle=bundle,
        state=state,
        pretest_freeze=pretest_freeze,
        split=split,
        authoritative_sample_cache=authoritative_sample_cache,
    )


def _validate_same_predictors_across_splits(
    test_id_bundles: tuple[OfficialPredictorSplitForecasts, ...],
    test_ood_bundles: tuple[OfficialPredictorSplitForecasts, ...],
    identity_name: str,
) -> None:
    """证明 ID/OOD 仅 split payload 不同，predictor locks 完全相同。"""

    if len(test_id_bundles) != len(test_ood_bundles):
        raise ValueError(f"{identity_name} ID/OOD bundle 数量不一致")
    fields = (
        "baseline",
        "training_seed",
        "predictor_artifact_sha256",
        "prediction_config_sha256",
        "protocol_sha256",
        "pretest_freeze_sha256",
    )
    for test_id, test_ood in zip(test_id_bundles, test_ood_bundles, strict=True):
        if any(getattr(test_id, name) != getattr(test_ood, name) for name in fields):
            raise ValueError(f"{identity_name} ID/OOD 必须使用同一 locked predictor")


@dataclass(frozen=True, slots=True)
class OfficialPredictorSplitMetrics:
    """一个 authoritative split forecast bundle 的 frozen point-metric result。"""

    forecasts: OfficialPredictorSplitForecasts
    metrics: PointMetricSummary

    def __post_init__(self) -> None:
        """验证 P/Z/schema、trace inventory 与 trace geometry 精确一致。"""

        if not isinstance(self.forecasts, OfficialPredictorSplitForecasts):
            raise TypeError("forecasts 必须是 OfficialPredictorSplitForecasts")
        if not isinstance(self.metrics, PointMetricSummary):
            raise TypeError("metrics 必须是 PointMetricSummary")
        if self.metrics.prediction_horizon != self.forecasts.prediction_horizon:
            raise ValueError("metrics/forecasts prediction_horizon 不一致")
        if self.metrics.num_zones != self.forecasts.num_zones:
            raise ValueError("metrics/forecasts num_zones 不一致")
        if self.metrics.zone_schema_sha256 != self.forecasts.zone_schema_sha256:
            raise ValueError("metrics/forecasts zone schema 不一致")
        metric_by_trace = {metric.trace_id: metric for metric in self.metrics.trace_metrics}
        if set(metric_by_trace) != set(self.forecasts.trace_ids):
            raise ValueError("metric traces 必须精确覆盖 frozen forecast trace IDs")

        records_by_trace: dict[str, list[OfficialPointForecastRecord]] = {
            trace_id: [] for trace_id in self.forecasts.trace_ids
        }
        for record in self.forecasts.records:
            records_by_trace[record.point_record.trace_id].append(record)
        for trace_id in self.forecasts.trace_ids:
            records = records_by_trace[trace_id]
            if not records:
                raise ValueError("frozen trace 不得缺少 metric source records")
            geometries = {
                (
                    record.point_record.trace_start_step,
                    record.point_record.trace_num_steps,
                )
                for record in records
            }
            if len(geometries) != 1:
                raise ValueError("同一 frozen trace 的 forecast geometry 必须唯一")
            expected_start, expected_num_steps = next(iter(geometries))
            trace_metric = metric_by_trace[trace_id]
            if (
                trace_metric.trace_start_step != expected_start
                or trace_metric.trace_num_steps != expected_num_steps
            ):
                raise ValueError("metric trace geometry 与 forecast records 不一致")


def _evaluate_official_predictor_split_metrics(
    forecasts: OfficialPredictorSplitForecasts,
) -> OfficialPredictorSplitMetrics:
    """通过唯一 accepted point-metric path 评估一个已完整验证的 bundle。"""

    if not forecasts.point_records:
        raise ValueError("official metric bundle 不得为空")
    metrics = evaluate_point_forecasts(forecasts.point_records)
    return OfficialPredictorSplitMetrics(forecasts=forecasts, metrics=metrics)


@dataclass(frozen=True, slots=True)
class OfficialSealedPointMetrics:
    """完整 sealed TEST_ID/TEST_OOD point-metric 输入层，不表示最终 scientific success。

    本对象保留 overall、horizon、zone、trace、MAE、bias 与 per-seed summaries，但不声称完成
    target-zero/nonzero、condition、near-OOD 或 structural-OOD aggregation；这些 subgroup
    公式尚未在本 Slice 冻结。
    """

    sealed_evaluation_state_sha256: str
    pretraining_freeze_sha256: str
    pretest_freeze_sha256: str
    baseline_selection: BaselineSelectionResult
    learned_selection: LearnedModelSelectionResult
    test_id_baselines: tuple[OfficialPredictorSplitMetrics, ...]
    test_id_learned: tuple[OfficialPredictorSplitMetrics, ...]
    test_ood_baselines: tuple[OfficialPredictorSplitMetrics, ...]
    test_ood_learned: tuple[OfficialPredictorSplitMetrics, ...]

    def __post_init__(self) -> None:
        """验证四组 canonical completeness 与 sealed identity snapshot。"""

        sealed_sha = _normalize_sha256(
            self.sealed_evaluation_state_sha256,
            "sealed_evaluation_state_sha256",
        )
        layer_a_sha = _normalize_sha256(
            self.pretraining_freeze_sha256,
            "pretraining_freeze_sha256",
        )
        pretest_sha = _normalize_sha256(self.pretest_freeze_sha256, "pretest_freeze_sha256")
        if not isinstance(self.baseline_selection, BaselineSelectionResult):
            raise TypeError("baseline_selection 必须是 BaselineSelectionResult")
        if not isinstance(self.learned_selection, LearnedModelSelectionResult):
            raise TypeError("learned_selection 必须是 LearnedModelSelectionResult")

        group_values = (
            (self.test_id_baselines, "test_id_baselines"),
            (self.test_id_learned, "test_id_learned"),
            (self.test_ood_baselines, "test_ood_baselines"),
            (self.test_ood_learned, "test_ood_learned"),
        )
        normalized_groups: list[tuple[OfficialPredictorSplitMetrics, ...]] = []
        for value, name in group_values:
            group = _materialize_tuple(value, name)
            if any(not isinstance(item, OfficialPredictorSplitMetrics) for item in group):
                raise TypeError(f"{name} 必须全部是 OfficialPredictorSplitMetrics")
            normalized_groups.append(group)  # type: ignore[arg-type]
        id_baselines, id_learned, ood_baselines, ood_learned = normalized_groups

        for group, split in (
            (id_baselines, SplitLabel.TEST_ID),
            (id_learned, SplitLabel.TEST_ID),
            (ood_baselines, SplitLabel.TEST_OOD),
            (ood_learned, SplitLabel.TEST_OOD),
        ):
            if any(item.forecasts.split is not split for item in group):
                raise ValueError("metric group split 不一致")
            for item in group:
                forecasts = item.forecasts
                if forecasts.sealed_evaluation_state_sha256 != sealed_sha:
                    raise ValueError("metric group sealed state SHA 不一致")
                if forecasts.pretraining_freeze_sha256 != layer_a_sha:
                    raise ValueError("metric group Layer-A SHA 不一致")
                if forecasts.pretest_freeze_sha256 != pretest_sha:
                    raise ValueError("metric group PreTestFreeze SHA 不一致")

        if tuple(item.forecasts.baseline for item in id_baselines) != _BASELINE_ORDER:
            raise ValueError("TEST_ID baseline metrics 必须按 B0--B5 canonical order")
        if tuple(item.forecasts.baseline for item in ood_baselines) != _BASELINE_ORDER:
            raise ValueError("TEST_OOD baseline metrics 必须按 B0--B5 canonical order")
        expected_seeds = self.learned_selection.fixed_training_seeds
        if tuple(item.forecasts.training_seed for item in id_learned) != expected_seeds:
            raise ValueError("TEST_ID learned metrics 必须按 frozen seed order")
        if tuple(item.forecasts.training_seed for item in ood_learned) != expected_seeds:
            raise ValueError("TEST_OOD learned metrics 必须按 frozen seed order")
        if len(id_baselines) != 6 or len(ood_baselines) != 6:
            raise ValueError("sealed metrics 必须保留每个 split 的全部六个 baselines")

        object.__setattr__(self, "sealed_evaluation_state_sha256", sealed_sha)
        object.__setattr__(self, "pretraining_freeze_sha256", layer_a_sha)
        object.__setattr__(self, "pretest_freeze_sha256", pretest_sha)
        object.__setattr__(self, "test_id_baselines", id_baselines)
        object.__setattr__(self, "test_id_learned", id_learned)
        object.__setattr__(self, "test_ood_baselines", ood_baselines)
        object.__setattr__(self, "test_ood_learned", ood_learned)

    @property
    def selected_baseline_test_id(self) -> OfficialPredictorSplitMetrics:
        """按 validation-locked B* identity 定位 TEST_ID metrics，不读取 test ranking。"""

        return next(
            item
            for item in self.test_id_baselines
            if item.forecasts.baseline is self.baseline_selection.selected_kind
        )


def evaluate_official_sealed_point_metrics(
    *,
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
    baseline_selection: BaselineSelectionResult,
    learned_selection: LearnedModelSelectionResult,
    test_id_artifacts: Iterable[VerifiedPredictionArtifact],
    test_ood_artifacts: Iterable[VerifiedPredictionArtifact],
    test_id_baselines: Iterable[OfficialPredictorSplitForecasts],
    test_id_learned: Iterable[OfficialPredictorSplitForecasts],
    test_ood_baselines: Iterable[OfficialPredictorSplitForecasts],
    test_ood_learned: Iterable[OfficialPredictorSplitForecasts],
) -> OfficialSealedPointMetrics:
    """验证完整 sealed inventory 后统一计算 frozen point metrics。

    任何 real official failure 必须由 future orchestration 记录为
    ``PREDICTION_EVALUATION_FAILURE``，不得继续 smaller-n evaluation。本函数不构造 final
    scientific success，也不发明尚未冻结的 mandatory subgroup aggregation。
    """

    _validate_spent_state_binding(state, pretest_freeze)
    validation_signature = _expected_validation_signature(pretest_freeze)
    _validate_baseline_selection(
        pretest_freeze,
        baseline_selection,
        validation_signature,
    )
    _validate_learned_selection(
        pretest_freeze,
        learned_selection,
        validation_signature,
    )

    id_trace_ids = pretest_freeze.test_id_trace_ids
    ood_trace_ids = pretest_freeze.test_ood_trace_ids
    id_sources = _expected_sources_for_split(
        pretest_freeze,
        SplitLabel.TEST_ID,
        id_trace_ids,
    )
    ood_sources = _expected_sources_for_split(
        pretest_freeze,
        SplitLabel.TEST_OOD,
        ood_trace_ids,
    )
    id_artifacts = _materialize_verified_artifacts(
        test_id_artifacts,
        "test_id_artifacts",
        id_trace_ids,
        id_sources,
    )
    ood_artifacts = _materialize_verified_artifacts(
        test_ood_artifacts,
        "test_ood_artifacts",
        ood_trace_ids,
        ood_sources,
    )
    authoritative_sample_cache = _build_authoritative_sample_cache(
        pretest_freeze,
        id_artifacts,
        ood_artifacts,
    )

    expected_seeds = pretest_freeze.pretraining_freeze.fixed_training_seeds
    id_baselines = _materialize_baseline_bundles(
        test_id_baselines,
        "test_id_baselines",
    )
    id_learned = _materialize_learned_bundles(
        test_id_learned,
        "test_id_learned",
        expected_seeds,
    )
    ood_baselines = _materialize_baseline_bundles(
        test_ood_baselines,
        "test_ood_baselines",
    )
    ood_learned = _materialize_learned_bundles(
        test_ood_learned,
        "test_ood_learned",
        expected_seeds,
    )

    for split, baseline_bundles, learned_bundles in (
        (SplitLabel.TEST_ID, id_baselines, id_learned),
        (SplitLabel.TEST_OOD, ood_baselines, ood_learned),
    ):
        for baseline, bundle in zip(_BASELINE_ORDER, baseline_bundles, strict=True):
            _validate_baseline_bundle_identity(
                bundle=bundle,
                expected_baseline=baseline,
                state=state,
                pretest_freeze=pretest_freeze,
                split=split,
                authoritative_sample_cache=authoritative_sample_cache,
            )
        for seed, bundle in zip(expected_seeds, learned_bundles, strict=True):
            _validate_learned_bundle_identity(
                bundle=bundle,
                expected_seed=seed,
                state=state,
                pretest_freeze=pretest_freeze,
                split=split,
                authoritative_sample_cache=authoritative_sample_cache,
            )

    _validate_same_predictors_across_splits(id_baselines, ood_baselines, "baseline")
    _validate_same_predictors_across_splits(id_learned, ood_learned, "learned")

    id_baseline_metrics = tuple(
        _evaluate_official_predictor_split_metrics(bundle) for bundle in id_baselines
    )
    id_learned_metrics = tuple(
        _evaluate_official_predictor_split_metrics(bundle) for bundle in id_learned
    )
    ood_baseline_metrics = tuple(
        _evaluate_official_predictor_split_metrics(bundle) for bundle in ood_baselines
    )
    ood_learned_metrics = tuple(
        _evaluate_official_predictor_split_metrics(bundle) for bundle in ood_learned
    )

    return OfficialSealedPointMetrics(
        sealed_evaluation_state_sha256=state.sha256,
        pretraining_freeze_sha256=state.pretraining_freeze_sha256,
        pretest_freeze_sha256=pretest_freeze.sha256,
        baseline_selection=baseline_selection,
        learned_selection=learned_selection,
        test_id_baselines=id_baseline_metrics,
        test_id_learned=id_learned_metrics,
        test_ood_baselines=ood_baseline_metrics,
        test_ood_learned=ood_learned_metrics,
    )


__all__ = [
    "OfficialPredictorSplitMetrics",
    "OfficialSealedPointMetrics",
    "evaluate_official_sealed_point_metrics",
]
