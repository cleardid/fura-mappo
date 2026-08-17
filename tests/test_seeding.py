import random

import numpy as np
import pytest

from fura_mappo.utils.seeding import create_numpy_generator, seed_python_and_numpy


def _assert_numpy_random_states_equal(left: tuple[object, ...], right: tuple[object, ...]) -> None:
    """比较 NumPy 旧式全局随机状态。"""

    assert left[0] == right[0]
    np.testing.assert_array_equal(left[1], right[1])
    assert left[2:] == right[2:]


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


def test_create_numpy_generator_reproduces_without_sharing_state() -> None:
    """相同种子的独立 Generator 应复现且互不推进。"""

    first = create_numpy_generator(20260817)
    second = create_numpy_generator(np.int64(20260817))
    control = create_numpy_generator(20260817)

    np.testing.assert_array_equal(first.integers(0, 100, size=16), control.integers(0, 100, 16))
    first.random(20)
    np.testing.assert_array_equal(second.random(12), create_numpy_generator(20260817).random(12))


def test_create_numpy_generator_does_not_change_global_random_states() -> None:
    """创建和推进独立 Generator 不得污染 Python 或 NumPy 全局状态。"""

    numpy_state = np.random.get_state()
    python_state = random.getstate()

    generator = create_numpy_generator(7)
    generator.poisson([0.5, 2.0], size=(10, 2))

    _assert_numpy_random_states_equal(numpy_state, np.random.get_state())
    assert python_state == random.getstate()


@pytest.mark.parametrize("invalid_seed", [True, False, 1.5, "1", None])
def test_create_numpy_generator_rejects_non_integer_seed(invalid_seed: object) -> None:
    with pytest.raises(TypeError, match="整数"):
        create_numpy_generator(invalid_seed)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_seed", [-1, np.int64(-10)])
def test_create_numpy_generator_rejects_negative_seed(invalid_seed: int) -> None:
    with pytest.raises(ValueError, match="非负整数"):
        create_numpy_generator(invalid_seed)
