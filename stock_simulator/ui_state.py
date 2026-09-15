from __future__ import annotations

from .models import DailyBar, PositionSlot, TradeNode


def node_label(node: TradeNode) -> str:
    return "开盘" if node == TradeNode.OPEN else "收盘"


def format_title(bar: DailyBar, node: TradeNode, show_identity: bool, stock_name: str = "") -> str:
    if not show_identity:
        return "********"
    identity_items = [bar.code.upper()]
    if stock_name:
        identity_items.append(stock_name)
    identity_part = "  ".join(identity_items) + "  "
    return f"{identity_part}{bar.date}  {node_label(node)}价 {bar.price_at(node):.2f}"


def shifted_window_anchor(current_index: int, pan_offset: int) -> int:
    return max(0, current_index - max(0, pan_offset))


def visible_bars(bars: list[DailyBar], current_index: int, window_size: int, pan_offset: int = 0) -> list[DailyBar]:
    safe_index = max(0, min(shifted_window_anchor(current_index, pan_offset), len(bars) - 1))
    start = max(0, safe_index - window_size + 1)
    return bars[start : safe_index + 1]


def budget_from_ratio(cash: float, ratio: float) -> int:
    return int(max(0, cash) * ratio)


def holding_avg_price(slots: list[PositionSlot]) -> float | None:
    quantity = sum(slot.quantity for slot in slots)
    if quantity <= 0:
        return None
    cost = sum(slot.cost for slot in slots)
    return round(cost / quantity, 3)


def percent_change_from_base(base_price: float | None, current_price: float) -> float | None:
    if not base_price or base_price <= 0:
        return None
    return round((current_price - base_price) / base_price * 100, 2)


def maximum_drawdown(equity_values: list[float], minimum_equity: float = 0.0) -> float:
    span = maximum_drawdown_span(equity_values, minimum_equity)
    return 0.0 if span is None else span[0]


def maximum_drawdown_span(
    equity_values: list[float],
    minimum_equity: float = 0.0,
) -> tuple[float, int, int] | None:
    """Return drawdown percent plus the original peak/trough point indexes."""
    minimum = max(0.0, minimum_equity)
    peak_value: float | None = None
    peak_index: int | None = None
    worst_pct = 0.0
    worst_start: int | None = None
    worst_end: int | None = None
    for index, value in enumerate(equity_values):
        if value <= minimum:
            continue
        if peak_value is None or value > peak_value:
            peak_value = value
            peak_index = index
            continue
        drawdown_pct = (value - peak_value) / peak_value * 100
        if drawdown_pct < worst_pct:
            worst_pct = drawdown_pct
            worst_start = peak_index
            worst_end = index
    if worst_start is None or worst_end is None:
        return None
    return round(worst_pct, 2), worst_start, worst_end


def open_close_range_amplitude(
    bars: list[DailyBar],
    start_index: int | None,
    current_index: int,
    current_node: TradeNode,
    start_node: TradeNode = TradeNode.OPEN,
) -> float | None:
    if start_index is None or not bars:
        return None
    start = max(0, min(start_index, len(bars) - 1))
    end = max(start, min(current_index, len(bars) - 1))
    prices: list[float] = []
    for index in range(start, end + 1):
        bar = bars[index]
        if index > start or start_node == TradeNode.OPEN:
            prices.append(bar.open)
        if index < end or current_node == TradeNode.CLOSE:
            prices.append(bar.close)
    if not prices:
        return 0.0
    low = min(prices)
    high = max(prices)
    if low <= 0:
        return 0.0
    return round((high - low) / low * 100, 2)


def post_buy_highest_change_from_base(
    base_price: float | None,
    bars: list[DailyBar],
    buy_index: int | None,
    current_index: int,
    current_node: TradeNode,
    buy_node: TradeNode = TradeNode.OPEN,
) -> float | None:
    if not base_price or base_price <= 0 or buy_index is None or not bars:
        return None
    start = max(0, min(buy_index, len(bars) - 1))
    end = max(start, min(current_index, len(bars) - 1))
    prices: list[float] = []
    for index in range(start, end + 1):
        bar = bars[index]
        if index > start or buy_node == TradeNode.OPEN:
            prices.append(bar.open)
        if index < end or current_node == TradeNode.CLOSE:
            prices.append(bar.close)
    if not prices:
        prices.append(base_price)
    return percent_change_from_base(base_price, max(prices))


def moving_average(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    result: list[float | None] = [None] * len(values)
    rolling_total = 0.0
    for index, value in enumerate(values):
        rolling_total += value
        if index >= period:
            rolling_total -= values[index - period]
        if index + 1 >= period:
            result[index] = round(rolling_total / period, 3)
    return result


def change_metrics(bars: list[DailyBar], current_index: int) -> tuple[float, float]:
    bar = bars[current_index]
    if current_index <= 0:
        return 0.0, 0.0
    prev_close = bars[current_index - 1].close
    if prev_close <= 0:
        return 0.0, 0.0
    change = round(bar.close - prev_close, 2)
    change_pct = round(change / prev_close * 100, 2)
    return change, change_pct


def candle_state(bar: DailyBar, prev_close: float | None) -> str:
    if prev_close and prev_close > 0:
        change_pct = (bar.close - prev_close) / prev_close * 100
        if change_pct >= 9.8:
            return "limit_up"
        if change_pct <= -9.8:
            return "limit_down"
    if bar.close >= bar.open:
        return "up"
    return "down"


def trade_marker_position(bar: DailyBar) -> str:
    if bar.close >= bar.open:
        return "below"
    return "above"


def opposite_marker_position(position: str) -> str:
    return "above" if position == "below" else "below"


def trade_marker_position_for_trade(bar: DailyBar, side: str, node: TradeNode) -> str:
    is_red = bar.close >= bar.open
    if node == TradeNode.OPEN:
        return "below" if is_red else "above"
    return "above" if is_red else "below"


def candle_body_is_filled(_state: str) -> bool:
    return True


def amplitude(bar: DailyBar) -> float:
    if bar.open <= 0:
        return 0.0
    return round((bar.high - bar.low) / bar.open * 100, 2)


def amount_yi(amount: float) -> float:
    return round(amount / 100000000, 2)
