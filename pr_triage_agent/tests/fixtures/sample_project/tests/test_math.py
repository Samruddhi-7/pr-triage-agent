import pytest

from src.math_utils import add, divide


class TestAdd:
    def test_add_positive(self) -> None:
        assert add(1, 2) == 3

    def test_add_negative(self) -> None:
        assert add(-1, 1) == 0

    def test_add_zero(self) -> None:
        assert add(0, 0) == 0


class TestDivide:
    def test_divide_normal(self) -> None:
        assert divide(10, 2) == 5.0

    def test_divide_by_zero(self) -> None:
        with pytest.raises(ValueError):
            divide(1, 0)
