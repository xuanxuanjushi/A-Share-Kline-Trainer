import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from stock_simulator.kline_widget import KLineWidget
from stock_simulator.tdx_reader import TdxDayReader
from stock_simulator.models import DailyBar
import tempfile
from pathlib import Path
from stock_simulator.app import MainWindow
from stock_simulator.models import RoundRecord, TradeNode
from stock_simulator.engine import DailySimulationEngine


class PerformanceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def chart(self):
        widget = KLineWidget(None)
        bars = [DailyBar('x', f'2024-01-{i+1:02}', 2, 5, 1, float(i+1), 100, 100) for i in range(5)]
        widget.set_data(bars, bars, [], 4, 0, 5, True)
        widget.boll_n = 3
        self.addCleanup(widget.close)
        return widget

    def test_boll_repeated_read_reuses_result_and_preserves_values(self):
        widget = self.chart()
        first = widget._boll_series()
        self.assertEqual(first[0], [None, None, 2, 3, 4])
        self.assertAlmostEqual(first[1][2], 2 + 2 * (2/3)**0.5)
        self.assertIs(widget._boll_series(), first)

    def test_boll_invalidation_covers_middle_edit_parameters_and_hidden_day(self):
        widget = self.chart()
        before = widget._boll_series()
        widget.all_bars[2] = replace(widget.all_bars[2], close=6)
        self.assertEqual(widget._boll_series()[0][2], 3)
        widget.boll_k = 3
        self.assertNotEqual(widget._boll_series()[1][2], before[1][2])
        widget.reveal_current_full = False
        self.assertAlmostEqual(widget._boll_series()[0][-1], 4)
        widget.pan_offset = 1
        self.assertAlmostEqual(widget._boll_series()[0][-1], 5)

    def test_blank_data_directory_does_not_discover_current_working_directory(self):
        with patch('stock_simulator.tdx_reader._scan_tdx_location', side_effect=AssertionError('unexpected disk scan')):
            reader = TdxDayReader('')
        self.assertIsNone(reader._stock_codes_cache)

    def window(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for target, value in (
            ('stock_simulator.config.CONFIG_PATH', Path(temporary.name)/'settings.json'),
            ('stock_simulator.app.CONFIG_PATH', Path(temporary.name)/'settings.json'),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with patch.object(MainWindow, '_load_startup_market'), patch.object(MainWindow, '_start_adjust_initialize'):
            window = MainWindow()
        window.engine = DailySimulationEngine(self.chart().all_bars, 10000, 1, start_index=4)
        window.trade_started = True
        def dispose():
            window._migration_restore_pending_restart = True
            window._persist_timer.stop()
            window.close()
        self.addCleanup(dispose)
        return window

    def test_panning_does_not_schedule_save_but_market_step_does(self):
        window = self.window()
        window.pan_left(1)
        self.assertFalse(window._persist_timer.isActive())
        window.show_close_phase()
        self.assertTrue(window._persist_timer.isActive())

    def test_unchanged_round_log_preserves_row_and_updates_changed_profit(self):
        window = self.window()
        window.round_records = [RoundRecord(1, 'x', 'name', 12)]
        window._refresh_round_log()
        item = window.round_log.item(0)
        window._refresh_round_log()
        self.assertIs(window.round_log.item(0), item)
        window.round_records[0] = replace(window.round_records[0], profit=25)
        window._refresh_round_log()
        self.assertIn('+25', window.round_log.item(0).text())

    def test_rolling_boll_matches_window_reference_over_long_history(self):
        import math
        import random
        widget = self.chart()
        randomizer = random.Random(20260906)
        for base in (10.0, 1000000.0):
            closes = [base + randomizer.random() for _ in range(3000)]
            widget.all_bars = [replace(widget.all_bars[0], date=str(i), close=value) for i, value in enumerate(closes)]
            widget.boll_n = 20
            mid, upper, lower = widget._boll_series()
            for i in range(19, len(closes), 37):
                values = closes[i-19:i+1]
                mean = sum(values)/20
                sd = math.sqrt(sum((value-mean)**2 for value in values)/20)
                self.assertAlmostEqual(mid[i], mean, delta=1e-7)
                self.assertAlmostEqual(upper[i], mean+2*sd, delta=1e-7)
                self.assertAlmostEqual(lower[i], mean-2*sd, delta=1e-7)

    def test_cached_indicators_do_not_change_drawn_output(self):
        from PySide6.QtGui import QPixmap
        widget = self.chart()
        widget.resize(800,600)
        for mode in ('boll','gma'):
            widget.main_overlay_mode=mode
            first=QPixmap(widget.size())
            widget.render(first)
            second=QPixmap(widget.size())
            widget.render(second)
            self.assertEqual(first.toImage(), second.toImage())
