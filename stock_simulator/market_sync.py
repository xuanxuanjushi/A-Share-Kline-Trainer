"""Local market synchronization; all scanning and calculation runs off the GUI thread."""
from dataclasses import dataclass, replace
from pathlib import Path

from .index_data import SHANGHAI_INDEX_CODE, save_index_cache, load_index_cache, merge_index_bars
from .market_stats import MarketStatsBuildResult, build_market_stats_cache
from .models import DailyBar
from .tdx_reader import DAY_RECORD, TdxDataLocation, TdxDayReader


@dataclass
class LocalMarketUpdate:
    fingerprint: tuple
    stats: MarketStatsBuildResult
    bars: list[DailyBar]


def _stamp(path: Path) -> tuple:
    try:
        info = path.stat()
        return str(path), info.st_size, info.st_mtime_ns
    except FileNotFoundError:
        return str(path), None, None


def _source_stamp(reader: TdxDayReader, location: TdxDataLocation) -> tuple:
    paths = [path for _, path in reader.market_a_share_day_files()]
    sh = location.day_dirs.get('sh', location.root / 'vipdoc/sh/lday')
    paths.extend(sh / f'{code}.day' for code in ('sh999999', 'sh000001'))
    return tuple(_stamp(path) for path in paths)


def sync_local_market(cache_dir: Path, location: TdxDataLocation,
                      previous: tuple | None = None) -> LocalMarketUpdate | None:
    reader = TdxDayReader(location, adjust_type='none')
    stats_path = cache_dir / 'market_stats_daily.json'
    index_path = cache_dir / 'shanghai_index_daily.json'
    source = _source_stamp(reader, location)
    fingerprint = (source, _stamp(stats_path), _stamp(index_path))
    if previous == fingerprint:
        return None
    if any(size is not None and size % DAY_RECORD.size for _, size, _ in source):
        raise ValueError('通达信日K仍在写入，稍后自动重试。')
    by_date = {}
    # Some installations update only sh000001. Keep the longer history while
    # choosing the most recently written file for overlapping dates.
    index_sources = sorted((item for item in source[-2:] if item[1]), key=lambda item: item[2])
    for name, _, _ in index_sources:
        for bar in reader.read_daily_bars(Path(name).stem):
            by_date[bar.date] = replace(bar, code=SHANGHAI_INDEX_CODE)
    bars = [by_date[date] for date in sorted(by_date)]
    stats = build_market_stats_cache(stats_path, reader)
    if _source_stamp(reader, location) != source:
        raise ValueError('通达信数据正在写入，稍后自动重试。')
    if bars:
        cached = load_index_cache(index_path)
        saved = (merge_index_bars(bars, cached) if cached and cached[-1].date > bars[-1].date
                 else merge_index_bars(cached, bars))
        save_index_cache(index_path, saved)
        bars = saved
    return LocalMarketUpdate((source, _stamp(stats_path), _stamp(index_path)), stats, bars)
