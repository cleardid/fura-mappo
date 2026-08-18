from __future__ import annotations

import io
import json
import random
import struct
import warnings
import zipfile
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

import fura_mappo.demand.serialization as serialization_module
from fura_mappo.demand.config import compute_config_hash, load_demand_config
from fura_mappo.demand.factory import create_demand_process
from fura_mappo.demand.models import DemandEvent, DemandTrace
from fura_mappo.demand.serialization import (
    DemandTraceArtifact,
    load_demand_trace,
    save_demand_trace,
)

_REAL_RUNTIME_MANIFEST = serialization_module._runtime_manifest


def _config(num_steps: int = 2, intensity: float = 1.0) -> dict[str, object]:
    return {
        "schema": "fura-mappo.demand-generation",
        "version": 1,
        "demand": {
            "type": "stationary_poisson",
            "seed": 17,
            "intensities": [intensity, intensity],
            "zone_bounds": [[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]],
            "priority_range": [0.2, 0.8],
            "service_time_range": [1, 3],
            "deadline_offset_range": [2, 4],
        },
        "generation": {"num_steps": num_steps},
    }


def _trace() -> DemandTrace:
    events = (
        DemandEvent(10, 3, 0, (0.25, 0.75), 0.3, 2, 6),
        DemandEvent(11, 3, 1, (1.25, 0.5), 0.7, 3, 7),
        DemandEvent(12, 4, 1, (1.75, 0.25), 0.4, 1, 6),
    )
    return DemandTrace(
        start_step=3,
        counts=np.array([[1, 1], [0, 1]], dtype=np.int64),
        intensities=np.array([[0.5, 1.0], [0.5, 1.0]], dtype=np.float64),
        events=events,
    )


@pytest.fixture(autouse=True)
def _stable_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        serialization_module,
        "_collect_git_state",
        lambda: ("e44855d0256234724b9320122454da0d25be13d1", False),
    )
    monkeypatch.setattr(
        serialization_module,
        "_runtime_manifest",
        lambda: {
            "python": {"version": "3.11.0", "implementation": "CPython"},
            "platform": {"system": "TestOS", "release": "1", "machine": "test"},
            "numpy": np.__version__,
            "pyyaml": "6.0",
            "conda_environment": "test",
        },
    )


def _assert_traces_equal(left: DemandTrace, right: DemandTrace) -> None:
    assert left.start_step == right.start_step
    np.testing.assert_array_equal(left.counts, right.counts)
    np.testing.assert_array_equal(left.intensities, right.intensities)
    assert left.events == right.events


def _zip_payloads(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path, "r") as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def _write_payloads(
    path: Path,
    payloads: dict[str, bytes],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> None:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)


def _npy_bytes(array: np.ndarray, *, allow_pickle: bool = False) -> bytes:
    stream = io.BytesIO()
    np.save(stream, array, allow_pickle=allow_pickle)
    return stream.getvalue()


def _rewrite_manifest(path: Path, transform: object) -> None:
    payloads = _zip_payloads(path)
    manifest_array = np.load(io.BytesIO(payloads["manifest.npy"]), allow_pickle=False)
    manifest = json.loads(manifest_array.tobytes().decode("utf-8"))
    transformed = transform(manifest)  # type: ignore[operator]
    manifest_bytes = json.dumps(
        transformed, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payloads["manifest.npy"] = _npy_bytes(np.frombuffer(manifest_bytes, dtype=np.uint8))
    _write_payloads(path, payloads)


@pytest.mark.parametrize(
    "name", ["stationary_poisson", "drifting_hotspot", "markov_switching", "burst"]
)
def test_all_four_processes_round_trip_exactly(tmp_path: Path, name: str) -> None:
    config = load_demand_config(Path("configs/demand") / f"{name}.yaml")
    process = create_demand_process(config["demand"])  # type: ignore[arg-type]
    trace = process.generate(config["generation"]["num_steps"])  # type: ignore[index]
    path = tmp_path / f"{name}.npz"

    returned = save_demand_trace(path, trace, resolved_config=config)
    artifact = load_demand_trace(path)

    assert returned == path
    _assert_traces_equal(artifact.trace, trace)
    assert artifact.manifest["process_type"] == name


def test_exact_member_order_dtypes_shapes_manifest_and_event_columns(tmp_path: Path) -> None:
    path = tmp_path / "trace.npz"
    save_demand_trace(path, _trace(), resolved_config=_config())

    with zipfile.ZipFile(path, "r") as archive:
        assert tuple(info.filename for info in archive.infolist()) == tuple(
            f"{name}.npy" for name in serialization_module._MEMBER_ORDER
        )
        arrays = {
            name: np.load(io.BytesIO(archive.read(f"{name}.npy")), allow_pickle=False)
            for name in serialization_module._MEMBER_ORDER
        }

    assert arrays["counts"].dtype.str == "<i8"
    assert arrays["intensities"].dtype.str == "<f8"
    assert arrays["positions"].shape == (3, 2)
    assert arrays["manifest"].dtype == np.uint8
    np.testing.assert_array_equal(arrays["event_id"], [10, 11, 12])
    np.testing.assert_array_equal(arrays["arrival_step"], [3, 3, 4])
    np.testing.assert_array_equal(arrays["zone_id"], [0, 1, 1])
    np.testing.assert_array_equal(arrays["positions"], [[0.25, 0.75], [1.25, 0.5], [1.75, 0.25]])
    np.testing.assert_array_equal(arrays["priority"], [0.3, 0.7, 0.4])
    np.testing.assert_array_equal(arrays["service_time"], [2, 3, 1])
    np.testing.assert_array_equal(arrays["deadline"], [6, 7, 6])

    manifest = load_demand_trace(path).manifest
    assert set(manifest) == serialization_module._MANIFEST_FIELDS
    assert manifest["schema"] == "fura-mappo.demand-trace"
    assert manifest["version"] == 1
    assert manifest["start_step"] == 3
    assert manifest["num_steps"] == 2
    assert manifest["num_zones"] == 2
    assert manifest["num_events"] == 3
    assert manifest["config_sha256"] == compute_config_hash(_config())
    assert manifest["content_hash_algorithm"] == "sha256-logical-v1"


def test_zero_event_shapes_and_high_compression_are_accepted(tmp_path: Path) -> None:
    config = _config(num_steps=500, intensity=0.0)
    trace = create_demand_process(config["demand"]).generate(500)  # type: ignore[arg-type]
    path = tmp_path / "zeros.npz"

    save_demand_trace(path, trace, resolved_config=config)
    artifact = load_demand_trace(path)

    assert artifact.trace.events == ()
    with zipfile.ZipFile(path, "r") as archive:
        positions = np.load(io.BytesIO(archive.read("positions.npy")), allow_pickle=False)
        event_id = np.load(io.BytesIO(archive.read("event_id.npy")), allow_pickle=False)
    assert positions.shape == (0, 2)
    assert event_id.shape == (0,)


def test_artifact_defensively_freezes_manifest() -> None:
    source = {"nested": {"items": [1, 2]}}
    artifact = DemandTraceArtifact(trace=_trace(), manifest=source)
    source["nested"]["items"][0] = 99  # type: ignore[index]

    assert artifact.manifest["nested"]["items"] == (1, 2)  # type: ignore[index]
    assert isinstance(artifact.manifest, MappingProxyType)
    with pytest.raises(TypeError):
        artifact.manifest["new"] = 1  # type: ignore[index]


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        (None, None),
        ("", None),
        ("fura-mappo", "fura-mappo"),
        ("base", "base"),
        ("/Users/alice/miniconda3/envs/fura-mappo", "fura-mappo"),
        (r"C:\Users\alice\miniconda3\envs\fura-mappo", "fura-mappo"),
        ("relative/envs/research/", "research"),
        (r"relative\envs\research\\", "research"),
    ],
)
def test_runtime_manifest_records_only_conda_environment_name(
    monkeypatch: pytest.MonkeyPatch,
    environment: str | None,
    expected: str | None,
) -> None:
    if environment is None:
        monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)
    else:
        monkeypatch.setenv("CONDA_DEFAULT_ENV", environment)

    recorded = _REAL_RUNTIME_MANIFEST()["conda_environment"]

    assert recorded == expected
    if recorded is not None:
        assert "/" not in recorded and "\\" not in recorded
        assert "alice" not in recorded


@pytest.mark.parametrize("environment", ["fura-mappo", None])
def test_reader_accepts_conda_environment_name_or_null(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment: str | None,
) -> None:
    runtime = {
        "python": {"version": "3.11.0", "implementation": "CPython"},
        "platform": {"system": "TestOS", "release": "1", "machine": "test"},
        "numpy": np.__version__,
        "pyyaml": "6.0",
        "conda_environment": environment,
    }
    monkeypatch.setattr(serialization_module, "_runtime_manifest", lambda: runtime)
    path = tmp_path / "trace.npz"

    save_demand_trace(path, _trace(), resolved_config=_config())
    artifact = load_demand_trace(path)

    assert artifact.manifest["runtime"]["conda_environment"] == environment  # type: ignore[index]


@pytest.mark.parametrize(
    "environment",
    [
        "/Users/alice/miniconda3/envs/fura-mappo",
        r"C:\Users\alice\miniconda3\envs\fura-mappo",
        "relative/envs/fura-mappo",
        r"relative\envs\fura-mappo",
        "",
    ],
)
def test_reader_rejects_pathlike_or_empty_conda_environment(
    tmp_path: Path,
    environment: str,
) -> None:
    path = tmp_path / "trace.npz"
    save_demand_trace(path, _trace(), resolved_config=_config())

    def replace_environment(manifest: dict[str, object]) -> dict[str, object]:
        runtime = manifest["runtime"]
        assert isinstance(runtime, dict)
        runtime["conda_environment"] = environment
        return manifest

    _rewrite_manifest(path, replace_environment)

    with pytest.raises(ValueError, match="conda_environment"):
        load_demand_trace(path)


def test_save_validates_paths_config_trace_and_int64_events(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        save_demand_trace(b"trace.npz", _trace(), resolved_config=_config())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=".npz"):
        save_demand_trace(tmp_path / "trace.NPZ", _trace(), resolved_config=_config())
    with pytest.raises(FileNotFoundError):
        save_demand_trace(tmp_path / "missing" / "trace.npz", _trace(), resolved_config=_config())
    with pytest.raises(TypeError):
        save_demand_trace(tmp_path / "trace.npz", object(), resolved_config=_config())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="num_steps"):
        save_demand_trace(tmp_path / "trace.npz", _trace(), resolved_config=_config(3))

    too_large = DemandTrace(
        0,
        [[1]],
        [[1.0]],
        (DemandEvent(2**63, 0, 0, (0.0, 0.0), 0.5, 1, 1),),
    )
    one_zone_config = _config(1)
    one_zone_demand = dict(one_zone_config["demand"])  # type: ignore[arg-type]
    one_zone_demand["intensities"] = [1.0]
    one_zone_demand["zone_bounds"] = [[0.0, 1.0, 0.0, 1.0]]
    one_zone_config["demand"] = one_zone_demand
    with pytest.raises(ValueError, match="int64"):
        save_demand_trace(tmp_path / "large.npz", too_large, resolved_config=one_zone_config)


def test_existing_targets_overwrite_and_symlink_policy(tmp_path: Path) -> None:
    path = tmp_path / "trace.npz"
    path.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        save_demand_trace(path, _trace(), resolved_config=_config())
    assert path.read_bytes() == b"original"

    save_demand_trace(path, _trace(), resolved_config=_config(), overwrite=True)
    _assert_traces_equal(load_demand_trace(path).trace, _trace())

    link = tmp_path / "link.npz"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="符号链接"):
        save_demand_trace(link, _trace(), resolved_config=_config(), overwrite=True)
    dangling = tmp_path / "dangling.npz"
    dangling.symlink_to(tmp_path / "missing-target")
    with pytest.raises(ValueError, match="符号链接"):
        save_demand_trace(dangling, _trace(), resolved_config=_config())


def test_atomic_write_link_and_replace_failures_cleanup_and_preserve_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trace.npz"

    def fail_write(stream: object, arrays: object) -> None:
        raise OSError("injected write failure")

    monkeypatch.setattr(serialization_module, "_write_npz", fail_write)
    with pytest.raises(OSError, match="injected"):
        save_demand_trace(path, _trace(), resolved_config=_config())
    assert not path.exists()
    assert not list(tmp_path.glob(".trace.npz.*.tmp"))

    monkeypatch.undo()

    def fail_link(source: object, target: object) -> None:
        raise OSError("link")

    monkeypatch.setattr(serialization_module.os, "link", fail_link)
    with pytest.raises(OSError, match="link"):
        save_demand_trace(path, _trace(), resolved_config=_config())
    assert not path.exists()
    assert not list(tmp_path.glob(".trace.npz.*.tmp"))

    monkeypatch.undo()
    path.write_bytes(b"original")

    def fail_replace(source: object, target: object) -> None:
        raise OSError("replace")

    monkeypatch.setattr(serialization_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace"):
        save_demand_trace(path, _trace(), resolved_config=_config(), overwrite=True)
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob(".trace.npz.*.tmp"))


@pytest.mark.parametrize("stage", ["fsync", "validation"])
def test_prepublication_failures_leave_no_target_and_cleanup_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    path = tmp_path / "trace.npz"
    if stage == "fsync":
        monkeypatch.setattr(
            serialization_module.os,
            "fsync",
            lambda descriptor: (_ for _ in ()).throw(OSError("fsync")),
        )
    else:
        monkeypatch.setattr(
            serialization_module,
            "_load_demand_trace_path",
            lambda temporary: (_ for _ in ()).throw(ValueError("validation")),
        )

    with pytest.raises((OSError, ValueError), match=stage):
        save_demand_trace(path, _trace(), resolved_config=_config())

    assert not path.exists()
    assert not list(tmp_path.glob(".trace.npz.*.tmp"))


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "directory", "bzip2"])
def test_reader_rejects_invalid_zip_member_sets(tmp_path: Path, mutation: str) -> None:
    source = tmp_path / "source.npz"
    target = tmp_path / "invalid.npz"
    save_demand_trace(source, _trace(), resolved_config=_config())
    payloads = _zip_payloads(source)
    if mutation == "missing":
        payloads.pop("counts.npy")
        _write_payloads(target, payloads)
    elif mutation == "extra":
        payloads["extra.npy"] = b"extra"
        _write_payloads(target, payloads)
    elif mutation == "duplicate":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(target, "w") as archive:
                for name, payload in payloads.items():
                    archive.writestr(name, payload)
                archive.writestr("counts.npy", payloads["counts.npy"])
    elif mutation == "directory":
        payloads["nested/"] = b""
        _write_payloads(target, payloads)
    else:
        _write_payloads(target, payloads, compression=zipfile.ZIP_BZIP2)

    with pytest.raises(ValueError):
        load_demand_trace(target)


@pytest.mark.parametrize("payload", [b"not a zip", b"PK\x03\x04", b""])
def test_reader_rejects_random_or_truncated_files(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "broken.npz"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        load_demand_trace(path)


@pytest.mark.parametrize(
    ("member", "array"),
    [
        ("counts.npy", np.array([[1, 1]], dtype=np.int32)),
        ("positions.npy", np.zeros((3,), dtype="<f8")),
        ("counts.npy", np.array([object()], dtype=object)),
    ],
)
def test_reader_rejects_wrong_dtype_shape_and_object_before_loading(
    tmp_path: Path, member: str, array: np.ndarray
) -> None:
    source = tmp_path / "source.npz"
    target = tmp_path / "invalid.npz"
    save_demand_trace(source, _trace(), resolved_config=_config())
    payloads = _zip_payloads(source)
    payloads[member] = _npy_bytes(array, allow_pickle=array.dtype == object)
    _write_payloads(target, payloads)

    with pytest.raises(ValueError, match="dtype|维度"):
        load_demand_trace(target)


def test_reader_uses_allow_pickle_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "trace.npz"
    save_demand_trace(path, _trace(), resolved_config=_config())
    calls: list[object] = []
    original = serialization_module.np.load

    def recording_load(*args: object, **kwargs: object) -> object:
        calls.append(kwargs.get("allow_pickle"))
        return original(*args, **kwargs)

    monkeypatch.setattr(serialization_module.np, "load", recording_load)
    load_demand_trace(path)
    assert calls and all(value is False for value in calls)


def test_reader_streams_members_without_zipfile_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trace.npz"
    save_demand_trace(path, _trace(), resolved_config=_config())

    def forbidden_read(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("ZipFile.read 不应加载完整成员")

    monkeypatch.setattr(zipfile.ZipFile, "read", forbidden_read)

    artifact = load_demand_trace(path)

    _assert_traces_equal(artifact.trace, _trace())


def test_reader_rejects_huge_npy_header_before_np_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.npz"
    target = tmp_path / "huge.npz"
    save_demand_trace(source, _trace(), resolved_config=_config())
    payloads = _zip_payloads(source)
    header = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        header,
        {"descr": "<i8", "fortran_order": False, "shape": (2**40, 2**40)},
    )
    payloads["counts.npy"] = header.getvalue()
    _write_payloads(target, payloads)
    calls: list[object] = []
    original = serialization_module.np.load

    def recording_load(*args: object, **kwargs: object) -> object:
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(serialization_module.np, "load", recording_load)
    with pytest.raises(ValueError, match="声明数组过大|大小不一致"):
        load_demand_trace(target)
    assert calls == []


def test_reader_rejects_encryption_flag_and_crc_corruption(tmp_path: Path) -> None:
    source = tmp_path / "source.npz"
    save_demand_trace(source, _trace(), resolved_config=_config())
    payloads = _zip_payloads(source)

    encrypted = tmp_path / "encrypted.npz"
    _write_payloads(encrypted, payloads, compression=zipfile.ZIP_STORED)
    encrypted_bytes = bytearray(encrypted.read_bytes())
    local_offset = encrypted_bytes.index(b"PK\x03\x04")
    central_offset = encrypted_bytes.index(b"PK\x01\x02")
    local_flags = struct.unpack_from("<H", encrypted_bytes, local_offset + 6)[0] | 1
    central_flags = struct.unpack_from("<H", encrypted_bytes, central_offset + 8)[0] | 1
    struct.pack_into("<H", encrypted_bytes, local_offset + 6, local_flags)
    struct.pack_into("<H", encrypted_bytes, central_offset + 8, central_flags)
    encrypted.write_bytes(encrypted_bytes)
    with pytest.raises(ValueError, match="加密"):
        load_demand_trace(encrypted)

    corrupted = tmp_path / "crc.npz"
    _write_payloads(corrupted, payloads, compression=zipfile.ZIP_STORED)
    with zipfile.ZipFile(corrupted, "r") as archive:
        info = archive.getinfo("priority.npy")
        filename_length = len(info.filename.encode("utf-8"))
        data_offset = info.header_offset + 30 + filename_length + len(info.extra)
    corrupted_bytes = bytearray(corrupted.read_bytes())
    corrupted_bytes[data_offset + info.file_size - 1] ^= 0x01
    corrupted.write_bytes(corrupted_bytes)
    with pytest.raises(ValueError, match="损坏"):
        load_demand_trace(corrupted)


def test_reader_rejects_manifest_utf8_duplicate_json_and_nonfinite(tmp_path: Path) -> None:
    source = tmp_path / "source.npz"
    save_demand_trace(source, _trace(), resolved_config=_config())
    original = _zip_payloads(source)
    for index, payload in enumerate((b"\xff", b'{"schema":"x","schema":"y"}', b'{"value":NaN}')):
        target = tmp_path / f"manifest-{index}.npz"
        changed = dict(original)
        changed["manifest.npy"] = _npy_bytes(np.frombuffer(payload, dtype=np.uint8))
        _write_payloads(target, changed)
        with pytest.raises(ValueError):
            load_demand_trace(target)


@pytest.mark.parametrize(
    "transform",
    [
        lambda manifest: {key: value for key, value in manifest.items() if key != "version"},
        lambda manifest: {**manifest, "extra": 1},
        lambda manifest: {**manifest, "schema": "unknown"},
        lambda manifest: {**manifest, "version": 2},
        lambda manifest: {**manifest, "config_sha256": "0" * 64},
        lambda manifest: {**manifest, "content_sha256": "0" * 64},
    ],
)
def test_reader_rejects_manifest_schema_and_hash_mismatches(
    tmp_path: Path, transform: object
) -> None:
    path = tmp_path / "trace.npz"
    save_demand_trace(path, _trace(), resolved_config=_config())
    _rewrite_manifest(path, transform)
    with pytest.raises(ValueError):
        load_demand_trace(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("version", "version 必须是整数"),
        ("num_steps", "generation.num_steps 必须是整数"),
        ("demand_scalar", "demand 必须是 Mapping"),
        ("demand_list", "demand 必须是 Mapping"),
    ],
)
def test_reader_converts_resolved_config_type_errors_to_value_error(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    path = tmp_path / "trace.npz"
    save_demand_trace(path, _trace(), resolved_config=_config())

    def corrupt_resolved_config(manifest: dict[str, object]) -> dict[str, object]:
        resolved = manifest["resolved_config"]
        assert isinstance(resolved, dict)
        if mutation == "version":
            resolved["version"] = "1"
        elif mutation == "num_steps":
            generation = resolved["generation"]
            assert isinstance(generation, dict)
            generation["num_steps"] = "3"
        elif mutation == "demand_scalar":
            resolved["demand"] = "stationary_poisson"
        else:
            resolved["demand"] = []
        return manifest

    _rewrite_manifest(path, corrupt_resolved_config)

    with pytest.raises(ValueError, match=message):
        load_demand_trace(path)


def test_load_path_type_and_missing_file_exceptions_remain_precise(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        load_demand_trace(b"trace.npz")  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        load_demand_trace(tmp_path / "missing.npz")


def test_reader_rejects_declared_resource_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trace.npz"
    save_demand_trace(path, _trace(), resolved_config=_config())

    monkeypatch.setattr(serialization_module, "_MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError, match="2 GiB"):
        load_demand_trace(path)
    monkeypatch.setattr(serialization_module, "_MAX_FILE_BYTES", 2 * 1024**3)
    monkeypatch.setattr(serialization_module, "_MAX_MANIFEST_MEMBER_BYTES", 1)
    with pytest.raises(ValueError, match="manifest"):
        load_demand_trace(path)
    monkeypatch.setattr(serialization_module, "_MAX_MANIFEST_MEMBER_BYTES", 4 * 1024**2)
    monkeypatch.setattr(serialization_module, "_MAX_TOTAL_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(ValueError, match="总解压"):
        load_demand_trace(path)


def test_save_and_load_do_not_pollute_global_random_states(tmp_path: Path) -> None:
    numpy_state = np.random.get_state()
    python_state = random.getstate()
    path = tmp_path / "trace.npz"

    save_demand_trace(path, _trace(), resolved_config=_config())
    load_demand_trace(path)

    current_numpy = np.random.get_state()
    assert numpy_state[0] == current_numpy[0]
    np.testing.assert_array_equal(numpy_state[1], current_numpy[1])
    assert numpy_state[2:] == current_numpy[2:]
    assert python_state == random.getstate()
