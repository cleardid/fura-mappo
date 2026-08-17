"""随机种子管理工具。"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SeedState:
    """记录一次随机种子初始化的结果。

    Attributes:
        seed: 实际使用的非负整数种子。
        python_hash_seed: 写入 ``PYTHONHASHSEED`` 的字符串。
    """

    seed: int
    python_hash_seed: str


def create_numpy_generator(seed: int) -> np.random.Generator:
    """创建不依赖 NumPy 全局随机状态的独立生成器。

    Args:
        seed: 非负整数随机种子。NumPy 整数标量会规范化为 Python ``int``。

    Returns:
        使用指定种子创建的全新 ``numpy.random.Generator``。

    Raises:
        TypeError: ``seed`` 是布尔值或不是整数时抛出。
        ValueError: ``seed`` 为负数时抛出。
    """

    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise TypeError("seed 必须是整数且不能是布尔值")

    normalized_seed = int(seed)
    if normalized_seed < 0:
        raise ValueError("seed 必须是非负整数")

    return np.random.default_rng(normalized_seed)


def seed_python_and_numpy(seed: int) -> SeedState:
    """为 Python 标准库和 NumPy 设置随机种子。

    WP-00 暂不依赖 PyTorch。加入 PyTorch 后，应在同一入口中继续设置
    ``torch.manual_seed``、CUDA 种子和确定性相关选项。

    Args:
        seed: 非负整数随机种子。

    Returns:
        保存实际种子值的不可变对象。

    Raises:
        TypeError: ``seed`` 不是整数时抛出。
        ValueError: ``seed`` 为负数时抛出。
    """

    if not isinstance(seed, int):
        raise TypeError("seed 必须是整数")
    if seed < 0:
        raise ValueError("seed 必须是非负整数")

    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    return SeedState(seed=seed, python_hash_seed=str(seed))
