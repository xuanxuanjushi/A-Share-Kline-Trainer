import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_simulator.tdx_reader import DAY_RECORD, TdxDataLocation, TdxDayReader
from stock_simulator.market_stats import build_market_stats_cache


class MarketSyncTests(unittest.TestCase):
    def test_fresh_package_does_not_seed_author_market_statistics(self):
        from stock_simulator.config import ensure_packaged_user_files
        profile = self.root / 'profile/settings.json'
        ensure_packaged_user_files(config_path=profile, is_packaged=True,
            bundled_index_data=b'[{"date":"2026-09-04"}]',
            bundled_market_data=b'{"root":"D:/TDX","stats":{"2026-09-04":{}}}')
        self.assertEqual(json.loads(profile.read_text())['tdx_root'], '')
        self.assertFalse((profile.parent / 'market_stats_daily.json').exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.day = self.root / 'tdx/vipdoc/sh/lday'
        self.day.mkdir(parents=True)
        self.location = TdxDataLocation(self.root / 'tdx', {'sh': self.day})
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.stock = self.day / 'sh600000.day'
        self.index = self.day / 'sh999999.day'
        self.stock.write_bytes(self.row(20260903, 1000))
        self.index.write_bytes(self.row(20260903, 390000))

    @staticmethod
    def row(date, close):
        return DAY_RECORD.pack(date, close, close + 10, close - 10, close, 100000., 1000, 0)

    def sync(self, previous=None):
        from stock_simulator.market_sync import sync_local_market
        return sync_local_market(self.cache, self.location, previous)

    def test_cleared_stats_with_preserved_file_offsets_are_rebuilt(self):
        path = self.cache / 'market_stats_daily.json'
        build_market_stats_cache(path, TdxDayReader(self.location))
        document = json.loads(path.read_text())
        document['stats'] = {}
        path.write_text(json.dumps(document))
        result = build_market_stats_cache(path, TdxDayReader(self.location))
        self.assertIn('2026-09-03', result.stats)

    def test_unchanged_data_does_not_recompute_or_rewrite(self):
        first = self.sync()
        with patch('stock_simulator.market_sync.build_market_stats_cache', side_effect=AssertionError('recomputed')):
            self.assertIsNone(self.sync(first.fingerprint))

    def test_same_directory_append_updates_both_index_and_statistics(self):
        first = self.sync()
        with self.stock.open('ab') as stream:
            stream.write(self.row(20260904, 1100))
        with self.index.open('ab') as stream:
            stream.write(self.row(20260904, 393012))
        result = self.sync(first.fingerprint)
        self.assertEqual(result.bars[-1].date, '2026-09-04')
        self.assertEqual(result.stats.stats['2026-09-04'].up_count, 1)

    def test_deleted_and_partially_cleared_cache_are_rebuilt(self):
        first = self.sync()
        path = self.cache / 'market_stats_daily.json'
        path.unlink()
        restored = self.sync(first.fingerprint)
        self.assertIn('2026-09-03', restored.stats.stats)
        document = json.loads(path.read_text())
        document['stats'].pop('2026-09-03')
        path.write_text(json.dumps(document))
        restored = self.sync(restored.fingerprint)
        self.assertIn('2026-09-03', restored.stats.stats)

    def test_same_size_source_edit_recalculates(self):
        first = self.sync()
        self.stock.write_bytes(self.row(20260904, 1100))
        result = self.sync(first.fingerprint)
        self.assertIn('2026-09-04', result.stats.stats)
        self.assertNotIn('2026-09-03', result.stats.stats)

    def test_incomplete_download_is_not_committed_and_can_retry(self):
        first = self.sync()
        self.stock.write_bytes(self.stock.read_bytes() + b'partial')
        with self.assertRaisesRegex(ValueError, '写入'):
            self.sync(first.fingerprint)
        self.stock.write_bytes(self.row(20260904, 1100))
        result = self.sync(first.fingerprint)
        self.assertIn('2026-09-04', result.stats.stats)

    def test_alternate_index_file_and_deleted_index_cache(self):
        alternate = self.day / 'sh000001.day'
        alternate.write_bytes(self.row(20260904, 393012))
        first = self.sync()
        self.assertEqual(first.bars[-1].date, '2026-09-04')
        self.assertEqual(first.bars[-1].code, 'sh999999')
        (self.cache / 'shanghai_index_daily.json').unlink()
        restored = self.sync(first.fingerprint)
        self.assertTrue((self.cache / 'shanghai_index_daily.json').is_file())
        self.assertEqual(restored.bars, first.bars)

    def test_download_during_calculation_keeps_previous_cache(self):
        first = self.sync()
        path = self.cache / 'market_stats_daily.json'
        before = path.read_bytes()
        self.stock.write_bytes(self.row(20260904, 1100))
        from stock_simulator.market_stats import _accumulate_day_file
        def downloading(*args):
            _accumulate_day_file(*args)
            self.stock.write_bytes(self.row(20260905, 1200))
        with patch('stock_simulator.market_stats._accumulate_day_file', side_effect=downloading):
            with self.assertRaisesRegex(ValueError, '写入'):
                self.sync(first.fingerprint)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn('2026-09-05', self.sync(first.fingerprint).stats.stats)


import test_performance_regressions as performance_tests
from stock_simulator.app import MainWindow


class MarketSyncWindowTests(unittest.TestCase):
    setUpClass = classmethod(performance_tests.PerformanceRegressionTests.setUpClass.__func__)
    window = performance_tests.PerformanceRegressionTests.window
    chart = performance_tests.PerformanceRegressionTests.chart

    def test_startup_advances_to_latest_even_when_statistics_fail(self):
        from dataclasses import replace
        from stock_simulator.market_stats import DailyMarketStats
        from stock_simulator.index_data import save_index_cache
        import stock_simulator.app as app_module
        window = self.window()
        cached = [replace(window.engine.bars[0], code='sh999999', date='2026-08-21')]
        newer = cached + [replace(cached[0], date='2026-09-04')]
        save_index_cache(app_module.CONFIG_PATH.parent / 'shanghai_index_daily.json', cached)
        window.market_stats_by_date = {'2026-08-21': DailyMarketStats('2026-08-21', up_count=123)}
        window.engine = None
        window.tdx_path.clear()
        window._market_sync_location = None
        MainWindow._index_update_requested = False
        def complete_online(worker):
            if isinstance(worker, app_module.IndexUpdateWorker):
                window._finish_shanghai_index_update(newer)
            elif isinstance(worker, app_module.PublicMarketStatsWorker):
                window._finish_public_market_stats_update((None, 'network unavailable'))
        with patch.dict('os.environ', {'QT_QPA_PLATFORM': ''}), \
             patch('stock_simulator.app.find_tdx_installation', return_value=None), \
             patch('stock_simulator.app.QThreadPool') as pool:
            pool.globalInstance.return_value.start.side_effect = complete_online
            window._load_startup_market()
        self.assertEqual(window.engine.current_bar.date, '2026-09-04')
        self.assertIn('请选择通达信目录', window.index_market_labels['上涨/下跌家数'].text())
        self.assertGreater(pool.globalInstance.return_value.start.call_count, 0)

    def test_fresh_startup_does_not_select_discovered_directory_or_start_statistics(self):
        from dataclasses import replace
        from stock_simulator.index_data import save_index_cache
        import stock_simulator.app as app_module
        fixture = MarketSyncTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.index.write_bytes(fixture.row(20260904, 393012))
        window = self.window()
        save_index_cache(app_module.CONFIG_PATH.parent / 'shanghai_index_daily.json',
                         [replace(window.engine.bars[0], code='sh999999', date='2026-08-21')])
        window.engine = None
        window.tdx_path.clear()
        window._market_sync_location = None
        with patch.dict('os.environ', {'QT_QPA_PLATFORM': ''}), \
             patch('stock_simulator.app.find_tdx_installation', return_value=fixture.location) as discover, \
             patch('stock_simulator.app.QThreadPool') as pool:
            window._load_startup_market()
        discover.assert_not_called()
        self.assertEqual(window.tdx_path.text(), '')
        self.assertEqual(window.settings.tdx_root, '')
        self.assertIsNone(window.market_stats_worker)
        self.assertIsNone(window.public_market_stats_worker)
        self.assertIsNotNone(window.index_update_worker)

    def test_newer_online_index_replaces_cache_but_older_response_cannot_roll_back(self):
        from dataclasses import replace
        window = self.window()
        cached = [replace(window.engine.bars[0], code='sh999999', date='2026-08-21')]
        window._market_sync_location = None
        window._activate_browse_engine(cached, '上证指数', '')
        window._finish_shanghai_index_update(cached + [replace(cached[0], date='2026-09-04')])
        self.assertEqual(window.engine.current_bar.date, '2026-09-04')
        window._finish_shanghai_index_update(cached)
        self.assertEqual(window.engine.current_bar.date, '2026-09-04')

    def test_online_is_attempted_even_with_local_directory_and_cached_index(self):
        window = self.window()
        window._market_sync_location = TdxDataLocation(Path('test-tdx'), {})
        MainWindow._index_update_requested = False
        with patch.object(window, '_check_local_market'), \
             patch.dict('os.environ', {'QT_QPA_PLATFORM': ''}), \
             patch('stock_simulator.app.QThreadPool') as pool:
            window._request_shanghai_index_update()
            pool.globalInstance.return_value.start.assert_called_once()
        MainWindow._index_update_requested = False

    def test_late_local_statistics_cannot_roll_back_newer_online_index(self):
        from dataclasses import replace
        from stock_simulator.market_sync import LocalMarketUpdate
        from stock_simulator.market_stats import MarketStatsBuildResult
        window = self.window()
        older = [replace(window.engine.bars[0], code='sh999999', date='2026-08-21')]
        newer = older + [replace(older[0], date='2026-09-04')]
        window._activate_browse_engine(newer, '上证指数', '')
        window.market_stats_root = 'test-tdx'
        update = LocalMarketUpdate(('new',), MarketStatsBuildResult('test-tdx', {}, 1, True), older)
        window._finish_market_stats_update(('test-tdx', update, ''))
        self.assertEqual(window.engine.current_bar.date, '2026-09-04')

    def test_online_first_result_opens_empty_window_without_statistics(self):
        from dataclasses import replace
        window = self.window()
        bars = [replace(window.engine.bars[0], code='sh999999', date='2026-09-04')]
        window.engine = None
        window.shanghai_index_bars = []
        window._finish_shanghai_index_update(bars)
        self.assertEqual(window.engine.current_bar.date, '2026-09-04')
        self.assertIn('请选择通达信目录', window.index_market_labels['上涨/下跌家数'].text())

    def test_online_failure_preserves_available_chart(self):
        from dataclasses import replace
        window = self.window()
        bars = [replace(window.engine.bars[0], code='sh999999', date='2026-09-04')]
        window._activate_browse_engine(bars, '上证指数', '')
        engine = window.engine
        window._finish_shanghai_index_update([])
        self.assertIs(window.engine, engine)
        self.assertEqual(window.engine.current_bar.date, '2026-09-04')

    def test_online_update_keeps_active_training_and_later_stats_display_automatically(self):
        from dataclasses import replace
        from stock_simulator.market_stats import DailyMarketStats
        window = self.window()
        window.training_mode = True
        engine = window.engine
        bars = [replace(engine.bars[0], code='sh999999', date='2026-09-04')]
        window._finish_shanghai_index_update(bars)
        self.assertIs(window.engine, engine)
        self.assertEqual(window.shanghai_index_bars[-1].date, '2026-09-04')
        window._activate_browse_engine(bars, '上证指数', '')
        from stock_simulator.market_sync import LocalMarketUpdate
        from stock_simulator.market_stats import MarketStatsBuildResult
        window.market_stats_root = 'chosen-tdx'
        window._market_sync_location = TdxDataLocation(Path('chosen-tdx'), {})
        stats = {'2026-09-04': DailyMarketStats('2026-09-04', up_count=123, down_count=45)}
        window._finish_market_stats_update(('chosen-tdx', LocalMarketUpdate(('fresh',),
            MarketStatsBuildResult('chosen-tdx', stats, 1, True), bars), ''))
        self.assertIn('123 / 45', window.index_market_labels['上涨/下跌家数'].text())

    def test_selected_directory_loads_matching_statistics_cache_immediately(self):
        import stock_simulator.app as app_module
        fixture = MarketSyncTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        window = self.window()
        build_market_stats_cache(app_module.CONFIG_PATH.parent / 'market_stats_daily.json', TdxDayReader(fixture.location))
        window._request_market_stats_update(fixture.location)
        self.assertIn('2026-09-03', window.market_stats_by_date)

    def test_typing_path_alone_does_not_start_statistics(self):
        window = self.window()
        window._market_sync_location = None
        window.tdx_path.setText('D:/TDX')
        with patch.object(window, '_request_market_stats_update') as request:
            window._check_local_market()
            request.assert_not_called()

    def test_same_root_can_be_checked_again_after_completion(self):
        window = self.window()
        location = TdxDataLocation(Path('test-tdx'), {})
        window.market_stats_root = str(location.root)
        window.market_stats_requested_root = str(location.root)
        with patch.dict('os.environ', {'QT_QPA_PLATFORM': ''}), patch('stock_simulator.app.QThreadPool') as pool:
            window._request_market_stats_update(location)
            pool.globalInstance.return_value.start.assert_called_once()

    def test_late_network_failure_cannot_replace_local_status(self):
        window = self.window()
        window._market_sync_location = TdxDataLocation(Path('test-tdx'), {})
        window.market_stats_status = ''
        window._finish_public_market_stats_update((None, 'timeout'))
        self.assertEqual(window.market_stats_status, '')

    def test_local_update_does_not_replace_training_engine(self):
        from stock_simulator.market_sync import LocalMarketUpdate
        from stock_simulator.market_stats import MarketStatsBuildResult, DailyMarketStats
        window = self.window()
        window.training_mode = True
        engine = window.engine
        window.market_stats_root = 'test-tdx'
        stats = {'2026-09-04': DailyMarketStats('2026-09-04', up_count=12)}
        result = LocalMarketUpdate(('stamp',), MarketStatsBuildResult('test-tdx', stats, 12, True), [])
        window._finish_market_stats_update(('test-tdx', result, ''))
        self.assertIs(window.engine, engine)
        self.assertEqual(window.market_stats_by_date, stats)

    def test_unchanged_check_does_not_refresh_chart(self):
        window = self.window()
        window.market_stats_root = 'test-tdx'
        with patch.object(window, '_refresh') as refresh:
            window._finish_market_stats_update(('test-tdx', None, ''))
            refresh.assert_not_called()

    def test_old_directory_result_is_discarded(self):
        from stock_simulator.market_sync import LocalMarketUpdate
        from stock_simulator.market_stats import MarketStatsBuildResult
        window = self.window()
        window.market_stats_root = 'new-directory'
        original = window.market_stats_by_date
        result = LocalMarketUpdate(('old',), MarketStatsBuildResult('old', {}, 0, True), [])
        window._finish_market_stats_update(('old', result, ''))
        self.assertIs(window.market_stats_by_date, original)
        self.assertIsNone(window._market_sync_fingerprint)

    def test_import_append_and_cache_clear_reach_visible_labels(self):
        fixture = MarketSyncTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        window = self.window()
        # A fresh window has training_mode=True before any engine is opened.
        window.training_mode = True
        window.engine = None
        with patch('stock_simulator.app.CONFIG_PATH', fixture.cache / 'settings.json'), \
             patch.dict('os.environ', {'QT_QPA_PLATFORM': ''}), \
             patch('stock_simulator.app.QThreadPool') as pool:
            pool.globalInstance.return_value.start.side_effect = lambda worker: worker.run()
            window._request_market_stats_update(fixture.location)
            self.assertEqual(window.engine.current_bar.date, '2026-09-03')
            fixture.stock.write_bytes(fixture.stock.read_bytes() + fixture.row(20260904, 1100))
            fixture.index.write_bytes(fixture.index.read_bytes() + fixture.row(20260904, 393012))
            window._check_local_market()
            self.assertEqual(window.engine.current_bar.date, '2026-09-04')
            self.assertIn('1 / 0', window.index_market_labels['上涨/下跌家数'].text())
            cache_time = (fixture.cache / 'shanghai_index_daily.json').stat().st_mtime_ns
            with patch.object(window, '_refresh') as refresh:
                window._check_local_market()
                refresh.assert_not_called()
            self.assertEqual((fixture.cache / 'shanghai_index_daily.json').stat().st_mtime_ns, cache_time)
            (fixture.cache / 'market_stats_daily.json').unlink()
            window.market_stats_by_date.clear()
            window._check_local_market()
            self.assertIn('2026-09-04', window.market_stats_by_date)

    def test_stats_only_update_displays_without_full_refresh_or_pan(self):
        from dataclasses import replace
        from stock_simulator.market_sync import LocalMarketUpdate
        from stock_simulator.market_stats import MarketStatsBuildResult, DailyMarketStats
        window = self.window()
        bars = [replace(bar, code='sh999999') for bar in window.engine.bars]
        window._activate_browse_engine(bars, '上证指数', '')
        window.market_stats_root = 'test-tdx'
        date = bars[-1].date
        stats = {date: DailyMarketStats(date, up_count=123, down_count=45)}
        result = LocalMarketUpdate(('new',), MarketStatsBuildResult('test-tdx', stats, 168, True), bars)
        engine = window.engine
        with patch.object(window, '_refresh') as full_refresh:
            window._finish_market_stats_update(('test-tdx', result, ''))
            self.assertIn('123 / 45', window.index_market_labels['上涨/下跌家数'].text())
            full_refresh.assert_not_called()
        self.assertIs(window.engine, engine)

    def test_stats_update_refreshes_held_index_without_touching_training(self):
        from dataclasses import replace
        from stock_simulator.market_sync import LocalMarketUpdate
        from stock_simulator.market_stats import MarketStatsBuildResult, DailyMarketStats
        window = self.window()
        window.training_mode = True
        window.reveal_current_full = True
        window._draw_chart()
        bars = [replace(bar, code='sh999999') for bar in window.engine.bars]
        window.shanghai_index_bars = bars
        window._show_held_index_preview()
        window.market_stats_root = 'test-tdx'
        date = bars[-1].date
        stats = {date: DailyMarketStats(date, up_count=77, down_count=12)}
        result = LocalMarketUpdate(('new',), MarketStatsBuildResult('test-tdx', stats, 89, True), bars)
        engine = window.engine
        window._finish_market_stats_update(('test-tdx', result, ''))
        self.assertIn('77 / 12', window.index_market_labels['上涨/下跌家数'].text())
        self.assertIs(window.engine, engine)
        self.assertTrue(window.index_preview_active)
