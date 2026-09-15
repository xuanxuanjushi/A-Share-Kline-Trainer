from __future__ import annotations

import json
import os
from pathlib import Path
import re
import urllib.request
from uuid import uuid4

from .models import DailyBar


SHANGHAI_INDEX_CODE = "sh999999"
SHANGHAI_INDEX_NAME = "上证指数"
SHANGHAI_INDEX_ALIASES = {"上证指数", "szzs", "03", "sh000001", "sh999999"}
TENCENT_INDEX_UPDATE_URL = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    "?param=sh000001,day,,,2000,qfq"
)
EASTMONEY_INDEX_UPDATE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid=1.000001&klt=101&fqt=0&lmt=1000000&end=20500101"
    "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57"
)
SHANGHAI_INDEX_UPDATE_URL = TENCENT_INDEX_UPDATE_URL
INDEX_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}


def is_shanghai_index_query(query: str) -> bool:
    cleaned = query.strip()
    return cleaned in SHANGHAI_INDEX_ALIASES or cleaned.lower() in SHANGHAI_INDEX_ALIASES


def parse_shanghai_index_response(payload: bytes | str) -> list[DailyBar]:
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    document = json.loads(text)
    data = document.get("data") or {}
    index_data = data.get("sh000001") or {} if isinstance(data, dict) else {}
    rows = index_data.get("day") or index_data.get("qfqday") or [] if isinstance(index_data, dict) else []
    bars: list[DailyBar] = []
    for row in rows:
        fields = row.split(",") if isinstance(row, str) else row
        if len(fields) < 6:
            continue
        try:
            bars.append(
                DailyBar(
                    code=SHANGHAI_INDEX_CODE,
                    date=fields[0],
                    open=float(fields[1]),
                    close=float(fields[2]),
                    high=float(fields[3]),
                    low=float(fields[4]),
                    volume=int(float(fields[5])),
                    amount=float(fields[6]) if len(fields) >= 7 else 0.0,
                )
            )
        except (TypeError, ValueError):
            continue
    bars = _normalize_index_bars(bars)
    if not bars:
        raise ValueError("联网行情没有返回可用的上证指数日K数据。")
    return bars


def parse_eastmoney_index_response(payload: bytes | str) -> list[DailyBar]:
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    document = json.loads(text)
    data = document.get("data") or {}
    rows = data.get("klines") or [] if isinstance(data, dict) else []
    bars: list[DailyBar] = []
    for row in rows:
        fields = row.split(",") if isinstance(row, str) else row
        if len(fields) < 7:
            continue
        try:
            bars.append(
                DailyBar(
                    code=SHANGHAI_INDEX_CODE,
                    date=str(fields[0]),
                    open=float(fields[1]),
                    close=float(fields[2]),
                    high=float(fields[3]),
                    low=float(fields[4]),
                    volume=int(float(fields[5])),
                    amount=float(fields[6]),
                )
            )
        except (TypeError, ValueError):
            continue
    bars = _normalize_index_bars(bars)
    if not bars:
        raise ValueError("备用行情源没有返回可用的上证指数日K数据。")
    return bars


def fetch_shanghai_index_bars(history: list[DailyBar] | None = None, timeout: float = 8.0) -> list[DailyBar]:
    sources = (
        (EASTMONEY_INDEX_UPDATE_URL, parse_eastmoney_index_response),
        (TENCENT_INDEX_UPDATE_URL, parse_shanghai_index_response),
    )
    failures: list[Exception] = []
    for url, parser in sources:
        try:
            request = urllib.request.Request(url, headers=INDEX_REQUEST_HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                updates = parser(response.read())
            return merge_index_bars(history or [], updates)
        except Exception as exc:
            failures.append(exc)
    detail = str(failures[-1]) if failures else "未知错误"
    raise RuntimeError(f"所有上证指数行情源均更新失败：{detail}")


def merge_index_bars(history: list[DailyBar], updates: list[DailyBar]) -> list[DailyBar]:
    merged = {bar.date: bar for bar in _normalize_index_bars(history)}
    for bar in _normalize_index_bars(updates):
        previous = merged.get(bar.date)
        if previous is not None and bar.amount <= 0:
            bar = DailyBar(
                code=bar.code,
                date=bar.date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                amount=previous.amount,
                volume=bar.volume,
            )
        merged[bar.date] = bar
    return [merged[date] for date in sorted(merged)]


def save_index_cache(path: Path, bars: list[DailyBar]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "amount": bar.amount,
            "volume": bar.volume,
        }
        for bar in _normalize_index_bars(bars)
    ]
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_index_cache(path: Path) -> list[DailyBar]:
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []
    rows = document.get("bars", []) if isinstance(document, dict) else document
    if not isinstance(rows, list):
        return []
    bars: list[DailyBar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            bars.append(
                DailyBar(
                    code=SHANGHAI_INDEX_CODE,
                    date=str(row["date"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    amount=float(row.get("amount", 0)),
                    volume=int(row.get("volume", 0)),
                )
            )
        except (TypeError, ValueError, KeyError):
            continue
    return _normalize_index_bars(bars)


def _normalize_index_bars(bars: list[DailyBar]) -> list[DailyBar]:
    normalized: dict[str, DailyBar] = {}
    for bar in bars:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(bar.date)):
            continue
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            continue
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            continue
        normalized[bar.date] = DailyBar(
            code=SHANGHAI_INDEX_CODE,
            date=bar.date,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            amount=max(0.0, float(bar.amount)),
            volume=max(0, int(bar.volume)),
        )
    return [normalized[date] for date in sorted(normalized)]
