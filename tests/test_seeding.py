import random

import numpy as np
import pytest

from fura_mappo.utils.seeding import seed_python_and_numpy


def test_seed_reproduces_python_and_numpy_sequences() -> None:
    """同一随机种子应产生一致的 Python 与 NumPy 随机序列。"""

    first_state = seed_python_and_numpy(20260817)
    first_python = [random.random() for _ in range(4)]
    first_numpy = np.random.random(4)

    second_state = seed_python_and_numpy(20260817)
    second_python = [random.random() for _ in range(4)]
    second_numpy = np.random.random(4)

    assert first_state == second_state
    assert first_python == second_python
    np.testing.assert_allclose(first_numpy, second_numpy)


@pytest.mark.parametrize("invalid_seed", [-1, -100])
def test_negative_seed_is_rejected(invalid_seed: int) -> None:
    with pytest.raises(ValueError, match="非负整数"):
        seed_python_and_numpy(invalid_seed)


def test_non_integer_seed_is_rejected() -> None:
    with pytest.raises(TypeError, match="整数"):
        seed_python_and_numpy(1.5)  # type: ignore[arg-type]
