from __future__ import annotations

import hashlib
import inspect
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from pathlib import Path

import numpy as np
import pytest

import fura_mappo.prediction as prediction_module
import fura_mappo.prediction.governance as governance_module
from fura_mappo.demand import DemandEvent, DemandTrace, save_demand_trace
from fura_mappo.prediction import (
    B5SupportPreflightResult,
    BaselineSelectionFailure,
    CalibrationDisposition,
    DatasetProtocolSpec,
    DatasetSplitManifest,
    HistoryTransformKind,
    LearnedConfigFreezeIdentity,
    PointObjectiveKind,
    PredictionOODKind,
    PreTrainingFreeze,
    PreTrainingFreezeFailure,
    SplitLabel,
    TraceOODAssignment,
    VerifiedPredictionArtifact,
    ZoneSchema,
    build_pretraining_freeze,
    build_split_manifest_from_artifacts,
    load_verified_prediction_artifact,
    preflight_layer_a_b5_support,
)


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _zone_sha256() -> str:
    return ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]]).sha256


def _trace(
    *,
    start_step: int,
    num_steps: int,
    marker: int,
    intensities: tuple[float, float],
) -> DemandTrace:
    counts = np.zeros((num_steps, 2), dtype=np.int64)
    counts[0, marker % 2] = marker
    events = tuple(
        DemandEvent(
            event_id=event_id,
            arrival_step=start_step,
            zone_id=marker % 2,
            position=(marker % 2 + 0.5, 0.5),
            priority=0.5,
            service_time=1,
            deadline=start_step + 2,
        )
        for event_id in range(marker)
    )
    intensity_array = np.tile(np.asarray(intensities, dtype=np.float64), (num_steps, 1))
    return DemandTrace(start_step, counts, intensity_array, events)


def _resolved_config(
    *,
    seed: int,
    num_steps: int,
    intensities: tuple[float, float],
) -> dict[str, object]:
    return {
        "schema": "fura-mappo.demand-generation",
        "version": 1,
        "demand": {
            "type": "stationary_poisson",
            "seed": seed,
            "intensities": list(intensities),
            "zone_bounds": [[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]],
            "priority_range": [0.5, 0.5],
            "service_time_range": [1, 1],
            "deadline_offset_range": [2, 2],
        },
        "generation": {"num_steps": num_steps},
    }


def _verified_artifact(
    tmp_path: Path,
    *,
    trace_id: str,
    seed: int,
    start_step: int,
    num_steps: int,
    marker: int,
    intensities: tuple[float, float],
) -> VerifiedPredictionArtifact:
    trace = _trace(
        start_step=start_step,
        num_steps=num_steps,
        marker=marker,
        intensities=intensities,
    )
    path = save_demand_trace(
        tmp_path / f"{trace_id}.npz",
        trace,
        resolved_config=_resolved_config(
            seed=seed,
            num_steps=num_steps,
            intensities=intensities,
        ),
    )
    return load_verified_prediction_artifact(path, trace_id)


@dataclass(frozen=True)
class _PreflightFixture:
    freeze: PreTrainingFreeze
    artifacts: tuple[VerifiedPredictionArtifact, ...]
    primary_protocol: DatasetProtocolSpec
    secondary_protocols: tuple[DatasetProtocolSpec, ...]


def _fixture(
    tmp_path: Path,
    *,
    geometry: dict[str, tuple[int, int]] | None = None,
    sealed_calibration: bool = False,
) -> _PreflightFixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    geometry = geometry or {}
    primary = DatasetProtocolSpec(4, 2, _zone_sha256())
    secondary = (
        DatasetProtocolSpec(4, 4, _zone_sha256()),
        DatasetProtocolSpec(4, 8, _zone_sha256()),
    )
    definitions: list[tuple[SplitLabel, str, int, int, tuple[float, float]]] = [
        (SplitLabel.TRAIN, "train_a", 1, 1, (0.2, 0.3)),
        (SplitLabel.TRAIN, "train_b", 2, 2, (0.2, 0.3)),
        (SplitLabel.VALIDATION, "validation_a", 3, 3, (0.2, 0.3)),
        (SplitLabel.TEST_ID, "test_id_a", 4, 4, (0.2, 0.3)),
        (SplitLabel.TEST_OOD, "test_ood_a", 5, 5, (0.7, 0.8)),
    ]
    if sealed_calibration:
        definitions.append((SplitLabel.CALIBRATION, "calibration_a", 6, 6, (0.2, 0.3)))
    artifacts = tuple(
        _verified_artifact(
            tmp_path,
            trace_id=trace_id,
            seed=seed,
            start_step=geometry.get(trace_id, (10, 10))[0],
            num_steps=geometry.get(trace_id, (10, 10))[1],
            marker=marker,
            intensities=intensities,
        )
        for _, trace_id, seed, marker, intensities in definitions
    )
    manifest = build_split_manifest_from_artifacts(
        tuple(
            (split, artifact)
            for (split, _, _, _, _), artifact in zip(definitions, artifacts, strict=True)
        ),
        primary,
    )
    freeze = build_pretraining_freeze(
        primary_protocol=primary,
        secondary_protocols=secondary,
        split_manifest=manifest,
        verified_artifacts=artifacts,
        calibration_disposition=(
            CalibrationDisposition.SEALED if sealed_calibration else CalibrationDisposition.EMPTY
        ),
        ood_assignments=(
            TraceOODAssignment("test_id_a", PredictionOODKind.ID, "primary_id"),
            TraceOODAssignment("test_ood_a", PredictionOODKind.NEAR_OOD, "near_axis_a"),
        ),
        fixed_training_seeds=(3, 1, 2),
        learned_config_identities=(
            LearnedConfigFreezeIdentity(
                config_sha256=_sha256("candidate"),
                protocol_sha256=primary.sha256,
                objective=PointObjectiveKind.O0,
                transform=HistoryTransformKind.T0,
                model_complexity_key=(8, 32),
                canonical_order=0,
            ),
        ),
        rng_namespace_plan_sha256=_sha256("rng-plan"),
        training_plan_sha256=_sha256("training-plan"),
        baseline_plan_sha256=_sha256("baseline-plan"),
    )
    return _PreflightFixture(freeze, artifacts, primary, secondary)


def _preflight(
    fixture: _PreflightFixture,
    *,
    protocol_sha256: str | None = None,
    artifacts: object | None = None,
    freeze: PreTrainingFreeze | None = None,
) -> B5SupportPreflightResult:
    return preflight_layer_a_b5_support(
        pretraining_freeze=freeze or fixture.freeze,
        protocol_sha256=protocol_sha256 or fixture.primary_protocol.sha256,
        verified_artifacts=(
            fixture.artifacts if artifacts is None else artifacts  # type: ignore[arg-type]
        ),
    )


def test_valid_full_role_coverage_returns_exact_structural_result(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    freeze_sha = fixture.freeze.sha256
    baseline_plan_sha = fixture.freeze.baseline_plan_sha256

    result = _preflight(fixture)

    assert result.pretraining_freeze_sha256 == freeze_sha
    assert result.protocol_sha256 == fixture.primary_protocol.sha256
    assert result.prediction_horizon == 2
    assert result.zone_schema_sha256 == _zone_sha256()
    assert result.support_start_step == 10
    assert result.support_stop_step == 20
    assert result.support_length == 10
    assert fixture.freeze.sha256 == freeze_sha
    assert fixture.freeze.baseline_plan_sha256 == baseline_plan_sha
    assert not hasattr(fixture.freeze, "b5_support")


@pytest.mark.parametrize("prediction_horizon", [2, 4, 8])
def test_preflight_is_generic_for_each_frozen_prediction_horizon(
    tmp_path: Path,
    prediction_horizon: int,
) -> None:
    fixture = _fixture(tmp_path)
    protocols = (fixture.primary_protocol, *fixture.secondary_protocols)
    protocol = next(item for item in protocols if item.prediction_horizon == prediction_horizon)

    result = _preflight(fixture, protocol_sha256=protocol.sha256)

    assert result.protocol_sha256 == protocol.sha256
    assert result.prediction_horizon == prediction_horizon
    assert (result.support_start_step, result.support_stop_step) == (10, 20)


def test_empty_common_train_support_uses_baseline_selection_failure(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        geometry={"train_a": (10, 2), "train_b": (12, 2)},
    )

    with pytest.raises(BaselineSelectionFailure) as captured:
        _preflight(fixture)

    assert captured.value.status == "PREDICTION_BASELINE_SELECTION_FAILURE"
    message = str(captured.value)
    assert fixture.primary_protocol.sha256 in message
    assert "split=train" in message
    assert "trace_id=" in message
    assert "support=[12,12)" in message


@pytest.mark.parametrize(
    ("trace_id", "split_label"),
    [
        ("train_a", SplitLabel.TRAIN),
        ("validation_a", SplitLabel.VALIDATION),
        ("test_id_a", SplitLabel.TEST_ID),
        ("test_ood_a", SplitLabel.TEST_OOD),
    ],
)
def test_required_interval_gap_uses_baseline_failure_with_location(
    tmp_path: Path,
    trace_id: str,
    split_label: SplitLabel,
) -> None:
    geometry = (
        {"train_a": (10, 10), "train_b": (12, 8)} if trace_id == "train_a" else {trace_id: (10, 11)}
    )
    fixture = _fixture(tmp_path, geometry=geometry)

    with pytest.raises(BaselineSelectionFailure) as captured:
        _preflight(fixture)

    assert captured.value.status == "PREDICTION_BASELINE_SELECTION_FAILURE"
    message = str(captured.value)
    assert f"protocol_sha256={fixture.primary_protocol.sha256}" in message
    assert f"split={split_label.value}" in message
    assert f"trace_id={trace_id}" in message
    assert "support=[" in message
    assert "required=[" in message


def test_sealed_calibration_outside_support_is_ignored(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        geometry={"calibration_a": (100, 5)},
        sealed_calibration=True,
    )

    result = _preflight(fixture)

    assert fixture.freeze.calibration_disposition is CalibrationDisposition.SEALED
    assert (result.support_start_step, result.support_stop_step) == (10, 20)


def test_one_step_trace_has_empty_required_interval_and_is_accepted(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        geometry={"validation_a": (100, 1)},
    )

    result = _preflight(fixture)

    assert result.support_length == 10


@pytest.mark.parametrize("protocol_sha256", [_sha256("unknown"), "A" * 64, "short"])
def test_unknown_or_invalid_protocol_sha_uses_pretraining_freeze_failure(
    tmp_path: Path,
    protocol_sha256: str,
) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(PreTrainingFreezeFailure) as captured:
        _preflight(fixture, protocol_sha256=protocol_sha256)

    assert captured.value.status == "PRE_TRAINING_DATA_FREEZE_FAILURE"


def test_artifact_exact_coverage_rejects_missing_extra_and_duplicate_trace_id(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    extra = _verified_artifact(
        tmp_path,
        trace_id="extra_trace",
        seed=99,
        start_step=10,
        num_steps=10,
        marker=9,
        intensities=(0.4, 0.5),
    )

    with pytest.raises(PreTrainingFreezeFailure) as missing:
        _preflight(fixture, artifacts=fixture.artifacts[:-1])
    with pytest.raises(PreTrainingFreezeFailure) as extra_failure:
        _preflight(fixture, artifacts=(*fixture.artifacts, extra))
    with pytest.raises(PreTrainingFreezeFailure) as duplicate:
        _preflight(fixture, artifacts=(*fixture.artifacts, fixture.artifacts[0]))

    assert missing.value.status == "PRE_TRAINING_DATA_FREEZE_FAILURE"
    assert extra_failure.value.status == "PRE_TRAINING_DATA_FREEZE_FAILURE"
    assert duplicate.value.status == "PRE_TRAINING_DATA_FREEZE_FAILURE"


def test_authoritative_source_mismatch_and_direct_freeze_cannot_bypass_rebind(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    forged_manifest = DatasetSplitManifest(
        tuple(
            replace(
                entry,
                source=replace(entry.source, content_sha256=_sha256("forged-content")),
            )
            if entry.source.trace_id == "validation_a"
            else entry
            for entry in fixture.freeze.split_manifest.entries
        )
    )
    direct_freeze = PreTrainingFreeze(
        primary_protocol=fixture.freeze.primary_protocol,
        secondary_protocols=fixture.freeze.secondary_protocols,
        split_manifest=forged_manifest,
        calibration_disposition=fixture.freeze.calibration_disposition,
        ood_assignments=fixture.freeze.ood_assignments,
        fixed_training_seeds=fixture.freeze.fixed_training_seeds,
        learned_config_identities=fixture.freeze.learned_config_identities,
        rng_namespace_plan_sha256=fixture.freeze.rng_namespace_plan_sha256,
        training_plan_sha256=fixture.freeze.training_plan_sha256,
        baseline_plan_sha256=fixture.freeze.baseline_plan_sha256,
    )

    with pytest.raises(PreTrainingFreezeFailure) as captured:
        _preflight(fixture, freeze=direct_freeze)

    assert captured.value.status == "PRE_TRAINING_DATA_FREEZE_FAILURE"
    assert "binding" in str(captured.value)


def test_verified_artifact_caller_order_does_not_change_result(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    first = _preflight(fixture)
    second = _preflight(fixture, artifacts=reversed(fixture.artifacts))

    assert first == second


def test_result_is_immutable_slotted_and_structural_only(tmp_path: Path) -> None:
    result = _preflight(_fixture(tmp_path))

    assert [item.name for item in fields(B5SupportPreflightResult)] == [
        "pretraining_freeze_sha256",
        "protocol_sha256",
        "prediction_horizon",
        "zone_schema_sha256",
        "support_start_step",
        "support_stop_step",
    ]
    assert not hasattr(result, "__dict__")
    forbidden = (
        "verified_artifacts",
        "artifact",
        "trace",
        "sources",
        "targets",
        "step_means",
        "predictor",
        "forecast",
        "metrics",
        "baseline_selection",
        "learned_selection",
        "checkpoint",
        "rmse",
        "bootstrap",
        "label",
    )
    assert all(not hasattr(result, name) for name in forbidden)
    with pytest.raises(FrozenInstanceError):
        result.support_start_step = 0  # type: ignore[misc]


def test_direct_result_construction_is_structural_and_validates_interval() -> None:
    result = B5SupportPreflightResult(
        pretraining_freeze_sha256=_sha256("freeze"),
        protocol_sha256=_sha256("protocol"),
        prediction_horizon=8,
        zone_schema_sha256=_sha256("zone"),
        support_start_step=3,
        support_stop_step=9,
    )

    assert result.support_length == 6
    with pytest.raises(ValueError, match="非空半开区间"):
        replace(result, support_stop_step=3)


def test_wrong_top_level_freeze_type_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(TypeError, match="PreTrainingFreeze"):
        preflight_layer_a_b5_support(
            pretraining_freeze=object(),  # type: ignore[arg-type]
            protocol_sha256=fixture.primary_protocol.sha256,
            verified_artifacts=fixture.artifacts,
        )


def test_support_failure_does_not_repair_or_mutate_freeze(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        geometry={"validation_a": (10, 11)},
    )
    freeze_sha = fixture.freeze.sha256
    entries = fixture.freeze.split_manifest.entries

    with pytest.raises(BaselineSelectionFailure):
        _preflight(fixture)

    assert fixture.freeze.sha256 == freeze_sha
    assert fixture.freeze.split_manifest.entries == entries


def test_production_preflight_only_reads_frozen_scalar_source_geometry() -> None:
    source = inspect.getsource(governance_module)
    preflight_source = inspect.getsource(preflight_layer_a_b5_support)
    forbidden = (
        ".artifact",
        ".counts",
        ".intensities",
        "DemandEvent",
        "fit_absolute_step_train_climatology",
        ".predict(",
        "evaluate_point_forecasts",
        "select_validation_baselines",
        "select_learned_validation_config",
        "bootstrap_locked_test_delta_rmse",
        "numpy",
        "np.",
        "random",
        "torch",
        "PREDICTION_EVALUATION_FAILURE",
        "FIRST_OFFICIAL_TEST_EXECUTION",
        "SPENT",
    )

    assert all(token not in source for token in forbidden)
    assert "split_manifest.entries" in preflight_source
    assert ".start_step" in preflight_source
    assert ".num_steps" in preflight_source


def test_public_preflight_surface_is_minimal() -> None:
    assert governance_module.__all__ == [
        "CalibrationDisposition",
        "LearnedConfigFreezeIdentity",
        "PredictionOODKind",
        "PreTrainingFreeze",
        "PreTrainingFreezeFailure",
        "TraceOODAssignment",
        "build_pretraining_freeze",
    ]
    assert prediction_module.B5SupportPreflightResult is B5SupportPreflightResult
    assert prediction_module.preflight_layer_a_b5_support is preflight_layer_a_b5_support
    assert "B5SupportPreflightResult" in prediction_module.__all__
    assert "preflight_layer_a_b5_support" in prediction_module.__all__
    assert "_b5_support_failure" not in governance_module.__all__
    assert "_resolve_frozen_protocol" not in governance_module.__all__
