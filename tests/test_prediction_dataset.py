from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from fura_mappo.demand import DemandEvent, DemandTrace, save_demand_trace
from fura_mappo.prediction import (
    DatasetProtocolSpec,
    DatasetSplitManifest,
    PredictionSource,
    SplitEntry,
    SplitLabel,
    VerifiedPredictionArtifact,
    ZoneSchema,
    build_split_manifest_from_artifacts,
    compute_condition_sha256,
    compute_realized_trace_sha256,
    compute_sample_id,
    derive_prediction_context,
    derive_prediction_samples_from_artifact,
    derive_prediction_target,
    derive_synthetic_prediction_samples,
    load_verified_prediction_artifact,
    validate_prediction_source_for_artifact,
    validate_split_manifest_artifacts,
)


def _zone_schema() -> ZoneSchema:
    return ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]])


def _trace(
    counts: list[list[int]],
    *,
    start_step: int = 5,
    intensity_offset: float = 0.0,
) -> DemandTrace:
    count_array = np.asarray(counts, dtype=np.int64)
    events: list[DemandEvent] = []
    event_id = 0
    for row, zone_counts in enumerate(count_array):
        arrival = start_step + row
        for zone_id, zone_count in enumerate(zone_counts):
            for _ in range(int(zone_count)):
                events.append(
                    DemandEvent(
                        event_id=event_id,
                        arrival_step=arrival,
                        zone_id=zone_id,
                        position=(zone_id + 0.5, 0.5),
                        priority=0.5,
                        service_time=1,
                        deadline=arrival + 2,
                    )
                )
                event_id += 1
    intensities = np.full(count_array.shape, intensity_offset, dtype=np.float64)
    return DemandTrace(start_step, count_array, intensities, tuple(events))


def _single_event_trace(
    *,
    position_x: float = 0.5,
    priority: float = 0.5,
) -> DemandTrace:
    """构造可精确控制 realized float 表示的合法两 zone trace。"""

    event = DemandEvent(
        event_id=0,
        arrival_step=0,
        zone_id=0,
        position=(position_x, 0.5),
        priority=priority,
        service_time=1,
        deadline=2,
    )
    return DemandTrace(
        0,
        [[1, 0]],
        np.zeros((1, 2), dtype=np.float64),
        (event,),
    )


def _spec(*, history_length: int = 3, horizon: int = 3) -> DatasetProtocolSpec:
    return DatasetProtocolSpec(history_length, horizon, _zone_schema().sha256)


def _source(
    trace: DemandTrace,
    *,
    trace_id: str = "trace_1",
    seed: int = 1,
    condition: str = "c" * 64,
    content: str = "b" * 64,
    realized_trace_sha256: str | None = None,
    zone_schema_sha256: str | None = None,
) -> PredictionSource:
    return PredictionSource(
        trace_id=trace_id,
        seed=seed,
        process_type="stationary_poisson",
        config_sha256="a" * 64,
        content_sha256=content,
        realized_trace_sha256=realized_trace_sha256 or content,
        condition_sha256=condition,
        zone_schema_sha256=zone_schema_sha256 or _zone_schema().sha256,
        start_step=trace.start_step,
        num_steps=trace.counts.shape[0],
        num_zones=trace.counts.shape[1],
    )


def _resolved_config(seed: int, num_steps: int = 4) -> dict[str, object]:
    return {
        "schema": "fura-mappo.demand-generation",
        "version": 1,
        "demand": {
            "type": "stationary_poisson",
            "seed": seed,
            "intensities": [0.2, 0.3],
            "zone_bounds": [[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]],
            "priority_range": [0.5, 0.5],
            "service_time_range": [1, 1],
            "deadline_offset_range": [2, 2],
        },
        "generation": {"num_steps": num_steps},
    }


def _save_verified_artifact(
    tmp_path: Path,
    trace: DemandTrace,
    *,
    trace_id: str = "trace_7",
    seed: int = 7,
    filename: str = "trace.npz",
) -> tuple[Path, VerifiedPredictionArtifact]:
    config = _resolved_config(seed, num_steps=trace.counts.shape[0])
    path = save_demand_trace(tmp_path / filename, trace, resolved_config=config)
    return path, load_verified_prediction_artifact(path, trace_id)


def test_dataset_protocol_hash_is_stable_and_semantic() -> None:
    first = _spec(history_length=3, horizon=2)
    second = _spec(history_length=np.int64(3), horizon=np.int32(2))
    changed_history = _spec(history_length=4, horizon=2)
    changed_horizon = _spec(history_length=3, horizon=3)

    assert first == second
    assert first.sha256 == second.sha256
    assert first.sha256 != changed_history.sha256
    assert first.sha256 != changed_horizon.sha256
    with pytest.raises(ValueError, match="target_kind"):
        DatasetProtocolSpec(3, 2, _zone_schema().sha256, target_kind="intensity")


def test_exact_history_future_indexing_and_episode_masks() -> None:
    trace = _trace([[1, 0], [0, 0], [2, 1], [0, 3]])
    spec = _spec()

    first_context = derive_prediction_context(trace, spec, 5)
    first_target = derive_prediction_target(trace, spec, 5)
    late_context = derive_prediction_context(trace, spec, 7)
    late_target = derive_prediction_target(trace, spec, 7)

    np.testing.assert_array_equal(first_context.history_counts, [[0, 0], [0, 0], [1, 0]])
    np.testing.assert_array_equal(first_context.history_mask, [False, False, True])
    np.testing.assert_array_equal(first_target.counts, [[0, 0], [2, 1], [0, 3]])
    np.testing.assert_array_equal(first_target.valid_mask, [True, True, True])
    np.testing.assert_array_equal(late_context.history_counts, [[1, 0], [0, 0], [2, 1]])
    np.testing.assert_array_equal(late_context.history_mask, [True, True, True])
    np.testing.assert_array_equal(late_target.counts, [[0, 3], [0, 0], [0, 0]])
    np.testing.assert_array_equal(late_target.valid_mask, [True, False, False])
    assert late_context.absolute_step == 7
    assert late_context.steps_remaining == 2


def test_real_zero_demand_is_distinct_from_padding() -> None:
    trace = _trace([[0, 0], [0, 0], [1, 0]])
    spec = _spec(history_length=2, horizon=3)
    context = derive_prediction_context(trace, spec, 5)
    target = derive_prediction_target(trace, spec, 5)

    np.testing.assert_array_equal(context.history_counts, [[0, 0], [0, 0]])
    np.testing.assert_array_equal(context.history_mask, [False, True])
    np.testing.assert_array_equal(target.counts, [[0, 0], [1, 0], [0, 0]])
    np.testing.assert_array_equal(target.valid_mask, [True, True, False])


def test_sample_order_ids_and_one_step_trace_semantics() -> None:
    trace = _trace([[1, 0], [0, 0], [2, 1], [0, 3]])
    spec = _spec()
    source = _source(trace)
    samples = derive_synthetic_prediction_samples(trace, source, spec)

    assert tuple(sample.context.absolute_step for sample in samples) == (5, 6, 7)
    assert tuple(sample.sample_id for sample in samples) == tuple(
        compute_sample_id(spec, source, anchor) for anchor in (5, 6, 7)
    )
    assert len(set(sample.sample_id for sample in samples)) == 3
    one_step = _trace([[0, 0]])
    assert derive_synthetic_prediction_samples(one_step, _source(one_step), spec) == ()


def test_prefix_invariance_blocks_future_count_and_event_leakage() -> None:
    prefix = [[1, 0], [0, 1]]
    trace_a = _trace([*prefix, [3, 0], [0, 0]])
    trace_b = _trace([*prefix, [0, 2], [4, 1]])
    spec = _spec(history_length=4, horizon=2)

    context_a = derive_prediction_context(trace_a, spec, 6)
    context_b = derive_prediction_context(trace_b, spec, 6)
    np.testing.assert_array_equal(context_a.history_counts, context_b.history_counts)
    np.testing.assert_array_equal(context_a.history_mask, context_b.history_mask)
    assert context_a.absolute_step == context_b.absolute_step
    assert context_a.steps_remaining == context_b.steps_remaining
    assert not hasattr(context_a, "trace")
    assert not hasattr(context_a, "events")


def test_intensity_isolation_for_context_target_and_samples() -> None:
    counts = [[1, 0], [0, 1], [2, 0]]
    trace_a = _trace(counts, intensity_offset=0.0)
    trace_b = _trace(counts, intensity_offset=999.0)
    spec = _spec(history_length=2, horizon=2)
    source_a = _source(trace_a, content="1" * 64)
    source_b = _source(trace_b, content="2" * 64)

    for anchor in (5, 6, 7):
        left_context = derive_prediction_context(trace_a, spec, anchor)
        right_context = derive_prediction_context(trace_b, spec, anchor)
        left_target = derive_prediction_target(trace_a, spec, anchor)
        right_target = derive_prediction_target(trace_b, spec, anchor)
        np.testing.assert_array_equal(left_context.history_counts, right_context.history_counts)
        np.testing.assert_array_equal(left_context.history_mask, right_context.history_mask)
        np.testing.assert_array_equal(left_target.counts, right_target.counts)
        np.testing.assert_array_equal(left_target.valid_mask, right_target.valid_mask)

    samples_a = derive_synthetic_prediction_samples(trace_a, source_a, spec)
    samples_b = derive_synthetic_prediction_samples(trace_b, source_b, spec)
    for left, right in zip(samples_a, samples_b, strict=True):
        np.testing.assert_array_equal(left.context.history_counts, right.context.history_counts)
        np.testing.assert_array_equal(left.target.counts, right.target.counts)
        assert left.sample_id != right.sample_id


def test_offline_objects_do_not_alias_source_counts() -> None:
    trace = _trace([[1, 0], [0, 1], [2, 0]])
    sample = derive_synthetic_prediction_samples(trace, _source(trace), _spec())[0]

    assert not np.shares_memory(sample.context.history_counts, trace.counts)
    assert not np.shares_memory(sample.target.counts, trace.counts)


def test_dataset_derivation_does_not_consume_numpy_global_rng() -> None:
    trace = _trace([[1, 0], [0, 1], [2, 0]])
    before = np.random.get_state()
    derive_synthetic_prediction_samples(trace, _source(trace), _spec())
    after = np.random.get_state()

    assert before[0] == after[0]
    np.testing.assert_array_equal(before[1], after[1])
    assert before[2:] == after[2:]


def test_condition_identity_removes_only_seed_and_preserves_generation_and_dynamics() -> None:
    seed_one = _resolved_config(1)
    seed_two = _resolved_config(2)
    changed_steps = _resolved_config(2, num_steps=5)
    changed_dynamics = _resolved_config(2)
    demand = changed_dynamics["demand"]
    assert isinstance(demand, dict)
    demand["intensities"] = [0.4, 0.3]

    assert compute_condition_sha256(seed_one) == compute_condition_sha256(seed_two)
    assert compute_condition_sha256(seed_one) != compute_condition_sha256(changed_steps)
    assert compute_condition_sha256(seed_one) != compute_condition_sha256(changed_dynamics)
    assert seed_one["demand"]["seed"] == 1  # type: ignore[index]


def test_verified_artifact_source_binds_zone_schema_and_manifest(
    tmp_path: Path,
) -> None:
    trace = _trace([[1, 0], [0, 1], [0, 0], [1, 1]], start_step=0)
    _, verified = _save_verified_artifact(tmp_path, trace)
    source = verified.source

    assert source.seed == 7
    assert source.config_sha256 == verified.artifact.manifest["config_sha256"]
    assert source.content_sha256 == verified.artifact.manifest["content_sha256"]
    assert source.realized_trace_sha256 == compute_realized_trace_sha256(trace)
    assert source.condition_sha256 == compute_condition_sha256(_resolved_config(7))
    assert source.zone_schema_sha256 == _zone_schema().sha256
    assert not hasattr(source, "resolved_config")
    assert not hasattr(source, "manifest")
    with pytest.raises(TypeError, match="load_verified_prediction_artifact"):
        VerifiedPredictionArtifact(verified.artifact, source, object())


def test_source_zone_schema_must_match_dataset_protocol(tmp_path: Path) -> None:
    trace = _trace([[1, 0], [0, 1], [0, 0], [1, 1]], start_step=0)
    _, verified = _save_verified_artifact(tmp_path, trace)
    matching = _spec()
    same_zone_count_different_geometry = ZoneSchema([[0.0, 10.0, 0.0, 1.0], [10.0, 20.0, 0.0, 1.0]])
    mismatching = DatasetProtocolSpec(3, 3, same_zone_count_different_geometry.sha256)

    assert len(derive_prediction_samples_from_artifact(verified, matching)) == 3
    with pytest.raises(ValueError, match="zone_schema_sha256"):
        derive_prediction_samples_from_artifact(verified, mismatching)
    forged_synthetic_source = replace(
        verified.source,
        zone_schema_sha256=same_zone_count_different_geometry.sha256,
    )
    with pytest.raises(ValueError, match="zone_schema_sha256"):
        derive_synthetic_prediction_samples(trace, forged_synthetic_source, matching)


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    [
        ("content_sha256", "1" * 64),
        ("realized_trace_sha256", "5" * 64),
        ("config_sha256", "2" * 64),
        ("seed", 999),
        ("process_type", "forged_process"),
        ("condition_sha256", "3" * 64),
        ("zone_schema_sha256", "4" * 64),
        ("start_step", 1),
        ("num_steps", 99),
        ("num_zones", 99),
    ],
)
def test_authoritative_artifact_rejects_forged_source_metadata(
    tmp_path: Path,
    field_name: str,
    forged_value: object,
) -> None:
    trace = _trace([[1, 0], [0, 1], [0, 0], [1, 1]], start_step=0)
    _, verified = _save_verified_artifact(tmp_path, trace)
    forged = replace(verified.source, **{field_name: forged_value})

    with pytest.raises(ValueError, match=field_name):
        validate_prediction_source_for_artifact(verified, forged)


def test_same_artifact_cannot_cross_splits_by_forging_descriptor(
    tmp_path: Path,
) -> None:
    trace = _trace([[1, 0], [0, 1], [0, 0], [1, 1]], start_step=0)
    path, train_artifact = _save_verified_artifact(tmp_path, trace, trace_id="train")
    test_artifact = load_verified_prediction_artifact(path, "test")
    spec = _spec()

    with pytest.raises(ValueError, match="content_sha256|seed"):
        build_split_manifest_from_artifacts(
            (
                (SplitLabel.TRAIN, train_artifact),
                (SplitLabel.TEST_ID, test_artifact),
            ),
            spec,
        )

    forged_test_source = replace(
        test_artifact.source,
        seed=8,
        config_sha256="8" * 64,
        content_sha256="9" * 64,
        realized_trace_sha256="a" * 64,
    )
    forged_manifest = DatasetSplitManifest(
        (
            SplitEntry(SplitLabel.TRAIN, train_artifact.source),
            SplitEntry(SplitLabel.TEST_ID, forged_test_source),
        )
    )
    with pytest.raises(ValueError, match="verified artifact"):
        validate_split_manifest_artifacts(
            forged_manifest,
            spec,
            {"train": train_artifact, "test": test_artifact},
        )


def test_verified_manifest_build_and_revalidation_accept_exact_artifacts(
    tmp_path: Path,
) -> None:
    train_trace = _trace([[1, 0], [0, 1], [0, 0], [1, 1]], start_step=0)
    test_trace = _trace([[0, 1], [1, 0], [0, 0], [1, 0]], start_step=0)
    _, train = _save_verified_artifact(
        tmp_path,
        train_trace,
        trace_id="train",
        seed=7,
        filename="train.npz",
    )
    _, test = _save_verified_artifact(
        tmp_path,
        test_trace,
        trace_id="test",
        seed=8,
        filename="test.npz",
    )
    spec = _spec()
    manifest = build_split_manifest_from_artifacts(
        ((SplitLabel.TRAIN, train), (SplitLabel.TEST_ID, test)),
        spec,
    )

    validate_split_manifest_artifacts(manifest, spec, {"train": train, "test": test})
    assert {entry.source.trace_id for entry in manifest.entries} == {"train", "test"}


def test_same_realized_trace_repackaged_with_different_metadata_is_rejected(
    tmp_path: Path,
) -> None:
    trace = _trace([[1, 0], [0, 1], [0, 0], [1, 1]], start_step=0)
    _, artifact_a = _save_verified_artifact(
        tmp_path,
        trace,
        trace_id="train",
        seed=7,
        filename="a.npz",
    )
    _, artifact_b = _save_verified_artifact(
        tmp_path,
        trace,
        trace_id="test",
        seed=8,
        filename="b.npz",
    )

    assert artifact_a.source.content_sha256 != artifact_b.source.content_sha256
    assert artifact_a.source.seed != artifact_b.source.seed
    assert artifact_a.source.realized_trace_sha256 == artifact_b.source.realized_trace_sha256
    with pytest.raises(ValueError, match="realized_trace_sha256"):
        build_split_manifest_from_artifacts(
            (
                (SplitLabel.TRAIN, artifact_a),
                (SplitLabel.TEST_ID, artifact_b),
            ),
            _spec(),
        )


def test_distinct_realized_artifacts_are_allowed_in_id_splits(tmp_path: Path) -> None:
    trace_a = _trace([[1, 0], [0, 1], [0, 0], [1, 1]], start_step=0)
    trace_b = _trace([[0, 1], [1, 0], [0, 0], [1, 0]], start_step=0)
    _, artifact_a = _save_verified_artifact(
        tmp_path,
        trace_a,
        trace_id="train",
        seed=7,
        filename="distinct-a.npz",
    )
    _, artifact_b = _save_verified_artifact(
        tmp_path,
        trace_b,
        trace_id="test",
        seed=8,
        filename="distinct-b.npz",
    )

    assert artifact_a.source.realized_trace_sha256 != artifact_b.source.realized_trace_sha256
    manifest = build_split_manifest_from_artifacts(
        (
            (SplitLabel.TRAIN, artifact_a),
            (SplitLabel.TEST_ID, artifact_b),
        ),
        _spec(),
    )
    assert len(manifest.entries) == 2


def test_realized_trace_hash_is_deterministic_and_intensity_isolated() -> None:
    trace = _trace([[1, 0], [0, 1], [2, 0]], intensity_offset=0.0)
    copied_with_other_intensity = _trace(
        [[1, 0], [0, 1], [2, 0]],
        intensity_offset=999.0,
    )

    digest = compute_realized_trace_sha256(trace)
    assert digest == compute_realized_trace_sha256(trace)
    assert digest == compute_realized_trace_sha256(copied_with_other_intensity)
    assert len(digest) == 64
    assert digest == digest.lower()


def test_realized_trace_hash_canonicalizes_position_signed_zero() -> None:
    positive_zero = _single_event_trace(position_x=0.0)
    negative_zero = _single_event_trace(position_x=-0.0)

    assert compute_realized_trace_sha256(positive_zero) == compute_realized_trace_sha256(
        negative_zero
    )


def test_realized_trace_hash_canonicalizes_priority_signed_zero() -> None:
    positive_zero = _single_event_trace(priority=0.0)
    negative_zero = _single_event_trace(priority=-0.0)

    assert compute_realized_trace_sha256(positive_zero) == compute_realized_trace_sha256(
        negative_zero
    )


def test_signed_zero_repackaged_artifacts_cannot_cross_splits(tmp_path: Path) -> None:
    positive_zero = _single_event_trace(position_x=0.0, priority=0.0)
    negative_zero = _single_event_trace(position_x=-0.0, priority=-0.0)
    _, artifact_a = _save_verified_artifact(
        tmp_path,
        positive_zero,
        trace_id="signed-zero-train",
        seed=7,
        filename="signed-zero-a.npz",
    )
    _, artifact_b = _save_verified_artifact(
        tmp_path,
        negative_zero,
        trace_id="signed-zero-test",
        seed=8,
        filename="signed-zero-b.npz",
    )

    assert artifact_a.source.content_sha256 != artifact_b.source.content_sha256
    assert artifact_a.source.realized_trace_sha256 == artifact_b.source.realized_trace_sha256
    with pytest.raises(ValueError, match="realized_trace_sha256"):
        build_split_manifest_from_artifacts(
            (
                (SplitLabel.TRAIN, artifact_a),
                (SplitLabel.TEST_ID, artifact_b),
            ),
            _spec(),
        )


def test_realized_trace_hash_changes_with_realized_content() -> None:
    trace = _trace([[1, 0], [0, 1], [2, 0]])
    changed_count = _trace([[0, 1], [0, 1], [2, 0]])
    changed_events = list(trace.events)
    changed_events[0] = replace(changed_events[0], priority=0.75)
    changed_event = DemandTrace(
        trace.start_step,
        trace.counts,
        trace.intensities,
        tuple(changed_events),
    )
    changed_position_events = list(trace.events)
    changed_position_events[0] = replace(changed_position_events[0], position=(0.25, 0.5))
    changed_position = DemandTrace(
        trace.start_step,
        trace.counts,
        trace.intensities,
        tuple(changed_position_events),
    )
    empty_at_five = _trace([[0, 0]], start_step=5)
    empty_at_six = _trace([[0, 0]], start_step=6)

    assert compute_realized_trace_sha256(trace) != compute_realized_trace_sha256(changed_count)
    assert compute_realized_trace_sha256(trace) != compute_realized_trace_sha256(changed_event)
    assert compute_realized_trace_sha256(trace) != compute_realized_trace_sha256(changed_position)
    assert compute_realized_trace_sha256(empty_at_five) != compute_realized_trace_sha256(
        empty_at_six
    )


def test_split_manifest_canonicalizes_order_and_allows_id_condition_reuse() -> None:
    trace = _trace([[0, 0], [0, 0]])
    condition = "c" * 64
    train = SplitEntry(
        SplitLabel.TRAIN,
        _source(trace, trace_id="train", seed=1, condition=condition),
    )
    test_id = SplitEntry(
        SplitLabel.TEST_ID,
        _source(trace, trace_id="test", seed=2, condition=condition, content="d" * 64),
    )
    first = DatasetSplitManifest((test_id, train))
    second = DatasetSplitManifest((train, test_id))

    assert first == second
    assert first.sha256 == second.sha256
    assert tuple(entry.split for entry in first.entries) == (SplitLabel.TRAIN, SplitLabel.TEST_ID)


@pytest.mark.parametrize(
    "duplicate_field",
    ["trace_id", "content_sha256", "realized_trace_sha256", "seed"],
)
def test_split_manifest_rejects_global_identity_leakage(duplicate_field: str) -> None:
    trace = _trace([[0, 0], [0, 0]])
    train_source = _source(trace, trace_id="train", seed=1, content="1" * 64)
    test_source = _source(trace, trace_id="test", seed=2, content="2" * 64)
    test_source = replace(test_source, **{duplicate_field: getattr(train_source, duplicate_field)})

    with pytest.raises(ValueError, match=duplicate_field):
        DatasetSplitManifest(
            (
                SplitEntry(SplitLabel.TRAIN, train_source),
                SplitEntry(SplitLabel.TEST_ID, test_source),
            )
        )


def test_split_manifest_rejects_ood_condition_overlap_and_allows_heldout_condition() -> None:
    trace = _trace([[0, 0], [0, 0]])
    train = SplitEntry(SplitLabel.TRAIN, _source(trace, trace_id="train", seed=1))
    overlapping_ood = SplitEntry(
        SplitLabel.TEST_OOD,
        _source(trace, trace_id="ood", seed=2, content="2" * 64),
    )
    with pytest.raises(ValueError, match="test_ood condition"):
        DatasetSplitManifest((train, overlapping_ood))

    heldout = replace(
        overlapping_ood,
        source=replace(overlapping_ood.source, condition_sha256="e" * 64),
    )
    manifest = DatasetSplitManifest((train, heldout))
    assert {entry.split for entry in manifest.entries} == {SplitLabel.TRAIN, SplitLabel.TEST_OOD}
