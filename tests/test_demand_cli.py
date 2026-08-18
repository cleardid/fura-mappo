from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

import fura_mappo.demand.cli as cli_module
import fura_mappo.demand.serialization as serialization_module
from fura_mappo.demand.cli import main
from fura_mappo.demand.config import compute_config_hash, load_demand_config
from fura_mappo.demand.serialization import load_demand_trace
from fura_mappo.demand.summary import summarize_demand_trace

_EXAMPLES = ("stationary_poisson", "drifting_hotspot", "markov_switching", "burst")
_COMMIT = "e44855d0256234724b9320122454da0d25be13d1"


def _example(name: str = "stationary_poisson") -> Path:
    return (Path(__file__).parents[1] / "configs" / "demand" / f"{name}.yaml").resolve()


def _patch_git(monkeypatch: pytest.MonkeyPatch, state: tuple[str | None, bool | None]) -> None:
    monkeypatch.setattr(cli_module, "_collect_git_state", lambda: state)
    monkeypatch.setattr(serialization_module, "_collect_git_state", lambda: state)


def _subprocess(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "fura_mappo.demand", *arguments],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("name", _EXAMPLES)
def test_module_cli_generate_all_four_types_with_fixed_seed(tmp_path: Path, name: str) -> None:
    output = tmp_path / f"{name}.npz"

    result = _subprocess(
        "generate",
        "--config",
        str(_example(name)),
        "--output",
        str(output),
        "--allow-dirty",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    stdout = json.loads(result.stdout)
    assert stdout["status"] == "ok"
    assert stdout["output"] == output.name
    assert len(stdout["config_sha256"]) == 64
    assert len(stdout["content_sha256"]) == 64
    assert len(stdout["file_sha256"]) == 64
    artifact = load_demand_trace(output)
    assert artifact.manifest["process_type"] == name


def test_generate_overrides_resolved_config_hash_and_preserves_yaml(tmp_path: Path) -> None:
    source = _example()
    before = source.read_bytes()
    output = tmp_path / "override.npz"

    result = _subprocess(
        "generate",
        "--config",
        str(source),
        "--seed",
        "99",
        "--num-steps",
        "3",
        "--output",
        str(output),
        "--allow-dirty",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    artifact = load_demand_trace(output)
    resolved = artifact.manifest["resolved_config"]
    assert resolved["demand"]["seed"] == 99  # type: ignore[index]
    assert resolved["generation"]["num_steps"] == 3  # type: ignore[index]
    assert artifact.trace.counts.shape[0] == 3
    assert artifact.manifest["config_sha256"] == compute_config_hash(resolved)  # type: ignore[arg-type]
    assert source.read_bytes() == before


def test_default_output_naming_and_directory_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_git(monkeypatch, (_COMMIT, False))
    monkeypatch.chdir(tmp_path)
    config = load_demand_config(_example())
    expected_hash = compute_config_hash(config)

    exit_code = main(["generate", "--config", str(_example())])

    assert exit_code == 0
    output = (
        tmp_path / "artifacts/demand" / f"stationary_poisson-s20260818-n5-{expected_hash[:12]}.npz"
    )
    assert output.is_file()
    assert json.loads(capsys.readouterr().out)["output"].startswith("artifacts/demand/")


def test_dirty_policy_precedes_generation_and_directory_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_git(monkeypatch, (_COMMIT, True))
    monkeypatch.chdir(tmp_path)

    exit_code = main(["generate", "--config", str(_example())])

    assert exit_code == 7
    assert not (tmp_path / "artifacts").exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--allow-dirty" in captured.err
    assert "Traceback" not in captured.err


def test_allow_dirty_and_git_unavailable_are_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dirty_output = tmp_path / "dirty.npz"
    _patch_git(monkeypatch, (_COMMIT, True))
    assert (
        main(
            [
                "generate",
                "--config",
                str(_example()),
                "--output",
                str(dirty_output),
                "--allow-dirty",
            ]
        )
        == 0
    )
    assert load_demand_trace(dirty_output).manifest["git_dirty"] is True
    capsys.readouterr()

    unavailable_output = tmp_path / "unavailable.npz"
    _patch_git(monkeypatch, (None, None))
    assert (
        main(
            [
                "generate",
                "--config",
                str(_example()),
                "--output",
                str(unavailable_output),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert "警告" in captured.err and str(tmp_path) not in captured.err
    manifest = load_demand_trace(unavailable_output).manifest
    assert manifest["git_commit"] is None and manifest["git_dirty"] is None


def test_explicit_output_parent_existing_force_and_symlink_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_git(monkeypatch, (_COMMIT, False))
    missing = tmp_path / "missing" / "trace.npz"
    base_args = ["generate", "--config", str(_example()), "--output"]
    assert main([*base_args, str(missing)]) == 6
    assert not missing.parent.exists()
    capsys.readouterr()

    output = tmp_path / "trace.npz"
    assert main([*base_args, str(output)]) == 0
    first = output.read_bytes()
    capsys.readouterr()
    assert main([*base_args, str(output)]) == 5
    assert output.read_bytes() == first
    capsys.readouterr()
    assert main([*base_args, str(output), "--force"]) == 0
    capsys.readouterr()

    link = tmp_path / "link.npz"
    link.symlink_to(output)
    assert main([*base_args, str(link), "--force"]) == 6
    captured = capsys.readouterr()
    assert str(tmp_path) not in captured.err


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (("generate", "--config", "missing.yaml"), 6),
        (("generate", "--config", "config.txt"), 3),
        (("generate", "--config", "missing.yaml", "--num-steps", "0"), 6),
    ],
)
def test_generate_error_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
    expected: int,
) -> None:
    _patch_git(monkeypatch, (_COMMIT, False))
    monkeypatch.chdir(tmp_path)
    assert main(list(arguments)) == expected
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_invalid_override_is_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_git(monkeypatch, (_COMMIT, False))
    assert main(["generate", "--config", str(_example()), "--num-steps", "0"]) == 3
    assert "num_steps" in capsys.readouterr().err


def test_summarize_stdout_matches_public_function(tmp_path: Path) -> None:
    artifact_path = tmp_path / "trace.npz"
    generated = _subprocess(
        "generate",
        "--config",
        str(_example()),
        "--output",
        str(artifact_path),
        "--allow-dirty",
        cwd=tmp_path,
    )
    assert generated.returncode == 0, generated.stderr

    result = _subprocess("summarize", "--input", str(artifact_path), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    expected = summarize_demand_trace(load_demand_trace(artifact_path).trace)
    assert json.loads(result.stdout) == expected
    assert result.stderr == ""


def test_summarize_atomic_json_existing_force_symlink_and_corruption(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact_path = tmp_path / "trace.npz"
    generated = _subprocess(
        "generate",
        "--config",
        str(_example()),
        "--output",
        str(artifact_path),
        "--allow-dirty",
        cwd=tmp_path,
    )
    assert generated.returncode == 0
    output = tmp_path / "summary.json"
    args = ["summarize", "--input", str(artifact_path), "--output", str(output)]

    assert main(args) == 0
    summary = json.loads(output.read_text(encoding="utf-8"))
    assert output.read_bytes().endswith(b"\n")
    assert summary == summarize_demand_trace(load_demand_trace(artifact_path).trace)
    capsys.readouterr()
    original = output.read_bytes()
    assert main(args) == 5
    assert output.read_bytes() == original
    capsys.readouterr()
    assert main([*args, "--force"]) == 0
    capsys.readouterr()

    link = tmp_path / "summary-link.json"
    link.symlink_to(output)
    assert main(["summarize", "--input", str(artifact_path), "--output", str(link), "--force"]) == 6
    capsys.readouterr()

    broken = tmp_path / "broken.npz"
    broken.write_bytes(b"broken")
    assert main(["summarize", "--input", str(broken)]) == 4
    assert "Traceback" not in capsys.readouterr().err


def test_default_error_hides_traceback_and_debug_shows_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_unexpectedly(path: object) -> object:
        raise RuntimeError("internal marker")

    monkeypatch.setattr(cli_module, "load_demand_config", fail_unexpectedly)
    assert main(["generate", "--config", str(_example())]) == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err and "internal marker" not in captured.err

    assert main(["--debug", "generate", "--config", str(_example())]) == 1
    captured = capsys.readouterr()
    assert "Traceback" in captured.err and "internal marker" in captured.err


def test_argparse_usage_help_and_pyproject_console_script(tmp_path: Path) -> None:
    invalid = _subprocess("unknown", cwd=tmp_path)
    assert invalid.returncode == 2
    assert invalid.stdout == ""
    help_result = _subprocess("--help", cwd=tmp_path)
    assert help_result.returncode == 0
    assert "generate" in help_result.stdout and "summarize" in help_result.stdout
    assert "plot" not in help_result.stdout

    with Path("pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)
    assert pyproject["project"]["scripts"]["fura-demand"] == "fura_mappo.demand.cli:main"


def test_cli_does_not_require_matplotlib() -> None:
    assert "matplotlib" not in sys.modules
    assert "MATPLOTLIB" not in os.environ
