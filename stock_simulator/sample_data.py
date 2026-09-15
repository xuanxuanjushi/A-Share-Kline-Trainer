from __future__ import annotations

import json
import random
from functools import lru_cache
from importlib import resources

from .engine import DailySimulationEngine
from .models import DailyBar
from .session import (
    CONTINUATION_MIN_FORWARD_BARS,
    CONTINUATION_MIN_HISTORY_BARS,
    MIN_REQUIRED_BARS,
    RANDOM_TRAINING_WINDOW_BARS,
    _has_abnormal_daily_change,
    _has_main_board_drop_over_limit,
    _start_index,
)


SAMPLE_KLINE_NAME = "测试K线"
SAMPLE_KLINE_RESOURCE = "sample_klines_2015_2026.json"
SAMPLE_MIN_HISTORY_BARS = 120


@lru_cache(maxsize=1)
def _load_sample_stock_records() -> tuple[tuple[str, str, tuple[DailyBar, ...]], ...]:
    with resources.files("stock_simulator.assets").joinpath(SAMPLE_KLINE_RESOURCE).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    records = []
    for sample in payload["samples"]:
        records.append(
            (
                sample["code"],
                sample.get("name") or SAMPLE_KLINE_NAME,
                tuple(DailyBar(**item) for item in sample["bars"]),
            )
        )
    return tuple(records)


def load_sample_stocks() -> list[dict]:
    """Return cheap independent views over the immutable bundled sample cache."""

    return [
        {"code": code, "name": name, "bars": list(bars)}
        for code, name, bars in _load_sample_stock_records()
    ]


def load_sample_bars(code: str | None = None) -> list[DailyBar]:
    samples = load_sample_stocks()
    if code:
        normalized = code.strip().lower()
        for sample in samples:
            if sample["code"] == normalized:
                return sample["bars"]
        raise ValueError(f"内置测试K线不存在：{code}")
    return samples[0]["bars"]


def choose_sample_session_data(start_date: str | None, code: str | None = None) -> tuple[list[DailyBar], int]:
    samples = load_sample_stocks()
    sample = _sample_by_code(samples, code) if code else samples[random.randrange(len(samples))]
    bars = sample["bars"]
    if len(bars) < MIN_REQUIRED_BARS:
        raise ValueError("内置测试K线数据太少，无法模拟")
    start_index = _start_index(bars, start_date) if start_date else _random_sample_start_index(bars)
    start_index = max(SAMPLE_MIN_HISTORY_BARS, start_index)
    return bars, start_index


def create_sample_engine(
    start_date: str | None,
    initial_cash: float,
    slot_count: int,
    commission_rate: float,
    stamp_tax_rate: float,
    min_commission: float,
    code: str | None = None,
) -> DailySimulationEngine:
    bars, start_index = choose_sample_session_data(start_date, code)
    return DailySimulationEngine(
        bars=bars,
        initial_cash=initial_cash,
        slot_count=slot_count,
        commission_rate=commission_rate,
        stamp_tax_rate=stamp_tax_rate,
        min_commission=min_commission,
        start_index=start_index,
    )


def create_continued_sample_engine(
    after_date: str,
    account_initial_cash: float,
    slot_count: int,
    commission_rate: float,
    stamp_tax_rate: float,
    min_commission: float,
    exclude_code: str | None = None,
) -> tuple[DailySimulationEngine, str]:
    bars, start_index, code = _choose_continued_sample_session(after_date, exclude_code)
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


def _choose_continued_sample_session(
    after_date: str,
    exclude_code: str | None = None,
) -> tuple[list[DailyBar], int, str]:
    samples = load_sample_stocks()
    random.shuffle(samples)
    best: tuple[str, list[DailyBar], int, str] | None = None
    for sample in samples:
        if exclude_code and sample["code"] == exclude_code:
            continue
        bars = sample["bars"]
        if len(bars) < MIN_REQUIRED_BARS:
            continue
        start_index = _continuation_start_index(bars, after_date)
        if start_index is None:
            continue
        if start_index < CONTINUATION_MIN_HISTORY_BARS:
            continue
        if len(bars) - start_index < CONTINUATION_MIN_FORWARD_BARS:
            continue
        window_end = min(len(bars), start_index + CONTINUATION_MIN_FORWARD_BARS)
        forward_window = bars[start_index:window_end]
        if _has_abnormal_daily_change(forward_window):
            continue
        if _has_main_board_drop_over_limit(forward_window):
            continue
        candidate_date = bars[start_index].date
        if best is None or candidate_date < best[0]:
            best = (candidate_date, bars, start_index, sample["code"])
    if best is not None:
        return best[1], best[2], best[3]
    raise ValueError("没有找到适合在指定日期之后继续模拟的测试K线。")


def _continuation_start_index(bars: list[DailyBar], after_date: str) -> int | None:
    for index, bar in enumerate(bars):
        if bar.date > after_date:
            return index
    return None


def _random_sample_start_index(bars: list[DailyBar]) -> int:
    latest_safe_index = max(0, len(bars) - RANDOM_TRAINING_WINDOW_BARS)
    earliest_safe_index = min(SAMPLE_MIN_HISTORY_BARS, latest_safe_index)
    valid_indices = list(range(earliest_safe_index, latest_safe_index + 1))
    return random.choice(valid_indices)


def _sample_by_code(samples: list[dict], code: str) -> dict:
    normalized = code.strip().lower()
    for sample in samples:
        if sample["code"] == normalized:
            return sample
    raise ValueError(f"内置测试K线不存在：{code}")
