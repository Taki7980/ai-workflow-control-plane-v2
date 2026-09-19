from collections.abc import Callable


def on_event(value: int) -> int:
    return value + 1


def dispatch(callback: Callable[[int], int], value: int) -> int:
    return callback(value)


def run_callback() -> int:
    return dispatch(on_event, 3)
