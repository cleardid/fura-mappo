"""WP-03 ES-01 safe no-pickle checkpoint directory tests。"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import zipfile
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pytest

import fura_mappo.prediction.checkpoint as checkpoint_module
from fura_mappo.prediction import (
    OfficialCheckpoint,
    OfficialCheckpointManifest,
    OfficialLearnedTrainingConfig,
    load_official_checkpoint,
    load_official_point_experiment_spec,
    plan_official_learned_configs,
    write_official_checkpoint,
)

_SPEC_PATH = Path("configs/experiments/wp03_point_primary_v1.yaml")
_LEARNED_CONFIG = plan_official_learned_configs(load_official_point_experiment_spec(_SPEC_PATH))[0]
_WEIGHT_NAMES = (
    "linear1.weight",
    "linear1.bias",
    "linear2.weight",
    "linear2.bias",
    "output.weight",
    "output.bias",
)


def _weights(*, history_length: int = 4, hidden_width: int = 64) -> dict[str, np.ndarray]:
    input_dimension = 5 * history_length + 1
    shapes = {
        "linear1.weight": (hidden_width, input_dimension),
        "linear1.bias": (hidden_width,),
        "linear2.weight": (hidden_width, hidden_width),
        "linear2.bias": (hidden_width,),
        "output.weight": (8, hidden_width),
        "output.bias": (8,),
    }
    result: dict[str, np.ndarray] = {}
    offset = 0
    for name in _WEIGHT_NAMES:
        size = int(np.prod(shapes[name]))
        values = np.arange(offset, offset + size, dtype=np.float32).reshape(shapes[name])
        result[name] = np.ascontiguousarray(values / np.float32(1000.0))
        offset += size
    return result


def _write(
    path: Path,
    weights: Mapping[str, np.ndarray] | None = None,
    learned_config: OfficialLearnedTrainingConfig = _LEARNED_CONFIG,
    epoch: int = 7,
) -> Path:
    return write_official_checkpoint(
        path,
        learned_config=learned_config,
        training_seed=610001,
        epoch=epoch,
        validation_primary_rmse=0.125,
        runtime_provenance_sha256="e" * 64,
        weights=(
            _weights(
                history_length=learned_config.history_length,
                hidden_width=learned_config.hidden_width,
            )
            if weights is None
            else weights
        ),
    )


def _rewrite_npz(
    checkpoint: Path,
    arrays: Mapping[str, np.ndarray],
) -> None:
    weights_path = checkpoint / "weights.npz"
    replacement = checkpoint / "replacement.npz"
    with replacement.open("xb") as stream:
        np.savez(stream, **arrays)
    os.replace(replacement, weights_path)


def _manifest(checkpoint: Path) -> dict[str, object]:
    return json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(checkpoint: Path, value: Mapping[str, object]) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    (checkpoint / "manifest.json").write_text(payload + "\n", encoding="utf-8")


def _manifest_constructor_kwargs() -> dict[str, object]:
    config = _LEARNED_CONFIG
    return {
        "official_spec_sha256": config.official_spec_sha256,
        "config_sha256": config.config_sha256,
        "protocol_sha256": config.protocol_sha256,
        "training_plan_sha256": config.training_plan_sha256,
        "rng_namespace_plan_sha256": config.rng_namespace_plan_sha256,
        "objective": config.objective.value,
        "transform": config.transform.value,
        "learning_rate": config.learning_rate,
        "canonical_order": config.canonical_order,
        "feature_encoding_sha256": config.feature_encoding_sha256,
        "architecture_sha256": config.architecture_sha256,
        "model_complexity_key": config.model_complexity_key,
        "training_seed": 610001,
        "epoch": 1,
        "validation_primary_rmse": 0.0,
        "history_length": config.history_length,
        "hidden_width": config.hidden_width,
        "input_dimension": 5 * config.history_length + 1,
        "output_dimension": 8,
        "runtime_provenance_sha256": "e" * 64,
        "checkpoint_content_sha256": "f" * 64,
    }


def _append_trailing_bytes_to_npy_member(checkpoint: Path, member_name: str) -> None:
    weights_path = checkpoint / "weights.npz"
    replacement = checkpoint / "replacement.npz"
    with zipfile.ZipFile(weights_path, "r") as source:
        members = {name: source.read(name) for name in source.namelist()}
    assert set(members) == {f"{name}.npy" for name in _WEIGHT_NAMES}
    members[member_name] += b"adversarial trailing bytes"
    with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in members.items():
            target.writestr(name, payload)
    os.replace(replacement, weights_path)


def test_atomic_noreplace_rejects_existing_empty_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    destination_inode_before = destination.stat().st_ino

    with pytest.raises(FileExistsError):
        checkpoint_module._rename_directory_noreplace(source, destination)

    assert source.is_dir()
    assert destination.is_dir()
    assert destination.stat().st_ino == destination_inode_before


def test_atomic_noreplace_rejects_existing_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.write_bytes(b"preserve existing file")

    with pytest.raises(FileExistsError):
        checkpoint_module._rename_directory_noreplace(source, destination)

    assert source.is_dir()
    assert destination.read_bytes() == b"preserve existing file"


def test_atomic_noreplace_rejects_existing_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    link_target = tmp_path / "link-target"
    destination = tmp_path / "destination"
    source.mkdir()
    link_target.mkdir()
    try:
        destination.symlink_to(link_target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation unsupported: {error}")
    destination_inode_before = destination.lstat().st_ino
    link_value_before = os.readlink(destination)

    with pytest.raises(FileExistsError):
        checkpoint_module._rename_directory_noreplace(source, destination)

    assert source.is_dir()
    assert destination.is_symlink()
    assert destination.lstat().st_ino == destination_inode_before
    assert os.readlink(destination) == link_value_before


def test_atomic_noreplace_unsupported_platform_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    monkeypatch.setattr(checkpoint_module, "_current_platform", lambda: "unsupported")

    with pytest.raises(OSError) as captured:
        checkpoint_module._rename_directory_noreplace(source, destination)

    assert captured.value.errno == errno.ENOTSUP
    assert source.is_dir()
    assert not destination.exists()


def test_atomic_noreplace_missing_platform_primitive_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    monkeypatch.setattr(checkpoint_module, "_current_platform", lambda: "darwin")
    monkeypatch.setattr(checkpoint_module, "_load_process_libc", lambda: object())

    with pytest.raises(OSError) as captured:
        checkpoint_module._rename_directory_noreplace(source, destination)

    assert captured.value.errno == errno.ENOTSUP
    assert source.is_dir()
    assert not destination.exists()


def test_writer_atomic_publication_does_not_depend_on_precheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "model.ckpt"
    destination.mkdir()
    destination_inode_before = destination.stat().st_ino
    monkeypatch.setattr(checkpoint_module, "_check_checkpoint_target_absent", lambda _path: None)

    with pytest.raises(FileExistsError):
        _write(destination)

    assert destination.is_dir()
    assert destination.stat().st_ino == destination_inode_before
    assert list(destination.iterdir()) == []
    assert list(tmp_path.iterdir()) == [destination]


def test_checkpoint_roundtrip_is_no_overwrite_and_defensive(tmp_path: Path) -> None:
    inputs = _weights()
    target = tmp_path / "model.ckpt"
    assert _write(target, inputs) == target

    checkpoint = load_official_checkpoint(target)
    assert isinstance(checkpoint, OfficialCheckpoint)
    assert checkpoint.manifest.config_sha256 == _LEARNED_CONFIG.config_sha256
    assert checkpoint.manifest.protocol_sha256 == _LEARNED_CONFIG.protocol_sha256
    assert checkpoint.manifest.objective == _LEARNED_CONFIG.objective.value
    assert checkpoint.manifest.transform == _LEARNED_CONFIG.transform.value
    assert checkpoint.manifest.model_complexity_key == _LEARNED_CONFIG.model_complexity_key
    assert checkpoint.manifest.validation_primary_rmse == 0.125
    assert checkpoint.manifest.input_dimension == 21
    assert checkpoint.manifest.output_dimension == 8
    for name in _WEIGHT_NAMES:
        assert np.array_equal(checkpoint.weights[name], inputs[name])
        assert not checkpoint.weights[name].flags.writeable

    inputs["output.bias"][:] = -1.0
    assert np.all(checkpoint.weights["output.bias"] >= 0.0)
    with pytest.raises(ValueError, match="read-only"):
        checkpoint.weights["output.bias"][0] = 1.0
    with pytest.raises(TypeError):
        checkpoint.weights["extra"] = np.zeros(1, dtype=np.float32)  # type: ignore[index]
    with pytest.raises(FileExistsError):
        _write(target)


def test_logical_digest_ignores_raw_npz_container_identity(tmp_path: Path) -> None:
    first = tmp_path / "first.ckpt"
    second = tmp_path / "second.ckpt"
    _write(first)
    _write(second)
    digest = load_official_checkpoint(first).manifest.checkpoint_content_sha256

    second_weights = second / "weights.npz"
    before = hashlib.sha256(second_weights.read_bytes()).hexdigest()
    with zipfile.ZipFile(second_weights, "a") as archive:
        archive.comment = b"different raw ZIP bytes; logical arrays unchanged"
    after = hashlib.sha256(second_weights.read_bytes()).hexdigest()

    assert before != after
    assert load_official_checkpoint(second).manifest.checkpoint_content_sha256 == digest


def test_npy_member_trailing_bytes_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "trailing.ckpt"
    _write(target)
    _append_trailing_bytes_to_npy_member(target, "linear1.weight.npy")

    with pytest.raises(ValueError, match="trailing"):
        load_official_checkpoint(target)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_missing_or_extra_npz_member_is_rejected(tmp_path: Path, mutation: str) -> None:
    target = tmp_path / f"{mutation}.ckpt"
    _write(target)
    arrays = _weights()
    if mutation == "missing":
        arrays.pop("output.bias")
    else:
        arrays["unexpected"] = np.zeros(1, dtype=np.float32)
    _rewrite_npz(target, arrays)

    with pytest.raises(ValueError, match="members"):
        load_official_checkpoint(target)


@pytest.mark.parametrize("mutation", ["shape", "dtype", "fortran", "nan", "inf", "object"])
def test_invalid_npz_array_is_rejected(tmp_path: Path, mutation: str) -> None:
    target = tmp_path / f"{mutation}.ckpt"
    _write(target)
    arrays = _weights()
    if mutation == "shape":
        arrays["output.bias"] = np.zeros(7, dtype=np.float32)
    elif mutation == "dtype":
        arrays["output.bias"] = np.zeros(8, dtype=np.float64)
    elif mutation == "fortran":
        arrays["linear1.weight"] = np.asfortranarray(arrays["linear1.weight"])
    elif mutation == "nan":
        arrays["output.bias"][0] = np.nan
    elif mutation == "inf":
        arrays["output.bias"][0] = np.inf
    else:
        arrays["output.bias"] = np.asarray([object()] * 8, dtype=object)
    _rewrite_npz(target, arrays)

    with pytest.raises(ValueError):
        load_official_checkpoint(target)


def test_writer_rejects_invalid_arrays_before_publication(tmp_path: Path) -> None:
    invalid = _weights()
    invalid["linear1.weight"] = np.asfortranarray(invalid["linear1.weight"])
    invalid["linear2.bias"][0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        _write(tmp_path / "invalid.ckpt", invalid)
    assert not (tmp_path / "invalid.ckpt").exists()


def test_symlink_checkpoint_and_member_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "real.ckpt"
    _write(target)
    directory_link = tmp_path / "directory-link.ckpt"
    directory_link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        load_official_checkpoint(directory_link)

    member_target = tmp_path / "member.ckpt"
    _write(member_target)
    manifest = member_target / "manifest.json"
    saved = tmp_path / "saved-manifest.json"
    manifest.rename(saved)
    manifest.symlink_to(saved)
    with pytest.raises(ValueError, match="符号链接"):
        load_official_checkpoint(member_target)


def test_manifest_corruption_and_hash_corruption_are_rejected(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.ckpt"
    _write(malformed)
    manifest_path = malformed / "manifest.json"
    manifest_path.write_text('{"not":"the manifest"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="field set"):
        load_official_checkpoint(malformed)

    noncanonical = tmp_path / "noncanonical.ckpt"
    _write(noncanonical)
    value = _manifest(noncanonical)
    (noncanonical / "manifest.json").write_text(
        json.dumps(value, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="canonical"):
        load_official_checkpoint(noncanonical)

    wrong_hash = tmp_path / "wrong-hash.ckpt"
    _write(wrong_hash)
    value = _manifest(wrong_hash)
    value["checkpoint_content_sha256"] = "f" * 64
    _write_manifest(wrong_hash, value)
    with pytest.raises(ValueError, match="logical content SHA"):
        load_official_checkpoint(wrong_hash)


def test_manifest_size_limit_is_enforced(tmp_path: Path) -> None:
    target = tmp_path / "oversized.ckpt"
    _write(target)
    with (target / "manifest.json").open("wb") as stream:
        stream.write(b" " * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="1 MiB"):
        load_official_checkpoint(target)


def test_invalid_runtime_sha_is_rejected_without_publication(tmp_path: Path) -> None:
    target = tmp_path / "invalid-sha.ckpt"
    with pytest.raises(ValueError, match="SHA-256"):
        write_official_checkpoint(
            target,
            learned_config=_LEARNED_CONFIG,
            training_seed=610001,
            epoch=7,
            validation_primary_rmse=0.125,
            runtime_provenance_sha256="NOT-A-SHA",
            weights=_weights(),
        )
    assert not target.exists()


@pytest.mark.parametrize("epoch", [1, 300])
def test_manifest_accepts_authoritative_epoch_boundaries(epoch: int) -> None:
    values = _manifest_constructor_kwargs()
    values["epoch"] = epoch

    manifest = OfficialCheckpointManifest(**values)  # type: ignore[arg-type]

    assert manifest.epoch == epoch


@pytest.mark.parametrize("epoch", [0, 301, True])
def test_manifest_rejects_epoch_outside_authoritative_plan(epoch: object) -> None:
    values = _manifest_constructor_kwargs()
    values["epoch"] = epoch

    with pytest.raises((TypeError, ValueError)):
        OfficialCheckpointManifest(**values)  # type: ignore[arg-type]


def test_writer_rejects_epoch_above_authoritative_plan_without_residue(tmp_path: Path) -> None:
    target = tmp_path / "epoch-301.ckpt"

    with pytest.raises(ValueError, match="max_epochs"):
        _write(target, epoch=301)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_strict_reader_rejects_hash_consistent_epoch_above_plan(tmp_path: Path) -> None:
    target = tmp_path / "epoch-corruption.ckpt"
    _write(target, epoch=300)
    value = _manifest(target)
    value["epoch"] = 301
    identity = dict(value)
    identity.pop("checkpoint_content_sha256")
    value["checkpoint_content_sha256"] = checkpoint_module._logical_content_sha256(
        identity,
        _weights(),
    )
    _write_manifest(target, value)

    with pytest.raises(ValueError, match="max_epochs"):
        load_official_checkpoint(target)


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        pytest.param("config_sha256", "0" * 64, id="wrong-config-sha"),
        pytest.param("protocol_sha256", "0" * 64, id="wrong-protocol-sha"),
        pytest.param("training_plan_sha256", "0" * 64, id="wrong-training-plan-sha"),
        pytest.param("rng_namespace_plan_sha256", "0" * 64, id="wrong-rng-plan-sha"),
        pytest.param("objective", "O1", id="wrong-objective"),
        pytest.param("transform", "T1", id="wrong-transform"),
        pytest.param("learning_rate", 0.001, id="wrong-learning-rate"),
        pytest.param("canonical_order", 1, id="wrong-canonical-order"),
        pytest.param(
            "model_complexity_key",
            [_LEARNED_CONFIG.model_complexity_key[0] + 1],
            id="wrong-model-complexity-key",
        ),
        pytest.param("history_length", 8, id="history-length-config-mismatch"),
        pytest.param("hidden_width", 128, id="hidden-width-config-mismatch"),
        pytest.param("feature_encoding_sha256", "0" * 64, id="wrong-feature-encoding-sha"),
        pytest.param("architecture_sha256", "0" * 64, id="wrong-architecture-sha"),
    ],
)
def test_strict_reader_rejects_each_frozen_config_identity_mutation(
    tmp_path: Path,
    field: str,
    wrong_value: object,
) -> None:
    target = tmp_path / f"{field}.ckpt"
    _write(target)
    value = _manifest(target)
    value[field] = wrong_value
    _write_manifest(target, value)

    with pytest.raises((TypeError, ValueError)):
        load_official_checkpoint(target)


def test_public_manifest_constructor_rejects_arbitrary_official_hashes() -> None:
    values = _manifest_constructor_kwargs()
    values["config_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="config_sha256"):
        OfficialCheckpointManifest(**values)  # type: ignore[arg-type]


def test_manifest_version_rejects_bool_as_integer() -> None:
    values = _manifest_constructor_kwargs()
    values["version"] = True
    with pytest.raises(ValueError, match="schema/version"):
        OfficialCheckpointManifest(**values)  # type: ignore[arg-type]
