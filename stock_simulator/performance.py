from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left, bisect_right
import math
import statistics

from .models import DailyBar, EquityPoint, TradeNode, TradeResult, TradeSegment


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PerformanceMetrics:
    initial_asset: float
    ending_asset: float
    net_profit: float
    total_return: float
    benchmark_return: float | None
    excess_return: float | None
    annual_return: float | None
    max_drawdown: float
    annual_volatility: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    calmar_ratio: float | None
    return_drawdown_ratio: float | None
    information_ratio: float | None
    segment_count: int
    win_rate: float | None
    profit_loss_ratio: float | None
    profit_factor: float | None
    expectancy: float | None
    average_win: float | None
    average_loss: float | None
    best_segment: float | None
    worst_segment: float | None
    trade_count: int
    holding_days: int
    fee_and_tax: float
    stock_count: int
    round_count: int
    sample_days: int


def build_trade_segments(
    trades: list[TradeResult],
    bars: list[DailyBar],
    starting_asset: float,
) -> list[TradeSegment]:
    """Turn accepted fills into complete flat-to-flat position cycles."""
    accepted = [trade for trade in trades if trade.accepted and trade.side in {"buy", "sell"} and trade.quantity > 0]
    if not accepted:
        return []
    date_indices = {bar.date: index for index, bar in enumerate(bars)}
    position = 0
    cycle_trades: list[TradeResult] = []
    running_asset = float(starting_asset)
    segments: list[TradeSegment] = []
    for trade in accepted:
        if trade.side == "buy":
            if position <= 0:
                position = 0
                cycle_trades = []
            cycle_trades.append(trade)
            position += trade.quantity
            continue
        if position <= 0:
            continue
        cycle_trades.append(trade)
        position = max(0, position - trade.quantity)
        if position > 0:
            continue
        buys = [item for item in cycle_trades if item.side == "buy"]
        sells = [item for item in cycle_trades if item.side == "sell"]
        if not buys or not sells:
            cycle_trades = []
            continue
        cash_out = sum(item.amount + item.fee + item.tax for item in buys)
        cash_in = sum(item.amount - item.fee - item.tax for item in sells)
        profit = round(cash_in - cash_out, 2)
        end_asset = round(running_asset + profit, 2)
        rate = round(profit / running_asset * 100, 6) if running_asset > 0 else 0.0
        start_date = buys[0].date
        end_date = sells[-1].date
        start_index = date_indices.get(start_date)
        end_index = date_indices.get(end_date)
        holding_days = (
            abs(end_index - start_index) + 1
            if start_index is not None and end_index is not None
            else 0
        )
        segments.append(
            TradeSegment(
                index=len(segments) + 1,
                start_date=start_date,
                end_date=end_date,
                start_node=buys[0].node,
                end_node=sells[-1].node,
                start_asset=round(running_asset, 2),
                end_asset=end_asset,
                profit=profit,
                return_rate=rate,
                holding_days=holding_days,
                buy_count=len(buys),
                sell_count=len(sells),
                fee=round(sum(item.fee for item in cycle_trades), 2),
                tax=round(sum(item.tax for item in cycle_trades), 2),
            )
        )
        running_asset = end_asset
        cycle_trades = []
    return segments


def benchmark_interval_return(
    bars: list[DailyBar],
    start_date: str,
    start_node: TradeNode,
    end_date: str,
    end_node: TradeNode,
) -> float | None:
    if not bars or not start_date or not end_date:
        return None
    # TDX and bundled daily bars are already chronological.  Keep that common
    # path linear and use binary search for the two boundaries; only repair the
    # uncommon out-of-order input instead of sorting on every calculation.
    ordered = bars
    if any(previous.date > current.date for previous, current in zip(bars, bars[1:])):
        ordered = sorted(bars, key=lambda item: item.date)
    dates = [bar.date for bar in ordered]
    start_index = bisect_left(dates, start_date)
    end_index = bisect_right(dates, end_date) - 1
    if start_index >= len(ordered) or end_index < start_index:
        return None
    start_bar = ordered[start_index]
    end_bar = ordered[end_index]
    start_price = start_bar.price_at(start_node)
    end_price = end_bar.price_at(end_node)
    if start_price <= 0:
        return None
    return round((end_price / start_price - 1) * 100, 6)


def calculate_performance_metrics(
    *,
    initial_asset: float,
    ending_asset: float,
    segments: list[TradeSegment],
    trades: list[TradeResult],
    equity_points: list[EquityPoint],
    index_bars: list[DailyBar],
    start_date: str,
    start_node: TradeNode,
    end_date: str,
    end_node: TradeNode,
    stock_count: int = 1,
    round_count: int = 1,
) -> PerformanceMetrics:
    initial = max(0.0, float(initial_asset))
    ending = max(0.0, float(ending_asset))
    net_profit = round(ending - initial, 2)
    total_return = round(net_profit / initial * 100, 6) if initial > 0 else 0.0

    daily_assets = _daily_assets(equity_points)
    values = [initial] if initial > 0 else []
    values.extend(value for _date, value in daily_assets if value > 0)
    if ending > 0 and (not values or abs(values[-1] - ending) > 0.005):
        values.append(ending)
    returns = _simple_returns(values)
    annual_return = _annual_return(initial, ending, len(returns))
    annual_volatility = _annual_volatility(returns)
    sharpe_ratio = _sharpe_ratio(returns)
    sortino_ratio = _sortino_ratio(returns)
    max_drawdown = _maximum_drawdown(values)
    calmar_ratio = None
    if annual_return is not None and max_drawdown < 0:
        calmar_ratio = round((annual_return / 100) / abs(max_drawdown / 100), 6)
    return_drawdown_ratio = None
    if max_drawdown < 0:
        return_drawdown_ratio = round(total_return / abs(max_drawdown), 6)
    elif total_return > 0:
        return_drawdown_ratio = math.inf

    benchmark_return = benchmark_interval_return(
        index_bars, start_date, start_node, end_date, end_node
    )
    excess_return = (
        round(total_return - benchmark_return, 6)
        if benchmark_return is not None
        else None
    )
    information_ratio = _information_ratio(daily_assets, index_bars)

    segment_rates = [segment.return_rate for segment in segments]
    wins = [value for value in segment_rates if value > 0]
    losses = [value for value in segment_rates if value < 0]
    segment_count = len(segment_rates)
    win_rate = round(len(wins) / segment_count * 100, 6) if segment_count else None
    average_win = round(sum(wins) / len(wins), 6) if wins else None
    average_loss = round(sum(losses) / len(losses), 6) if losses else None
    if average_win is not None and average_loss not in (None, 0):
        profit_loss_ratio = round(average_win / abs(average_loss), 6)
    elif average_win is not None and average_loss is None:
        profit_loss_ratio = math.inf
    elif average_loss is not None:
        profit_loss_ratio = 0.0
    else:
        profit_loss_ratio = None
    gross_profit = sum(segment.profit for segment in segments if segment.profit > 0)
    gross_loss = abs(sum(segment.profit for segment in segments if segment.profit < 0))
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 6)
    elif gross_profit > 0:
        profit_factor = math.inf
    else:
        profit_factor = None
    expectancy = round(sum(segment_rates) / segment_count, 6) if segment_count else None
    accepted_trades = [trade for trade in trades if trade.accepted and trade.side in {"buy", "sell"}]

    return PerformanceMetrics(
        initial_asset=round(initial, 2),
        ending_asset=round(ending, 2),
        net_profit=net_profit,
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        annual_return=annual_return,
        max_drawdown=max_drawdown,
        annual_volatility=annual_volatility,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        calmar_ratio=calmar_ratio,
        return_drawdown_ratio=return_drawdown_ratio,
        information_ratio=information_ratio,
        segment_count=segment_count,
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        profit_factor=profit_factor,
        expectancy=expectancy,
        average_win=average_win,
        average_loss=average_loss,
        best_segment=max(segment_rates) if segment_rates else None,
        worst_segment=min(segment_rates) if segment_rates else None,
        trade_count=len(accepted_trades),
        holding_days=sum(segment.holding_days for segment in segments),
        fee_and_tax=round(sum(trade.fee + trade.tax for trade in accepted_trades), 2),
        stock_count=max(0, int(stock_count)),
        round_count=max(0, int(round_count)),
        sample_days=len(returns),
    )


def _daily_assets(points: list[EquityPoint]) -> list[tuple[str, float]]:
    latest_by_date: dict[str, float] = {}
    for point in points:
        if point.date and point.total_asset > 0:
            latest_by_date[point.date] = float(point.total_asset)
    return [(date, latest_by_date[date]) for date in sorted(latest_by_date)]


def _simple_returns(values: list[float]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(values, values[1:]):
        if previous > 0 and current > 0:
            returns.append(current / previous - 1)
    return returns


def _annual_return(initial: float, ending: float, periods: int) -> float | None:
    if initial <= 0 or ending <= 0 or periods <= 0:
        return None
    try:
        result = ((ending / initial) ** (TRADING_DAYS_PER_YEAR / periods) - 1) * 100
    except OverflowError:
        return None
    return round(result, 6) if math.isfinite(result) else None


def _annual_volatility(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    return round(statistics.stdev(returns) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100, 6)


def _sharpe_ratio(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    deviation = statistics.stdev(returns)
    if deviation <= 0:
        return None
    return round(statistics.mean(returns) / deviation * math.sqrt(TRADING_DAYS_PER_YEAR), 6)


def _sortino_ratio(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    downside = [min(0.0, value) for value in returns]
    downside_deviation = math.sqrt(sum(value * value for value in downside) / len(downside))
    if downside_deviation <= 0:
        return None
    return round(statistics.mean(returns) / downside_deviation * math.sqrt(TRADING_DAYS_PER_YEAR), 6)


def _maximum_drawdown(values: list[float]) -> float:
    valid = [value for value in values if value > 0]
    if not valid:
        return 0.0
    peak = valid[0]
    result = 0.0
    for value in valid:
        peak = max(peak, value)
        result = min(result, (value / peak - 1) * 100)
    return round(result, 6)


def _information_ratio(daily_assets: list[tuple[str, float]], index_bars: list[DailyBar]) -> float | None:
    if len(daily_assets) < 3 or not index_bars:
        return None
    index_close = {bar.date: bar.close for bar in index_bars if bar.close > 0}
    aligned = [(date, asset, index_close[date]) for date, asset in daily_assets if date in index_close]
    if len(aligned) < 3:
        return None
    excess_returns = []
    for previous, current in zip(aligned, aligned[1:]):
        strategy_return = current[1] / previous[1] - 1
        benchmark_return = current[2] / previous[2] - 1
        excess_returns.append(strategy_return - benchmark_return)
    if len(excess_returns) < 2:
        return None
    deviation = statistics.stdev(excess_returns)
    if deviation <= 0:
        return None
    return round(statistics.mean(excess_returns) / deviation * math.sqrt(TRADING_DAYS_PER_YEAR), 6)
