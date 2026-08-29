"""WP-03B final sealed official-evaluation orchestration trust root。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import InitVar, dataclass

from fura_mappo.prediction.bootstrap import (
    PairedTraceBootstrapResult,
    bootstrap_locked_test_delta_rmse,
)
from fura_mappo.prediction.breakdowns import (
    OfficialSealedMandatoryBreakdowns,
    compute_official_mandatory_breakdowns,
)
from fura_mappo.prediction.comparison import (
    LockedTestPointEstimate,
    TrainingSeedTestResult,
    compute_locked_test_point_estimate,
)
from fura_mappo.prediction.dataset import SplitLabel, VerifiedPredictionArtifact
from fura_mappo.prediction.evaluation import (
    OfficialPredictorSplitForecasts,
    bind_official_baseline_split_forecasts,
    bind_official_learned_split_forecasts,
)
from fura_mappo.prediction.governance import (
    OfficialTestExecutionKind,
    PredictionEvaluationFailure,
    PreTestFreeze,
    SealedEvaluationState,
    TestSetDisposition,
    record_prediction_evaluation_failure,
)
from fura_mappo.prediction.interpretation import (
    PrimaryIDInterpretation,
    PrimaryIDLabel,
    interpret_primary_id_bootstrap,
)
from fura_mappo.prediction.model_selection import LearnedModelSelectionResult
from fura_mappo.prediction.models import ForecastRecord
from fura_mappo.prediction.official_metrics import (
    OfficialSealedPointMetrics,
    evaluate_official_sealed_point_metrics,
)
from fura_mappo.prediction.selection import BaselineKind, BaselineSelectionResult

_BASELINE_ORDER = tuple(BaselineKind)
_OFFICIAL_RESULT_TOKEN = object()


def _validate_spent_admission(
    state: object,
    pretest_freeze: object,
) -> tuple[SealedEvaluationState, PreTestFreeze]:
    """在读取任何 raw inventory 前验证 already-SPENT exact Layer-B admission。"""

    if not isinstance(state, SealedEvaluationState):
        raise TypeError("state 必须是 SealedEvaluationState")
    if not isinstance(pretest_freeze, PreTestFreeze):
        raise TypeError("pretest_freeze 必须是 PreTestFreeze")
    if state.disposition is not TestSetDisposition.SPENT:
        raise ValueError("final official evaluation 要求 already-SPENT state")
    if state.first_official_test_execution is None:
        raise ValueError("SPENT state 必须保留 first official execution")
    if pretest_freeze.sha256 not in state.registered_pretest_freeze_sha256s:
        raise ValueError("pretest_freeze 必须属于 registered Layer-B freezes")
    if pretest_freeze.pretraining_freeze_sha256 != state.pretraining_freeze_sha256:
        raise ValueError("pretest_freeze Layer-A SHA 与 sealed state 不一致")
    if pretest_freeze.test_id_trace_ids != state.test_id_trace_ids:
        raise ValueError("pretest_freeze TEST_ID identities 与 sealed state 不一致")
    if pretest_freeze.test_ood_trace_ids != state.test_ood_trace_ids:
        raise ValueError("pretest_freeze TEST_OOD identities 与 sealed state 不一致")
    return state, pretest_freeze


def _validate_breakdown_bindings(
    breakdowns: OfficialSealedMandatoryBreakdowns,
    point_metrics: OfficialSealedPointMetrics,
) -> None:
    """证明 mandatory breakdown 四组逐项绑定 exact upstream metric objects。"""

    if not isinstance(breakdowns, OfficialSealedMandatoryBreakdowns):
        raise TypeError("mandatory_breakdowns 类型错误")
    group_pairs = (
        (breakdowns.test_id_baselines, point_metrics.test_id_baselines),
        (breakdowns.test_id_learned, point_metrics.test_id_learned),
        (breakdowns.test_ood_baselines, point_metrics.test_ood_baselines),
        (breakdowns.test_ood_learned, point_metrics.test_ood_learned),
    )
    for breakdown_group, metric_group in group_pairs:
        if len(breakdown_group) != len(metric_group) or any(
            breakdown.metrics is not metrics
            for breakdown, metrics in zip(breakdown_group, metric_group, strict=True)
        ):
            raise ValueError("mandatory breakdown 未逐项绑定 exact point metrics")


def _canonical_test_id_signature(
    pretest_freeze: PreTestFreeze,
) -> tuple[tuple[str, int, int], ...]:
    """从 Layer-A TEST_ID sources 派生 PointMetricSummary canonical signature。"""

    signature = tuple(
        sorted(
            (
                (
                    entry.source.trace_id,
                    entry.source.start_step,
                    entry.source.num_steps,
                )
                for entry in pretest_freeze.pretraining_freeze.split_manifest.entries
                if entry.split is SplitLabel.TEST_ID
            ),
            key=lambda item: item[0],
        )
    )
    if not signature:
        raise ValueError("Layer-A manifest 必须包含 TEST_ID traces")
    if tuple(item[0] for item in signature) != tuple(sorted(pretest_freeze.test_id_trace_ids)):
        raise ValueError("Layer-A TEST_ID metric signature 与 PreTestFreeze inventory 不一致")
    return signature


def _validate_point_estimate_bindings(
    *,
    pretest_freeze: PreTestFreeze,
    point_metrics: OfficialSealedPointMetrics,
    point_estimate: LockedTestPointEstimate,
) -> None:
    """验证 B*、all-seed metrics、checkpoint 与 Layer-A trace geometry identity。"""

    if not isinstance(point_estimate, LockedTestPointEstimate):
        raise TypeError("point_estimate 类型错误")
    if point_estimate.learned_selection is not point_metrics.learned_selection:
        raise ValueError("point estimate learned selection 未绑定 exact upstream object")
    if point_estimate.baseline_selection is not point_metrics.baseline_selection:
        raise ValueError("point estimate baseline selection 未绑定 exact upstream object")
    if point_estimate.baseline_metrics is not point_metrics.selected_baseline_test_id.metrics:
        raise ValueError("point estimate baseline metrics 不是 validation-locked B* TEST_ID object")

    learned_metrics = point_metrics.test_id_learned
    expected_seeds = pretest_freeze.pretraining_freeze.fixed_training_seeds
    actual_seeds = tuple(result.training_seed for result in point_estimate.learned_seed_results)
    if actual_seeds != expected_seeds or len(learned_metrics) != len(expected_seeds):
        raise ValueError("point estimate 未精确保留 frozen learned seeds")
    checkpoint_by_seed = {
        identity.training_seed: identity.checkpoint_sha256
        for identity in pretest_freeze.learned_predictor_identities
    }
    if set(checkpoint_by_seed) != set(expected_seeds):
        raise ValueError("PreTestFreeze learned checkpoint coverage 不完整")
    for seed_result, metric_result in zip(
        point_estimate.learned_seed_results,
        learned_metrics,
        strict=True,
    ):
        if seed_result.metrics is not metric_result.metrics:
            raise ValueError("point estimate seed metrics 未绑定 exact TEST_ID learned object")
        if seed_result.checkpoint_sha256 != checkpoint_by_seed[seed_result.training_seed]:
            raise ValueError("point estimate seed checkpoint 未绑定 Layer-B identity")
    if point_estimate.test_trace_signature != _canonical_test_id_signature(pretest_freeze):
        raise ValueError("point estimate TEST_ID trace geometry 未精确重绑定 Layer-A manifest")


@dataclass(frozen=True, slots=True, eq=False)
class OfficialPredictionEvaluationResult:
    """完整连续 official orchestration 的 factory-only in-memory success trust root。"""

    state: SealedEvaluationState
    pretest_freeze: PreTestFreeze
    point_metrics: OfficialSealedPointMetrics
    mandatory_breakdowns: OfficialSealedMandatoryBreakdowns
    point_estimate: LockedTestPointEstimate
    bootstrap_result: PairedTraceBootstrapResult
    interpretation: PrimaryIDInterpretation
    _verification_token: InitVar[object] = None

    def __post_init__(self, _verification_token: object) -> None:
        """拒绝直接伪造并防御性重验完整 upstream identity chain。"""

        if _verification_token is not _OFFICIAL_RESULT_TOKEN:
            raise TypeError(
                "OfficialPredictionEvaluationResult 必须由 "
                "finalize_official_prediction_evaluation 构造"
            )
        state, pretest_freeze = _validate_spent_admission(self.state, self.pretest_freeze)
        if not isinstance(self.point_metrics, OfficialSealedPointMetrics):
            raise TypeError("point_metrics 类型错误")
        if self.point_metrics.sealed_evaluation_state_sha256 != state.sha256:
            raise ValueError("point metrics sealed state SHA 不一致")
        if self.point_metrics.pretraining_freeze_sha256 != state.pretraining_freeze_sha256:
            raise ValueError("point metrics Layer-A SHA 不一致")
        if self.point_metrics.pretest_freeze_sha256 != pretest_freeze.sha256:
            raise ValueError("point metrics PreTestFreeze SHA 不一致")
        if (
            self.point_metrics.baseline_selection.selected_kind
            is not pretest_freeze.selected_baseline
        ):
            raise ValueError("point metrics baseline selection 与 Layer-B B* 不一致")
        if self.point_metrics.learned_selection.fixed_training_seeds != (
            pretest_freeze.pretraining_freeze.fixed_training_seeds
        ):
            raise ValueError("point metrics learned seeds 与 Layer-B freeze 不一致")
        _validate_breakdown_bindings(self.mandatory_breakdowns, self.point_metrics)
        _validate_point_estimate_bindings(
            pretest_freeze=pretest_freeze,
            point_metrics=self.point_metrics,
            point_estimate=self.point_estimate,
        )
        if not isinstance(self.bootstrap_result, PairedTraceBootstrapResult):
            raise TypeError("bootstrap_result 类型错误")
        if self.bootstrap_result.point_estimate is not self.point_estimate:
            raise ValueError("bootstrap result 未绑定 exact point estimate")
        if self.bootstrap_result.spec is not pretest_freeze.bootstrap_spec:
            raise ValueError("bootstrap result 未绑定 exact Layer-B bootstrap spec")
        if not isinstance(self.interpretation, PrimaryIDInterpretation):
            raise TypeError("interpretation 类型错误")
        if self.interpretation.bootstrap_result is not self.bootstrap_result:
            raise ValueError("interpretation 未绑定 exact bootstrap result")

    @property
    def label(self) -> PrimaryIDLabel:
        return self.interpretation.label

    @property
    def delta_rmse(self) -> float:
        return self.point_estimate.delta_rmse

    @property
    def ci_lower(self) -> float:
        return self.bootstrap_result.ci_lower

    @property
    def ci_upper(self) -> float:
        return self.bootstrap_result.ci_upper

    @property
    def test_algorithm_mse(self) -> float:
        return self.point_estimate.test_algorithm_mse

    @property
    def test_algorithm_rmse(self) -> float:
        return self.point_estimate.test_algorithm_rmse

    @property
    def baseline_mse(self) -> float:
        return self.point_estimate.baseline_mse

    @property
    def baseline_rmse(self) -> float:
        return self.point_estimate.baseline_rmse

    @property
    def selected_baseline(self) -> BaselineKind:
        return self.point_metrics.baseline_selection.selected_kind

    @property
    def per_seed_test_diagnostics(self) -> tuple[tuple[int, float, float], ...]:
        """返回 frozen ascending ``(seed, Test MSE_r, Test RMSE_r)`` vector。"""

        return tuple(
            (
                result.training_seed,
                result.metrics.primary_mse,
                result.metrics.primary_rmse,
            )
            for result in self.point_estimate.learned_seed_results
        )

    @property
    def evaluation_plan_sha256(self) -> str:
        return self.pretest_freeze.evaluation_plan_sha256

    @property
    def predictor_implementation_sha256(self) -> str:
        return self.pretest_freeze.predictor_implementation_sha256

    @property
    def metric_implementation_sha256(self) -> str:
        return self.pretest_freeze.metric_implementation_sha256

    @property
    def bootstrap_implementation_sha256(self) -> str:
        return self.pretest_freeze.bootstrap_implementation_sha256

    @property
    def official_failure_state_plan_sha256(self) -> str:
        return self.pretest_freeze.official_failure_state_plan_sha256

    @property
    def git_commit_sha(self) -> str:
        return self.pretest_freeze.git_commit_sha

    @property
    def runtime_provenance_sha256(self) -> str:
        return self.pretest_freeze.runtime_provenance_sha256


def _record_failure(
    *,
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
    failure_split: SplitLabel,
    failure_action_kind: OfficialTestExecutionKind,
    phase: str,
    error: Exception,
) -> PredictionEvaluationFailure:
    """通过 accepted governance factory 记录一次 deterministic terminal failure。"""

    return record_prediction_evaluation_failure(
        state=state,
        pretest_freeze=pretest_freeze,
        failure_split=failure_split,
        failure_action_kind=failure_action_kind,
        failure_reason=f"{phase}: {type(error).__name__}: {error}",
    )


def _validate_mapping_keys(
    value: object,
    expected_keys: tuple[object, ...],
    name: str,
) -> Mapping[object, object]:
    """在读取任何 mapping value 前验证 exact key inventory。"""

    if not isinstance(value, Mapping):
        raise TypeError(f"{name} 必须是 Mapping")
    actual_keys = tuple(value.keys())
    if len(actual_keys) != len(expected_keys) or set(actual_keys) != set(expected_keys):
        raise ValueError(f"{name} keys 必须精确覆盖 frozen inventory")
    return value


def _materialize_forecast_records(
    mapping: Mapping[object, object],
    key: object,
    name: str,
) -> tuple[ForecastRecord, ...]:
    """读取一个 predictor raw ForecastRecord finite tuple。"""

    value = mapping[key]
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} 必须是 ForecastRecord finite iterable")
    records = tuple(value)  # type: ignore[arg-type]
    if any(not isinstance(record, ForecastRecord) for record in records):
        raise TypeError(f"{name} 必须全部是 ForecastRecord")
    return records


def _materialize_artifacts(
    value: object,
    name: str,
) -> tuple[VerifiedPredictionArtifact, ...]:
    """物化 raw safe-loaded artifact inventory，不创建 alternate trust path。"""

    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} 必须是 VerifiedPredictionArtifact finite iterable")
    artifacts = tuple(value)  # type: ignore[arg-type]
    if any(not isinstance(artifact, VerifiedPredictionArtifact) for artifact in artifacts):
        raise TypeError(f"{name} 必须全部是 VerifiedPredictionArtifact")
    return artifacts


def finalize_official_prediction_evaluation(
    *,
    state: SealedEvaluationState,
    pretest_freeze: PreTestFreeze,
    baseline_selection: BaselineSelectionResult,
    learned_selection: LearnedModelSelectionResult,
    test_id_artifacts: Iterable[VerifiedPredictionArtifact],
    test_ood_artifacts: Iterable[VerifiedPredictionArtifact],
    test_id_baseline_forecast_records: Mapping[BaselineKind, Iterable[ForecastRecord]],
    test_ood_baseline_forecast_records: Mapping[BaselineKind, Iterable[ForecastRecord]],
    test_id_learned_forecast_records: Mapping[int, Iterable[ForecastRecord]],
    test_ood_learned_forecast_records: Mapping[int, Iterable[ForecastRecord]],
) -> OfficialPredictionEvaluationResult | PredictionEvaluationFailure:
    """从 raw authoritative inputs 连续构造唯一 final official prediction result。

    第一 executable gate 在任何 raw inventory access 前要求 already-SPENT exact Layer-B admission。
    本函数不执行 first-exposure transition、predictor inference、forecast generation、retry、
    fallback 或 persistence。Admission 后任一普通 exception 都通过 accepted governance
    recorder 终止为
    ``PREDICTION_EVALUATION_FAILURE``；``KeyboardInterrupt``、``SystemExit`` 与 ``GeneratorExit``
    不会被转换。
    """

    state, pretest_freeze = _validate_spent_admission(state, pretest_freeze)
    frozen_seeds = pretest_freeze.pretraining_freeze.fixed_training_seeds

    mapping_specs = (
        (
            test_id_baseline_forecast_records,
            _BASELINE_ORDER,
            "test_id_baseline_forecast_records",
            SplitLabel.TEST_ID,
        ),
        (
            test_id_learned_forecast_records,
            frozen_seeds,
            "test_id_learned_forecast_records",
            SplitLabel.TEST_ID,
        ),
        (
            test_ood_baseline_forecast_records,
            _BASELINE_ORDER,
            "test_ood_baseline_forecast_records",
            SplitLabel.TEST_OOD,
        ),
        (
            test_ood_learned_forecast_records,
            frozen_seeds,
            "test_ood_learned_forecast_records",
            SplitLabel.TEST_OOD,
        ),
    )
    normalized_mappings: list[Mapping[object, object]] = []
    for mapping, expected_keys, name, split in mapping_specs:
        try:
            normalized_mappings.append(_validate_mapping_keys(mapping, expected_keys, name))
        except Exception as error:
            return _record_failure(
                state=state,
                pretest_freeze=pretest_freeze,
                failure_split=split,
                failure_action_kind=OfficialTestExecutionKind.SCIENTIFIC_RESULT_READBACK,
                phase="RAW_FORECAST_INVENTORY",
                error=error,
            )

    (
        id_baseline_mapping,
        id_learned_mapping,
        ood_baseline_mapping,
        ood_learned_mapping,
    ) = normalized_mappings
    record_specs = (
        (id_baseline_mapping, _BASELINE_ORDER, "TEST_ID baseline", SplitLabel.TEST_ID),
        (id_learned_mapping, frozen_seeds, "TEST_ID learned", SplitLabel.TEST_ID),
        (ood_baseline_mapping, _BASELINE_ORDER, "TEST_OOD baseline", SplitLabel.TEST_OOD),
        (ood_learned_mapping, frozen_seeds, "TEST_OOD learned", SplitLabel.TEST_OOD),
    )
    materialized_record_groups: list[dict[object, tuple[ForecastRecord, ...]]] = []
    for mapping, keys, name, split in record_specs:
        records_by_key: dict[object, tuple[ForecastRecord, ...]] = {}
        for key in keys:
            try:
                records_by_key[key] = _materialize_forecast_records(
                    mapping,
                    key,
                    f"{name}[{key}]",
                )
            except Exception as error:
                return _record_failure(
                    state=state,
                    pretest_freeze=pretest_freeze,
                    failure_split=split,
                    failure_action_kind=OfficialTestExecutionKind.SCIENTIFIC_RESULT_READBACK,
                    phase="RAW_FORECAST_READBACK",
                    error=error,
                )
        materialized_record_groups.append(records_by_key)
    (
        id_baseline_records,
        id_learned_records,
        ood_baseline_records,
        ood_learned_records,
    ) = materialized_record_groups

    materialized_artifacts: list[tuple[VerifiedPredictionArtifact, ...]] = []
    for value, name, split in (
        (test_id_artifacts, "test_id_artifacts", SplitLabel.TEST_ID),
        (test_ood_artifacts, "test_ood_artifacts", SplitLabel.TEST_OOD),
    ):
        try:
            materialized_artifacts.append(_materialize_artifacts(value, name))
        except Exception as error:
            return _record_failure(
                state=state,
                pretest_freeze=pretest_freeze,
                failure_split=split,
                failure_action_kind=OfficialTestExecutionKind.TARGET_RESULT_EVALUATION,
                phase="VERIFIED_ARTIFACT_READBACK",
                error=error,
            )
    id_artifacts, ood_artifacts = materialized_artifacts

    bound_id_baselines: list[OfficialPredictorSplitForecasts] = []
    bound_id_learned: list[OfficialPredictorSplitForecasts] = []
    bound_ood_baselines: list[OfficialPredictorSplitForecasts] = []
    bound_ood_learned: list[OfficialPredictorSplitForecasts] = []
    binding_specs = (
        (
            SplitLabel.TEST_ID,
            id_artifacts,
            _BASELINE_ORDER,
            id_baseline_records,
            bound_id_baselines,
            True,
        ),
        (
            SplitLabel.TEST_ID,
            id_artifacts,
            frozen_seeds,
            id_learned_records,
            bound_id_learned,
            False,
        ),
        (
            SplitLabel.TEST_OOD,
            ood_artifacts,
            _BASELINE_ORDER,
            ood_baseline_records,
            bound_ood_baselines,
            True,
        ),
        (
            SplitLabel.TEST_OOD,
            ood_artifacts,
            frozen_seeds,
            ood_learned_records,
            bound_ood_learned,
            False,
        ),
    )
    for split, artifacts, keys, records_by_key, destination, is_baseline in binding_specs:
        for key in keys:
            try:
                if is_baseline:
                    destination.append(
                        bind_official_baseline_split_forecasts(
                            state=state,
                            pretest_freeze=pretest_freeze,
                            split=split,
                            baseline=key,  # type: ignore[arg-type]
                            verified_artifacts=artifacts,
                            forecast_records=records_by_key[key],
                        )
                    )
                else:
                    destination.append(
                        bind_official_learned_split_forecasts(
                            state=state,
                            pretest_freeze=pretest_freeze,
                            split=split,
                            training_seed=key,  # type: ignore[arg-type]
                            verified_artifacts=artifacts,
                            forecast_records=records_by_key[key],
                        )
                    )
            except Exception as error:
                return _record_failure(
                    state=state,
                    pretest_freeze=pretest_freeze,
                    failure_split=split,
                    failure_action_kind=OfficialTestExecutionKind.TARGET_RESULT_EVALUATION,
                    phase="SLICE14_FORECAST_BINDING",
                    error=error,
                )

    cross_split_anchor = state.first_official_test_execution.split
    try:
        point_metrics = evaluate_official_sealed_point_metrics(
            state=state,
            pretest_freeze=pretest_freeze,
            baseline_selection=baseline_selection,
            learned_selection=learned_selection,
            test_id_artifacts=id_artifacts,
            test_ood_artifacts=ood_artifacts,
            test_id_baselines=tuple(bound_id_baselines),
            test_id_learned=tuple(bound_id_learned),
            test_ood_baselines=tuple(bound_ood_baselines),
            test_ood_learned=tuple(bound_ood_learned),
        )
    except Exception as error:
        return _record_failure(
            state=state,
            pretest_freeze=pretest_freeze,
            failure_split=cross_split_anchor,
            failure_action_kind=OfficialTestExecutionKind.METRIC_COMPUTATION,
            phase="SEALED_METRICS_CROSS_SPLIT",
            error=error,
        )

    try:
        mandatory_breakdowns = compute_official_mandatory_breakdowns(
            pretest_freeze=pretest_freeze,
            sealed_metrics=point_metrics,
        )
    except Exception as error:
        return _record_failure(
            state=state,
            pretest_freeze=pretest_freeze,
            failure_split=cross_split_anchor,
            failure_action_kind=OfficialTestExecutionKind.METRIC_COMPUTATION,
            phase="MANDATORY_BREAKDOWNS_CROSS_SPLIT",
            error=error,
        )

    try:
        checkpoint_by_seed = {
            identity.training_seed: identity.checkpoint_sha256
            for identity in pretest_freeze.learned_predictor_identities
        }
        if set(checkpoint_by_seed) != set(frozen_seeds):
            raise ValueError("PreTestFreeze learned checkpoint inventory 不完整")
        learned_seed_results = tuple(
            TrainingSeedTestResult(
                training_seed=metric.forecasts.training_seed,
                checkpoint_sha256=checkpoint_by_seed[metric.forecasts.training_seed],
                metrics=metric.metrics,
            )
            for metric in point_metrics.test_id_learned
        )
        point_estimate = compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            learned_seed_results,
            point_metrics.selected_baseline_test_id.metrics,
        )
        _validate_point_estimate_bindings(
            pretest_freeze=pretest_freeze,
            point_metrics=point_metrics,
            point_estimate=point_estimate,
        )
    except Exception as error:
        return _record_failure(
            state=state,
            pretest_freeze=pretest_freeze,
            failure_split=SplitLabel.TEST_ID,
            failure_action_kind=OfficialTestExecutionKind.METRIC_COMPUTATION,
            phase="PRIMARY_ID_POINT_ESTIMATE",
            error=error,
        )

    try:
        bootstrap_result = bootstrap_locked_test_delta_rmse(
            point_estimate,
            pretest_freeze.bootstrap_spec,
        )
    except Exception as error:
        return _record_failure(
            state=state,
            pretest_freeze=pretest_freeze,
            failure_split=SplitLabel.TEST_ID,
            failure_action_kind=OfficialTestExecutionKind.BOOTSTRAP_COMPUTATION,
            phase="PRIMARY_ID_BOOTSTRAP",
            error=error,
        )

    try:
        interpretation = interpret_primary_id_bootstrap(bootstrap_result)
        return OfficialPredictionEvaluationResult(
            state=state,
            pretest_freeze=pretest_freeze,
            point_metrics=point_metrics,
            mandatory_breakdowns=mandatory_breakdowns,
            point_estimate=point_estimate,
            bootstrap_result=bootstrap_result,
            interpretation=interpretation,
            _verification_token=_OFFICIAL_RESULT_TOKEN,
        )
    except Exception as error:
        return _record_failure(
            state=state,
            pretest_freeze=pretest_freeze,
            failure_split=SplitLabel.TEST_ID,
            failure_action_kind=OfficialTestExecutionKind.SCIENTIFIC_RESULT_READBACK,
            phase="PRIMARY_ID_INTERPRETATION",
            error=error,
        )


__all__ = [
    "OfficialPredictionEvaluationResult",
    "finalize_official_prediction_evaluation",
]
