def add(a: int, b: int) -> int:
    return a + b


def unused_function():
    x = 42
    return x


def divide(a: int, b: int) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
