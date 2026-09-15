from __future__ import annotations

from datetime import datetime
import random
import re

from .engine import DailySimulationEngine
from .models import DailyBar
from .tdx_reader import TdxDayReader


MIN_REQUIRED_BARS = 80
RANDOM_MIN_HISTORY_BARS = 120
RANDOM_TRAINING_WINDOW_BARS = 120
RANDOM_MAX_ATTEMPTS = 120
CONTINUATION_MIN_HISTORY_BARS = 120
CONTINUATION_MIN_FORWARD_BARS = 120


def choose_session_bars(reader: TdxDayReader, code: str | None, start_date: str | None) -> list[DailyBar]:
    bars, start_index = choose_session_data(reader, code, start_date)
    return bars[start_index:]


def choose_session_data(
    reader: TdxDayReader,
    code: str | None,
    start_date: str | None,
    min_forward_bars: int = RANDOM_TRAINING_WINDOW_BARS,
    allowed_codes: set[str] | None = None,
) -> tuple[list[DailyBar], int]:
    if code:
        selected_code = reader.normalize_code(code)
        bars = _clean_bars(reader.read_daily_bars(selected_code))
        if len(bars) < MIN_REQUIRED_BARS:
            raise ValueError("这只股票的日K数据太少，无法模拟")
        start_index = _start_index(bars, start_date)
    else:
        bars, start_index = _choose_random_session(
            reader, start_date, min_forward_bars, allowed_codes
        )
    return bars, start_index


def _clean_bars(bars: list[DailyBar]) -> list[DailyBar]:
    return [bar for bar in bars if bar.open > 0 and bar.close > 0]


def _choose_random_session(
    reader: TdxDayReader,
    start_date: str | None,
    min_forward_bars: int,
    allowed_codes: set[str] | None = None,
) -> tuple[list[DailyBar], int]:
    """Choose from forward-adjusted data using only history/forward bounds."""
    codes = reader.scan_stock_codes()
    if allowed_codes is not None:
        # 按“主板/创业板/科创板/北交所/ST”勾选过滤随机换股的候选股票。
        codes = [code for code in codes if code in allowed_codes]
    if not codes:
        raise ValueError("没有找到通达信日K数据，请检查目录是否包含 lday 数据。")

    for selected_code in random.sample(codes, min(len(codes), RANDOM_MAX_ATTEMPTS)):
        try:
            bars = _clean_bars(reader.read_daily_bars(selected_code))
        except Exception:
            continue
        forward_bars = max(1, int(min_forward_bars))
        if len(bars) < RANDOM_MIN_HISTORY_BARS + forward_bars:
            continue
        try:
            if start_date:
                start_index = _start_index(bars, start_date)
                if start_index < RANDOM_MIN_HISTORY_BARS or len(bars) - start_index < forward_bars:
                    continue
            else:
                start_index = random.choice(_random_start_indices(bars, forward_bars))
        except ValueError:
            continue
        return bars, start_index

    raise ValueError("没有找到满足前置半年历史和所选训练时长的股票。")


# Bundled sample continuation keeps its historical safety checks. Real TDX
# random selection intentionally does not call these functions anymore.
def _has_abnormal_daily_change(bars: list[DailyBar], threshold_pct: float = 35.0) -> bool:
    for previous, current in zip(bars, bars[1:]):
        if previous.close <= 0:
            continue
        change_pct = abs((current.close - previous.close) / previous.close * 100)
        if change_pct >= threshold_pct:
            return True
    return False


def _has_main_board_drop_over_limit(bars: list[DailyBar], threshold_pct: float = 11.0) -> bool:
    if not bars or not _is_main_board_code(bars[0].code):
        return False
    for previous, current in zip(bars, bars[1:]):
        if previous.close <= 0:
            continue
        change_pct = (current.close - previous.close) / previous.close * 100
        if change_pct < -threshold_pct:
            return True
    return False


def _is_main_board_code(code: str) -> bool:
    return code.startswith("sh60") or code.startswith("sz00")


def _random_start_indices(
    bars: list[DailyBar],
    min_forward_bars: int = RANDOM_TRAINING_WINDOW_BARS,
) -> list[int]:
    latest_safe_index = len(bars) - max(1, int(min_forward_bars))
    earliest_safe_index = RANDOM_MIN_HISTORY_BARS
    if latest_safe_index < earliest_safe_index:
        return []
    return list(range(earliest_safe_index, latest_safe_index + 1))


def create_engine(
    reader: TdxDayReader,
    code: str | None,
    start_date: str | None,
    initial_cash: float,
    slot_count: int,
    commission_rate: float,
    stamp_tax_rate: float,
    min_commission: float,
    random_min_forward_bars: int = RANDOM_TRAINING_WINDOW_BARS,
    allowed_codes: set[str] | None = None,
) -> DailySimulationEngine:
    bars, start_index = choose_session_data(
        reader,
        code,
        start_date,
        min_forward_bars=random_min_forward_bars,
        allowed_codes=allowed_codes,
    )
    return DailySimulationEngine(
        bars=bars,
        initial_cash=initial_cash,
        slot_count=slot_count,
        commission_rate=commission_rate,
        stamp_tax_rate=stamp_tax_rate,
        min_commission=min_commission,
        start_index=start_index,
    )


def create_continued_engine(
    reader: TdxDayReader,
    after_date: str,
    account_initial_cash: float,
    slot_count: int,
    commission_rate: float,
    stamp_tax_rate: float,
    min_commission: float,
    exclude_code: str | None = None,
    min_forward_bars: int = CONTINUATION_MIN_FORWARD_BARS,
    allowed_codes: set[str] | None = None,
) -> tuple[DailySimulationEngine, str]:
    """Build a new engine for the next stock, advancing to the next trading day."""
    bars, start_index, code = choose_continued_session_data(
        reader,
        after_date,
        exclude_code,
        min_forward_bars=min_forward_bars,
        allowed_codes=allowed_codes,
    )
    engine = DailySimulationEngine(
        bars=bars,
        initial_cash=account_initial_cash,
        slot_count=slot_count,
        commission_rate=commission_rate,
        stamp_tax_rate=stamp_tax_rate,
        min_commission=min_commission,
        start_index=start_index,
    )
    return engine, code


def choose_continued_session_data(
    reader: TdxDayReader,
    after_date: str,
    exclude_code: str | None = None,
    min_forward_bars: int = CONTINUATION_MIN_FORWARD_BARS,
    allowed_codes: set[str] | None = None,
) -> tuple[list[DailyBar], int, str]:
    """Prepare continuation bars without constructing an account engine.

    This split lets the UI do disk I/O, candidate validation, and adjustment in
    a background worker, then create the lightweight engine only when the user
    clicks the switch button.
    """
    return _choose_continuation_session(
        reader,
        after_date,
        exclude_code,
        min_forward_bars,
        allowed_codes,
    )


def _choose_continuation_session(
    reader: TdxDayReader,
    after_date: str,
    exclude_code: str | None = None,
    min_forward_bars: int = CONTINUATION_MIN_FORWARD_BARS,
    allowed_codes: set[str] | None = None,
) -> tuple[list[DailyBar], int, str]:
    codes = reader.scan_stock_codes()
    if allowed_codes is not None:
        codes = [code for code in codes if code in allowed_codes]
    if not codes:
        raise ValueError("没有找到通达信日K数据，请检查目录是否包含 lday 数据。")

    for selected_code in random.sample(codes, min(len(codes), RANDOM_MAX_ATTEMPTS)):
        if exclude_code and selected_code == exclude_code:
            continue
        try:
            bars = _clean_bars(reader.read_daily_bars(selected_code))
        except Exception:
            continue
        start_index = _continuation_start_index(bars, after_date)
        if start_index is None:
            continue
        if not _valid_continuation_candidate(bars, start_index, min_forward_bars):
            continue
        # A valid candidate already starts strictly after the current date.
        # Returning it immediately avoids decoding and adjusting up to another
        # 119 stocks merely to find the same next trading day.
        return bars, start_index, selected_code
    raise ValueError("没有找到适合在指定日期之后继续模拟的股票（可能历史不足，或已到最新交易日）。")


def _valid_continuation_candidate(
    bars: list[DailyBar],
    start_index: int,
    min_forward_bars: int = CONTINUATION_MIN_FORWARD_BARS,
) -> bool:
    if len(bars) < MIN_REQUIRED_BARS:
        return False
    if start_index < CONTINUATION_MIN_HISTORY_BARS:
        return False
    if len(bars) - start_index < max(1, int(min_forward_bars)):
        return False
    return True


def _continuation_start_index(bars: list[DailyBar], after_date: str) -> int | None:
    for index, bar in enumerate(bars):
        if bar.date > after_date:
            return index
    return None


def normalize_start_date(value: str) -> str:
    cleaned = value.strip().replace("/", "-").replace(".", "-")
    compact = cleaned.replace("-", "")
    formats = {4: "%Y", 6: "%Y%m", 8: "%Y%m%d"}
    date_format = formats.get(len(compact))
    if date_format is None or not re.fullmatch(r"\d+", compact):
        raise ValueError("日期支持 2018、201612、20180506 或 2018-05-06 格式。")
    try:
        parsed = datetime.strptime(compact, date_format)
    except ValueError as exc:
        raise ValueError("日期无效，请检查年份、月份和日期。") from exc
    if len(compact) == 4:
        return f"{parsed.year:04d}-01-01"
    if len(compact) == 6:
        return f"{parsed.year:04d}-{parsed.month:02d}-01"
    return parsed.strftime("%Y-%m-%d")


def _start_index(bars: list[DailyBar], start_date: str | None) -> int:
    if start_date:
        normalized = normalize_start_date(start_date)
        for index, bar in enumerate(bars):
            if bar.date >= normalized:
                return index
        raise ValueError("指定日期之后没有可用日K数据")

    latest_safe_index = max(0, len(bars) - 20)
    earliest_safe_index = min(60, latest_safe_index)
    if latest_safe_index <= earliest_safe_index:
        return 0
    return random.randint(earliest_safe_index, latest_safe_index)
