from __future__ import annotations

import json
from pathlib import Path

import pytest

from fura_mappo.experiments.h1_gate import (
    build_primary_environment_config,
    compute_environment_config_hash,
    load_h1_gate_spec,
)
from fura_mappo.prediction import (
    DatasetProtocolSpec,
    DatasetSplitManifest,
    PredictionSource,
    SplitEntry,
    SplitLabel,
    ZoneSchema,
    dataset_protocol_to_dict,
    read_dataset_protocol,
    read_split_manifest,
    split_manifest_to_dict,
    write_dataset_protocol,
    write_split_manifest,
)

_SPEC_SHA = "fc719e4634ab13ba55d0b95e63497688b3ab07c259d1421c5ed0c468cec3fade"
_ENV_SHA = "d1d856b13ac8edf79422428a96bddc03b901053dbeaabe56571e9baeef6eafa1"


def _protocol() -> DatasetProtocolSpec:
    schema = ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]])
    return DatasetProtocolSpec(4, 2, schema.sha256)


def _source(trace_id: str, seed: int, content: str, condition: str) -> PredictionSource:
    return PredictionSource(
        trace_id=trace_id,
        seed=seed,
        process_type="stationary_poisson",
        config_sha256=f"{seed:x}".rjust(64, "0"),
        content_sha256=content,
        realized_trace_sha256=f"{seed + 10:x}".rjust(64, "0"),
        condition_sha256=condition,
        zone_schema_sha256=_protocol().zone_schema_sha256,
        start_step=0,
        num_steps=8,
        num_zones=2,
    )


def _manifest() -> DatasetSplitManifest:
    return DatasetSplitManifest(
        (
            SplitEntry(SplitLabel.TEST_OOD, _source("ood", 3, "3" * 64, "e" * 64)),
            SplitEntry(SplitLabel.TEST_ID, _source("test", 2, "2" * 64, "c" * 64)),
            SplitEntry(SplitLabel.TRAIN, _source("train", 1, "1" * 64, "c" * 64)),
        )
    )


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def test_protocol_canonical_round_trip_and_no_overwrite(tmp_path: Path) -> None:
    spec = _protocol()
    path = write_dataset_protocol(tmp_path / "protocol.json", spec)

    assert path.read_bytes() == _canonical(dataset_protocol_to_dict(spec))
    assert read_dataset_protocol(path) == spec
    with pytest.raises(FileExistsError):
        write_dataset_protocol(path, spec)


def test_split_manifest_canonical_round_trip_and_order(tmp_path: Path) -> None:
    manifest = _manifest()
    path = write_split_manifest(tmp_path / "splits.json", manifest)

    assert path.read_bytes() == _canonical(split_manifest_to_dict(manifest))
    loaded = read_split_manifest(path)
    assert loaded == manifest
    assert tuple(entry.split for entry in loaded.entries) == (
        SplitLabel.TRAIN,
        SplitLabel.TEST_ID,
        SplitLabel.TEST_OOD,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": 1}),
        lambda value: value.pop("history_kind"),
        lambda value: value.update({"version": 2}),
        lambda value: value.update({"version": True}),
        lambda value: value.update({"sha256": "0" * 64}),
        lambda value: value.update({"history_length": 5}),
    ],
)
def test_protocol_reader_rejects_schema_and_hash_mutations(
    tmp_path: Path,
    mutation: object,
) -> None:
    value = dataset_protocol_to_dict(_protocol())
    mutation(value)  # type: ignore[operator]
    path = tmp_path / "bad.json"
    path.write_bytes(_canonical(value))

    with pytest.raises((TypeError, ValueError)):
        read_dataset_protocol(path)


def test_reader_rejects_duplicate_nonfinite_and_noncanonical_json(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}\n', encoding="utf-8")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}\n', encoding="utf-8")
    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text('{ "a": 1 }\n', encoding="utf-8")

    for path in (duplicate, nonfinite, noncanonical):
        with pytest.raises(ValueError):
            read_dataset_protocol(path)


def test_split_reader_rejects_unknown_nested_fields_and_noncanonical_order(
    tmp_path: Path,
) -> None:
    value = split_manifest_to_dict(_manifest())
    entries = value["entries"]
    assert isinstance(entries, list)
    first = entries[0]
    assert isinstance(first, dict)
    source = first["source"]
    assert isinstance(source, dict)
    source["unknown"] = 1
    path = tmp_path / "unknown.json"
    path.write_bytes(_canonical(value))
    with pytest.raises(ValueError, match="字段"):
        read_split_manifest(path)

    reordered = split_manifest_to_dict(_manifest())
    reordered_entries = reordered["entries"]
    assert isinstance(reordered_entries, list)
    reordered_entries.reverse()
    reordered_path = tmp_path / "reordered.json"
    reordered_path.write_bytes(_canonical(reordered))
    with pytest.raises(ValueError, match="ordering"):
        read_split_manifest(reordered_path)


def test_reader_rejects_symlink(tmp_path: Path) -> None:
    target = write_dataset_protocol(tmp_path / "target.json", _protocol())
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="符号链接"):
        read_dataset_protocol(link)


def test_wp03a_does_not_change_frozen_h1_scientific_identities() -> None:
    spec = load_h1_gate_spec(Path("configs/experiments/wp02d_h1.yaml"))

    assert spec.sha256 == _SPEC_SHA
    assert compute_environment_config_hash(build_primary_environment_config(spec)) == _ENV_SHA
