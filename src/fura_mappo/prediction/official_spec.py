"""WP-03 official point-prediction v1 的冻结 spec 与纯 identity planning。"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import cast

import numpy as np
import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken

from fura_mappo.demand import compute_config_hash
from fura_mappo.prediction.dataset import DatasetProtocolSpec
from fura_mappo.prediction.model_selection import HistoryTransformKind, PointObjectiveKind
from fura_mappo.prediction.models import ZoneSchema

EXPECTED_WP03_POINT_PRIMARY_V1_SPEC_SHA256 = (
    "93fd011f0dbbdbc784db1b12e18aa37c4d15121c22620649b7218d2799c84fd0"
)

_SPEC_SCHEMA = "fura-mappo.wp03-point-experiment"
_SPEC_VERSION = 1
_MAX_SPEC_BYTES = 1024 * 1024
_MAX_YAML_NODES = 10_000
_MAX_YAML_DEPTH = 64
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_HISTORY_LENGTHS = (4, 8, 16, 32)
_WIDTHS = (64, 128)
_LEARNING_RATES = (0.0003, 0.001)
_OBJECTIVES = (PointObjectiveKind.O0, PointObjectiveKind.O1)
_TRANSFORMS = (HistoryTransformKind.T0, HistoryTransformKind.T1)
_TRAINING_SEEDS = (610001, 610002, 610003)

_TOP_FIELDS = frozenset(
    {
        "schema",
        "version",
        "experiment",
        "episode",
        "conditions",
        "splits",
        "protocols",
        "feature_encoding",
        "architecture",
        "search",
        "training",
        "initialization",
        "determinism",
        "bootstrap",
        "baselines",
        "feasibility",
        "artifact",
    }
)
_DRIFT_FIELDS = frozenset(
    {
        "type",
        "base_intensities",
        "hotspot_amplitudes",
        "hotspot_scales",
        "initial_hotspot_positions",
        "hotspot_velocities",
        "zone_bounds",
        "priority_range",
        "service_time_range",
        "deadline_offset_range",
        "generation",
    }
)
_STANDARD_SPLIT_FIELDS = frozenset(
    {"count", "seed_start", "seed_end", "cell_id", "trace_id_pattern"}
)
_FEATURE_ENCODING_IDENTITY = "wp03-point-feature-encoding-v1"
_ARCHITECTURE_IDENTITY = "wp03-stateless-mlp-v1"


def _official_feature_encoding_tree() -> dict[str, object]:
    """返回不共享可变状态的 frozen feature-encoding v1 tree。"""

    return {
        "identity": _FEATURE_ENCODING_IDENTITY,
        "history_values": "transformed_history_counts_oldest_to_newest_zone_ascending_row_major",
        "history_mask": "float32_zero_one",
        "absolute_step": "divide_by_255",
        "excluded_numeric_fields": [
            "steps_remaining",
            "prediction_horizon",
            "zone_schema_sha256",
        ],
        "transforms": ["T0", "T1"],
        "padding": "zeros_remain_zero",
        "dtype": "float32",
        "fitted_normalization": "NONE",
    }


def _official_architecture_tree() -> dict[str, object]:
    """返回不共享可变状态的 frozen stateless MLP v1 tree。"""

    return {
        "identity": _ARCHITECTURE_IDENTITY,
        "family": "stateless_feed_forward_mlp",
        "hidden_layer_count": 2,
        "hidden_widths": [64, 128],
        "hidden_activation": "ReLU",
        "output_dimension": 8,
        "output_link": "softplus_plus_epsilon",
        "output_epsilon": 1e-6,
        "prohibited": [
            "dropout",
            "batch_normalization",
            "layer_normalization",
            "residual_state",
            "persistent_hidden_state",
        ],
    }


def _official_zone_schema_sha256() -> str:
    bounds = np.asarray(
        (
            (0.0, 1.0, 0.0, 1.0),
            (1.0, 2.0, 0.0, 1.0),
            (2.0, 3.0, 0.0, 1.0),
            (3.0, 4.0, 0.0, 1.0),
        ),
        dtype=np.float64,
    )
    return ZoneSchema(bounds).sha256


class _StrictSafeLoader(yaml.SafeLoader):
    """拒绝重复 Mapping key 的 SafeLoader。"""


def _construct_unique_mapping(
    loader: _StrictSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    """构造无重复 key 的 YAML Mapping。"""

    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"YAML Mapping 包含重复键 {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _validate_yaml_nodes(root: Node | None) -> None:
    """在对象构造前限制 YAML 节点类型、数量、深度与 merge key。"""

    if root is None:
        raise ValueError("WP-03 YAML specification 不能为空")
    allowed_tags = {
        "tag:yaml.org,2002:map",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
    }
    stack: list[tuple[Node, int]] = [(root, 1)]
    node_count = 0
    while stack:
        node, depth = stack.pop()
        node_count += 1
        if node_count > _MAX_YAML_NODES:
            raise ValueError(f"YAML 节点数不能超过 {_MAX_YAML_NODES}")
        if depth > _MAX_YAML_DEPTH:
            raise ValueError(f"YAML 嵌套深度不能超过 {_MAX_YAML_DEPTH}")
        if node.tag not in allowed_tags:
            raise ValueError("YAML specification 包含不安全或不支持的类型标签")
        if isinstance(node, MappingNode):
            seen: set[str] = set()
            for key_node, value_node in node.value:
                if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                    raise ValueError("YAML Mapping 的键必须是字符串")
                if key_node.value == "<<":
                    raise ValueError("YAML specification 不允许 merge key")
                if key_node.value in seen:
                    raise ValueError(f"YAML Mapping 包含重复键 {key_node.value!r}")
                seen.add(key_node.value)
                stack.extend(((value_node, depth + 1), (key_node, depth + 1)))
        elif isinstance(node, SequenceNode):
            stack.extend((item, depth + 1) for item in node.value)
        elif not isinstance(node, ScalarNode):
            raise ValueError("YAML specification 包含不支持的节点类型")


def _copy_plain_tree(value: object, name: str = "WP-03 specification") -> object:
    """复制 JSON-style tree，拒绝 bool、非有限 float 与特殊对象。"""

    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} 不允许布尔值")
    if isinstance(value, str):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError(f"{name} 不允许 NaN 或无穷值")
        return normalized
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{name} 的 Mapping key 必须是字符串")
            result[key] = _copy_plain_tree(item, name)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_copy_plain_tree(item, name) for item in value]
    raise TypeError(f"{name} 包含不支持的值类型")


def _freeze_tree(value: object) -> object:
    """把 plain tree 递归冻结为 MappingProxyType 与 tuple。"""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_tree(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_tree(item) for item in value)
    return value


def _plain_tree(value: object) -> object:
    """把冻结 tree 转回独立的 dict/list tree。"""

    if isinstance(value, Mapping):
        return {str(key): _plain_tree(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain_tree(item) for item in value]
    return value


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} 必须是 Mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} 必须是 Sequence")
    return cast(Sequence[object], value)


def _require_fields(value: Mapping[str, object], fields: frozenset[str], name: str) -> None:
    if set(value) != set(fields):
        missing = sorted(set(fields) - set(value))
        extra = sorted(set(value) - set(fields))
        raise ValueError(f"{name} 字段不匹配；missing={missing!r}, extra={extra!r}")


def _validate_field_sets(config: Mapping[str, object]) -> None:
    """验证 v1 schema 的 exact field sets 与固定 sequence cardinality。"""

    _require_fields(config, _TOP_FIELDS, "specification")
    experiment = _mapping(config["experiment"], "experiment")
    _require_fields(
        experiment,
        frozenset(
            {
                "experiment_id",
                "primary_prediction_horizon",
                "secondary_prediction",
                "calibration",
            }
        ),
        "experiment",
    )
    _require_fields(
        _mapping(experiment["secondary_prediction"], "experiment.secondary_prediction"),
        frozenset({"horizons", "disposition"}),
        "experiment.secondary_prediction",
    )
    _require_fields(
        _mapping(experiment["calibration"], "experiment.calibration"),
        frozenset({"disposition", "trace_count"}),
        "experiment.calibration",
    )
    _require_fields(
        _mapping(config["episode"], "episode"),
        frozenset({"start_step", "num_steps", "num_zones", "zone_bounds"}),
        "episode",
    )
    conditions = _mapping(config["conditions"], "conditions")
    _require_fields(
        conditions,
        frozenset({"id", "near_v020", "near_v030", "structural_markov"}),
        "conditions",
    )
    for name in ("id", "near_v020", "near_v030"):
        condition = _mapping(conditions[name], f"conditions.{name}")
        _require_fields(condition, _DRIFT_FIELDS, f"conditions.{name}")
        _require_fields(
            _mapping(condition["generation"], f"conditions.{name}.generation"),
            frozenset({"num_steps"}),
            f"conditions.{name}.generation",
        )
    structural = _mapping(conditions["structural_markov"], "conditions.structural_markov")
    _require_fields(
        structural,
        frozenset(
            {
                "type",
                "state_intensities",
                "transition_matrix",
                "initial_state",
                "zone_bounds",
                "priority_range",
                "service_time_range",
                "deadline_offset_range",
                "generation",
            }
        ),
        "conditions.structural_markov",
    )
    _require_fields(
        _mapping(structural["generation"], "conditions.structural_markov.generation"),
        frozenset({"num_steps"}),
        "conditions.structural_markov.generation",
    )

    splits = _mapping(config["splits"], "splits")
    _require_fields(
        splits,
        frozenset({"train", "validation", "calibration", "test_id", "test_ood", "ood_reporting"}),
        "splits",
    )
    for name in ("train", "validation", "test_id"):
        _require_fields(
            _mapping(splits[name], f"splits.{name}"),
            _STANDARD_SPLIT_FIELDS,
            f"splits.{name}",
        )
    _require_fields(
        _mapping(splits["calibration"], "splits.calibration"),
        frozenset({"count", "disposition"}),
        "splits.calibration",
    )
    test_ood = _mapping(splits["test_ood"], "splits.test_ood")
    _require_fields(test_ood, frozenset({"count", "cells"}), "splits.test_ood")
    cells = _sequence(test_ood["cells"], "splits.test_ood.cells")
    if len(cells) != 3:
        raise ValueError("splits.test_ood.cells 必须精确包含 3 个 cell")
    for index, cell_value in enumerate(cells):
        _require_fields(
            _mapping(cell_value, f"splits.test_ood.cells[{index}]"),
            frozenset({"kind", "cell_id", "count", "seed_start", "seed_end", "trace_id_pattern"}),
            f"splits.test_ood.cells[{index}]",
        )
    _require_fields(
        _mapping(splits["ood_reporting"], "splits.ood_reporting"),
        frozenset({"cell_weights", "pooled_official_score", "reporting"}),
        "splits.ood_reporting",
    )

    sections: tuple[tuple[str, frozenset[str]], ...] = (
        (
            "protocols",
            frozenset(
                {
                    "prediction_horizon",
                    "history_lengths",
                    "primary_history_length",
                    "additional_history_lengths",
                }
            ),
        ),
        (
            "feature_encoding",
            frozenset(
                {
                    "identity",
                    "history_values",
                    "history_mask",
                    "absolute_step",
                    "excluded_numeric_fields",
                    "transforms",
                    "padding",
                    "dtype",
                    "fitted_normalization",
                }
            ),
        ),
        (
            "architecture",
            frozenset(
                {
                    "identity",
                    "family",
                    "hidden_layer_count",
                    "hidden_widths",
                    "hidden_activation",
                    "output_dimension",
                    "output_link",
                    "output_epsilon",
                    "prohibited",
                }
            ),
        ),
        (
            "search",
            frozenset(
                {
                    "objectives",
                    "transforms",
                    "learning_rates",
                    "canonical_dimensions",
                    "selection_total_order",
                    "candidate_count",
                }
            ),
        ),
        (
            "initialization",
            frozenset(
                {
                    "rng",
                    "numpy_global_rng",
                    "torch_global_rng",
                    "hidden_weights",
                    "output_weights",
                    "biases",
                    "layer_order",
                }
            ),
        ),
        (
            "determinism",
            frozenset(
                {
                    "numeric_dtype",
                    "amp",
                    "stochastic_layers",
                    "torch_compile",
                    "deterministic_algorithms",
                    "tf32",
                    "cudnn_benchmark",
                    "device_count",
                    "validation_contract",
                }
            ),
        ),
        (
            "bootstrap",
            frozenset(
                {"num_resamples", "generator", "rng_seed", "method", "quantile_method", "interval"}
            ),
        ),
        (
            "baselines",
            frozenset(
                {
                    "kinds",
                    "b2_history_lengths",
                    "b2_internal_total_order",
                    "b3_history_lengths",
                    "b3_alphas",
                    "b3_internal_total_order",
                    "two_stage_rule",
                    "bstar_tie_order",
                    "required_complete_finite_valid_forecasts",
                    "failure_state",
                    "fixed_representation_protocol",
                    "matching_history_protocols",
                    "b5_train_support",
                    "b5_required_future_support",
                    "support_interval_kind",
                }
            ),
        ),
        (
            "feasibility",
            frozenset({"anchors_per_trace", "valid_target_cells_per_trace", "training_run_count"}),
        ),
        ("artifact", frozenset({"reserved_root", "publication", "git_tracking"})),
    )
    for section_name, expected_fields in sections:
        _require_fields(
            _mapping(config[section_name], section_name),
            expected_fields,
            section_name,
        )
    training = _mapping(config["training"], "training")
    _require_fields(
        training,
        frozenset(
            {
                "training_seeds",
                "optimizer",
                "mode",
                "sample_order",
                "shuffle",
                "sampler_rng",
                "dtype",
                "amp",
                "device_count",
                "max_epochs",
                "patience",
                "min_improvement",
                "checkpoint_rule",
                "initial_best",
                "final_retrain",
            }
        ),
        "training",
    )
    _require_fields(
        _mapping(training["optimizer"], "training.optimizer"),
        frozenset(
            {"name", "betas", "eps", "weight_decay", "amsgrad", "scheduler", "gradient_clipping"}
        ),
        "training.optimizer",
    )
    _require_fields(
        _mapping(
            _mapping(config["baselines"], "baselines")["two_stage_rule"],
            "baselines.two_stage_rule",
        ),
        frozenset({"step_1", "step_2"}),
        "baselines.two_stage_rule",
    )


def _seed_range(entry: Mapping[str, object], name: str) -> tuple[int, ...]:
    start = entry["seed_start"]
    end = entry["seed_end"]
    count = entry["count"]
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end, count)):
        raise ValueError(f"{name} seed/count 必须是非 bool 整数")
    if start < 0 or end < start or count != end - start + 1:
        raise ValueError(f"{name} count 与 inclusive seed range 不一致")
    return tuple(range(start, end + 1))


def _near_condition_guard(
    id_condition: Mapping[str, object],
    near_condition: Mapping[str, object],
    velocity_x: float,
    name: str,
) -> None:
    id_copy = cast(dict[str, object], _plain_tree(id_condition))
    near_copy = cast(dict[str, object], _plain_tree(near_condition))
    actual_velocity = near_copy.pop("hotspot_velocities")
    id_copy.pop("hotspot_velocities")
    if near_copy != id_copy or actual_velocity != [[velocity_x, 0.0]]:
        raise ValueError(f"{name} 必须只改变 hotspot velocity x")


def _validate_scientific_consistency(config: Mapping[str, object]) -> None:
    """执行不生成 data 的 frozen v1 cross-field consistency checks。"""

    if config["schema"] != _SPEC_SCHEMA or config["version"] != _SPEC_VERSION:
        raise ValueError("WP-03 specification schema/version 不受支持")
    experiment = _mapping(config["experiment"], "experiment")
    if experiment["primary_prediction_horizon"] != 2:
        raise ValueError("Primary prediction horizon 必须为 2")
    episode = _mapping(config["episode"], "episode")
    if (episode["start_step"], episode["num_steps"], episode["num_zones"]) != (0, 256, 4):
        raise ValueError("episode identity 必须精确为 start=0/N=256/Z=4")

    splits = _mapping(config["splits"], "splits")
    demand_seeds: list[int] = []
    expected_counts = {"train": 128, "validation": 64, "test_id": 128}
    for name, expected_count in expected_counts.items():
        entry = _mapping(splits[name], f"splits.{name}")
        seeds = _seed_range(entry, f"splits.{name}")
        if len(seeds) != expected_count:
            raise ValueError(f"splits.{name} count 必须精确等于 {expected_count}")
        demand_seeds.extend(seeds)
    test_ood = _mapping(splits["test_ood"], "splits.test_ood")
    ood_seeds: list[int] = []
    for index, value in enumerate(_sequence(test_ood["cells"], "test_ood.cells")):
        seeds = _seed_range(_mapping(value, f"test_ood.cells[{index}]"), f"test_ood.cells[{index}]")
        if len(seeds) != 32:
            raise ValueError("每个 TEST_OOD cell 必须精确包含 32 seeds")
        ood_seeds.extend(seeds)
    if test_ood["count"] != 96 or len(ood_seeds) != 96:
        raise ValueError("TEST_OOD count 必须精确为 96=32+32+32")
    demand_seeds.extend(ood_seeds)
    if len(demand_seeds) != 416 or len(set(demand_seeds)) != 416:
        raise ValueError("全部 416 demand seeds 必须全局唯一")

    training = _mapping(config["training"], "training")
    training_seeds = tuple(_sequence(training["training_seeds"], "training.training_seeds"))
    bootstrap = _mapping(config["bootstrap"], "bootstrap")
    bootstrap_seed = bootstrap["rng_seed"]
    registered = (*demand_seeds, *training_seeds, bootstrap_seed)
    if len(training_seeds) != 3 or len(set(training_seeds)) != 3:
        raise ValueError("training seeds 必须精确包含 3 个唯一值")
    if len(registered) != 420 or len(set(registered)) != 420:
        raise ValueError("全部 registered seeds 必须是 420 个唯一 identities")

    conditions = _mapping(config["conditions"], "conditions")
    id_condition = _mapping(conditions["id"], "conditions.id")
    _near_condition_guard(
        id_condition,
        _mapping(conditions["near_v020"], "conditions.near_v020"),
        0.20,
        "near_v020",
    )
    _near_condition_guard(
        id_condition,
        _mapping(conditions["near_v030"], "conditions.near_v030"),
        0.30,
        "near_v030",
    )
    structural = _mapping(conditions["structural_markov"], "conditions.structural_markov")
    state_intensities = _sequence(structural["state_intensities"], "state_intensities")
    totals = [
        sum(float(value) for value in _sequence(row, "state_intensity"))
        for row in state_intensities
    ]
    id_total = sum(
        float(value) for value in _sequence(id_condition["base_intensities"], "base_intensities")
    ) + float(_sequence(id_condition["hotspot_amplitudes"], "hotspot_amplitudes")[0])
    if any(not math.isclose(total, 0.65, rel_tol=0.0, abs_tol=1e-12) for total in totals):
        raise ValueError("Markov state total intensities 必须精确为 nominal 0.65")
    if not math.isclose(id_total, 0.65, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("ID nominal intensity total 必须精确为 0.65")

    protocols = _mapping(config["protocols"], "protocols")
    history_lengths = tuple(_sequence(protocols["history_lengths"], "history_lengths"))
    search = _mapping(config["search"], "search")
    widths = tuple(
        _sequence(_mapping(config["architecture"], "architecture")["hidden_widths"], "widths")
    )
    objectives = tuple(_sequence(search["objectives"], "objectives"))
    transforms = tuple(_sequence(search["transforms"], "transforms"))
    learning_rates = tuple(_sequence(search["learning_rates"], "learning_rates"))
    candidate_count = (
        len(widths) * len(learning_rates) * len(history_lengths) * len(objectives) * len(transforms)
    )
    if candidate_count != 64 or search["candidate_count"] != 64:
        raise ValueError("learned candidate count 必须精确为 64")
    feasibility = _mapping(config["feasibility"], "feasibility")
    if feasibility["training_run_count"] != 192 or candidate_count * len(training_seeds) != 192:
        raise ValueError("training run count 必须精确为 192")
    num_steps = cast(int, episode["num_steps"])
    horizon = cast(int, experiment["primary_prediction_horizon"])
    zones = cast(int, episode["num_zones"])
    anchors = num_steps - 1
    valid_cells = zones * sum(num_steps - lead for lead in range(1, horizon + 1))
    if feasibility["anchors_per_trace"] != anchors or anchors != 255:
        raise ValueError("anchors per trace 必须精确为 255")
    if feasibility["valid_target_cells_per_trace"] != valid_cells or valid_cells != 2036:
        raise ValueError("valid target cells per trace 必须精确为 2036")


@dataclass(frozen=True, slots=True)
class OfficialPointExperimentSpec:
    """递归只读、hash-bound 的 WP-03 point-prediction v1 scientific spec。"""

    config: Mapping[str, object]
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        copied = _copy_plain_tree(self.config)
        if not isinstance(copied, dict):
            raise TypeError("config 顶层必须是 Mapping")
        _validate_field_sets(copied)
        _validate_scientific_consistency(copied)
        digest = compute_config_hash(copied)
        if digest != EXPECTED_WP03_POINT_PRIMARY_V1_SPEC_SHA256:
            raise ValueError("WP-03 scientific YAML 与 frozen v1 identity 不一致")
        frozen = _freeze_tree(copied)
        if not isinstance(frozen, Mapping):
            raise RuntimeError("frozen specification 必须保持 Mapping")
        object.__setattr__(self, "config", frozen)
        object.__setattr__(self, "sha256", digest)

    @property
    def experiment_id(self) -> str:
        experiment = cast(Mapping[str, object], self.config["experiment"])
        return cast(str, experiment["experiment_id"])

    @property
    def prediction_horizon(self) -> int:
        experiment = cast(Mapping[str, object], self.config["experiment"])
        return cast(int, experiment["primary_prediction_horizon"])

    @property
    def history_lengths(self) -> tuple[int, ...]:
        protocols = cast(Mapping[str, object], self.config["protocols"])
        return cast(tuple[int, ...], protocols["history_lengths"])

    @property
    def training_seeds(self) -> tuple[int, ...]:
        training = cast(Mapping[str, object], self.config["training"])
        return cast(tuple[int, ...], training["training_seeds"])

    @property
    def zone_bounds(self) -> tuple[tuple[float, ...], ...]:
        episode = cast(Mapping[str, object], self.config["episode"])
        return cast(tuple[tuple[float, ...], ...], episode["zone_bounds"])

    @property
    def reserved_artifact_root(self) -> str:
        artifact = cast(Mapping[str, object], self.config["artifact"])
        return cast(str, artifact["reserved_root"])

    def to_plain_tree(self) -> dict[str, object]:
        """返回完全独立的 canonical plain tree copy。"""

        return cast(dict[str, object], _plain_tree(self.config))


def load_official_point_experiment_spec(
    path: str | os.PathLike[str],
) -> OfficialPointExperimentSpec:
    """安全加载并严格绑定 frozen WP-03 point experiment YAML。"""

    if isinstance(path, bytes):
        raise TypeError("path 不能是 bytes")
    try:
        raw_path = os.fspath(path)
    except TypeError as error:
        raise TypeError("path 必须是 str 或 os.PathLike[str]") from error
    if isinstance(raw_path, bytes):
        raise TypeError("path 不能是 bytes")
    spec_path = Path(raw_path)
    if spec_path.suffix != ".yaml":
        raise ValueError("WP-03 specification 后缀必须精确为 .yaml")
    with spec_path.open("rb") as stream:
        payload = stream.read(_MAX_SPEC_BYTES + 1)
    if len(payload) > _MAX_SPEC_BYTES:
        raise ValueError(f"WP-03 YAML 不能超过 {_MAX_SPEC_BYTES} 字节")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("WP-03 YAML 必须是有效 UTF-8") from error
    try:
        for token in yaml.scan(text, Loader=_StrictSafeLoader):
            if isinstance(token, AnchorToken):
                raise ValueError("YAML specification 不允许 anchor")
            if isinstance(token, AliasToken):
                raise ValueError("YAML specification 不允许 alias")
        root = yaml.compose(text, Loader=_StrictSafeLoader)
        _validate_yaml_nodes(root)
        loaded = yaml.load(text, Loader=_StrictSafeLoader)
    except yaml.YAMLError as error:
        raise ValueError("WP-03 YAML 语法或安全校验失败") from error
    try:
        if not isinstance(loaded, Mapping):
            raise TypeError("WP-03 YAML 顶层必须是 Mapping")
        return OfficialPointExperimentSpec(cast(Mapping[str, object], loaded))
    except TypeError as error:
        raise ValueError(f"WP-03 YAML 内容错误：{error}") from error


@dataclass(frozen=True, slots=True)
class OfficialDatasetProtocols:
    """P2L4 primary 与 P2L8/P2L16/P2L32 additional protocols。"""

    primary_protocol: DatasetProtocolSpec
    additional_protocols: tuple[DatasetProtocolSpec, ...]

    def __post_init__(self) -> None:
        additional = tuple(self.additional_protocols)
        protocols = (self.primary_protocol, *additional)
        if tuple(protocol.history_length for protocol in protocols) != _HISTORY_LENGTHS:
            raise ValueError("official protocols 必须按 L=4,8,16,32 canonical ordering")
        if any(protocol.prediction_horizon != 2 for protocol in protocols):
            raise ValueError("official protocols 必须全部使用 P=2")
        if len({protocol.sha256 for protocol in protocols}) != 4:
            raise ValueError("official protocol SHA 必须全部唯一")
        object.__setattr__(self, "additional_protocols", additional)

    @property
    def all_protocols(self) -> tuple[DatasetProtocolSpec, ...]:
        return (self.primary_protocol, *self.additional_protocols)


def build_official_dataset_protocols(spec: OfficialPointExperimentSpec) -> OfficialDatasetProtocols:
    """只构造 frozen P2L4/P2L8/P2L16/P2L32 protocol identities。"""

    if not isinstance(spec, OfficialPointExperimentSpec):
        raise TypeError("spec 必须是 OfficialPointExperimentSpec")
    zone_schema = ZoneSchema(np.asarray(spec.zone_bounds, dtype=np.float64))
    if zone_schema.sha256 != _official_zone_schema_sha256():
        raise ValueError("spec zone geometry 与 frozen v1 identity 不一致")
    protocols = tuple(
        DatasetProtocolSpec(
            history_length=history_length,
            prediction_horizon=spec.prediction_horizon,
            zone_schema_sha256=zone_schema.sha256,
        )
        for history_length in spec.history_lengths
    )
    return OfficialDatasetProtocols(protocols[0], protocols[1:])


def _validate_expected_spec_sha(value: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("official_spec_sha256 必须是小写 SHA-256")
    if value != EXPECTED_WP03_POINT_PRIMARY_V1_SPEC_SHA256:
        raise ValueError("official_spec_sha256 不属于 frozen v1")
    return value


@dataclass(frozen=True, slots=True)
class OfficialTrainingPlan:
    """无 runtime/path/timestamp 自由度的 frozen training plan identity。"""

    official_spec_sha256: str
    identity: Mapping[str, object] = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        spec_sha = _validate_expected_spec_sha(self.official_spec_sha256)
        identity: dict[str, object] = {
            "schema": "fura-mappo.wp03-official-training-plan",
            "version": 1,
            "official_spec_sha256": spec_sha,
            "feature_encoding_identity": _FEATURE_ENCODING_IDENTITY,
            "architecture_identity": _ARCHITECTURE_IDENTITY,
            "history_lengths": list(_HISTORY_LENGTHS),
            "objectives": [item.value for item in _OBJECTIVES],
            "transforms": [item.value for item in _TRANSFORMS],
            "hidden_widths": list(_WIDTHS),
            "learning_rates": list(_LEARNING_RATES),
            "selection_total_order": [
                "validation_algorithm_rmse",
                "model_complexity_key",
                "shorter_history_length",
                "objective_O0_before_O1",
                "transform_T0_before_T1",
                "canonical_order",
            ],
            "optimizer": {
                "name": "AdamW",
                "betas": [0.9, 0.999],
                "eps": 1e-8,
                "weight_decay": 1e-4,
                "amsgrad": "DISABLED",
                "scheduler": "NONE",
                "gradient_clipping": "NONE",
            },
            "training": {
                "mode": "full_batch",
                "sample_order": "canonical_fixed",
                "shuffle": "NONE",
                "dtype": "float32",
                "amp": "DISABLED",
                "max_epochs": 300,
                "patience": 30,
                "min_improvement": 1e-5,
                "checkpoint_rule": "new_rmse_strictly_less_than_best_minus_min_improvement",
                "initial_best": "first_finite_epoch",
                "final_retrain": "NONE",
            },
            "initialization": {
                "rng": "local_explicit_generator",
                "hidden_weights": "xavier_uniform_gain_sqrt_2",
                "output_weights": "xavier_uniform_gain_1",
                "biases": "zero",
                "layer_order": "fixed_canonical",
            },
            "determinism": {
                "no_amp": "REQUIRED",
                "no_stochastic_layers": "REQUIRED",
                "no_torch_compile": "REQUIRED",
                "deterministic_algorithms": "REQUIRED",
                "tf32": "DISABLED",
                "cudnn_benchmark": "DISABLED",
                "device_count": 1,
                "validation_contract": "safe_load_twice_and_order_invariant_exact_equal",
            },
        }
        frozen = cast(Mapping[str, object], _freeze_tree(identity))
        object.__setattr__(self, "official_spec_sha256", spec_sha)
        object.__setattr__(self, "identity", frozen)
        object.__setattr__(self, "sha256", compute_config_hash(identity))

    def to_plain_tree(self) -> dict[str, object]:
        return cast(dict[str, object], _plain_tree(self.identity))


@dataclass(frozen=True, slots=True)
class OfficialRNGNamespacePlan:
    """Demand/model/bootstrap 相互独立的 frozen RNG namespace identity。"""

    official_spec_sha256: str
    identity: Mapping[str, object] = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        spec_sha = _validate_expected_spec_sha(self.official_spec_sha256)
        identity: dict[str, object] = {
            "schema": "fura-mappo.wp03-official-rng-namespace-plan",
            "version": 1,
            "official_spec_sha256": spec_sha,
            "demand_generation": {
                "source_seed_ranges": [
                    [410000, 410127],
                    [420000, 420063],
                    [430000, 430127],
                    [440000, 440031],
                    [441000, 441031],
                    [450000, 450031],
                ],
                "derivation": "NONE",
            },
            "model_initialization": {"seeds": list(_TRAINING_SEEDS), "scope": "run_local"},
            "sampler": "NONE",
            "optimizer_stochastic_rng": "NONE",
            "point_inference": "NONE",
            "prediction_bootstrap": {"generator": "PCG64", "seed": 910001},
            "cross_namespace_derivation": "PROHIBITED",
        }
        frozen = cast(Mapping[str, object], _freeze_tree(identity))
        object.__setattr__(self, "official_spec_sha256", spec_sha)
        object.__setattr__(self, "identity", frozen)
        object.__setattr__(self, "sha256", compute_config_hash(identity))

    def to_plain_tree(self) -> dict[str, object]:
        return cast(dict[str, object], _plain_tree(self.identity))


@dataclass(frozen=True, slots=True)
class OfficialBaselinePlan:
    """只描述 B0--B5 frozen hierarchy、protocol mapping 与 B5 support。"""

    official_spec_sha256: str
    identity: Mapping[str, object] = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        spec_sha = _validate_expected_spec_sha(self.official_spec_sha256)
        identity: dict[str, object] = {
            "schema": "fura-mappo.wp03-official-baseline-plan",
            "version": 1,
            "official_spec_sha256": spec_sha,
            "baseline_kinds": [f"B{index}" for index in range(6)],
            "b2_history_lengths": list(_HISTORY_LENGTHS),
            "b2_internal_total_order": [
                "validation_primary_rmse",
                "shorter_history_length",
            ],
            "b3_grid": {
                "history_lengths": list(_HISTORY_LENGTHS),
                "alphas": [0.25, 0.50, 0.75],
            },
            "b3_internal_total_order": [
                "validation_primary_rmse",
                "shorter_history_length",
                "smaller_alpha",
            ],
            "two_stage_rule": {
                "step_1": "lock_each_baseline_internal_variant",
                "step_2": "compare_six_locked_variants_by_validation_primary_rmse",
            },
            "bstar_tie_order": [f"B{index}" for index in range(6)],
            "required_complete_finite_valid_forecasts": "REQUIRED",
            "failure_state": "PREDICTION_BASELINE_SELECTION_FAILURE",
            "fixed_protocol_mapping": {
                "baselines": ["B0", "B1", "B4", "B5"],
                "protocol": "P2L4",
            },
            "matching_history_protocols": ["B2", "B3"],
            "b5_support": {
                "train_common_absolute_support": [0, 256],
                "required_future_support": [1, 256],
                "interval_kind": "half_open",
            },
            "execution": "NONE",
        }
        frozen = cast(Mapping[str, object], _freeze_tree(identity))
        object.__setattr__(self, "official_spec_sha256", spec_sha)
        object.__setattr__(self, "identity", frozen)
        object.__setattr__(self, "sha256", compute_config_hash(identity))

    def to_plain_tree(self) -> dict[str, object]:
        return cast(dict[str, object], _plain_tree(self.identity))


def build_official_training_plan(spec: OfficialPointExperimentSpec) -> OfficialTrainingPlan:
    if not isinstance(spec, OfficialPointExperimentSpec):
        raise TypeError("spec 必须是 OfficialPointExperimentSpec")
    return OfficialTrainingPlan(spec.sha256)


def build_official_rng_namespace_plan(
    spec: OfficialPointExperimentSpec,
) -> OfficialRNGNamespacePlan:
    if not isinstance(spec, OfficialPointExperimentSpec):
        raise TypeError("spec 必须是 OfficialPointExperimentSpec")
    return OfficialRNGNamespacePlan(spec.sha256)


def build_official_baseline_plan(spec: OfficialPointExperimentSpec) -> OfficialBaselinePlan:
    if not isinstance(spec, OfficialPointExperimentSpec):
        raise TypeError("spec 必须是 OfficialPointExperimentSpec")
    return OfficialBaselinePlan(spec.sha256)


def compute_official_model_complexity_key(
    history_length: int,
    hidden_width: int,
) -> tuple[int]:
    """返回 authoritative ``(d*W + W*W + 10*W + 8,)`` complexity key。"""

    if isinstance(history_length, bool) or not isinstance(history_length, int):
        raise TypeError("history_length 必须是非 bool 整数")
    if isinstance(hidden_width, bool) or not isinstance(hidden_width, int):
        raise TypeError("hidden_width 必须是非 bool 整数")
    if history_length not in _HISTORY_LENGTHS:
        raise ValueError("history_length 不属于 frozen L set")
    if hidden_width not in _WIDTHS:
        raise ValueError("hidden_width 不属于 frozen W set")
    input_dimension = 5 * history_length + 1
    parameter_count = (
        input_dimension * hidden_width
        + hidden_width
        + hidden_width * hidden_width
        + hidden_width
        + 8 * hidden_width
        + 8
    )
    return (parameter_count,)


@dataclass(frozen=True, slots=True)
class OfficialLearnedTrainingConfig:
    """一个 learned candidate 的完整、共享语义绑定 engineering identity。"""

    official_spec_sha256: str
    protocol_sha256: str
    history_length: int
    objective: PointObjectiveKind
    transform: HistoryTransformKind
    hidden_width: int
    learning_rate: float
    training_plan_sha256: str
    rng_namespace_plan_sha256: str
    feature_encoding_sha256: str
    architecture_sha256: str
    canonical_order: int
    model_complexity_key: tuple[int] = field(init=False)
    config_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        spec_sha = _validate_expected_spec_sha(self.official_spec_sha256)
        if (
            not isinstance(self.protocol_sha256, str)
            or _SHA256_PATTERN.fullmatch(self.protocol_sha256) is None
        ):
            raise ValueError("protocol_sha256 必须是小写 SHA-256")
        if self.history_length not in _HISTORY_LENGTHS:
            raise ValueError("history_length 不属于 frozen L set")
        expected_protocol_sha = DatasetProtocolSpec(
            history_length=self.history_length,
            prediction_horizon=2,
            zone_schema_sha256=_official_zone_schema_sha256(),
        ).sha256
        if self.protocol_sha256 != expected_protocol_sha:
            raise ValueError("protocol_sha256 与 frozen history_length 不一致")
        if not isinstance(self.objective, PointObjectiveKind):
            raise TypeError("objective 必须是 PointObjectiveKind")
        if not isinstance(self.transform, HistoryTransformKind):
            raise TypeError("transform 必须是 HistoryTransformKind")
        if self.hidden_width not in _WIDTHS:
            raise ValueError("hidden_width 不属于 frozen W set")
        if isinstance(self.learning_rate, bool) or not isinstance(self.learning_rate, float):
            raise TypeError("learning_rate 必须是 float")
        if self.learning_rate not in _LEARNING_RATES:
            raise ValueError("learning_rate 不属于 frozen grid")
        for value, name in (
            (self.training_plan_sha256, "training_plan_sha256"),
            (self.rng_namespace_plan_sha256, "rng_namespace_plan_sha256"),
            (self.feature_encoding_sha256, "feature_encoding_sha256"),
            (self.architecture_sha256, "architecture_sha256"),
        ):
            if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} 必须是小写 SHA-256")
        if self.training_plan_sha256 != OfficialTrainingPlan(spec_sha).sha256:
            raise ValueError("training_plan_sha256 与 frozen v1 不一致")
        if self.rng_namespace_plan_sha256 != OfficialRNGNamespacePlan(spec_sha).sha256:
            raise ValueError("rng_namespace_plan_sha256 与 frozen v1 不一致")
        expected_feature_sha = compute_config_hash(_official_feature_encoding_tree())
        expected_architecture_sha = compute_config_hash(_official_architecture_tree())
        if self.feature_encoding_sha256 != expected_feature_sha:
            raise ValueError("feature_encoding_sha256 与 frozen v1 不一致")
        if self.architecture_sha256 != expected_architecture_sha:
            raise ValueError("architecture_sha256 与 frozen v1 不一致")
        width_rank = _WIDTHS.index(self.hidden_width)
        learning_rate_rank = _LEARNING_RATES.index(self.learning_rate)
        history_rank = _HISTORY_LENGTHS.index(self.history_length)
        objective_rank = _OBJECTIVES.index(self.objective)
        transform_rank = _TRANSFORMS.index(self.transform)
        expected_order = (
            ((width_rank * 2 + learning_rate_rank) * 4 + history_rank) * 2 + objective_rank
        ) * 2 + transform_rank
        if (
            isinstance(self.canonical_order, bool)
            or not isinstance(self.canonical_order, int)
            or self.canonical_order != expected_order
        ):
            raise ValueError("canonical_order 与 frozen nested order 不一致")
        complexity = compute_official_model_complexity_key(
            self.history_length,
            self.hidden_width,
        )
        identity: dict[str, object] = {
            "schema": "fura-mappo.wp03-official-learned-training-config",
            "version": 1,
            "official_spec_sha256": spec_sha,
            "protocol_sha256": self.protocol_sha256,
            "feature_encoding_sha256": self.feature_encoding_sha256,
            "architecture_sha256": self.architecture_sha256,
            "history_length": self.history_length,
            "objective": self.objective.value,
            "transform": self.transform.value,
            "hidden_width": self.hidden_width,
            "learning_rate": self.learning_rate,
            "model_complexity_key": list(complexity),
            "canonical_order": self.canonical_order,
            "training_plan_sha256": self.training_plan_sha256,
            "rng_namespace_plan_sha256": self.rng_namespace_plan_sha256,
        }
        object.__setattr__(self, "official_spec_sha256", spec_sha)
        object.__setattr__(self, "model_complexity_key", complexity)
        object.__setattr__(self, "config_sha256", compute_config_hash(identity))


def plan_official_learned_configs(
    spec: OfficialPointExperimentSpec,
) -> tuple[OfficialLearnedTrainingConfig, ...]:
    """返回 canonical order 0..63 的完整 learned config Cartesian plan。"""

    if not isinstance(spec, OfficialPointExperimentSpec):
        raise TypeError("spec 必须是 OfficialPointExperimentSpec")
    protocols = build_official_dataset_protocols(spec)
    protocol_by_history = {item.history_length: item for item in protocols.all_protocols}
    training_plan = build_official_training_plan(spec)
    rng_plan = build_official_rng_namespace_plan(spec)
    config = spec.to_plain_tree()
    feature_tree = cast(Mapping[str, object], config["feature_encoding"])
    architecture_tree = cast(Mapping[str, object], config["architecture"])
    if feature_tree != _official_feature_encoding_tree():
        raise RuntimeError("spec feature encoding 与 frozen planner identity 不一致")
    if architecture_tree != _official_architecture_tree():
        raise RuntimeError("spec architecture 与 frozen planner identity 不一致")
    feature_sha = compute_config_hash(feature_tree)
    architecture_sha = compute_config_hash(architecture_tree)
    planned: list[OfficialLearnedTrainingConfig] = []
    canonical_order = 0
    for width in _WIDTHS:
        for learning_rate in _LEARNING_RATES:
            for history_length in _HISTORY_LENGTHS:
                for objective in _OBJECTIVES:
                    for transform in _TRANSFORMS:
                        planned.append(
                            OfficialLearnedTrainingConfig(
                                official_spec_sha256=spec.sha256,
                                protocol_sha256=protocol_by_history[history_length].sha256,
                                history_length=history_length,
                                objective=objective,
                                transform=transform,
                                hidden_width=width,
                                learning_rate=learning_rate,
                                training_plan_sha256=training_plan.sha256,
                                rng_namespace_plan_sha256=rng_plan.sha256,
                                feature_encoding_sha256=feature_sha,
                                architecture_sha256=architecture_sha,
                                canonical_order=canonical_order,
                            )
                        )
                        canonical_order += 1
    result = tuple(planned)
    if len(result) != 64 or tuple(item.canonical_order for item in result) != tuple(range(64)):
        raise RuntimeError("official learned config planner 未产生 exact 64 canonical configs")
    if len({item.config_sha256 for item in result}) != 64:
        raise RuntimeError("official learned config hashes 必须全部唯一")
    return result


def official_training_run_count(spec: OfficialPointExperimentSpec) -> int:
    """返回 plan-only candidate×training-seed count；不执行 training。"""

    return len(plan_official_learned_configs(spec)) * len(spec.training_seeds)


__all__ = [
    "EXPECTED_WP03_POINT_PRIMARY_V1_SPEC_SHA256",
    "OfficialBaselinePlan",
    "OfficialDatasetProtocols",
    "OfficialLearnedTrainingConfig",
    "OfficialPointExperimentSpec",
    "OfficialRNGNamespacePlan",
    "OfficialTrainingPlan",
    "build_official_baseline_plan",
    "build_official_dataset_protocols",
    "build_official_rng_namespace_plan",
    "build_official_training_plan",
    "compute_official_model_complexity_key",
    "load_official_point_experiment_spec",
    "official_training_run_count",
    "plan_official_learned_configs",
]
