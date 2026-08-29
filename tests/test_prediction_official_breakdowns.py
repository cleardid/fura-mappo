from __future__ import annotations

import hashlib
import inspect
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from pathlib import Path

import numpy as np
import pytest

import fura_mappo.prediction as prediction_module
import fura_mappo.prediction.breakdowns as breakdowns_module
from fura_mappo.prediction import (
    BaselineKind,
    ConditionTraceBreakdown,
    DatasetSplitManifest,
    DemandForecast,
    ForecastProvenance,
    OfficialPointForecastRecord,
    OfficialPredictorSplitBreakdown,
    OfficialPredictorSplitForecasts,
    OfficialPredictorSplitMetrics,
    OfficialSealedMandatoryBreakdowns,
    OfficialSealedPointMetrics,
    OODCellTraceBreakdown,
    OODKindTraceBreakdown,
    PointForecastRecord,
    PredictionContext,
    PredictionOODKind,
    PredictionSample,
    PredictionSource,
    PredictionTarget,
    PreTestFreeze,
    PreTrainingFreeze,
    SplitEntry,
    SplitLabel,
    TargetStratumCellMetrics,
    TargetValueStratum,
    TraceOODAssignment,
    compute_official_mandatory_breakdowns,
    evaluate_point_forecasts,
)

_BASELINE_ORDER = tuple(BaselineKind)
_SEEDS = (3, 7)
_ZONE_SHA256 = hashlib.sha256(b"slice16-zone-schema").hexdigest()
_LAYER_A_SHA256 = hashlib.sha256(b"slice16-layer-a").hexdigest()
_PRETEST_SHA256 = hashlib.sha256(b"slice16-pretest").hexdigest()
_SEALED_SHA256 = hashlib.sha256(b"slice16-sealed").hexdigest()
_GIT_SHA = "1" * 40
_ID_TRACE_IDS = ("id_a", "id_b", "id_c")
_OOD_TRACE_IDS = ("ood_a", "ood_b", "ood_c")


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _source(
    *,
    trace_id: str,
    seed: int,
    start_step: int,
    condition_sha256: str,
) -> PredictionSource:
    return PredictionSource(
        trace_id=trace_id,
        seed=seed,
        process_type="synthetic_unit_fixture",
        config_sha256=_sha256(f"config:{trace_id}"),
        content_sha256=_sha256(f"content:{trace_id}"),
        realized_trace_sha256=_sha256(f"trace:{trace_id}"),
        condition_sha256=condition_sha256,
        zone_schema_sha256=_ZONE_SHA256,
        start_step=start_step,
        num_steps=4,
        num_zones=2,
    )


def _forge_pretraining(manifest: DatasetSplitManifest) -> PreTrainingFreeze:
    result = object.__new__(PreTrainingFreeze)
    object.__setattr__(result, "split_manifest", manifest)
    object.__setattr__(result, "fixed_training_seeds", _SEEDS)
    object.__setattr__(result, "sha256", _LAYER_A_SHA256)
    return result


def _forge_pretest(
    *,
    pretraining: PreTrainingFreeze,
    assignments: tuple[TraceOODAssignment, ...],
    layer_a_sha256: str = _LAYER_A_SHA256,
    sha256: str = _PRETEST_SHA256,
    test_id_trace_ids: tuple[str, ...] = _ID_TRACE_IDS,
    test_ood_trace_ids: tuple[str, ...] = _OOD_TRACE_IDS,
) -> PreTestFreeze:
    result = object.__new__(PreTestFreeze)
    object.__setattr__(result, "pretraining_freeze", pretraining)
    object.__setattr__(result, "pretraining_freeze_sha256", layer_a_sha256)
    object.__setattr__(result, "sha256", sha256)
    object.__setattr__(result, "test_id_trace_ids", test_id_trace_ids)
    object.__setattr__(result, "test_ood_trace_ids", test_ood_trace_ids)
    object.__setattr__(result, "final_ood_assignments", assignments)
    return result


def _target_counts(trace_rank: int, anchor_index: int) -> np.ndarray:
    mixed = (
        [[0, 1], [2, 0]],
        [[3, 0], [0, 4]],
        [[0, 5], [0, 0]],
    )
    if trace_rank == 0:
        return np.asarray(mixed[anchor_index], dtype=np.int64)
    if trace_rank == 1:
        values = np.full((2, 2), anchor_index + 1, dtype=np.int64)
        if anchor_index == 2:
            values[1] = 0
        return values
    return np.zeros((2, 2), dtype=np.int64)


def _metric_bundle(
    *,
    pretest: PreTestFreeze,
    source_by_trace: dict[str, PredictionSource],
    split: SplitLabel,
    baseline: BaselineKind | None,
    training_seed: int | None,
    offset: float,
) -> OfficialPredictorSplitMetrics:
    trace_ids = _ID_TRACE_IDS if split is SplitLabel.TEST_ID else _OOD_TRACE_IDS
    predictor_identity = baseline.value if baseline is not None else f"seed-{training_seed}"
    predictor_sha256 = _sha256(f"predictor:{predictor_identity}")
    config_sha256 = _sha256(f"config:{predictor_identity}")
    protocol_sha256 = _sha256("protocol")
    manifest_sha256 = pretest.pretraining_freeze.split_manifest.sha256
    records: list[OfficialPointForecastRecord] = []
    for trace_rank, trace_id in enumerate(trace_ids):
        source = source_by_trace[trace_id]
        for anchor_index in range(source.num_steps - 1):
            valid_mask = np.asarray(
                [True, anchor_index < source.num_steps - 2],
                dtype=np.bool_,
            )
            counts = _target_counts(trace_rank, anchor_index)
            context = PredictionContext(
                absolute_step=source.start_step + anchor_index,
                steps_remaining=source.num_steps - anchor_index,
                history_counts=np.zeros((1, source.num_zones), dtype=np.int64),
                history_mask=np.asarray([True], dtype=np.bool_),
                zone_schema_sha256=_ZONE_SHA256,
                prediction_horizon=2,
            )
            target = PredictionTarget(counts=counts, valid_mask=valid_mask)
            sample = PredictionSample(
                sample_id=_sha256(f"sample:{trace_id}:{anchor_index}"),
                context=context,
                target=target,
            )
            mean = counts.astype(np.float64)
            mean[valid_mask] += offset
            forecast = DemandForecast(
                absolute_step=context.absolute_step,
                horizon=2,
                zone_schema_sha256=_ZONE_SHA256,
                valid_mask=valid_mask,
                mean=mean,
            )
            provenance = ForecastProvenance(
                predictor_artifact_sha256=predictor_sha256,
                prediction_config_sha256=config_sha256,
                dataset_protocol_sha256=protocol_sha256,
                split_manifest_sha256=manifest_sha256,
                sample_id=sample.sample_id,
                execution_git_commit=_GIT_SHA,
            )
            point_record = PointForecastRecord(
                trace_id=trace_id,
                trace_start_step=source.start_step,
                trace_num_steps=source.num_steps,
                sample=sample,
                forecast=forecast,
            )
            records.append(OfficialPointForecastRecord(point_record, provenance))
    bundle = OfficialPredictorSplitForecasts(
        sealed_evaluation_state_sha256=_SEALED_SHA256,
        pretraining_freeze_sha256=_LAYER_A_SHA256,
        pretest_freeze_sha256=_PRETEST_SHA256,
        split=split,
        baseline=baseline,
        training_seed=training_seed,
        predictor_artifact_sha256=predictor_sha256,
        prediction_config_sha256=config_sha256,
        protocol_sha256=protocol_sha256,
        split_manifest_sha256=manifest_sha256,
        execution_git_commit=_GIT_SHA,
        prediction_horizon=2,
        num_zones=2,
        zone_schema_sha256=_ZONE_SHA256,
        trace_ids=trace_ids,
        records=tuple(records),
    )
    return OfficialPredictorSplitMetrics(bundle, evaluate_point_forecasts(bundle.point_records))


def _forge_sealed(
    *,
    test_id_baselines: object,
    test_id_learned: object,
    test_ood_baselines: object,
    test_ood_learned: object,
    layer_a_sha256: str = _LAYER_A_SHA256,
    pretest_sha256: str = _PRETEST_SHA256,
) -> OfficialSealedPointMetrics:
    result = object.__new__(OfficialSealedPointMetrics)
    object.__setattr__(result, "pretraining_freeze_sha256", layer_a_sha256)
    object.__setattr__(result, "pretest_freeze_sha256", pretest_sha256)
    object.__setattr__(result, "test_id_baselines", test_id_baselines)
    object.__setattr__(result, "test_id_learned", test_id_learned)
    object.__setattr__(result, "test_ood_baselines", test_ood_baselines)
    object.__setattr__(result, "test_ood_learned", test_ood_learned)
    return result


@dataclass(frozen=True)
class _Fixture:
    pretest: PreTestFreeze
    sealed: OfficialSealedPointMetrics
    result: OfficialSealedMandatoryBreakdowns


@pytest.fixture(scope="module")
def fixture() -> _Fixture:
    condition_a = "a" * 64
    condition_b = "b" * 64
    condition_c = "c" * 64
    condition_d = "d" * 64
    definitions = (
        (SplitLabel.TEST_ID, "id_a", 10, 100, condition_b),
        (SplitLabel.TEST_ID, "id_b", 11, 200, condition_a),
        (SplitLabel.TEST_ID, "id_c", 12, 300, condition_b),
        (SplitLabel.TEST_OOD, "ood_a", 20, 400, condition_d),
        (SplitLabel.TEST_OOD, "ood_b", 21, 500, condition_c),
        (SplitLabel.TEST_OOD, "ood_c", 22, 600, condition_d),
    )
    entries = tuple(
        SplitEntry(
            split,
            _source(
                trace_id=trace_id,
                seed=seed,
                start_step=start_step,
                condition_sha256=condition,
            ),
        )
        for split, trace_id, seed, start_step, condition in definitions
    )
    manifest = DatasetSplitManifest(entries)
    pretraining = _forge_pretraining(manifest)
    assignments = (
        TraceOODAssignment("id_a", PredictionOODKind.ID, "id_z"),
        TraceOODAssignment("id_b", PredictionOODKind.ID, "id_a"),
        TraceOODAssignment("id_c", PredictionOODKind.ID, "id_a"),
        TraceOODAssignment("ood_a", PredictionOODKind.NEAR_OOD, "near_z"),
        TraceOODAssignment("ood_b", PredictionOODKind.STRUCTURAL_OOD, "struct_a"),
        TraceOODAssignment("ood_c", PredictionOODKind.NEAR_OOD, "near_a"),
    )
    pretest = _forge_pretest(pretraining=pretraining, assignments=assignments)
    source_by_trace = {entry.source.trace_id: entry.source for entry in manifest.entries}
    id_baselines = tuple(
        _metric_bundle(
            pretest=pretest,
            source_by_trace=source_by_trace,
            split=SplitLabel.TEST_ID,
            baseline=baseline,
            training_seed=None,
            offset=float(index + 1),
        )
        for index, baseline in enumerate(_BASELINE_ORDER)
    )
    ood_baselines = tuple(
        _metric_bundle(
            pretest=pretest,
            source_by_trace=source_by_trace,
            split=SplitLabel.TEST_OOD,
            baseline=baseline,
            training_seed=None,
            offset=float(index + 1),
        )
        for index, baseline in enumerate(_BASELINE_ORDER)
    )
    id_learned = tuple(
        _metric_bundle(
            pretest=pretest,
            source_by_trace=source_by_trace,
            split=SplitLabel.TEST_ID,
            baseline=None,
            training_seed=seed,
            offset=seed / 10.0,
        )
        for seed in _SEEDS
    )
    ood_learned = tuple(
        _metric_bundle(
            pretest=pretest,
            source_by_trace=source_by_trace,
            split=SplitLabel.TEST_OOD,
            baseline=None,
            training_seed=seed,
            offset=seed / 10.0,
        )
        for seed in _SEEDS
    )
    sealed = _forge_sealed(
        test_id_baselines=id_baselines,
        test_id_learned=id_learned,
        test_ood_baselines=ood_baselines,
        test_ood_learned=ood_learned,
    )
    result = compute_official_mandatory_breakdowns(
        pretest_freeze=pretest,
        sealed_metrics=sealed,
    )
    return _Fixture(pretest, sealed, result)


def _clone_sealed(
    sealed: OfficialSealedPointMetrics,
    **changes: object,
) -> OfficialSealedPointMetrics:
    values = {
        "test_id_baselines": sealed.test_id_baselines,
        "test_id_learned": sealed.test_id_learned,
        "test_ood_baselines": sealed.test_ood_baselines,
        "test_ood_learned": sealed.test_ood_learned,
        "layer_a_sha256": sealed.pretraining_freeze_sha256,
        "pretest_sha256": sealed.pretest_freeze_sha256,
    }
    values.update(changes)
    return _forge_sealed(**values)


def test_target_value_stratum_is_exact_two_value_enum() -> None:
    assert tuple(TargetValueStratum) == (
        TargetValueStratum.ZERO,
        TargetValueStratum.POSITIVE,
    )
    assert tuple(item.value for item in TargetValueStratum) == ("ZERO", "POSITIVE")


def test_empty_cell_retains_explicit_absent_metrics() -> None:
    row = TargetStratumCellMetrics("trace", 1, 0, TargetValueStratum.ZERO, 0, None, None, None)
    assert row.count == 0
    assert row.mse is row.mae is row.bias is row.rmse is None


def test_nonempty_cell_normalizes_finite_metrics_and_derives_rmse() -> None:
    row = TargetStratumCellMetrics("trace", 1, 0, TargetValueStratum.POSITIVE, 2, 4, 1.5, -0.5)
    assert (row.mse, row.mae, row.bias, row.rmse) == (4.0, 1.5, -0.5, 2.0)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"lead": 0}, ValueError),
        ({"zone_id": -1}, ValueError),
        ({"count": -1}, ValueError),
        ({"count": True}, TypeError),
        ({"mse": -1.0}, ValueError),
        ({"mse": float("nan")}, ValueError),
        ({"mae": -1.0}, ValueError),
        ({"bias": float("inf")}, ValueError),
    ],
)
def test_nonempty_cell_rejects_invalid_scalar_contract(
    changes: dict[str, object], error: type[Exception]
) -> None:
    values: dict[str, object] = {
        "trace_id": "trace",
        "lead": 1,
        "zone_id": 0,
        "stratum": TargetValueStratum.POSITIVE,
        "count": 1,
        "mse": 1.0,
        "mae": 1.0,
        "bias": 1.0,
    }
    values.update(changes)
    with pytest.raises(error):
        TargetStratumCellMetrics(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values",
    [
        (0, 0.0, None, None),
        (0, None, 0.0, None),
        (0, None, None, 0.0),
        (1, None, 1.0, 1.0),
        (1, 1.0, None, 1.0),
        (1, 1.0, 1.0, None),
    ],
)
def test_cell_rejects_count_metric_presence_mismatch(values: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        TargetStratumCellMetrics("trace", 1, 0, TargetValueStratum.ZERO, *values)


def test_breakdown_rows_form_exact_complete_canonical_grid(fixture: _Fixture) -> None:
    for group in (
        fixture.result.test_id_baselines,
        fixture.result.test_id_learned,
        fixture.result.test_ood_baselines,
        fixture.result.test_ood_learned,
    ):
        for breakdown in group:
            forecasts = breakdown.metrics.forecasts
            assert len(breakdown.target_strata) == len(forecasts.trace_ids) * 2 * 2 * 2
            assert tuple(
                (row.trace_id, row.lead, row.zone_id, row.stratum)
                for row in breakdown.target_strata
            ) == tuple(
                (trace_id, lead, zone_id, stratum)
                for trace_id in forecasts.trace_ids
                for lead in (1, 2)
                for zone_id in (0, 1)
                for stratum in (TargetValueStratum.ZERO, TargetValueStratum.POSITIVE)
            )


def test_zero_positive_predicates_and_local_metrics_are_exact(fixture: _Fixture) -> None:
    breakdown = fixture.result.test_id_baselines[0]
    rows = {
        (row.trace_id, row.lead, row.zone_id, row.stratum): row for row in breakdown.target_strata
    }
    assert rows[("id_a", 1, 0, TargetValueStratum.ZERO)].count == 2
    assert rows[("id_a", 1, 0, TargetValueStratum.POSITIVE)].count == 1
    assert rows[("id_a", 1, 1, TargetValueStratum.ZERO)].count == 1
    assert rows[("id_a", 1, 1, TargetValueStratum.POSITIVE)].count == 2
    assert rows[("id_b", 2, 1, TargetValueStratum.ZERO)].count == 0
    assert rows[("id_b", 2, 1, TargetValueStratum.ZERO)].mse is None
    assert rows[("id_c", 2, 1, TargetValueStratum.POSITIVE)].count == 0
    assert rows[("id_c", 2, 1, TargetValueStratum.POSITIVE)].mae is None
    for row in breakdown.target_strata:
        if row.count:
            assert (row.mse, row.mae, row.bias, row.rmse) == (1.0, 1.0, 1.0, 1.0)


def test_masked_horizons_are_excluded_from_local_counts(fixture: _Fixture) -> None:
    rows = fixture.result.test_id_baselines[0].target_strata
    lead_one = sum(row.count for row in rows if row.trace_id == "id_a" and row.lead == 1)
    lead_two = sum(row.count for row in rows if row.trace_id == "id_a" and row.lead == 2)
    assert lead_one == 3 * 2
    assert lead_two == 2 * 2


def test_condition_groups_use_manifest_sha_and_frozen_member_order(fixture: _Fixture) -> None:
    breakdown = fixture.result.test_id_baselines[0]
    assert tuple(group.condition_sha256 for group in breakdown.conditions) == (
        "a" * 64,
        "b" * 64,
    )
    assert tuple(group.trace_ids for group in breakdown.conditions) == (
        ("id_b",),
        ("id_a", "id_c"),
    )
    assert tuple(trace_id for group in breakdown.conditions for trace_id in group.trace_ids) == (
        "id_b",
        "id_a",
        "id_c",
    )


def test_condition_groups_bind_existing_metric_and_row_objects(fixture: _Fixture) -> None:
    breakdown = fixture.result.test_id_baselines[0]
    metric_by_trace = {
        metric.trace_id: metric for metric in breakdown.metrics.metrics.trace_metrics
    }
    row_ids = {id(row) for row in breakdown.target_strata}
    for group in breakdown.conditions:
        assert all(metric is metric_by_trace[metric.trace_id] for metric in group.trace_metrics)
        assert all(
            id(row) in row_ids and row.trace_id in group.trace_ids
            for row in group.target_stratum_rows
        )


def test_coarse_ood_groups_are_exact_three_with_empty_groups(fixture: _Fixture) -> None:
    id_groups = fixture.result.test_id_baselines[0].ood_kinds
    ood_groups = fixture.result.test_ood_baselines[0].ood_kinds
    expected_kinds = (
        PredictionOODKind.ID,
        PredictionOODKind.NEAR_OOD,
        PredictionOODKind.STRUCTURAL_OOD,
    )
    assert tuple(group.kind for group in id_groups) == expected_kinds
    assert tuple(group.trace_ids for group in id_groups) == (_ID_TRACE_IDS, (), ())
    assert tuple(group.kind for group in ood_groups) == expected_kinds
    assert tuple(group.trace_ids for group in ood_groups) == (
        (),
        ("ood_a", "ood_c"),
        ("ood_b",),
    )


def test_ood_cells_use_kind_rank_then_cell_lexical_order(fixture: _Fixture) -> None:
    id_cells = fixture.result.test_id_baselines[0].ood_cells
    assert tuple((group.kind, group.cell_id, group.trace_ids) for group in id_cells) == (
        (PredictionOODKind.ID, "id_a", ("id_b", "id_c")),
        (PredictionOODKind.ID, "id_z", ("id_a",)),
    )
    ood_cells = fixture.result.test_ood_baselines[0].ood_cells
    assert tuple((group.kind, group.cell_id, group.trace_ids) for group in ood_cells) == (
        (PredictionOODKind.NEAR_OOD, "near_a", ("ood_c",)),
        (PredictionOODKind.NEAR_OOD, "near_z", ("ood_a",)),
        (PredictionOODKind.STRUCTURAL_OOD, "struct_a", ("ood_b",)),
    )


def test_all_group_families_exactly_partition_each_split(fixture: _Fixture) -> None:
    for breakdown in (
        fixture.result.test_id_baselines[0],
        fixture.result.test_ood_baselines[0],
    ):
        expected = set(breakdown.metrics.forecasts.trace_ids)
        for groups in (breakdown.conditions, breakdown.ood_kinds, breakdown.ood_cells):
            memberships = tuple(trace_id for group in groups for trace_id in group.trace_ids)
            assert len(memberships) == len(set(memberships))
            assert set(memberships) == expected


def test_six_baselines_remain_independent_and_canonical(fixture: _Fixture) -> None:
    for group in (fixture.result.test_id_baselines, fixture.result.test_ood_baselines):
        assert tuple(item.metrics.forecasts.baseline for item in group) == _BASELINE_ORDER
        assert tuple(item.metrics.metrics.primary_rmse for item in group) == (
            1.0,
            2.0,
            3.0,
            4.0,
            5.0,
            6.0,
        )


def test_learned_seeds_remain_independent_and_canonical(fixture: _Fixture) -> None:
    for group in (fixture.result.test_id_learned, fixture.result.test_ood_learned):
        assert tuple(item.metrics.forecasts.training_seed for item in group) == _SEEDS
        assert tuple(item.metrics.metrics.primary_rmse for item in group) == pytest.approx(
            (0.3, 0.7)
        )
        assert group[0].target_strata != group[1].target_strata


def test_sealed_output_rejects_baseline_masquerading_as_learned(fixture: _Fixture) -> None:
    with pytest.raises(ValueError, match="baseline identity"):
        OfficialSealedMandatoryBreakdowns(
            fixture.result.test_id_baselines,
            fixture.result.test_id_baselines[:1],
            fixture.result.test_ood_baselines,
            fixture.result.test_ood_baselines[:1],
        )


def test_output_has_exact_four_groups_without_verdict_or_persistence_fields(
    fixture: _Fixture,
) -> None:
    assert tuple(field.name for field in fields(OfficialSealedMandatoryBreakdowns)) == (
        "test_id_baselines",
        "test_id_learned",
        "test_ood_baselines",
        "test_ood_learned",
    )
    assert tuple(len(getattr(fixture.result, field.name)) for field in fields(fixture.result)) == (
        6,
        2,
        6,
        2,
    )
    prohibited = {
        "success",
        "status",
        "verdict",
        "label",
        "delta_rmse",
        "confidence_interval",
        "bootstrap",
        "schema",
        "version",
        "sha256",
    }
    assert prohibited.isdisjoint(field.name for field in fields(fixture.result))


@pytest.mark.parametrize(
    "instance",
    [
        TargetStratumCellMetrics("trace", 1, 0, TargetValueStratum.ZERO, 0, None, None, None),
        OODKindTraceBreakdown(PredictionOODKind.ID, (), (), ()),
    ],
)
def test_public_payloads_are_frozen_and_slotted(instance: object) -> None:
    assert not hasattr(instance, "__dict__")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        setattr(instance, fields(instance)[0].name, object())


def test_derived_payloads_are_frozen_and_slotted(fixture: _Fixture) -> None:
    instances = (
        fixture.result,
        fixture.result.test_id_baselines[0],
        fixture.result.test_id_baselines[0].conditions[0],
        fixture.result.test_id_baselines[0].ood_cells[0],
    )
    for instance in instances:
        assert not hasattr(instance, "__dict__")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            setattr(instance, fields(instance)[0].name, object())


def test_incomplete_row_grid_is_rejected(fixture: _Fixture) -> None:
    breakdown = fixture.result.test_id_baselines[0]
    with pytest.raises(ValueError, match="row grid"):
        replace(breakdown, target_strata=breakdown.target_strata[:-1])


def test_missing_condition_partition_is_rejected(fixture: _Fixture) -> None:
    breakdown = fixture.result.test_id_baselines[0]
    with pytest.raises(ValueError, match="partition"):
        replace(breakdown, conditions=breakdown.conditions[:-1])


def test_noncanonical_condition_order_is_rejected(fixture: _Fixture) -> None:
    breakdown = fixture.result.test_id_baselines[0]
    with pytest.raises(ValueError, match="condition SHA"):
        replace(breakdown, conditions=tuple(reversed(breakdown.conditions)))


def test_missing_coarse_kind_group_is_rejected(fixture: _Fixture) -> None:
    breakdown = fixture.result.test_id_baselines[0]
    with pytest.raises(ValueError, match="canonical three"):
        replace(breakdown, ood_kinds=breakdown.ood_kinds[:-1])


def test_noncanonical_cell_order_is_rejected(fixture: _Fixture) -> None:
    breakdown = fixture.result.test_id_baselines[0]
    with pytest.raises(ValueError, match="canonical ordering"):
        replace(breakdown, ood_cells=tuple(reversed(breakdown.ood_cells)))


@pytest.mark.parametrize("identity", ["layer_a", "pretest"])
def test_factory_rejects_freeze_identity_mismatch(fixture: _Fixture, identity: str) -> None:
    changes = (
        {"layer_a_sha256": "f" * 64} if identity == "layer_a" else {"pretest_sha256": "f" * 64}
    )
    with pytest.raises(ValueError, match="SHA"):
        compute_official_mandatory_breakdowns(
            pretest_freeze=fixture.pretest,
            sealed_metrics=_clone_sealed(fixture.sealed, **changes),
        )


def test_factory_rejects_missing_baseline(fixture: _Fixture) -> None:
    sealed = _clone_sealed(
        fixture.sealed,
        test_id_baselines=fixture.sealed.test_id_baselines[:-1],
    )
    with pytest.raises(ValueError, match="B0--B5"):
        compute_official_mandatory_breakdowns(
            pretest_freeze=fixture.pretest,
            sealed_metrics=sealed,
        )


def test_factory_rejects_missing_learned_seed(fixture: _Fixture) -> None:
    sealed = _clone_sealed(
        fixture.sealed,
        test_ood_learned=fixture.sealed.test_ood_learned[:-1],
    )
    with pytest.raises(ValueError, match="frozen seeds"):
        compute_official_mandatory_breakdowns(
            pretest_freeze=fixture.pretest,
            sealed_metrics=sealed,
        )


def test_factory_rejects_rebound_trace_tuple(fixture: _Fixture) -> None:
    pretest = _forge_pretest(
        pretraining=fixture.pretest.pretraining_freeze,
        assignments=fixture.pretest.final_ood_assignments,
        test_id_trace_ids=tuple(reversed(_ID_TRACE_IDS)),
    )
    with pytest.raises(ValueError, match="trace tuple"):
        compute_official_mandatory_breakdowns(
            pretest_freeze=pretest,
            sealed_metrics=fixture.sealed,
        )


@pytest.mark.parametrize(
    "failure_kind",
    ["missing", "duplicate", "wrong_id_kind", "wrong_ood_kind"],
)
def test_factory_rejects_invalid_final_ood_assignment_coverage(
    fixture: _Fixture,
    failure_kind: str,
) -> None:
    assignments = fixture.pretest.final_ood_assignments
    if failure_kind == "missing":
        changed = assignments[:-1]
    elif failure_kind == "duplicate":
        changed = (*assignments, assignments[0])
    elif failure_kind == "wrong_id_kind":
        changed = (
            replace(assignments[0], kind=PredictionOODKind.NEAR_OOD),
            *assignments[1:],
        )
    else:
        changed = (
            *assignments[:3],
            replace(assignments[3], kind=PredictionOODKind.ID),
            *assignments[4:],
        )
    pretest = _forge_pretest(
        pretraining=fixture.pretest.pretraining_freeze,
        assignments=changed,
    )
    with pytest.raises(ValueError, match="assignment|TEST_ID|TEST_OOD"):
        compute_official_mandatory_breakdowns(
            pretest_freeze=pretest,
            sealed_metrics=fixture.sealed,
        )


def test_factory_rejects_manifest_missing_requested_trace(fixture: _Fixture) -> None:
    manifest = DatasetSplitManifest(
        tuple(
            entry
            for entry in fixture.pretest.pretraining_freeze.split_manifest.entries
            if entry.source.trace_id != "id_c"
        )
    )
    pretest = _forge_pretest(
        pretraining=_forge_pretraining(manifest),
        assignments=fixture.pretest.final_ood_assignments,
    )
    with pytest.raises(ValueError, match="manifest condition membership"):
        compute_official_mandatory_breakdowns(
            pretest_freeze=pretest,
            sealed_metrics=fixture.sealed,
        )


@pytest.mark.parametrize(
    ("pretest", "sealed"),
    [(object(), None), (None, object())],
)
def test_factory_rejects_wrong_top_level_types(
    fixture: _Fixture,
    pretest: object,
    sealed: object,
) -> None:
    with pytest.raises(TypeError):
        compute_official_mandatory_breakdowns(
            pretest_freeze=fixture.pretest if pretest is None else pretest,  # type: ignore[arg-type]
            sealed_metrics=fixture.sealed if sealed is None else sealed,  # type: ignore[arg-type]
        )


def test_factory_does_not_mutate_inputs(fixture: _Fixture) -> None:
    before = (
        fixture.pretest.final_ood_assignments,
        fixture.pretest.pretraining_freeze.split_manifest.entries,
        fixture.sealed.test_id_baselines,
        tuple(
            record.point_record.forecast.mean.tobytes()
            for item in fixture.sealed.test_id_baselines
            for record in item.forecasts.records
        ),
    )
    compute_official_mandatory_breakdowns(
        pretest_freeze=fixture.pretest,
        sealed_metrics=fixture.sealed,
    )
    after = (
        fixture.pretest.final_ood_assignments,
        fixture.pretest.pretraining_freeze.split_manifest.entries,
        fixture.sealed.test_id_baselines,
        tuple(
            record.point_record.forecast.mean.tobytes()
            for item in fixture.sealed.test_id_baselines
            for record in item.forecasts.records
        ),
    )
    assert after == before


def test_trust_boundary_docstring_requires_slice17_continuous_chain() -> None:
    docstring = inspect.getdoc(compute_official_mandatory_breakdowns)
    assert docstring is not None
    for token in (
        "不是最终 official trust root",
        "structural direct construction",
        "raw safe-loaded artifacts",
        "Slice 14",
        "Slice 15",
        "立即调用本函数",
        "arbitrary caller-constructed sealed metrics",
    ):
        assert token in docstring


def test_production_source_is_descriptive_and_numerically_isolated() -> None:
    source = inspect.getsource(breakdowns_module)
    forbidden = (
        ".predict(",
        ".intensities",
        "compute_locked_test_point_estimate",
        "bootstrap_locked_test_delta_rmse",
        "interpret_primary_id_bootstrap",
        "record_prediction_evaluation_failure",
        "np.random",
        "random.",
        "torch",
        "subprocess",
        "json.dump",
        "yaml",
    )
    assert all(token not in source for token in forbidden)


def test_breakdown_payloads_have_no_group_aggregate_metric_fields() -> None:
    group_types = (
        ConditionTraceBreakdown,
        OODKindTraceBreakdown,
        OODCellTraceBreakdown,
    )
    forbidden = {"mse", "rmse", "mae", "bias", "weight", "aggregate"}
    for group_type in group_types:
        assert forbidden.isdisjoint(field.name for field in fields(group_type))


def test_public_exports_are_exactly_available() -> None:
    expected = (
        TargetValueStratum,
        TargetStratumCellMetrics,
        ConditionTraceBreakdown,
        OODKindTraceBreakdown,
        OODCellTraceBreakdown,
        OfficialPredictorSplitBreakdown,
        OfficialSealedMandatoryBreakdowns,
        compute_official_mandatory_breakdowns,
    )
    assert all(getattr(prediction_module, item.__name__) is item for item in expected)


def test_protocol_freezes_exact_descriptive_no_rescue_semantics() -> None:
    protocol = Path("docs/PREDICTION_BASELINE_PROTOCOL.md").read_text(encoding="utf-8")
    required = (
        "Mandatory breakdown exact reporting semantics",
        "target_count == 0",
        "target_count > 0",
        "count = 0",
        "MSE = absent",
        "MAE = absent",
        "Bias = absent",
        "condition_sha256",
        "ID < NEAR_OOD < STRUCTURAL_OOD",
        "B0--B5",
        "不得 rescue、替换或改变 Primary RMSE 与 Primary-ID label",
    )
    assert all(token in protocol for token in required)
    assert "本协议**不定义** overall ZERO RMSE、overall POSITIVE RMSE" in protocol
    assert "stratum 的 ZERO/POSITIVE aggregate weighting" in protocol
