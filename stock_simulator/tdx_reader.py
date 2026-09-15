from __future__ import annotations

import os
import random
import re
import struct
import threading
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import DailyBar


DAY_RECORD = struct.Struct("<iiiiifii")
MARKETS = ("sh", "sz")
OPTIONAL_MARKETS = ("bj",)
DAILY_BAR_CACHE_LIMIT = 256
ADJUST_CACHE_MAGIC = b"ABR1"
ADJUST_CACHE_VERSION = 2
ADJUST_CACHE_HEADER = struct.Struct("<4sIQQQQI")
ADJUST_CACHE_PRICE = struct.Struct("<iiii")
COMMON_TDX_DIR_NAMES = (
    "TDX",
    "tdx",
    "new_tdx",
    "new_tdx_v6",
    "通达信",
    "通达信金融终端",
    "通达信软件",
)


class TdxDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class TdxDataLocation:
    root: Path
    day_dirs: dict[str, Path]


def resolve_tdx_location(path: str | Path | None) -> TdxDataLocation | None:
    if path is None:
        return None
    raw_path = str(path).strip().strip('"')
    if not raw_path:
        return None
    base = Path(os.path.expandvars(raw_path)).expanduser()
    if not base.exists():
        return None

    for candidate in _path_and_parents(base):
        location = _standard_tdx_location(candidate)
        if location is not None:
            return location

    return _scan_tdx_location(base)


def find_tdx_installation(candidates: Iterable[str | Path] | None = None) -> TdxDataLocation | None:
    search_paths = list(candidates) if candidates is not None else list(_common_tdx_candidates())
    for candidate in search_paths:
        location = resolve_tdx_location(candidate)
        if location is not None:
            return location
    return None


class TdxDayReader:
    def __init__(
        self,
        tdx_root: str | Path | TdxDataLocation,
        adjust_provider=None,
        adjust_type: str = "qfq",
        adjust_cache_dir: str | Path | None = None,
    ):
        if isinstance(tdx_root, TdxDataLocation):
            location = tdx_root
            raw_root = location.root
        else:
            raw_root = Path(os.path.expandvars(str(tdx_root)).strip().strip('"')).expanduser()
            # Preserve an empty setting: Path('') becomes '.', which scans the
            # entire working folder even though no data source was selected.
            location = resolve_tdx_location(tdx_root) if str(tdx_root).strip() else None
        self.tdx_root = location.root if location is not None else raw_root
        self._market_day_dirs = location.day_dirs if location is not None else {market: self.tdx_root / "vipdoc" / market / "lday" for market in MARKETS}
        self._stock_codes_cache: list[str] | None = None
        self._daily_bars_cache: OrderedDict[str, list[DailyBar]] = OrderedDict()
        self._adjusted_bars_cache: OrderedDict[tuple[str, str, int], list[DailyBar]] = OrderedDict()
        self.adjust_provider = adjust_provider
        self.adjust_type = adjust_type if adjust_type in ("qfq", "hfq", "none") else "qfq"
        self.adjust_cache_dir = Path(adjust_cache_dir) if adjust_cache_dir is not None else None

    def scan_stock_codes(self) -> list[str]:
        if self._stock_codes_cache is not None:
            return list(self._stock_codes_cache)
        codes: list[str] = []
        for market in MARKETS:
            day_dir = self._day_dir(market)
            if not day_dir.exists():
                continue
            for file_path in day_dir.glob("*.day"):
                code = file_path.stem.lower()
                if self._is_common_a_share(code):
                    codes.append(code)
        self._stock_codes_cache = sorted(set(codes))
        return list(self._stock_codes_cache)

    def read_daily_bars(self, code: str) -> list[DailyBar]:
        normalized = self.normalize_code(code)
        rows = self._raw_daily_bars(normalized)
        if self._should_adjust(normalized):
            return self._adjusted_daily_bars(normalized, self.adjust_type, rows)
        return rows

    def adjustment_variants(self, code: str) -> dict[str, list[DailyBar]]:
        """Return raw, forward-adjusted and backward-adjusted bars from one warm cache."""
        normalized = self.normalize_code(code)
        rows = self._raw_daily_bars(normalized)
        variants = {"none": rows, "qfq": rows, "hfq": rows}
        provider = self.adjust_provider
        if provider is None or not provider.ready or provider.is_index_or_ineligible(normalized):
            return variants
        for adjust_type in ("qfq", "hfq"):
            variants[adjust_type] = self._adjusted_daily_bars(normalized, adjust_type, rows)
        return variants

    def _adjusted_daily_bars(
        self,
        normalized: str,
        adjust_type: str,
        rows: list[DailyBar],
    ) -> list[DailyBar]:
        """Load one requested adjustment variant without calculating the other one."""
        provider = self.adjust_provider
        if (
            adjust_type == "none"
            or provider is None
            or not provider.ready
            or provider.is_index_or_ineligible(normalized)
        ):
            return rows
        cache_key = (normalized, adjust_type, id(provider))
        adjusted = self._adjusted_bars_cache.get(cache_key)
        if adjusted is None:
            adjusted = self._load_persistent_adjusted_bars(normalized, adjust_type, rows)
        if adjusted is None:
            calculated = provider.apply(rows, normalized, adjust_type)
            adjusted = calculated or rows
            if calculated is not None:
                self._save_persistent_adjusted_bars(normalized, adjust_type, adjusted)
        if cache_key not in self._adjusted_bars_cache:
            self._adjusted_bars_cache[cache_key] = adjusted
            if len(self._adjusted_bars_cache) > DAILY_BAR_CACHE_LIMIT * 2:
                self._adjusted_bars_cache.popitem(last=False)
        self._adjusted_bars_cache.move_to_end(cache_key)
        return adjusted

    def _raw_daily_bars(self, normalized: str) -> list[DailyBar]:
        if normalized not in self._daily_bars_cache:
            self._daily_bars_cache[normalized] = self._read_raw_daily_bars(normalized)
        self._daily_bars_cache.move_to_end(normalized)
        if len(self._daily_bars_cache) > DAILY_BAR_CACHE_LIMIT:
            self._daily_bars_cache.popitem(last=False)
        return self._daily_bars_cache[normalized]

    def _adjust_cache_metadata(self, normalized: str) -> tuple[int, int, int, int] | None:
        provider_path = getattr(self.adjust_provider, "gbbq_path", None)
        if self.adjust_cache_dir is None or provider_path is None:
            return None
        day_path = self._day_dir(normalized[:2]) / f"{normalized}.day"
        try:
            day_stat = day_path.stat()
            provider_stat = Path(provider_path).stat()
        except OSError:
            return None
        return day_stat.st_size, day_stat.st_mtime_ns, provider_stat.st_size, provider_stat.st_mtime_ns

    def _adjust_cache_path(self, normalized: str, adjust_type: str) -> Path | None:
        if self.adjust_cache_dir is None:
            return None
        return self.adjust_cache_dir / f"{normalized}.{adjust_type}.abr"

    def _load_persistent_adjusted_bars(
        self,
        normalized: str,
        adjust_type: str,
        raw_rows: list[DailyBar],
    ) -> list[DailyBar] | None:
        metadata = self._adjust_cache_metadata(normalized)
        cache_path = self._adjust_cache_path(normalized, adjust_type)
        if metadata is None or cache_path is None:
            return None
        try:
            data = cache_path.read_bytes()
            header = ADJUST_CACHE_HEADER.unpack_from(data, 0)
        except (OSError, struct.error):
            return None
        magic, version, day_size, day_mtime, provider_size, provider_mtime, count = header
        if (
            magic != ADJUST_CACHE_MAGIC
            or version != ADJUST_CACHE_VERSION
            or (day_size, day_mtime, provider_size, provider_mtime) != metadata
            or count != len(raw_rows)
        ):
            return None
        try:
            price_data = zlib.decompress(data[ADJUST_CACHE_HEADER.size :])
        except zlib.error:
            return None
        if len(price_data) != count * ADJUST_CACHE_PRICE.size:
            return None
        adjusted: list[DailyBar] = []
        offset = 0
        try:
            for raw in raw_rows:
                open_price, high, low, close = ADJUST_CACHE_PRICE.unpack_from(price_data, offset)
                offset += ADJUST_CACHE_PRICE.size
                adjusted.append(
                    DailyBar(
                        code=raw.code,
                        date=raw.date,
                        open=open_price / 1000,
                        high=high / 1000,
                        low=low / 1000,
                        close=close / 1000,
                        amount=raw.amount,
                        volume=raw.volume,
                    )
                )
        except struct.error:
            return None
        try:
            os.utime(cache_path, None)
        except OSError:
            pass
        return adjusted

    def _save_persistent_adjusted_bars(
        self,
        normalized: str,
        adjust_type: str,
        rows: list[DailyBar],
    ) -> None:
        metadata = self._adjust_cache_metadata(normalized)
        cache_path = self._adjust_cache_path(normalized, adjust_type)
        if metadata is None or cache_path is None:
            return
        header = ADJUST_CACHE_HEADER.pack(
            ADJUST_CACHE_MAGIC,
            ADJUST_CACHE_VERSION,
            *metadata,
            len(rows),
        )
        price_data = bytearray(len(rows) * ADJUST_CACHE_PRICE.size)
        offset = 0
        for row in rows:
            ADJUST_CACHE_PRICE.pack_into(
                price_data,
                offset,
                round(row.open * 1000),
                round(row.high * 1000),
                round(row.low * 1000),
                round(row.close * 1000),
            )
            offset += ADJUST_CACHE_PRICE.size
        payload = header + zlib.compress(price_data, level=3)
        temporary = cache_path.with_name(
            f".{cache_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(payload)
            os.replace(temporary, cache_path)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass

    def _read_raw_daily_bars(self, normalized: str) -> list[DailyBar]:
        file_path = self._day_dir(normalized[:2]) / f"{normalized}.day"
        if not file_path.exists():
            raise TdxDataError(f"没有找到日K文件：{file_path}")

        data = file_path.read_bytes()
        rows: list[DailyBar] = []
        for offset in range(0, len(data) - DAY_RECORD.size + 1, DAY_RECORD.size):
            raw_date, open_price, high, low, close, amount, volume, _reserved = DAY_RECORD.unpack_from(data, offset)
            if raw_date <= 0:
                continue
            date_text = str(raw_date)
            rows.append(
                DailyBar(
                    code=normalized,
                    date=f"{date_text[0:4]}-{date_text[4:6]}-{date_text[6:8]}",
                    open=round(open_price / 100, 3),
                    high=round(high / 100, 3),
                    low=round(low / 100, 3),
                    close=round(close / 100, 3),
                    amount=float(amount),
                    volume=int(volume),
                )
            )
        return rows

    def _should_adjust(self, normalized: str) -> bool:
        if self.adjust_provider is None or not self.adjust_provider.ready:
            return False
        if self.adjust_type == "none":
            return False
        if self.adjust_provider.is_index_or_ineligible(normalized):
            return False
        return True

    def market_a_share_day_files(self) -> list[tuple[str, Path]]:
        """返回用于全市场统计的沪深京 A 股日K文件，不改变原有随机换股范围。"""
        files: list[tuple[str, Path]] = []
        for market in (*MARKETS, *OPTIONAL_MARKETS):
            day_dir = self._day_dir(market)
            if not day_dir.exists():
                continue
            for file_path in day_dir.glob("*.day"):
                code = file_path.stem.lower()
                if self._is_market_a_share(code):
                    files.append((code, file_path))
        return sorted(files, key=lambda item: item[0])

    def random_code(self) -> str:
        codes = self.scan_stock_codes()
        if not codes:
            raise TdxDataError("没有扫描到沪深 A 股日K数据")
        return random.choice(codes)

    @staticmethod
    def normalize_code(code: str) -> str:
        cleaned = code.strip().lower()
        if cleaned.startswith(("sh", "sz", "bj")):
            return cleaned
        if cleaned.startswith(("6", "5")):
            return f"sh{cleaned}"
        return f"sz{cleaned}"

    def _day_dir(self, market: str) -> Path:
        return self._market_day_dirs.get(market, self.tdx_root / "vipdoc" / market / "lday")

    @staticmethod
    def _is_common_a_share(code: str) -> bool:
        return (
            code.startswith("sh60")
            or code.startswith("sh68")
            or code.startswith("sz00")
            or code.startswith("sz30")
        )

    @staticmethod
    def _is_market_a_share(code: str) -> bool:
        return TdxDayReader._is_common_a_share(code) or bool(
            re.fullmatch(r"bj\d{6}", code)
        )


def _standard_tdx_location(root: Path) -> TdxDataLocation | None:
    day_dirs = {market: root / "vipdoc" / market / "lday" for market in MARKETS}
    if all(_has_market_day_file(day_dirs[market], market) for market in MARKETS):
        for market in OPTIONAL_MARKETS:
            optional_dir = root / "vipdoc" / market / "lday"
            if _has_market_day_file(optional_dir, market):
                day_dirs[market] = optional_dir
        return TdxDataLocation(root=root, day_dirs=day_dirs)
    return None


def _path_and_parents(path: Path) -> list[Path]:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return [resolved, *resolved.parents]


def _has_market_day_file(path: Path, market: str) -> bool:
    if not path.is_dir():
        return False
    try:
        return any(file_path.name.lower().startswith(market) and file_path.suffix.lower() == ".day" for file_path in path.iterdir())
    except OSError:
        return False


def _scan_tdx_location(base: Path, max_depth: int = 5) -> TdxDataLocation | None:
    if _is_drive_root(base):
        return None
    found: dict[str, Path] = {}
    base_depth = len(base.resolve().parts)
    try:
        walker = os.walk(base)
    except OSError:
        return None
    for dir_name, child_dirs, files in walker:
        directory = Path(dir_name)
        depth = len(directory.parts) - base_depth
        if depth >= max_depth:
            child_dirs[:] = []
        lower_files = [name.lower() for name in files]
        for market in (*MARKETS, *OPTIONAL_MARKETS):
            if market not in found and any(name.startswith(market) and name.endswith(".day") for name in lower_files):
                found[market] = directory
    if not all(market in found for market in MARKETS):
        return None
    included = {market: found[market] for market in (*MARKETS, *OPTIONAL_MARKETS) if market in found}
    return TdxDataLocation(root=_common_root(included.values(), base), day_dirs=included)


def _is_drive_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return resolved.parent == resolved


def _common_root(paths: Iterable[Path], fallback: Path) -> Path:
    text_paths = [str(path) for path in paths]
    if not text_paths:
        return fallback
    try:
        return Path(os.path.commonpath(text_paths))
    except ValueError:
        return fallback


def _common_tdx_candidates() -> Iterable[Path]:
    for drive in _existing_drive_roots():
        for name in COMMON_TDX_DIR_NAMES:
            yield drive / name
    for program_dir in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if not program_dir:
            continue
        for name in ("通达信", "通达信金融终端"):
            yield Path(program_dir) / name


def _existing_drive_roots() -> Iterable[Path]:
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        if root.exists():
            yield root
