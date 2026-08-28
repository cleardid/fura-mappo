from __future__ import annotations

import hashlib
import inspect
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path

import numpy as np
import pytest

import fura_mappo.prediction.governance as governance_module
from fura_mappo.demand import DemandEvent, DemandTrace, save_demand_trace
from fura_mappo.prediction import (
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
)


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _zone_sha256() -> str:
    return ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]]).sha256


def _trace(counts: list[list[int]], intensities: tuple[float, float]) -> DemandTrace:
    count_array = np.asarray(counts, dtype=np.int64)
    events: list[DemandEvent] = []
    event_id = 0
    for arrival_step, zone_counts in enumerate(count_array):
        for zone_id, zone_count in enumerate(zone_counts):
            for _ in range(int(zone_count)):
                events.append(
                    DemandEvent(
                        event_id=event_id,
                        arrival_step=arrival_step,
                        zone_id=zone_id,
                        position=(zone_id + 0.5, 0.5),
                        priority=0.5,
                        service_time=1,
                        deadline=arrival_step + 2,
                    )
                )
                event_id += 1
    intensity_array = np.tile(np.asarray(intensities, dtype=np.float64), (len(counts), 1))
    return DemandTrace(0, count_array, intensity_array, tuple(events))


def _resolved_config(
    seed: int,
    intensities: tuple[float, float],
    num_steps: int,
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
    counts: list[list[int]],
    intensities: tuple[float, float] = (0.2, 0.3),
) -> VerifiedPredictionArtifact:
    trace = _trace(counts, intensities)
    path = save_demand_trace(
        tmp_path / f"{trace_id}.npz",
        trace,
        resolved_config=_resolved_config(seed, intensities, len(counts)),
    )
    return load_verified_prediction_artifact(path, trace_id)


@dataclass(frozen=True)
class _LayerAFixture:
    primary_protocol: DatasetProtocolSpec
    secondary_protocols: tuple[DatasetProtocolSpec, ...]
    split_manifest: DatasetSplitManifest
    verified_artifacts: tuple[VerifiedPredictionArtifact, ...]
    calibration_disposition: CalibrationDisposition
    ood_assignments: tuple[TraceOODAssignment, ...]
    learned_config_identities: tuple[LearnedConfigFreezeIdentity, ...]


def _fixture(tmp_path: Path, *, calibration: bool = False) -> _LayerAFixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    primary = DatasetProtocolSpec(4, 2, _zone_sha256())
    secondary = (
        DatasetProtocolSpec(8, 2, _zone_sha256()),
        DatasetProtocolSpec(4, 4, _zone_sha256()),
    )
    definitions: list[tuple[SplitLabel, str, int, list[list[int]], tuple[float, float]]] = [
        (SplitLabel.TRAIN, "train_a", 1, [[1, 0], [0, 0], [0, 0], [0, 0]], (0.2, 0.3)),
        (SplitLabel.TRAIN, "train_b", 2, [[0, 1], [0, 0], [0, 0], [0, 0]], (0.2, 0.3)),
        (
            SplitLabel.VALIDATION,
            "validation_a",
            3,
            [[1, 1], [0, 0], [0, 0], [0, 0]],
            (0.2, 0.3),
        ),
        (
            SplitLabel.TEST_ID,
            "test_id_a",
            4,
            [[1, 0], [0, 1], [0, 0], [0, 0]],
            (0.2, 0.3),
        ),
        (
            SplitLabel.TEST_OOD,
            "test_ood_near",
            5,
            [[2, 0], [0, 0], [0, 0], [0, 0]],
            (0.7, 0.8),
        ),
        (
            SplitLabel.TEST_OOD,
            "test_ood_structural",
            6,
            [[0, 2], [0, 0], [0, 0], [0, 0]],
            (0.9, 1.0),
        ),
    ]
    if calibration:
        definitions.append(
            (
                SplitLabel.CALIBRATION,
                "calibration_a",
                7,
                [[1, 0], [1, 0], [0, 0], [0, 0]],
                (0.2, 0.3),
            )
        )
    artifacts = tuple(
        _verified_artifact(
            tmp_path,
            trace_id=trace_id,
            seed=seed,
            counts=counts,
            intensities=intensities,
        )
        for _, trace_id, seed, counts, intensities in definitions
    )
    manifest = build_split_manifest_from_artifacts(
        tuple(
            (split, artifact)
            for (split, _, _, _, _), artifact in zip(definitions, artifacts, strict=True)
        ),
        primary,
    )
    assignments = (
        TraceOODAssignment("test_id_a", PredictionOODKind.ID, "primary_id"),
        TraceOODAssignment("test_ood_near", PredictionOODKind.NEAR_OOD, "near_axis_a"),
        TraceOODAssignment(
            "test_ood_structural",
            PredictionOODKind.STRUCTURAL_OOD,
            "heldout_family_a",
        ),
    )
    candidates = (
        LearnedConfigFreezeIdentity(
            _sha256("candidate-a"),
            primary.sha256,
            PointObjectiveKind.O0,
            HistoryTransformKind.T0,
            (8, 32),
            0,
        ),
        LearnedConfigFreezeIdentity(
            _sha256("candidate-b"),
            primary.sha256,
            PointObjectiveKind.O1,
            HistoryTransformKind.T1,
            (16, 64),
            1,
        ),
    )
    return _LayerAFixture(
        primary_protocol=primary,
        secondary_protocols=secondary,
        split_manifest=manifest,
        verified_artifacts=artifacts,
        calibration_disposition=(
            CalibrationDisposition.SEALED if calibration else CalibrationDisposition.EMPTY
        ),
        ood_assignments=assignments,
        learned_config_identities=candidates,
    )


def _direct_freeze(fixture: _LayerAFixture, **changes: object) -> PreTrainingFreeze:
    values: dict[str, object] = {
        "primary_protocol": fixture.primary_protocol,
        "secondary_protocols": fixture.secondary_protocols,
        "split_manifest": fixture.split_manifest,
        "calibration_disposition": fixture.calibration_disposition,
        "ood_assignments": fixture.ood_assignments,
        "fixed_training_seeds": (11, 7, 9),
        "learned_config_identities": fixture.learned_config_identities,
        "rng_namespace_plan_sha256": _sha256("rng-plan"),
        "training_plan_sha256": _sha256("training-plan"),
        "baseline_plan_sha256": _sha256("baseline-plan"),
    }
    values.update(changes)
    return PreTrainingFreeze(**values)  # type: ignore[arg-type]


def _authoritative_freeze(fixture: _LayerAFixture, **changes: object) -> PreTrainingFreeze:
    values: dict[str, object] = {
        "primary_protocol": fixture.primary_protocol,
        "secondary_protocols": fixture.secondary_protocols,
        "split_manifest": fixture.split_manifest,
        "verified_artifacts": fixture.verified_artifacts,
        "calibration_disposition": fixture.calibration_disposition,
        "ood_assignments": fixture.ood_assignments,
        "fixed_training_seeds": (11, 7, 9),
        "learned_config_identities": fixture.learned_config_identities,
        "rng_namespace_plan_sha256": _sha256("rng-plan"),
        "training_plan_sha256": _sha256("training-plan"),
        "baseline_plan_sha256": _sha256("baseline-plan"),
    }
    values.update(changes)
    return build_pretraining_freeze(**values)  # type: ignore[arg-type]


def _manifest_with_source_change(
    fixture: _LayerAFixture,
    selected_trace_id: str = "train_b",
    **changes: object,
) -> DatasetSplitManifest:
    entries = tuple(
        replace(entry, source=replace(entry.source, **changes))
        if entry.source.trace_id == selected_trace_id
        else entry
        for entry in fixture.split_manifest.entries
    )
    return DatasetSplitManifest(entries)


def test_public_enums_and_failure_status_are_exact() -> None:
    assert [(item.name, item.value) for item in CalibrationDisposition] == [
        ("EMPTY", "EMPTY"),
        ("SEALED", "SEALED"),
    ]
    assert [(item.name, item.value) for item in PredictionOODKind] == [
        ("ID", "ID"),
        ("NEAR_OOD", "NEAR_OOD"),
        ("STRUCTURAL_OOD", "STRUCTURAL_OOD"),
    ]
    failure = PreTrainingFreezeFailure("synthetic")
    assert failure.status == "PRE_TRAINING_DATA_FREEZE_FAILURE"
    assert isinstance(failure, ValueError)


def test_valid_synthetic_direct_and_authoritative_builds_succeed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    direct = _direct_freeze(fixture)
    authoritative = _authoritative_freeze(fixture)

    assert direct.sha256 == authoritative.sha256
    assert len(direct.sha256) == 64
    assert direct.zone_schema_sha256 == fixture.primary_protocol.zone_schema_sha256
    assert direct.primary_prediction_horizon == 2
    assert direct.split_manifest is fixture.split_manifest
    assert direct.source_inventory == tuple(
        entry.source for entry in fixture.split_manifest.entries
    )
    assert not hasattr(authoritative, "verified_artifacts")
    assert not hasattr(authoritative, "artifact")


def test_freeze_is_deterministic_and_caller_order_invariant(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first = _authoritative_freeze(fixture)
    second = _authoritative_freeze(
        fixture,
        secondary_protocols=reversed(fixture.secondary_protocols),
        verified_artifacts=reversed(fixture.verified_artifacts),
        ood_assignments=reversed(fixture.ood_assignments),
        fixed_training_seeds=[9, 11, 7],
        learned_config_identities=reversed(fixture.learned_config_identities),
    )

    assert first == second
    assert first.sha256 == second.sha256
    assert tuple(protocol.sha256 for protocol in second.secondary_protocols) == tuple(
        sorted(protocol.sha256 for protocol in fixture.secondary_protocols)
    )
    assert tuple(item.trace_id for item in second.ood_assignments) == tuple(
        sorted(item.trace_id for item in fixture.ood_assignments)
    )
    assert second.fixed_training_seeds == (7, 9, 11)
    assert tuple(item.canonical_order for item in second.learned_config_identities) == (0, 1)


def test_collections_result_and_manifest_reference_are_immutable(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    secondary = list(fixture.secondary_protocols)
    assignments = list(fixture.ood_assignments)
    seeds = [11, 7, 9]
    candidates = list(fixture.learned_config_identities)
    freeze = _direct_freeze(
        fixture,
        secondary_protocols=secondary,
        ood_assignments=assignments,
        fixed_training_seeds=seeds,
        learned_config_identities=candidates,
    )
    expected_sha = freeze.sha256
    secondary.clear()
    assignments.clear()
    seeds.clear()
    candidates.clear()

    assert freeze.sha256 == expected_sha
    assert freeze.split_manifest is fixture.split_manifest
    assert isinstance(freeze.secondary_protocols, tuple)
    assert isinstance(freeze.ood_assignments, tuple)
    assert isinstance(freeze.fixed_training_seeds, tuple)
    assert isinstance(freeze.learned_config_identities, tuple)
    with pytest.raises(FrozenInstanceError):
        freeze.sha256 = "0" * 64  # type: ignore[misc]


def test_trace_ids_for_split_preserves_manifest_canonical_order(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    freeze = _direct_freeze(fixture)

    expected = tuple(
        entry.source.trace_id
        for entry in fixture.split_manifest.entries
        if entry.split is SplitLabel.TRAIN
    )
    assert freeze.trace_ids_for_split(SplitLabel.TRAIN) == expected
    with pytest.raises(TypeError, match="SplitLabel"):
        freeze.trace_ids_for_split("train")  # type: ignore[arg-type]


def test_factory_rejects_missing_extra_duplicate_and_mismatched_artifacts(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    extra = _verified_artifact(
        tmp_path,
        trace_id="extra_trace",
        seed=99,
        counts=[[0, 0], [1, 1], [0, 0], [0, 0]],
        intensities=(0.4, 0.5),
    )
    mismatched_manifest = _manifest_with_source_change(
        fixture,
        content_sha256=_sha256("forged-content"),
    )

    with pytest.raises(PreTrainingFreezeFailure, match="exact|精确"):
        _authoritative_freeze(fixture, verified_artifacts=fixture.verified_artifacts[:-1])
    with pytest.raises(PreTrainingFreezeFailure, match="exact|精确"):
        _authoritative_freeze(
            fixture,
            verified_artifacts=(*fixture.verified_artifacts, extra),
        )
    with pytest.raises(PreTrainingFreezeFailure, match="重复 trace_id"):
        _authoritative_freeze(
            fixture,
            verified_artifacts=(*fixture.verified_artifacts, fixture.verified_artifacts[0]),
        )
    with pytest.raises(PreTrainingFreezeFailure, match="binding"):
        _authoritative_freeze(fixture, split_manifest=mismatched_manifest)


@pytest.mark.parametrize(
    "missing_split",
    [SplitLabel.TRAIN, SplitLabel.VALIDATION, SplitLabel.TEST_ID, SplitLabel.TEST_OOD],
)
def test_required_split_roles_are_mandatory(
    tmp_path: Path,
    missing_split: SplitLabel,
) -> None:
    fixture = _fixture(tmp_path)
    manifest = DatasetSplitManifest(
        tuple(entry for entry in fixture.split_manifest.entries if entry.split is not missing_split)
    )
    assignments = tuple(
        assignment
        for assignment in fixture.ood_assignments
        if assignment.trace_id in {entry.source.trace_id for entry in manifest.entries}
    )

    with pytest.raises(PreTrainingFreezeFailure, match="required role"):
        _direct_freeze(fixture, split_manifest=manifest, ood_assignments=assignments)


def test_calibration_disposition_empty_and_sealed_semantics(tmp_path: Path) -> None:
    empty_fixture = _fixture(tmp_path / "empty")
    sealed_fixture = _fixture(tmp_path / "sealed", calibration=True)

    assert _direct_freeze(empty_fixture).calibration_disposition is CalibrationDisposition.EMPTY
    assert _direct_freeze(sealed_fixture).calibration_disposition is CalibrationDisposition.SEALED
    with pytest.raises(PreTrainingFreezeFailure, match="EMPTY"):
        _direct_freeze(
            sealed_fixture,
            calibration_disposition=CalibrationDisposition.EMPTY,
        )
    with pytest.raises(PreTrainingFreezeFailure, match="SEALED"):
        _direct_freeze(
            empty_fixture,
            calibration_disposition=CalibrationDisposition.SEALED,
        )


def test_valid_id_near_ood_and_structural_ood_assignments_are_preserved(
    tmp_path: Path,
) -> None:
    freeze = _direct_freeze(_fixture(tmp_path))
    by_trace = {assignment.trace_id: assignment for assignment in freeze.ood_assignments}

    assert by_trace["test_id_a"].kind is PredictionOODKind.ID
    assert by_trace["test_ood_near"].kind is PredictionOODKind.NEAR_OOD
    assert by_trace["test_ood_structural"].kind is PredictionOODKind.STRUCTURAL_OOD


def test_ood_assignments_reject_missing_duplicate_unknown_and_training_trace(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    assignments = fixture.ood_assignments

    with pytest.raises(PreTrainingFreezeFailure, match="精确覆盖"):
        _direct_freeze(fixture, ood_assignments=assignments[:-1])
    with pytest.raises(PreTrainingFreezeFailure, match="恰有一个"):
        _direct_freeze(fixture, ood_assignments=(*assignments, assignments[0]))
    with pytest.raises(PreTrainingFreezeFailure, match="精确覆盖"):
        _direct_freeze(
            fixture,
            ood_assignments=(
                *assignments,
                TraceOODAssignment("unknown_trace", PredictionOODKind.ID, "unknown_cell"),
            ),
        )
    with pytest.raises(PreTrainingFreezeFailure, match="精确覆盖"):
        _direct_freeze(
            fixture,
            ood_assignments=(
                *assignments,
                TraceOODAssignment("train_a", PredictionOODKind.ID, "not_evaluation"),
            ),
        )


def test_ood_assignments_reject_wrong_kind_for_test_id_and_test_ood(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    wrong_id = tuple(
        replace(assignment, kind=PredictionOODKind.NEAR_OOD)
        if assignment.trace_id == "test_id_a"
        else assignment
        for assignment in fixture.ood_assignments
    )
    wrong_ood = tuple(
        replace(assignment, kind=PredictionOODKind.ID)
        if assignment.trace_id == "test_ood_near"
        else assignment
        for assignment in fixture.ood_assignments
    )

    with pytest.raises(PreTrainingFreezeFailure, match="TEST_ID"):
        _direct_freeze(fixture, ood_assignments=wrong_id)
    with pytest.raises(PreTrainingFreezeFailure, match="TEST_OOD"):
        _direct_freeze(fixture, ood_assignments=wrong_ood)


@pytest.mark.parametrize(
    "seeds",
    [
        (1, 2),
        (1, 2, 2),
        (1, 2, -1),
        (1, 2, True),
        (1, 2, 3.0),
    ],
)
def test_fixed_training_seed_contract_rejects_invalid_sets(
    tmp_path: Path,
    seeds: tuple[object, ...],
) -> None:
    with pytest.raises(PreTrainingFreezeFailure):
        _direct_freeze(_fixture(tmp_path), fixed_training_seeds=seeds)


def test_fixed_training_seed_order_is_canonical_and_hash_invariant(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first = _direct_freeze(fixture, fixed_training_seeds=[3, 1, 2])
    second = _direct_freeze(fixture, fixed_training_seeds=[1, 2, 3])

    assert first.fixed_training_seeds == second.fixed_training_seeds == (1, 2, 3)
    assert first.sha256 == second.sha256


@pytest.mark.parametrize(
    ("changes", "error_type"),
    [
        ({"config_sha256": "A" * 64}, ValueError),
        ({"protocol_sha256": "x" * 64}, ValueError),
        ({"objective": "O0"}, TypeError),
        ({"transform": "T0"}, TypeError),
        ({"model_complexity_key": ()}, ValueError),
        ({"model_complexity_key": (-1,)}, ValueError),
        ({"model_complexity_key": (True,)}, TypeError),
        ({"canonical_order": -1}, ValueError),
        ({"canonical_order": True}, TypeError),
    ],
)
def test_learned_candidate_identity_rejects_invalid_fields(
    changes: dict[str, object],
    error_type: type[Exception],
) -> None:
    values: dict[str, object] = {
        "config_sha256": _sha256("candidate"),
        "protocol_sha256": _sha256("protocol"),
        "objective": PointObjectiveKind.O0,
        "transform": HistoryTransformKind.T0,
        "model_complexity_key": (8, 16),
        "canonical_order": 0,
    }
    values.update(changes)

    with pytest.raises(error_type):
        LearnedConfigFreezeIdentity(**values)  # type: ignore[arg-type]


def test_candidate_collection_rejects_empty_unknown_and_duplicate_identities(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    first, second = fixture.learned_config_identities
    unknown_protocol = replace(first, protocol_sha256=_sha256("unknown-protocol"))
    duplicate_config = replace(second, config_sha256=first.config_sha256)
    duplicate_order = replace(second, canonical_order=first.canonical_order)

    with pytest.raises(PreTrainingFreezeFailure, match="非空"):
        _direct_freeze(fixture, learned_config_identities=())
    with pytest.raises(PreTrainingFreezeFailure, match="unknown"):
        _direct_freeze(fixture, learned_config_identities=(unknown_protocol,))
    with pytest.raises(PreTrainingFreezeFailure, match="config_sha256"):
        _direct_freeze(fixture, learned_config_identities=(first, duplicate_config))
    with pytest.raises(PreTrainingFreezeFailure, match="canonical_order"):
        _direct_freeze(fixture, learned_config_identities=(first, duplicate_order))


def test_candidate_protocol_may_bind_primary_or_secondary_and_order_is_canonical(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    first, second = fixture.learned_config_identities
    secondary_candidate = replace(
        second,
        protocol_sha256=fixture.secondary_protocols[0].sha256,
    )
    freeze = _direct_freeze(
        fixture,
        learned_config_identities=(secondary_candidate, first),
    )

    assert tuple(item.canonical_order for item in freeze.learned_config_identities) == (0, 1)


def test_primary_cannot_repeat_in_secondary_and_secondary_shas_are_unique(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    repeated_secondary = fixture.secondary_protocols[0]

    with pytest.raises(PreTrainingFreezeFailure, match="primary protocol"):
        _direct_freeze(
            fixture,
            secondary_protocols=(fixture.primary_protocol,),
        )
    with pytest.raises(PreTrainingFreezeFailure, match="全部唯一"):
        _direct_freeze(
            fixture,
            secondary_protocols=(repeated_secondary, repeated_secondary),
        )


@pytest.mark.parametrize(
    "field_name",
    ["rng_namespace_plan_sha256", "training_plan_sha256", "baseline_plan_sha256"],
)
@pytest.mark.parametrize("invalid", ["a" * 63, "A" * 64, "g" * 64])
def test_plan_sha_fields_reject_invalid_identities(
    tmp_path: Path,
    field_name: str,
    invalid: str,
) -> None:
    with pytest.raises(PreTrainingFreezeFailure, match=field_name):
        _direct_freeze(_fixture(tmp_path), **{field_name: invalid})


@pytest.mark.parametrize(
    "field_name",
    ["rng_namespace_plan_sha256", "training_plan_sha256", "baseline_plan_sha256"],
)
def test_each_plan_sha_changes_final_layer_a_sha(tmp_path: Path, field_name: str) -> None:
    fixture = _fixture(tmp_path)
    original = _direct_freeze(fixture)
    changed = _direct_freeze(fixture, **{field_name: _sha256(f"changed-{field_name}")})

    assert changed.sha256 != original.sha256


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("content_sha256", _sha256("changed-content")),
        ("realized_trace_sha256", _sha256("changed-realized")),
        ("condition_sha256", _sha256("changed-condition")),
        ("seed", 99),
        ("trace_id", "train_b_changed"),
    ],
)
def test_source_inventory_identity_changes_layer_a_sha(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    fixture = _fixture(tmp_path)
    original = _direct_freeze(fixture)
    changed_manifest = _manifest_with_source_change(fixture, **{field_name: value})
    changed = _direct_freeze(fixture, split_manifest=changed_manifest)

    assert changed_manifest.sha256 != fixture.split_manifest.sha256
    assert changed.sha256 != original.sha256


def test_one_trace_split_change_changes_manifest_and_layer_a_sha(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    changed_manifest = DatasetSplitManifest(
        tuple(
            replace(entry, split=SplitLabel.VALIDATION)
            if entry.source.trace_id == "train_b"
            else entry
            for entry in fixture.split_manifest.entries
        )
    )

    assert changed_manifest.sha256 != fixture.split_manifest.sha256
    assert (
        _direct_freeze(fixture, split_manifest=changed_manifest).sha256
        != _direct_freeze(fixture).sha256
    )


def test_primary_and_secondary_protocol_identity_changes_affect_layer_a_sha(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    original = _direct_freeze(fixture)
    changed_secondary = DatasetProtocolSpec(16, 4, _zone_sha256())
    changed_protocol = _direct_freeze(fixture, secondary_protocols=(changed_secondary,))
    changed_primary = _direct_freeze(
        fixture,
        primary_protocol=fixture.secondary_protocols[0],
        secondary_protocols=(
            fixture.primary_protocol,
            fixture.secondary_protocols[1],
        ),
    )

    assert changed_protocol.sha256 != original.sha256
    assert changed_primary.sha256 != original.sha256


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("config_sha256", _sha256("changed-candidate")),
        ("model_complexity_key", (32, 128)),
        ("canonical_order", 3),
    ],
)
def test_each_candidate_identity_change_affects_layer_a_sha(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    fixture = _fixture(tmp_path)
    first, second = fixture.learned_config_identities
    changed_candidate = _direct_freeze(
        fixture,
        learned_config_identities=(first, replace(second, **{field_name: value})),
    )

    assert changed_candidate.sha256 != _direct_freeze(fixture).sha256


def test_ood_cell_identity_change_affects_layer_a_sha(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    original = _direct_freeze(fixture)
    changed_ood = _direct_freeze(
        fixture,
        ood_assignments=tuple(
            replace(assignment, cell_id="near_axis_b")
            if assignment.trace_id == "test_ood_near"
            else assignment
            for assignment in fixture.ood_assignments
        ),
    )

    assert changed_ood.sha256 != original.sha256


def test_training_seed_change_affects_layer_a_sha(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    assert (
        _direct_freeze(fixture, fixed_training_seeds=(1, 2, 3)).sha256
        != _direct_freeze(
            fixture,
            fixed_training_seeds=(1, 2, 4),
        ).sha256
    )


def test_cross_zone_secondary_protocol_and_manifest_source_are_rejected(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    other_zone = ZoneSchema([[0.0, 2.0, 0.0, 1.0], [2.0, 4.0, 0.0, 1.0]]).sha256
    wrong_secondary = DatasetProtocolSpec(4, 2, other_zone)
    wrong_manifest = _manifest_with_source_change(
        fixture,
        zone_schema_sha256=other_zone,
    )

    with pytest.raises(PreTrainingFreezeFailure, match="zone schema"):
        _direct_freeze(fixture, secondary_protocols=(wrong_secondary,))
    with pytest.raises(PreTrainingFreezeFailure, match="zone schema"):
        _direct_freeze(fixture, split_manifest=wrong_manifest)


@pytest.mark.parametrize(
    ("schema", "version"),
    [
        ("wrong-schema", 1),
        ("fura-mappo.prediction-pre-training-freeze", 2),
        ("fura-mappo.prediction-pre-training-freeze", True),
        ("fura-mappo.prediction-pre-training-freeze", 1.0),
    ],
)
def test_direct_construction_rejects_wrong_schema_or_version(
    tmp_path: Path,
    schema: str,
    version: object,
) -> None:
    with pytest.raises(PreTrainingFreezeFailure, match="schema/version"):
        _direct_freeze(_fixture(tmp_path), schema=schema, version=version)


def test_direct_construction_docstring_states_authoritative_trust_boundary() -> None:
    docstring = inspect.getdoc(PreTrainingFreeze)

    assert docstring is not None
    assert "structural identity consistency" in docstring
    assert "build_pretraining_freeze" in docstring
    assert "VerifiedPredictionArtifact" in docstring


def test_production_governance_has_no_data_training_selection_or_layer_b_surface() -> None:
    source = inspect.getsource(governance_module)
    forbidden = (
        "numpy",
        ".intensities",
        "DemandTrace",
        "PointMetricSummary",
        "BaselineSelectionResult",
        "LearnedModelSelectionResult",
        "PrimaryIDLabel",
        "bootstrap_locked_test_delta_rmse",
        "checkpoint_sha256",
        "TRAINING_STARTED",
        "TEST_STARTED",
        "SPENT",
        "90260819",
        "50000",
    )

    assert all(token not in source for token in forbidden)
    assert not hasattr(PreTrainingFreeze, "selected_baseline")
    assert not hasattr(PreTrainingFreeze, "selected_learned_config")
    assert not hasattr(PreTrainingFreeze, "bootstrap_spec")


def test_public_governance_surface_is_exact_and_minimal() -> None:
    assert governance_module.__all__ == [
        "CalibrationDisposition",
        "LearnedConfigFreezeIdentity",
        "PredictionOODKind",
        "PreTrainingFreeze",
        "PreTrainingFreezeFailure",
        "TraceOODAssignment",
        "build_pretraining_freeze",
    ]
    assert "_pretraining_freeze_identity" not in governance_module.__all__
    assert "_normalize_ood_assignments" not in governance_module.__all__
