from __future__ import annotations


TEST_TRADE_MENU_TEXT = "测试交易模式"
EXIT_TEST_TRADE_MENU_TEXT = "退出测试交易模式"


def menu_presentation(active: bool) -> tuple[str, bool]:
    """Return the menu label and enabled state for the transient mode."""
    return (
        (EXIT_TEST_TRADE_MENU_TEXT, True)
        if active
        else (TEST_TRADE_MENU_TEXT, False)
    )


def test_window_anchor(
    selected_index: int,
    previous_anchor: int,
    bar_count: int,
    window_size: int,
) -> tuple[int, int]:
    """Preserve the existing viewport instead of revealing extra future bars."""
    if bar_count <= 0:
        return 0, 0
    last_index = bar_count - 1
    selected = max(0, min(int(selected_index), last_index))
    previous = max(selected, min(int(previous_anchor), last_index))
    maximum_future = min(max(0, int(window_size) - 1), last_index - selected)
    future_slots = min(
        maximum_future,
        previous - selected,
    )
    return selected + future_slots, future_slots


def point_hits_candle_body(
    *,
    point_x: float,
    point_y: float,
    candle_x: float,
    candle_width: float,
    body_y_open: float,
    body_y_close: float,
    tolerance: float = 4.0,
) -> bool:
    """Return whether a point hits the candle body, excluding wick-only space."""
    half_width = max(1.0, float(candle_width) / 2.0) + max(0.0, tolerance)
    if abs(float(point_x) - float(candle_x)) > half_width:
        return False
    top = min(float(body_y_open), float(body_y_close)) - max(0.0, tolerance)
    bottom = max(float(body_y_open), float(body_y_close)) + max(0.0, tolerance)
    return top <= float(point_y) <= bottom
