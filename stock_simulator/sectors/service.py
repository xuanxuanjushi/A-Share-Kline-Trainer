"""Read-only, date-bounded TDX data API. No Qt or account state dependencies."""
from bisect import bisect_right, bisect_left
from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
from datetime import date
import json
import math
import os
from pathlib import Path
import re
import struct
import random
import threading

from ..models import DailyBar
from ..stock_info import StockInfoReader, stock_name_initials
from ..tdx_reader import DAY_RECORD, resolve_tdx_location
from .contracts import MarketContext
from ..session import normalize_start_date


_QUOTE_CACHE_LOCKS: dict[str, threading.Lock] = {}
_QUOTE_CACHE_LOCKS_GUARD = threading.Lock()


def _quote_cache_lock(path: Path | None) -> threading.Lock:
    if path is None:
        return threading.Lock()
    key = str(path)
    with _QUOTE_CACHE_LOCKS_GUARD:
        return _QUOTE_CACHE_LOCKS.setdefault(key, threading.Lock())


class SectorDataError(ValueError):
    pass


@dataclass(frozen=True)
class Sector:
    code: str
    name: str
    industry: str
    level: int = 1
    parent: str = ''
    path: str = ''
    category: str = 'industry'


@dataclass(frozen=True)
class Quote:
    code: str
    name: str
    price: float | None = None
    change: float | None = None
    change5: float | None = None
    change20: float | None = None
    amount: float | None = None
    status: str = ''
    change10: float | None = None
    turnover1: float | None = None
    turnover5: float | None = None
    turnover10: float | None = None
    turnover20: float | None = None
    turnover60: float | None = None
    open_change: float | None = None
    industry: str = ''
    bar_count: int = 0
    volume_ratio: float | None = None
    change_year: float | None = None
    # 连板数：2 表示连续两个交易日涨停；0 表示最近一日不是涨停。
    limit_up_streak: int = 0
    # 区间最高收盘价到最新收盘价的跌幅（正数表示下跌），用于“腰斩”清单。
    high_drop_half_month: float | None = None
    high_drop_month: float | None = None
    high_drop_quarter: float | None = None


# 涨停/跌停判定容差：涨停价按分取整、除权参考价等原因，实际涨跌幅常与
# 10% / 20% 有零点几个百分点的偏差，所以不要求严格相等。
LIMIT_TOLERANCE_PCT = 0.5

# 程序自己算出来的风格板块（不在通达信的 tdxzs.cfg 里）。
VIRTUAL_STYLE_SECTORS = (
    ('sh881901', '今日涨停', 'limit_up'),
    ('sh881902', '今日连板', 'limit_up_streak'),
    ('sh881903', '今日跌停', 'limit_down'),
    ('sh881904', '近半月腰斩', 'halved_half_month'),
    ('sh881905', '近一月腰斩', 'halved_month'),
    ('sh881906', '近三月腰斩', 'halved_quarter'),
)
VIRTUAL_STYLE_KIND_BY_CODE = {code: kind for code, _name, kind in VIRTUAL_STYLE_SECTORS}
VIRTUAL_STYLE_NAME_BY_CODE = {code: name for code, name, _kind in VIRTUAL_STYLE_SECTORS}

# 腰斩判定：区间最高收盘价到最新收盘价跌去约一半。不要求正好 50%，
# 跌幅落在 40%~60% 之间都算，方便把临界情况也选出来。
HALVED_MIN_DROP_PCT = 40.0
HALVED_MAX_DROP_PCT = 60.0

# 腰斩统计窗口（交易日），比自然半月/一月/三月略宽松一些。
HALVED_WINDOW_BARS = {
    'halved_half_month': 15,
    'halved_month': 25,
    'halved_quarter': 70,
}


def is_halved(drop_pct: float | None) -> bool:
    return (
        drop_pct is not None
        and HALVED_MIN_DROP_PCT <= drop_pct <= HALVED_MAX_DROP_PCT
    )


def limit_up_percent(code: str) -> float:
    """涨停/跌停幅度：科创板/创业板 20%，北交所 30%，其余（含 ST）10%。"""
    if code.startswith('bj'):
        return 30.0
    if code.startswith(('sh68', 'sz30')):
        return 20.0
    return 10.0


def is_limit_up_change(change_pct: float | None, percent: float) -> bool:
    return change_pct is not None and change_pct >= percent - LIMIT_TOLERANCE_PCT


def is_limit_down_change(change_pct: float | None, percent: float) -> bool:
    return change_pct is not None and change_pct <= -(percent - LIMIT_TOLERANCE_PCT)


class SectorService:
    QUOTE_CACHE_VERSION = 11

    def __init__(self, root: str, cache_dir: str | Path | None = None):
        self.source_root = str(Path(root).resolve())
        self.root = Path(root).resolve()
        self.location = resolve_tdx_location(root)
        if self.location:
            self.root = self.location.root.resolve()
        self.info = StockInfoReader(self.root)
        self._bars = OrderedDict()
        self._cached_bar_count = 0
        self._quote_bytes = OrderedDict()
        self._quote_byte_count = 0
        self._catalog_key = None
        self._sectors = ()
        self._members = {}
        self._industry_paths = {}
        self._quote_cache_path = (
            Path(cache_dir) / 'sector_quotes.json' if cache_dir else None
        )
        self._quote_cache = None
        self._quote_cache_mtime_ns = None
        self._quote_cache_lock = _quote_cache_lock(self._quote_cache_path)
        self._stock_quote_path = (
            Path(cache_dir) / 'stock_quotes.json' if cache_dir else None
        )
        self._stock_quote_cache = None
        self._stock_quote_mtime_ns = None
        self._stock_quote_lock = _quote_cache_lock(self._stock_quote_path)
        self._virtual_style_quotes = None
        self._virtual_style_date = ''

    def _catalog(self):
        cache = self.root / 'T0002/hq_cache'
        paths = [cache / 'tdxzs.cfg', cache / 'tdxhy.cfg']
        try:
            key = tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
            extra = cache / 'infoharbor_block.dat'
            key += ((extra.stat().st_mtime_ns, extra.stat().st_size) if extra.exists() else None,)
            if key == self._catalog_key:
                return
            texts = [p.read_text(encoding='gbk') for p in paths]
        except (OSError, UnicodeError) as exc:
            raise SectorDataError('缺少或无法读取行业资料 tdxzs.cfg / tdxhy.cfg，请在通达信更新基础资料后刷新。') from exc
        sectors = {}
        for line in texts[0].splitlines():
            fields = line.split('|')
            if len(fields) >= 6 and fields[2] == '2' and re.fullmatch(r'T(?:\d{4}|\d{6}|\d{8})', fields[5]) and re.fullmatch(r'880\d{3}', fields[1]):
                sectors[fields[5]] = Sector('sh' + fields[1], fields[0].strip(), fields[5], (len(fields[5])-3)//2)
        if not sectors:
            raise SectorDataError('行业资料中未找到通达信一级行业（Txxxx），请更新基础资料。')
        linked = {}
        for industry, sector in sorted(sectors.items(), key=lambda item: len(item[0])):
            parent = linked.get(industry[:-2])
            if sector.level > 1 and not parent:
                continue
            linked[industry] = replace(sector, parent=parent.code if parent else '', path=(parent.path + ' › ' if parent else '') + sector.name)
        sectors = linked
        members = {s.code: set() for s in sectors.values()}
        for line in texts[1].splitlines():
            f = line.split('|')
            if len(f) < 3 or not re.fullmatch(r'\d{6}', f[1]):
                continue
            if re.fullmatch(r'T\d{4}(?:\d{2}){0,2}', f[2]) and f[0] in ('0', '1', '2'):
                code = {'0': 'sz', '1': 'sh', '2': 'bj'}[f[0]] + f[1]
                if re.fullmatch(r'(sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})', code):
                    for size in (5, 7, 9):
                        sector = sectors.get(f[2][:size])
                        if sector:
                            members[sector.code].add(code)
        # Optional concept/style membership: absence must not break industry data.
        extras = {}
        for line in texts[0].splitlines():
            f = line.split('|')
            if len(f) >= 6 and f[2] in ('4', '5') and re.fullmatch(r'880\d{3}', f[1]):
                category = 'concept' if f[2] == '4' else 'style'
                code = 'sh'+f[1]
                extras[code] = Sector(code, f[0].strip(), f[5], path=f[0].strip(), category=category)
                members[code] = set()
        if extra.exists():
            current = None
            for line in extra.read_text(encoding='gbk', errors='replace').splitlines():
                if line.startswith('#'):
                    f = line.split(',')
                    code = 'sh'+f[2] if len(f)>2 else ''
                    expected = '#GN_' if code in extras and extras[code].category == 'concept' else '#FG_'
                    current = code if code in extras and f[0].startswith(expected) else None
                elif current:
                    for market, raw in re.findall(r'([012])#(\d{6})(?=,|$)', line):
                        code = {'0':'sz','1':'sh','2':'bj'}[market]+raw
                        if re.fullmatch(r'(sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})', code):
                            members[current].add(code)
        # 程序自己统计的风格板块（今日涨停/连板/跌停、腰斩等）：成份股实时计算。
        for code, name, _kind in VIRTUAL_STYLE_SECTORS:
            if code not in extras:
                extras[code] = Sector(code, name, name, path=name, category='style')
                members[code] = set()
        self._sectors = tuple(sorted([*sectors.values(), *extras.values()], key=lambda s: s.code))
        self._members = {k: tuple(sorted(v)) for k, v in members.items()}
        self._industry_paths.clear()
        self._catalog_key = key

    def sectors(self, level=1, parent='', category='industry'):
        self._catalog()
        return tuple(s for s in self._sectors if s.category == category and (category != 'industry' or (s.level == level and (not parent or s.parent == parent))))

    def member_codes(self, sector_code):
        self._catalog()
        if sector_code in VIRTUAL_STYLE_KIND_BY_CODE:
            return self.virtual_style_members(sector_code)
        if sector_code not in self._members:
            raise SectorDataError('未知行业代码')
        return self._members[sector_code]

    def is_virtual_style(self, sector_code) -> bool:
        """是否是程序自己统计的风格板块（今日涨停/连板/跌停、腰斩等）。"""
        return sector_code in VIRTUAL_STYLE_KIND_BY_CODE

    def _warmed_market_quotes(self):
        """本地最新交易日的全市场个股行情（来自个股行情缓存）。"""
        latest = self._latest_market_date()
        date, rows = self._cached_market_quotes(latest)
        if not rows and latest:
            # 最新交易日还没预热过（例如从旧训练日期启动）时补算一次。
            self._warm_market_snapshot(latest)
            date, rows = self._cached_market_quotes(latest)
        if not rows:
            date, rows = self._cached_market_quotes('')
        self._virtual_style_date = date
        self._virtual_style_quotes = rows
        return rows

    def _latest_market_date(self):
        try:
            return self.latest_date_with_forward_bars(0, 'sh000001')
        except (SectorDataError, ValueError):
            return ''

    def _cached_market_quotes(self, date):
        """读个股行情缓存；date 为空时取缓存里最新的一天。"""
        with self._stock_quote_lock:
            cache = self._load_stock_quote_cache()
            target = date
            if not target:
                for key in cache:
                    parts = key.split('|')
                    if len(parts) >= 3 and parts[1] > target:
                        target = parts[1]
            rows = []
            for key, entry in cache.items():
                parts = key.split('|')
                if len(parts) < 3 or parts[1] != target or not isinstance(entry, dict):
                    continue
                quote = self._quote_from_cache(entry.get('quote'))
                if quote is not None:
                    rows.append(quote)
        return target, rows

    def _warm_market_snapshot(self, date):
        """补算最新交易日的全市场行情；调用方已在后台线程里。"""
        try:
            from ..tdx_reader import TdxDayReader

            codes = TdxDayReader(self.root).scan_stock_codes()
        except Exception:
            return
        if not codes:
            return
        try:
            self.warm_stock_quotes(codes, MarketContext(str(self.root), date, True))
        except Exception:
            return

    def virtual_style_members(self, sector_code):
        kind = VIRTUAL_STYLE_KIND_BY_CODE.get(sector_code)
        if kind is None:
            raise SectorDataError('未知行业代码')
        selected = []
        for quote in self._warmed_market_quotes():
            percent = limit_up_percent(quote.code)
            if kind == 'limit_up':
                hit = is_limit_up_change(quote.change, percent)
            elif kind == 'limit_up_streak':
                hit = quote.limit_up_streak >= 2
            elif kind == 'limit_down':
                hit = is_limit_down_change(quote.change, percent)
            elif kind == 'halved_half_month':
                hit = is_halved(quote.high_drop_half_month)
            elif kind == 'halved_month':
                hit = is_halved(quote.high_drop_month)
            elif kind == 'halved_quarter':
                hit = is_halved(quote.high_drop_quarter)
            else:
                hit = False
            if hit:
                selected.append(quote.code)
        return tuple(sorted(selected))

    def _virtual_style_quote(self, sector_code, name):
        codes = set(self.virtual_style_members(sector_code))
        rows = [quote for quote in self._warmed_market_quotes() if quote.code in codes]

        def average(values):
            clean = [value for value in values if value is not None]
            return round(sum(clean) / len(clean), 2) if clean else None

        return Quote(
            code=sector_code,
            name=name or VIRTUAL_STYLE_NAME_BY_CODE.get(sector_code, ''),
            change=average([row.change for row in rows]),
            change5=average([row.change5 for row in rows]),
            change10=average([row.change10 for row in rows]),
            change20=average([row.change20 for row in rows]),
            amount=sum(row.amount for row in rows if row.amount) or None,
            volume_ratio=average([row.volume_ratio for row in rows]),
            status='按本地最新交易日统计',
            bar_count=len(rows),
        )

    def _day_path(self, code):
        day_dir = self.location.day_dirs.get(code[:2]) if self.location else None
        return (day_dir or self.root / 'vipdoc' / code[:2] / 'lday') / (code + '.day')

    def _quote_file_signature(self, code):
        try:
            stat = self._day_path(code).stat()
        except OSError:
            return None
        return [stat.st_mtime_ns, stat.st_size]

    def _catalog_signature(self):
        self._catalog()
        return [list(item) if item else None for item in (self._catalog_key or ())]

    def _name_source_signature(self):
        cache = self.root / 'T0002' / 'hq_cache'
        result = []
        for name in ('shs.tnf', 'szs.tnf', 'bjs.tnf'):
            try:
                stat = (cache / name).stat()
            except OSError:
                result.append(None)
            else:
                result.append([stat.st_mtime_ns, stat.st_size])
        return result

    def _load_quote_cache(self):
        if self._quote_cache_path is None:
            if self._quote_cache is None:
                self._quote_cache = {}
            return self._quote_cache
        try:
            mtime_ns = self._quote_cache_path.stat().st_mtime_ns
        except OSError:
            mtime_ns = None
        if self._quote_cache is not None and mtime_ns == self._quote_cache_mtime_ns:
            return self._quote_cache
        self._quote_cache = {}
        self._quote_cache_mtime_ns = mtime_ns
        if mtime_ns is None:
            return self._quote_cache
        try:
            payload = json.loads(self._quote_cache_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return self._quote_cache
        if not isinstance(payload, dict) or payload.get('version') != self.QUOTE_CACHE_VERSION:
            return self._quote_cache
        entries = payload.get('entries')
        if isinstance(entries, dict):
            self._quote_cache = entries
        return self._quote_cache

    @staticmethod
    def _quote_from_cache(value):
        if not isinstance(value, dict):
            return None
        try:
            return Quote(
                code=str(value['code']),
                name=str(value.get('name', '')),
                price=value.get('price'),
                change=value.get('change'),
                change5=value.get('change5'),
                change20=value.get('change20'),
                amount=value.get('amount'),
                status=str(value.get('status', '')),
                change10=value.get('change10'),
                turnover1=value.get('turnover1'),
                turnover5=value.get('turnover5'),
                turnover10=value.get('turnover10'),
                turnover20=value.get('turnover20'),
                turnover60=value.get('turnover60'),
                open_change=value.get('open_change'),
                industry=str(value.get('industry', '')),
                bar_count=int(value.get('bar_count', 0) or 0),
                volume_ratio=value.get('volume_ratio'),
                change_year=value.get('change_year'),
                limit_up_streak=int(value.get('limit_up_streak', 0) or 0),
                high_drop_half_month=value.get('high_drop_half_month'),
                high_drop_month=value.get('high_drop_month'),
                high_drop_quarter=value.get('high_drop_quarter'),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _quote_cache_lookup(self, key, signature):
        if self._quote_cache_path is None:
            return None
        with self._quote_cache_lock:
            entry = self._load_quote_cache().get(key)
        if not isinstance(entry, dict) or entry.get('signature') != signature:
            return None
        rows = entry.get('rows')
        if not isinstance(rows, list):
            return None
        result = [self._quote_from_cache(item) for item in rows]
        return result if all(item is not None for item in result) else None

    def _quote_cache_store(self, key, signature, rows):
        if self._quote_cache_path is None:
            return
        payload = {
            'version': self.QUOTE_CACHE_VERSION,
            'entries': {},
        }
        with self._quote_cache_lock:
            cache = self._load_quote_cache()
            cache[key] = {
                'signature': signature,
                'rows': [asdict(row) for row in rows],
            }
            # Keep the cache bounded; sector browsing rarely needs more than
            # a few date/category combinations in one session.
            while len(cache) > 96:
                cache.pop(next(iter(cache)))
            payload['entries'] = cache
            try:
                self._quote_cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self._quote_cache_path.with_name(
                    f'{self._quote_cache_path.name}.{os.getpid()}.{threading.get_ident()}.tmp'
                )
                temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
                os.replace(temporary, self._quote_cache_path)
                self._quote_cache_mtime_ns = self._quote_cache_path.stat().st_mtime_ns
            except OSError:
                # The cache is rebuildable; a read-only or locked data folder
                # must not break the live sector view.
                pass

    @staticmethod
    def _stock_quote_key(context, code, float_a_shares=None):
        return (
            f'{Path(context.root).resolve()}|{context.date}|{int(context.closed)}|'
            f'{code}|{int(float_a_shares or 0)}'
        )

    def _load_stock_quote_cache(self):
        if self._stock_quote_path is None:
            if self._stock_quote_cache is None:
                self._stock_quote_cache = {}
            return self._stock_quote_cache
        try:
            mtime_ns = self._stock_quote_path.stat().st_mtime_ns
        except OSError:
            mtime_ns = None
        if self._stock_quote_cache is not None and mtime_ns == self._stock_quote_mtime_ns:
            return self._stock_quote_cache
        self._stock_quote_cache = {}
        self._stock_quote_mtime_ns = mtime_ns
        if mtime_ns is None:
            return self._stock_quote_cache
        try:
            payload = json.loads(self._stock_quote_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return self._stock_quote_cache
        if not isinstance(payload, dict) or payload.get('version') != self.QUOTE_CACHE_VERSION:
            return self._stock_quote_cache
        entries = payload.get('entries')
        if isinstance(entries, dict):
            self._stock_quote_cache = entries
        return self._stock_quote_cache

    def _stock_quote_cache_lookup(self, code, name, context, float_a_shares=None, industry=''):
        if self._stock_quote_path is None:
            return None
        signature = self._quote_file_signature(code)
        with self._stock_quote_lock:
            entry = self._load_stock_quote_cache().get(
                self._stock_quote_key(context, code, float_a_shares)
            )
        if not isinstance(entry, dict) or entry.get('signature') != signature:
            return None
        quote = self._quote_from_cache(entry.get('quote'))
        if quote is None:
            return None
        return replace(quote, code=code, name=name, industry=industry or quote.industry)

    def warm_stock_quotes(self, codes, context):
        """Read all local symbols once and persist their compact daily quotes."""
        if self._stock_quote_path is None:
            return 0
        entries = {}
        changed = False
        for code in codes:
            float_a_shares = self.info.get(code).float_a_shares
            cached = self._stock_quote_cache_lookup(code, code, context, float_a_shares)
            if cached is not None:
                entries[self._stock_quote_key(context, code, float_a_shares)] = {
                    'signature': self._quote_file_signature(code),
                    'quote': asdict(cached),
                }
                continue
            signature_before = self._quote_file_signature(code)
            quote = self._compute_quote(code, code, context, float_a_shares)
            signature_after = self._quote_file_signature(code)
            if signature_before != signature_after:
                continue
            entries[self._stock_quote_key(context, code, float_a_shares)] = {
                'signature': signature_after,
                'quote': asdict(quote),
            }
            changed = True
        if not entries:
            return 0
        with self._stock_quote_lock:
            current = dict(self._load_stock_quote_cache())
            current.update(entries)
            # Bound the cache while keeping a full local-market snapshot.
            while len(current) > 20000:
                current.pop(next(iter(current)))
            self._stock_quote_cache = current
            if not changed and self._stock_quote_path.is_file():
                return len(entries)
            try:
                self._stock_quote_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self._stock_quote_path.with_name(
                    f'{self._stock_quote_path.name}.{os.getpid()}.{threading.get_ident()}.tmp'
                )
                temporary.write_text(
                    json.dumps(
                        {'version': self.QUOTE_CACHE_VERSION, 'entries': current},
                        ensure_ascii=False,
                    ),
                    encoding='utf-8',
                )
                os.replace(temporary, self._stock_quote_path)
                self._stock_quote_mtime_ns = self._stock_quote_path.stat().st_mtime_ns
            except OSError:
                pass
        return len(entries)

    def _read(self, code):
        if not re.fullmatch(r'(sh|sz|bj)\d{6}', code):
            raise SectorDataError('行情代码格式无效')
        path = self._day_path(code)
        try:
            stat = path.stat()
            key = (stat.st_mtime_ns, stat.st_size)
            cached = self._bars.get(code)
            if cached and cached[0] == key:
                self._bars.move_to_end(code)
                return cached[1], cached[2]
            if stat.st_size > 32 * 100000:
                raise SectorDataError(f'{code} 日线文件过大')
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise SectorDataError(f'{code} 没有本地日线，请下载日K数据') from exc
        except OSError as exc:
            raise SectorDataError(f'{code} 日线无法读取：{exc}') from exc
        if len(data) % DAY_RECORD.size:
            raise SectorDataError(f'{code} 日线文件损坏（记录长度异常）')
        bars = []
        try:
            for d, o, h, l, c, amount, volume, _ in DAY_RECORD.iter_unpack(data):
                day = date(d // 10000, d // 100 % 100, d % 100).isoformat()
                if not (0 < l <= min(o, c) <= max(o, c) <= h and math.isfinite(amount) and amount >= 0 and volume >= 0):
                    raise ValueError('价格或量额无效')
                if bars and day <= bars[-1].date:
                    raise ValueError('日期重复或乱序')
                bars.append(DailyBar(code, day, o / 100, h / 100, l / 100, c / 100, amount, volume))
        except ValueError as exc:
            raise SectorDataError(f'{code} 日线文件损坏：{exc}') from exc
        dates = tuple(b.date for b in bars)
        previous = self._bars.pop(code, None)
        if previous:
            self._cached_bar_count -= len(previous[1])
        self._bars[code] = (key, bars, dates)
        self._cached_bar_count += len(bars)
        # Keep an industry plus its members warm; bound both symbols and bars.
        while len(self._bars) > 768 or self._cached_bar_count > 2_000_000:
            _, removed = self._bars.popitem(last=False)
            self._cached_bar_count -= len(removed[1])
        return bars, dates

    def history(self, code, context: MarketContext):
        # Root normalization belongs to source setup, not to every stock quote.
        # Re-discovering a TDX installation scans thousands of directory entries.
        source = str(Path(context.root).resolve())
        if source not in (self.source_root, str(self.root)):
            raise SectorDataError('数据源已改变，请刷新')
        bars, dates = self._read(code)
        visible = bars[:bisect_right(dates, context.date)]
        if visible and not context.closed and visible[-1].date == context.date:
            last = visible[-1]
            visible[-1] = replace(last, high=last.open, low=last.open, close=last.open, amount=0, volume=0)
        return visible

    def _quote_data(self, code):
        if not re.fullmatch(r'(sh|sz|bj)\d{6}', code):
            raise SectorDataError('行情代码格式无效')
        path = self._day_path(code)
        try:
            stat = path.stat()
            key = (stat.st_mtime_ns, stat.st_size)
            cached = self._quote_bytes.get(code)
            if cached and cached[0] == key:
                self._quote_bytes.move_to_end(code)
                return cached[1]
            if stat.st_size > 32*100000:
                raise SectorDataError(f'{code} 日线文件过大')
            data = path.read_bytes()
        except OSError as exc:
            raise SectorDataError(f'{code} 没有或无法读取本地日线') from exc
        if len(data) % DAY_RECORD.size:
            raise SectorDataError(f'{code} 日线文件损坏（记录长度异常）')
        # Ranking and snapshot views only need the target session and a
        # handful of preceding records. Full-file validation stays on the
        # history path used before drawing a chart.
        old = self._quote_bytes.pop(code, None)
        if old:
            self._quote_byte_count -= len(old[1])
        self._quote_bytes[code] = (key, data)
        self._quote_byte_count += len(data)
        while self._quote_byte_count > 128*1024*1024:
            _, removed = self._quote_bytes.popitem(last=False)
            self._quote_byte_count -= len(removed[1])
        return data

    def quote(self, code, name, context, float_a_shares=None, industry=''):
        if code in VIRTUAL_STYLE_KIND_BY_CODE:
            return self._virtual_style_quote(code, name)
        cached = self._stock_quote_cache_lookup(
            code, name, context, float_a_shares, industry
        )
        if cached is not None:
            return cached
        return self._compute_quote(code, name, context, float_a_shares, industry)

    def _compute_quote(self, code, name, context, float_a_shares=None, industry=''):
        # Ranking needs at most five records, not thousands of DailyBar objects.
        try:
            if str(Path(context.root).resolve()) not in (self.source_root, str(self.root)):
                raise SectorDataError('数据源已改变，请刷新')
            data = self._quote_data(code)
        except SectorDataError as exc:
            return Quote(code, name, status=str(exc))
        target = int(context.date.replace('-', ''))
        lo, hi = 0, len(data)//DAY_RECORD.size
        while lo < hi:
            mid = (lo+hi)//2
            if struct.unpack_from('<I', data, mid*32)[0] <= target:
                lo = mid+1
            else:
                hi = mid
        index = lo-1
        if index < 0:
            return Quote(code, name, status='截止日之前无行情')
        record = DAY_RECORD.unpack_from(data, index*32)
        if record[0] != target:
            d = record[0]
            return Quote(code, name, status=f'当日无行情；最近 {d//10000:04d}-{d//100%100:02d}-{d%100:02d}')
        try:
            previous_date = 0
            for record_index in range(max(0, index-20), index+1):
                d, o, h, l, c, amount, volume, _ = DAY_RECORD.unpack_from(data, record_index*32)
                date(d//10000, d//100%100, d%100)
                if d <= previous_date or not (0 < l <= min(o, c) <= max(o, c) <= h
                                              and math.isfinite(amount) and amount >= 0 and volume >= 0):
                    raise ValueError('价格、日期或量额无效')
                previous_date = d
        except ValueError as exc:
            return Quote(code, name, status=f'{code} 日线文件损坏：{exc}')
        price = record[4] if context.closed else record[1]
        def change(n):
            return (price / DAY_RECORD.unpack_from(data, (index-n)*32)[4]-1)*100 if index >= n else None
        previous_close = DAY_RECORD.unpack_from(data, (index-1)*32)[4] if index >= 1 else None
        open_change = (
            (record[1] / previous_close - 1) * 100
            if previous_close and previous_close > 0 else None
        )
        turnover_end = index if context.closed else index - 1
        def turnover(n):
            if not float_a_shares or float_a_shares <= 0 or turnover_end < 0:
                return None
            start = max(0, turnover_end - n + 1)
            volume = sum(
                DAY_RECORD.unpack_from(data, record_index*32)[6]
                for record_index in range(start, turnover_end + 1)
            )
            return round(volume / float_a_shares * 100, 2)
        def volume_ratio():
            reference = index if context.closed else index - 1
            if reference < 5:
                return None
            current_volume = DAY_RECORD.unpack_from(data, reference*32)[6]
            base_volumes = [
                DAY_RECORD.unpack_from(data, record_index*32)[6]
                for record_index in range(reference - 5, reference)
            ]
            base_average = sum(base_volumes) / len(base_volumes)
            if base_average <= 0:
                return None
            return round(current_volume / base_average, 2)
        def limit_up_streak():
            # 与成交额、换手一致：开盘阶段以最近一个完整交易日为准。
            if turnover_end < 1:
                return 0
            limit = limit_up_percent(code)
            streak = 0
            for record_index in range(turnover_end, 0, -1):
                current = DAY_RECORD.unpack_from(data, record_index*32)[4]
                previous = DAY_RECORD.unpack_from(data, (record_index-1)*32)[4]
                if previous <= 0:
                    break
                if is_limit_up_change((current / previous - 1) * 100, limit):
                    streak += 1
                else:
                    break
            return streak
        def high_drop(bars):
            """区间最高收盘价到最新收盘价的跌幅（正数表示下跌）。"""
            if turnover_end < 0:
                return None
            start = max(0, turnover_end - max(1, int(bars)) + 1)
            highest = max(
                DAY_RECORD.unpack_from(data, record_index*32)[4]
                for record_index in range(start, turnover_end + 1)
            )
            if highest <= 0:
                return None
            current = DAY_RECORD.unpack_from(data, turnover_end*32)[4]
            return round((highest - current) / highest * 100, 2)
        return Quote(code, name, price/100, change(1), change(5), change(20), record[5] if context.closed else None,
                     '日K收盘' if context.closed else '开盘价涨幅；成交额未揭示', change10=change(10),
                     turnover1=turnover(1), turnover5=turnover(5), turnover10=turnover(10),
                     turnover20=turnover(20), turnover60=turnover(60),
                     open_change=open_change, industry=industry,
                     bar_count=len(data)//DAY_RECORD.size,
                     volume_ratio=volume_ratio(), change_year=change(250),
                     limit_up_streak=limit_up_streak(),
                     high_drop_half_month=high_drop(HALVED_WINDOW_BARS['halved_half_month']),
                     high_drop_month=high_drop(HALVED_WINDOW_BARS['halved_month']),
                     high_drop_quarter=high_drop(HALVED_WINDOW_BARS['halved_quarter']))

    def sector_quotes(self, context, level=1, parent='', category='industry', cancelled=None):
        sectors = self.sectors(level, parent, category)
        codes = tuple(item.code for item in sectors)
        if self._quote_cache_path is not None:
            signature = {
                'root': str(self.root),
                'catalog': self._catalog_signature(),
                'files': [self._quote_file_signature(code) for code in codes],
            }
            key = f'sectors|{context.date}|{int(context.closed)}|{level}|{parent}|{category}'
            cached = self._quote_cache_lookup(key, signature)
            if cached is not None:
                return cached
        rows = []
        for s in sectors:
            if cancelled and cancelled():
                return rows
            rows.append(self.quote(s.code, s.path, context))
        if self._quote_cache_path is not None:
            self._quote_cache_store(key, signature, rows)
        return rows

    def member_quotes(self, sector_code, context, cancelled=None):
        self.info._load_name_cache()
        codes = self.member_codes(sector_code)
        if self._quote_cache_path is not None:
            signature = {
                'root': str(self.root),
                'catalog': self._catalog_signature(),
                'names': self._name_source_signature(),
                'files': [self._quote_file_signature(code) for code in codes],
            }
            key = f'members|{sector_code}|{context.date}|{int(context.closed)}'
            cached = self._quote_cache_lookup(key, signature)
            if cached is not None:
                return cached
        rows = []
        for code in codes:
            if cancelled and cancelled():
                return rows
            info = self.info.get(code)
            rows.append(
                self.quote(
                    code,
                    info.name or self.info.name_for(code) or code,
                    context,
                    float_a_shares=info.float_a_shares,
                    industry=self.industry_path_for_stock(code),
                )
            )
        if self._quote_cache_path is not None:
            self._quote_cache_store(key, signature, rows)
        return rows

    def next_date(self, current, code='sh000001'):
        bars, dates = self._read(code)
        index = bisect_right(dates, current)
        if index >= len(bars):
            raise SectorDataError('已到当前板块的本地日线末尾，请更新通达信日K数据。')
        return dates[index]

    def latest_date_with_forward_bars(self, bars_count, code='sh000001'):
        bars, _dates = self._read(code)
        if not bars:
            raise SectorDataError('没有可定位的日K数据。')
        index = max(0, len(bars) - 1 - max(0, int(bars_count)))
        return bars[index].date

    def resolve_date(self, query, context, code='sh000001', boundary=None,
                     upper_date=None, fallback_code='sh000001'):
        bars = self.history(code, context) if context.locked else self._read(code)[0]
        if upper_date:
            bars = [bar for bar in bars if bar.date <= upper_date]
        if not bars and fallback_code and fallback_code != code:
            bars = self._read(fallback_code)[0]
            if upper_date:
                bars = [bar for bar in bars if bar.date <= upper_date]
        if not bars:
            raise SectorDataError('没有可定位的日K数据。')
        if boundary == 'random':
            dates = [bar.date for bar in bars if bar.date != context.date]
            if not dates:
                dates = [bar.date for bar in bars]
            rng = random.SystemRandom()
            years = sorted({value[:4] for value in dates})
            year = rng.choice(years)
            months = sorted({value[5:7] for value in dates if value.startswith(year)})
            month = rng.choice(months)
            days = [value for value in dates if value.startswith(f'{year}-{month}-')]
            return rng.choice(days)
        if boundary == 'first':
            return bars[0].date
        if boundary == 'last':
            return bars[-1].date
        target = normalize_start_date(query)
        if context.locked and target > context.date:
            raise SectorDataError(f'训练尚未揭示此日期，当前截止 {context.date}。')
        dates = [bar.date for bar in bars]
        return dates[min(bisect_left(dates, target), len(dates)-1)]

    @staticmethod
    def matches(query, code, name):
        query = query.strip().upper()
        if not query or query in code.upper() or query in name.upper():
            return True
        if not query.isascii() or not query.isalpha():
            return False
        # Accept common alternative readings without generating exponential variants.
        readings = {'行': 'HX', '重': 'CZ', '长': 'CZ', '乐': 'LY', '厦': 'SX',
                    '藏': 'CZ', '朝': 'CZ', '单': 'DSC', '和': 'HH', '柏': 'BB',
                    '华': 'H', '盛': 'SC', '强': 'QJ', '都': 'DD', '地': 'DD'}
        cleaned = re.sub(r'^(?:S\*?ST|\*ST|ST|N|C)', '', name.strip(), flags=re.I)
        choices = []
        for char in cleaned:
            initial = char.upper() if char.isascii() and char.isalpha() else stock_name_initials(char)
            if initial:
                choices.append(set(readings.get(char, initial)))
        return any(all(letter in choices[start+i] for i, letter in enumerate(query))
                   for start in range(len(choices)-len(query)+1))

    def search(self, query, level=1, parent='', category='industry'):
        sectors = self.sectors(level, parent, category)
        direct = {s.code for s in sectors if self.matches(query, s.code, s.name)}
        if direct:
            return direct, None
        names = self.info._load_name_cache()
        stocks = {code for code in set().union(*(set(self.member_codes(s.code)) for s in sectors))
                  if self.matches(query, code, names.get(code, ''))}
        return {s.code for s in sectors if stocks.intersection(self.member_codes(s.code))}, stocks

    def industries_for_stock(self, code):
        self._catalog()
        return tuple(s for s in self._sectors if s.category == 'industry' and s.level in (1, 2) and code in self._members[s.code])

    def industry_path_for_stock(self, code):
        self._catalog()
        cached = self._industry_paths.get(code)
        if cached is not None:
            return cached
        found = [s for s in self._sectors
                 if s.category == 'industry' and s.level in (1, 2) and code in self._members[s.code]]
        first = next((s for s in found if s.level == 1), None)
        second = next(
            (s for s in found if s.level == 2 and (first is None or s.parent == first.code)),
            None,
        )
        if first is not None and second is not None:
            path = f'{first.name} › {second.name}'
        elif first is not None:
            path = first.name
        elif second is not None:
            path = second.path or second.name
        else:
            path = ''
        self._industry_paths[code] = path
        return path

    def memberships_for_stock(self, code, category='concept', level=1):
        return tuple(s for s in self.sectors(level=level, category=category) if code in self._members[s.code])

    def chart_history(self, code, context, provider=None, adjust_type="qfq"):
        bars = self.history(code, context)
        if code.startswith('sh880') or adjust_type == 'none':
            return bars, '日K'
        label = '后复权' if adjust_type == 'hfq' else '前复权'
        if provider is None or not provider.ready:
            return bars, f'日K · {label}资料未就绪，暂用原始价格'
        adjusted = provider.apply(bars, code, adjust_type)
        return adjusted if adjusted is not None else bars, f'日K · {label}'

    def index_history(self, sector_code):
        return self._read(sector_code)[0]
