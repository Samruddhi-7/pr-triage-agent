from src.math_utils import add


class TestFailing:
    def test_this_fails(self) -> None:
        result = add(1, 1)
        assert result == 3, f"Expected 3 but got {result}"
