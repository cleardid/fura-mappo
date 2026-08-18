from fura_mappo import __version__
from fura_mappo.demand import __all__ as demand_exports


def test_package_version_is_available() -> None:
    """基础包应能被正确导入。"""

    assert __version__ == "0.0.1"


def test_demand_package_exports_wp01c_public_api() -> None:
    """需求包应显式导出 WP-01C 六个公共接口。"""

    assert {
        "DemandTraceArtifact",
        "load_demand_config",
        "compute_config_hash",
        "save_demand_trace",
        "load_demand_trace",
        "summarize_demand_trace",
    } <= set(demand_exports)
    assert "main" not in demand_exports
