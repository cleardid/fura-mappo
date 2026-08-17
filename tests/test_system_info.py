from fura_mappo.utils.system_info import collect_runtime_info


def test_runtime_info_contains_required_sections() -> None:
    """运行时信息必须包含实验复现所需的基本字段。"""

    info = collect_runtime_info()

    assert set(info) == {
        "python",
        "platform",
        "packages",
        "git_commit",
        "conda_environment",
        "gpu_query",
    }
    assert info["python"]["version"]
    assert info["platform"]["system"]
    assert isinstance(info["gpu_query"], list)
