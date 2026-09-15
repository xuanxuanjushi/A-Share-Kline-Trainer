import tempfile
import unittest
from pathlib import Path

from stock_simulator.tdx_reader import DAY_RECORD
from stock_simulator.sectors.service import SectorService, SectorDataError
from stock_simulator.sectors.contracts import MarketContext


class SectorServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        cache = self.root / 'T0002/hq_cache'
        cache.mkdir(parents=True)
        (cache / 'tdxzs.cfg').write_text('煤炭|880301|2|1|0|T0101\n煤炭开采|880302|2|1|1|T010101\n银行|880471|2|1|1|T1001\n概念|880900|4|1|0|概念\n', encoding='gbk')
        (cache / 'tdxhy.cfg').write_text('1|600000|T1001|||X1\n0|000001|T010101|||X2\n0|000001|T010101|||X2\n', encoding='gbk')
        for code in ('sh880301', 'sh880471', 'sz000001', 'sh600000'):
            folder = self.root / 'vipdoc' / code[:2] / 'lday'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (code + '.day')).write_bytes(b''.join(
                DAY_RECORD.pack(20200100 + day, 1000, close + 100, 900, close, 50000., 1000, 0)
                for day, close in ((2, 1000), (3, 1100), (6, 1200), (7, 5000))))
        self.service = SectorService(str(self.root))
        self.context = MarketContext(str(self.root), '2020-01-06', True)

    def test_only_first_level_industries_and_unique_members(self):
        sectors = self.service.sectors()
        self.assertEqual([s.code for s in sectors], ['sh880301', 'sh880471'])
        self.assertEqual(self.service.member_codes('sh880301'), ('sz000001',))

    def test_children_have_explicit_parent_and_members(self):
        second = self.service.sectors(level=2)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].parent, 'sh880301')
        self.assertEqual(second[0].path, '煤炭 › 煤炭开采')
        self.assertEqual(self.service.member_codes('sh880302'), ('sz000001',))
        self.assertEqual(self.service.sectors(level=3), ())
        self.assertEqual(self.service.sectors(level=2, parent='sh880471'), ())

    def test_snapshot_does_not_return_future_bars(self):
        bars = self.service.history('sz000001', self.context)
        self.assertEqual(bars[-1].close, 12)
        self.assertEqual(len(bars), 3)
        row = self.service.quote('sz000001', '测试', self.context)
        self.assertAlmostEqual(row.change, (12 / 11 - 1) * 100)
        self.assertIsNone(row.change5)

    def test_open_masks_high_low_close_volume_amount_and_changes(self):
        context = MarketContext(str(self.root), '2020-01-06', False)
        bar = self.service.history('sz000001', context)[-1]
        self.assertEqual((bar.open, bar.high, bar.low, bar.close, bar.amount, bar.volume), (10, 10, 10, 10, 0, 0))
        row = self.service.quote('sz000001', '测试', context)
        self.assertAlmostEqual(row.change, (10/11-1)*100)
        self.assertIsNone(row.amount)

    def test_missing_session_not_reported_as_today_return(self):
        row = self.service.quote('sz000001', '', MarketContext(str(self.root), '2020-01-05', True))
        self.assertIsNone(row.change)
        self.assertIn('当日无行情', row.status)

    def test_missing_and_corrupt_files_are_distinct(self):
        with self.assertRaisesRegex(SectorDataError, '没有本地日线'):
            self.service.history('sh600001', self.context)
        (self.root / 'vipdoc/sz/lday/sz000001.day').write_bytes(b'broken')
        with self.assertRaisesRegex(SectorDataError, '损坏'):
            self.service.history('sz000001', self.context)

    def test_reject_invalid_date_code_and_source(self):
        with self.assertRaises(ValueError):
            MarketContext(str(self.root), '2020-02-31', True)
        with self.assertRaises(SectorDataError):
            self.service.history('../secrets', self.context)
        with self.assertRaises(SectorDataError):
            self.service.history('sz000001', MarketContext('other', '2020-01-06', True))

    def test_source_file_update_invalidates_cache(self):
        self.service.history('sz000001', self.context)
        path = self.root / 'vipdoc/sz/lday/sz000001.day'
        path.write_bytes(DAY_RECORD.pack(20200102, 2000, 2000, 2000, 2000, 10., 10, 0))
        self.assertEqual(self.service.history('sz000001', self.context)[0].close, 20)

    def test_before_listing_empty(self):
        self.assertEqual(self.service.history('sz000001', MarketContext(str(self.root), '2010-01-01', True)), [])

    def test_short_date_and_boundaries_follow_trading_dates(self):
        for query, expected in [('2020', '2020-01-02'), ('202001', '2020-01-02'),
                                ('20200104', '2020-01-06'), ('2020-01-03', '2020-01-03')]:
            self.assertEqual(self.service.resolve_date(query, self.context, 'sz000001'), expected)
        self.assertEqual(self.service.resolve_date('', self.context, 'sz000001', 'first'), '2020-01-02')
        self.assertEqual(self.service.resolve_date('', self.context, 'sz000001', 'last'), '2020-01-07')
        from dataclasses import replace
        locked = replace(self.context, locked=True)
        self.assertEqual(self.service.resolve_date('', locked, 'sz000001', 'last'), '2020-01-06')
        with self.assertRaises(SectorDataError):
            self.service.resolve_date('20200107', locked, 'sz000001')
        with self.assertRaises(ValueError):
            self.service.resolve_date('20200231', self.context, 'sz000001')

    def test_ten_day_change_uses_ten_bars_and_hides_unrevealed_close(self):
        path = self.root / 'vipdoc/sh/lday/sh880301.day'
        path.write_bytes(b''.join(DAY_RECORD.pack(20200100 + d, 1000 + d * 100,
            1000 + d * 100, 1000 + d * 100, 1000 + d * 100, 1000., 100, 0)
            for d in range(1, 13)))
        context = MarketContext(str(self.root), '2020-01-11', True)
        self.assertAlmostEqual(self.service.quote('sh880301', '', context).change10, (21/11-1)*100)
        self.assertIsNone(self.service.quote('sh880301', '', MarketContext(str(self.root), '2020-01-10', True)).change10)
        self.assertAlmostEqual(self.service.quote('sh880301', '', MarketContext(str(self.root), '2020-01-11', False)).change10, (21/11-1)*100)

    def test_quote_computes_open_auction_change_and_turnover_rates(self):
        row = self.service._compute_quote(
            'sz000001', '测试', self.context, float_a_shares=10000
        )
        self.assertAlmostEqual(row.open_change, (10 / 11 - 1) * 100)
        self.assertEqual(row.turnover1, 10.0)
        self.assertEqual(row.turnover5, 30.0)
        self.assertEqual(row.turnover10, 30.0)
        self.assertEqual(row.turnover20, 30.0)
        self.assertEqual(row.turnover60, 30.0)

    def test_limit_up_percent_follows_board_rules(self):
        from stock_simulator.sectors.service import limit_up_percent

        self.assertEqual(limit_up_percent('sh600000'), 10.0)
        self.assertEqual(limit_up_percent('sz300750'), 20.0)
        self.assertEqual(limit_up_percent('sh688111'), 20.0)
        self.assertEqual(limit_up_percent('bj430047'), 30.0)
        # ST 股票按新规与主板一致，同样按 10% 处理。
        self.assertEqual(limit_up_percent('sz000001'), 10.0)

    def test_halved_style_lists_use_high_close_drop_with_band(self):
        cache = self.root / 'cache'
        cache.mkdir()
        series = {
            # 25 天里从 2000 跌到 1100（跌 45%）：算腰斩
            'sz000001': [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 2000,
                         1900, 1800, 1700, 1600, 1500, 1400, 1300, 1200, 1150, 1120,
                         1110, 1105, 1102, 1101, 1100],
            # 只跌 20%：不算
            'sh600000': [1000] * 9 + [2000] + [1900, 1800, 1700, 1600] + [1600] * 10,
            # 25 天里跌 65%（超过 60% 上沿）；但最近 15 天从 1500 跌到 700，约跌 53%
            'sh600519': [1000] * 9 + [2000] + [1500, 1400, 1300, 1200, 1100, 1000, 950,
                                              900, 850, 800, 780, 760, 740, 720, 700],
        }
        for code, closes in series.items():
            folder = self.root / 'vipdoc' / code[:2] / 'lday'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (code + '.day')).write_bytes(b''.join(
                DAY_RECORD.pack(20200100 + day, close, close, close, close, 50000., 1000, 0)
                for day, close in zip(range(2, 27), closes)
            ))
        service = SectorService(str(self.root), cache_dir=cache)
        context = MarketContext(str(self.root), '2020-01-26', True)
        service.warm_stock_quotes(sorted(series), context)
        # 近半月窗口里 600519 约跌 53%（在 40%~60% 内），近一月/近三月窗口跌 65%，超出上沿。
        self.assertEqual(set(service.member_codes('sh881904')), {'sz000001', 'sh600519'})
        self.assertEqual(set(service.member_codes('sh881905')), {'sz000001'})
        self.assertEqual(set(service.member_codes('sh881906')), {'sz000001'})
        quote = service.quote('sz000001', '测试', context)
        self.assertAlmostEqual(quote.high_drop_month, 45.0, places=1)
        self.assertAlmostEqual(quote.high_drop_half_month, 42.11, places=1)
        self.assertAlmostEqual(quote.high_drop_quarter, 45.0, places=1)

    def test_random_session_respects_allowed_codes(self):
        import tempfile

        from stock_simulator.session import choose_session_data
        from stock_simulator.tdx_reader import TdxDayReader

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for code in ('sh600000', 'sz300750'):
                folder = root / 'vipdoc' / code[:2] / 'lday'
                folder.mkdir(parents=True, exist_ok=True)
                (folder / (code + '.day')).write_bytes(b''.join(
                    DAY_RECORD.pack(20200101 + day, 1000, 1100, 900, 1000, 50000., 1000, 0)
                    for day in range(200)
                ))
            reader = TdxDayReader(str(root))
            for _ in range(10):
                bars, _start = choose_session_data(
                    reader, None, None, min_forward_bars=1, allowed_codes={'sh600000'}
                )
                self.assertEqual(bars[0].code, 'sh600000')
            with self.assertRaisesRegex(ValueError, '没有找到'):
                choose_session_data(
                    reader, None, None, min_forward_bars=1, allowed_codes={'sz300111'}
                )

    def test_saved_config_keeps_sector_favorites(self):
        from stock_simulator import config as config_module

        settings = config_module.AppSettings()
        settings.favorite_sectors = ['sh881901', 'sh880301']
        settings.favorite_stocks = ['sz000001', 'sh600000']
        config_module.save_settings(settings)
        loaded = config_module.load_settings()
        self.assertEqual(loaded.favorite_sectors, ['sh881901', 'sh880301'])
        self.assertEqual(loaded.favorite_stocks, ['sz000001', 'sh600000'])

    def test_today_style_sectors_use_latest_market_snapshot(self):
        cache = self.root / 'cache'
        cache.mkdir()
        series = {
            'sz000001': (1000, 1100, 1210),  # 连续两天涨停（两连板）
            'sh600000': (1000, 1000, 1100),  # 今天首板
            'sh600519': (1000, 1000, 900),   # 今天跌停
        }
        for code, closes in series.items():
            folder = self.root / 'vipdoc' / code[:2] / 'lday'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (code + '.day')).write_bytes(b''.join(
                DAY_RECORD.pack(20200100 + day, close, close, close, close, 50000., 1000, 0)
                for day, close in zip((2, 3, 6), closes)
            ))
        service = SectorService(str(self.root), cache_dir=cache)
        context = MarketContext(str(self.root), '2020-01-06', True)
        names = [sector.name for sector in service.sectors(category='style')]
        self.assertIn('今日涨停', names)
        self.assertIn('今日连板', names)
        self.assertIn('今日跌停', names)
        service.warm_stock_quotes(['sz000001', 'sh600000', 'sh600519'], context)
        self.assertEqual(set(service.member_codes('sh881901')), {'sz000001', 'sh600000'})
        self.assertEqual(set(service.member_codes('sh881902')), {'sz000001'})
        self.assertEqual(set(service.member_codes('sh881903')), {'sh600519'})
        summary = service.quote('sh881901', '今日涨停', context)
        self.assertEqual(summary.change, 10.0)
        self.assertEqual(summary.bar_count, 2)

    def test_quote_counts_consecutive_limit_up_days(self):
        path = self.root / 'vipdoc/sz/lday/sz000001.day'
        records = (
            (20200102, 1000), (20200103, 1100), (20200106, 1210), (20200107, 1331),
        )
        path.write_bytes(b''.join(
            DAY_RECORD.pack(day, close, close, close, close, 50000., 1000, 0)
            for day, close in records
        ))
        service = SectorService(str(self.root))
        latest = service.quote('sz000001', '测试', MarketContext(str(self.root), '2020-01-07', True))
        self.assertEqual(latest.limit_up_streak, 3)
        earlier = service.quote('sz000001', '测试', MarketContext(str(self.root), '2020-01-06', True))
        self.assertEqual(earlier.limit_up_streak, 2)
        first = service.quote('sz000001', '测试', MarketContext(str(self.root), '2020-01-03', True))
        self.assertEqual(first.limit_up_streak, 1)
        before = service.quote('sz000001', '测试', MarketContext(str(self.root), '2020-01-02', True))
        self.assertEqual(before.limit_up_streak, 0)

    def test_quote_computes_daily_volume_ratio(self):
        path = self.root / 'vipdoc/sz/lday/sz000001.day'
        records = []
        for index in range(7):
            day = 20200102 + index
            volume = 200 if index == 6 else 100
            records.append(DAY_RECORD.pack(day, 1000, 1010, 990, 1000, 1000., volume, 0))
        path.write_bytes(b''.join(records))
        row = self.service._compute_quote(
            'sz000001', '测试', MarketContext(str(self.root), '2020-01-08', True)
        )
        self.assertEqual(row.volume_ratio, 2.0)

    def test_search_initials_codes_polyphones_and_stock_membership(self):
        self.service.info._name_cache = {'sz000001': '铜陵有色', 'sh600000': '重庆银行'}
        for query in ('铜陵有色', 'TLYS', '000001', 'sz000001'):
            sectors, stocks = self.service.search(query)
            self.assertEqual(sectors, {'sh880301'})
            self.assertEqual(stocks, {'sz000001'})
        for query in ('CQYH', 'ZQYX'):
            self.assertEqual(self.service.search(query)[0], {'sh880471'})
        for query in ('MT', '煤炭', '880301'):
            self.assertEqual(self.service.search(query), ({'sh880301'}, None))
        self.assertEqual(self.service.search('不存在'), (set(), set()))

    def test_next_date_uses_selected_sector_calendar(self):
        self.assertEqual(self.service.next_date('2020-01-03', 'sh880301'), '2020-01-06')
        with self.assertRaises(SectorDataError):
            self.service.next_date('2020-01-07', 'sh880301')

    def test_stock_industries_include_both_levels(self):
        found = self.service.industries_for_stock('sz000001')
        self.assertEqual({s.code for s in found}, {'sh880301', 'sh880302'})
        self.assertEqual(self.service.industries_for_stock('sh600999'), ())

    def test_stock_industry_path_uses_first_and_second_level(self):
        self.assertEqual(
            self.service.industry_path_for_stock('sz000001'),
            '煤炭 › 煤炭开采',
        )
        self.assertEqual(self.service.industry_path_for_stock('sh600000'), '银行')
        self.assertEqual(self.service.industry_path_for_stock('sh600999'), '')

    def test_industry_working_set_remains_warm_beyond_192_symbols(self):
        from unittest.mock import patch
        data = (self.root / 'vipdoc/sh/lday/sh880301.day').read_bytes()
        codes = ['sh'+str(600000+i) for i in range(205)]
        for code in codes:
            (self.root / 'vipdoc/sh/lday' / (code+'.day')).write_bytes(data)
            self.service._read(code)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('warm data parsed again')):
            for code in codes:
                self.service._read(code)
        self.assertEqual(self.service._cached_bar_count, 205*4)

    def test_concept_style_members_are_separate_from_industries(self):
        cache = self.root / 'T0002/hq_cache'
        with (cache/'tdxzs.cfg').open('a', encoding='gbk') as f:
            f.write('PCB概念|880550|4|2|0|PCB概念\n高分红股|880526|5|2|0|高分红股\n')
        (cache/'infoharbor_block.dat').write_text('#GN_PCB概念,2,880550,,,,\n0#000001,1#600000,\n#FG_高分红股,1,880526,,,,\n1#600000,\n', encoding='gbk')
        self.assertIn('sh880550', {s.code for s in self.service.sectors(category='concept')})
        style_codes = [s.code for s in self.service.sectors(category='style')]
        self.assertIn('sh880526', style_codes)
        # 程序自己统计的风格板块（今日涨停/连板/跌停、腰斩）固定附加在风格列表里。
        self.assertEqual(
            style_codes[-6:],
            ['sh881901', 'sh881902', 'sh881903', 'sh881904', 'sh881905', 'sh881906'],
        )
        self.assertEqual(self.service.member_codes('sh880550'), ('sh600000', 'sz000001'))
        self.assertEqual(self.service.member_codes('sh880526'), ('sh600000',))
        self.assertEqual({s.code for s in self.service.industries_for_stock('sh600000')}, {'sh880471'})
        self.assertEqual(self.service.search('PCB', category='concept'), ({'sh880550'}, None))

    def test_chart_adjustment_receives_only_revealed_prices(self):
        from unittest.mock import Mock
        provider = Mock(ready=True)
        provider.apply.side_effect = lambda bars, code, mode: bars
        context = MarketContext(str(self.root), '2020-01-06', False)
        bars, label = self.service.chart_history('sz000001', context, provider)
        passed, code, mode = provider.apply.call_args.args
        self.assertEqual(passed[-1].date, context.date)
        self.assertEqual(passed[-1].close, passed[-1].open)
        self.assertEqual(mode, 'qfq')
        self.assertIn('前复权', label)
        provider.reset_mock()
        self.service.chart_history('sh880301', context, provider)
        provider.apply.assert_not_called()

    def test_compact_quotes_match_history_without_materializing_it(self):
        from unittest.mock import patch
        for day in ('2020-01-01','2020-01-03','2020-01-05','2020-01-06'):
            for closed in (True, False):
                context = MarketContext(str(self.root), day, closed)
                bars = self.service.history('sz000001', context)
                with patch.object(self.service, 'history', side_effect=AssertionError('ranking materialized chart')):
                    q = self.service.quote('sz000001', 'test', context)
                if bars and bars[-1].date == day:
                    self.assertEqual(q.price, bars[-1].close)
                    self.assertAlmostEqual(q.change, (bars[-1].close/bars[-2].close-1)*100)
                else:
                    self.assertIsNone(q.price)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('reread warm quote data')):
            self.service.quote('sz000001', 'test', self.context)

    def test_cancelled_batch_does_not_load_remaining_symbols(self):
        from unittest.mock import patch
        with patch.object(self.service, 'quote', side_effect=AssertionError('cancelled work still loaded')):
            self.assertEqual(self.service.sector_quotes(self.context, cancelled=lambda: True), [])
            self.assertEqual(self.service.member_quotes('sh880301', self.context, cancelled=lambda: True), [])

    def test_quote_fast_path_only_validates_needed_recent_records(self):
        path = self.root / 'vipdoc/sz/lday/sz000001.day'
        records = []
        for index in range(25):
            day = 20200101 + index
            price = 1000 + index * 10
            records.append(DAY_RECORD.pack(day, price, price + 10, price - 10, price, 1000., 100, 0))
        first = list(DAY_RECORD.unpack(records[0]))
        first[2], first[3] = first[3], first[2]
        records[0] = DAY_RECORD.pack(*first)
        path.write_bytes(b''.join(records))
        context = MarketContext(str(self.root), '2020-01-25', True)
        self.assertIsNotNone(self.service.quote('sz000001', '测试', context).price)
        with self.assertRaisesRegex(SectorDataError, '损坏'):
            self.service.history('sz000001', context)

    def test_sector_quote_cache_survives_service_restart(self):
        from unittest.mock import patch
        cache_dir = self.root / 'cache'
        first = SectorService(str(self.root), cache_dir=cache_dir)
        rows = first.sector_quotes(self.context)
        self.assertTrue((cache_dir / 'sector_quotes.json').is_file())
        second = SectorService(str(self.root), cache_dir=cache_dir)
        with patch.object(SectorService, 'quote', side_effect=AssertionError('cache miss')):
            cached = second.sector_quotes(self.context)
        self.assertEqual([item.code for item in cached], [item.code for item in rows])
        self.assertEqual([item.change for item in cached], [item.change for item in rows])

    def test_warm_stock_quotes_serves_member_rows_without_rereading_files(self):
        from unittest.mock import patch
        cache_dir = self.root / 'cache'
        first = SectorService(str(self.root), cache_dir=cache_dir)
        first.warm_stock_quotes(('sz000001', 'sh600000'), self.context)
        second = SectorService(str(self.root), cache_dir=cache_dir)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('quote cache miss')):
            rows = second.member_quotes('sh880301', self.context)
        self.assertEqual([row.code for row in rows], ['sz000001'])
        self.assertIsNotNone(rows[0].price)

    def test_random_date_uses_available_sessions_and_locked_boundary(self):
        from dataclasses import replace
        from unittest.mock import patch
        with patch('stock_simulator.sectors.service.random.SystemRandom.choice', side_effect=lambda bars: bars[-1]):
            self.assertEqual(self.service.resolve_date('', self.context, 'sz000001', 'random'), '2020-01-07')
            self.assertEqual(self.service.resolve_date('', replace(self.context, locked=True), 'sz000001', 'random'), '2020-01-03')
