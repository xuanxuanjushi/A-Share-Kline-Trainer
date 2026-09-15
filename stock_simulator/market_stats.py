from __future__ import annotations

import json
import hashlib
import math
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import DailyBar
from .tdx_reader import DAY_RECORD, TdxDayReader


MARKET_STATS_CACHE_VERSION = 1
PUBLIC_MARKET_PAGE_SIZE = 100
PUBLIC_MARKET_MIN_STOCKS = 4000
PUBLIC_MARKET_HOSTS = ("https://push2.eastmoney.com", "https://82.push2.eastmoney.com")
PUBLIC_MARKET_PATH = "/api/qt/clist/get"
PUBLIC_MARKET_QUERY = (
    "po=1&np=1&fltt=2&invt=2&fid=f3"
    "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    "&fields=f2,f3,f6,f12,f14,f18,f124"
)
PUBLIC_MARKET_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}
CHINA_TIMEZONE = timezone(timedelta(hours=8))


@dataclass
class DailyMarketStats:
    date: str
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    amount: float = 0.0
    limit_up_count: int = 0
    limit_down_count: int = 0


@dataclass(frozen=True)
class MarketStatsBuildResult:
    root: str
    stats: dict[str, DailyMarketStats]
    file_count: int
    rebuilt: bool


def load_market_stats_cache(path: Path, root: Path) -> dict[str, DailyMarketStats]:
    document = _read_cache_document(path)
    if not document or document.get("root") != _root_key(root):
        return {}
    return _stats_from_document(document)


def load_market_stats_snapshot(path: Path) -> dict[str, DailyMarketStats]:
    return _stats_from_document(_read_cache_document(path))


def public_market_stats_date(path: Path) -> str:
    document = _read_cache_document(path)
    value = document.get("public_latest_date", "") if document else ""
    return value if isinstance(value, str) else ""


def save_public_market_stats(path: Path, daily: DailyMarketStats) -> dict[str, DailyMarketStats]:
    document = _read_cache_document(path)
    if not document:
        document = {
            "version": MARKET_STATS_CACHE_VERSION,
            "root": "",
            "files": {},
            "stats": {},
        }
    raw_stats = document.get("stats")
    if not isinstance(raw_stats, dict):
        raw_stats = {}
        document["stats"] = raw_stats
    raw_stats[daily.date] = asdict(daily)
    document["public_latest_date"] = daily.date
    _write_cache_document(path, document)
    return _stats_from_document(document)


def fetch_public_market_stats(timeout: float = 8.0, max_workers: int = 8) -> DailyMarketStats:
    failures: list[Exception] = []
    for host in PUBLIC_MARKET_HOSTS:
        try:
            first = _fetch_public_market_page(host, 1, timeout)
            data = first.get("data") or {}
            total = int(data.get("total", 0))
            pages = max(1, math.ceil(total / PUBLIC_MARKET_PAGE_SIZE))
            page_documents = [first]
            if pages > 1:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    page_documents.extend(
                        executor.map(
                            lambda page: _fetch_public_market_page(host, page, timeout),
                            range(2, pages + 1),
                        )
                    )
            return parse_public_market_stats(page_documents)
        except Exception as exc:
            failures.append(exc)
    detail = str(failures[-1]) if failures else "未知错误"
    raise RuntimeError(f"公开市场统计更新失败：{detail}")


def parse_public_market_stats(documents: list[dict]) -> DailyMarketStats:
    quotes: dict[str, dict] = {}
    for document in documents:
        data = document.get("data") or {} if isinstance(document, dict) else {}
        rows = data.get("diff") or [] if isinstance(data, dict) else []
        if isinstance(rows, dict):
            rows = rows.values()
        for row in rows:
            if isinstance(row, dict) and row.get("f12"):
                quotes[str(row["f12"])] = row
    if len(quotes) < PUBLIC_MARKET_MIN_STOCKS:
        raise ValueError(f"公开市场统计股票数量不足：{len(quotes)}")

    timestamps = [_to_int(row.get("f124")) for row in quotes.values()]
    latest_timestamp = max((value for value in timestamps if value > 0), default=0)
    if latest_timestamp <= 0:
        raise ValueError("公开市场统计缺少交易日期。")
    date = datetime.fromtimestamp(latest_timestamp, CHINA_TIMEZONE).date().isoformat()
    daily = DailyMarketStats(date=date)
    for code, row in quotes.items():
        change_pct = _to_float(row.get("f3"))
        amount = _to_float(row.get("f6"))
        if amount > 0:
            daily.amount += amount
        if change_pct > 0:
            daily.up_count += 1
        elif change_pct < 0:
            daily.down_count += 1
        else:
            daily.flat_count += 1

        name = str(row.get("f14") or "")
        if name.upper().startswith(("N", "C")):
            continue
        limit_pct = _public_limit_pct(code, name)
        if change_pct >= limit_pct - 0.11:
            daily.limit_up_count += 1
        elif change_pct <= -limit_pct + 0.11:
            daily.limit_down_count += 1
    daily.amount = round(daily.amount, 2)
    return daily


def _fetch_public_market_page(host: str, page: int, timeout: float) -> dict:
    url = (
        f"{host}{PUBLIC_MARKET_PATH}?pn={page}&pz={PUBLIC_MARKET_PAGE_SIZE}"
        f"&{PUBLIC_MARKET_QUERY}"
    )
    request = urllib.request.Request(url, headers=PUBLIC_MARKET_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        document = json.loads(response.read().decode("utf-8-sig"))
    if not isinstance(document, dict) or not document.get("data"):
        raise ValueError("公开市场统计返回为空。")
    return document


def _public_limit_pct(code: str, name: str) -> float:
    if "ST" in name.upper():
        return 5.0
    if code.startswith(("68", "30")):
        return 20.0
    if code.startswith(("8", "9")):
        return 30.0
    return 10.0


def _to_float(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_market_stats_cache(path: Path, reader: TdxDayReader) -> MarketStatsBuildResult:
    files = reader.market_a_share_day_files()
    root = _root_key(reader.tdx_root)
    current_files = {
        code: {
            "path": str(file_path),
            "size": file_path.stat().st_size,
            "mtime_ns": file_path.stat().st_mtime_ns,
        }
        for code, file_path in files
    }
    document = _read_cache_document(path)
    cached_files = document.get("files", {}) if document and document.get("root") == root else {}
    stats = _stats_from_document(document) if document and document.get("root") == root else {}
    if any(item['size'] % DAY_RECORD.size for item in current_files.values()):
        raise ValueError("通达信日K仍在写入，稍后自动重试。")
    rebuild = (_requires_full_rebuild(cached_files, current_files)
               or not stats
               or document.get('stats_checksum') != _stats_checksum(document.get('stats', {})))
    if rebuild:
        stats = {}
        cached_files = {}

    for code, file_path in files:
        current = current_files[code]
        previous = cached_files.get(code, {})
        start_offset = 0 if rebuild else int(previous.get("size", 0))
        if start_offset == current["size"]:
            continue
        _accumulate_day_file(stats, code, file_path, start_offset)

    # A download may replace or append files while the background calculation runs.
    # Never commit offsets for a different snapshot than the one just calculated.
    after_files = reader.market_a_share_day_files()
    if ([code for code, _ in after_files] != [code for code, _ in files]
            or any(file_path.stat().st_size != current_files[code]['size']
                   or file_path.stat().st_mtime_ns != current_files[code]['mtime_ns']
                   for code, file_path in after_files)):
        raise ValueError("通达信数据正在写入，稍后自动重试。")
    raw_stats = {date: asdict(stats[date]) for date in sorted(stats)}
    _write_cache_document(
        path,
        {
            "version": MARKET_STATS_CACHE_VERSION,
            "root": root,
            "files": current_files,
            "stats": raw_stats,
            "stats_checksum": _stats_checksum(raw_stats),
        },
    )
    return MarketStatsBuildResult(root=root, stats=stats, file_count=len(files), rebuilt=rebuild)


def _stats_checksum(stats: dict) -> str:
    return hashlib.sha256(json.dumps(stats, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def previous_market_stats(
    stats_by_date: dict[str, DailyMarketStats],
    date: str,
) -> DailyMarketStats | None:
    previous_dates = [item for item in stats_by_date if item < date]
    if not previous_dates:
        return None
    return stats_by_date[max(previous_dates)]


def market_amount_change_pct(current: DailyMarketStats, previous: DailyMarketStats | None) -> float | None:
    if previous is None or previous.amount <= 0:
        return None
    return round((current.amount - previous.amount) / previous.amount * 100, 2)


def format_market_amount(amount: float) -> str:
    if amount >= 1_000_000_000_000:
        return f"{amount / 1_000_000_000_000:.2f}万亿"
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:.0f}亿"
    if amount >= 10_000:
        return f"{amount / 10_000:.0f}万"
    return f"{amount:.0f}"


def index_ma_state(bars: list[DailyBar], index: int) -> str:
    if not bars or index < 0:
        return "--"
    index = min(index, len(bars) - 1)
    closes = [bar.close for bar in bars[: index + 1]]
    current = closes[-1]
    averages: list[tuple[int, float]] = []
    for period in (5, 10, 20, 60):
        if len(closes) >= period:
            averages.append((period, sum(closes[-period:]) / period))
    if not averages:
        return "数据不足"
    above_periods = [period for period, average in averages if current >= average]
    if not above_periods:
        return "位于全部均线下方"
    period_text = "、".join(str(period) for period in above_periods)
    return f"站上{period_text}日线"


def market_state_text(
    index_change_pct: float,
    stats: DailyMarketStats,
    amount_change_pct: float | None,
) -> tuple[str, str]:
    score = 1 if index_change_pct > 0.2 else (-1 if index_change_pct < -0.2 else 0)
    breadth_total = stats.up_count + stats.down_count
    if breadth_total:
        up_ratio = stats.up_count / breadth_total
        if up_ratio >= 0.62:
            score += 2
        elif up_ratio >= 0.54:
            score += 1
        elif up_ratio <= 0.38:
            score -= 2
        elif up_ratio <= 0.46:
            score -= 1
    if stats.limit_up_count >= stats.limit_down_count * 3 + 10:
        score += 1
    elif stats.limit_down_count >= stats.limit_up_count * 2 + 5:
        score -= 1
    if amount_change_pct is not None and abs(amount_change_pct) >= 5:
        score += 1 if index_change_pct > 0 else (-1 if index_change_pct < 0 else 0)

    if score >= 4:
        return "强势｜赚钱较好", "up"
    if score >= 1:
        return "偏强｜机会较多", "up"
    if score <= -4:
        return "弱势｜风险较高", "down"
    if score <= -1:
        return "偏弱｜谨慎参与", "down"
    return "震荡｜强弱分化", "neutral"


def _requires_full_rebuild(cached_files: dict, current_files: dict) -> bool:
    if not cached_files:
        return True
    if set(cached_files) - set(current_files):
        return True
    for code, previous in cached_files.items():
        current = current_files.get(code)
        if current is None:
            return True
        old_size = int(previous.get("size", 0))
        new_size = int(current.get("size", 0))
        if old_size < 0 or old_size % DAY_RECORD.size or new_size < old_size:
            return True
        if new_size == old_size and int(previous.get("mtime_ns", 0)) != int(current.get("mtime_ns", 0)):
            return True
    return False


def _accumulate_day_file(
    stats: dict[str, DailyMarketStats],
    code: str,
    path: Path,
    start_offset: int,
) -> None:
    data = path.read_bytes()
    start_offset = max(0, min(start_offset, len(data)))
    start_offset -= start_offset % DAY_RECORD.size
    previous_close: int | None = None
    if start_offset >= DAY_RECORD.size:
        previous = DAY_RECORD.unpack_from(data, start_offset - DAY_RECORD.size)
        previous_close = int(previous[4])

    for offset in range(start_offset, len(data) - DAY_RECORD.size + 1, DAY_RECORD.size):
        raw_date, _open, _high, _low, close, amount, _volume, _reserved = DAY_RECORD.unpack_from(data, offset)
        if raw_date <= 0 or close <= 0:
            previous_close = close if close > 0 else previous_close
            continue
        date = _format_raw_date(raw_date)
        if date is None:
            previous_close = close
            continue
        daily = stats.setdefault(date, DailyMarketStats(date=date))
        if math.isfinite(amount) and amount > 0:
            daily.amount += float(amount)
        if previous_close and previous_close > 0:
            if close > previous_close:
                daily.up_count += 1
            elif close < previous_close:
                daily.down_count += 1
            else:
                daily.flat_count += 1
            change_pct = (close - previous_close) / previous_close * 100
            limit_pct = _board_limit_pct(code)
            if change_pct >= limit_pct - 0.11:
                daily.limit_up_count += 1
            elif change_pct <= -limit_pct + 0.11:
                daily.limit_down_count += 1
        previous_close = close


def _board_limit_pct(code: str) -> float:
    if code.startswith("bj"):
        return 30.0
    if code.startswith(("sh68", "sz30")):
        return 20.0
    return 10.0


def _format_raw_date(raw_date: int) -> str | None:
    text = str(raw_date)
    if len(text) != 8:
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _root_key(root: Path) -> str:
    try:
        return str(root.resolve())
    except OSError:
        return str(root)


def _read_cache_document(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(document, dict) or document.get("version") != MARKET_STATS_CACHE_VERSION:
        return {}
    return document


def _stats_from_document(document: dict | None) -> dict[str, DailyMarketStats]:
    if not document:
        return {}
    raw_stats = document.get("stats", {})
    if not isinstance(raw_stats, dict):
        return {}
    result: dict[str, DailyMarketStats] = {}
    for date, row in raw_stats.items():
        if not isinstance(row, dict):
            continue
        try:
            result[date] = DailyMarketStats(
                date=date,
                up_count=int(row.get("up_count", 0)),
                down_count=int(row.get("down_count", 0)),
                flat_count=int(row.get("flat_count", 0)),
                amount=float(row.get("amount", 0)),
                limit_up_count=int(row.get("limit_up_count", 0)),
                limit_down_count=int(row.get("limit_down_count", 0)),
            )
        except (TypeError, ValueError):
            continue
    return result


def _write_cache_document(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)
