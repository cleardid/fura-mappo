from fura_mappo import __version__


def test_package_version_is_available() -> None:
    """基础包应能被正确导入。"""

    assert __version__ == "0.0.1"
