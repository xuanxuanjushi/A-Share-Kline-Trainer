import os
import unittest
from unittest.mock import patch
from dataclasses import replace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QThreadPool, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from stock_simulator.app import MainWindow
from stock_simulator.sectors.page import SectorPage, NumericItem
from stock_simulator.sectors.contracts import MarketContext, TrainingRequest
from stock_simulator.sample_data import create_sample_engine as _sample_engine
from stock_simulator.models import TradeNode


def create_sample_engine():
    return _sample_engine(None, 100000, 4, .0003, .0005, 5)


class SectorUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.patches = [patch.object(MainWindow, '_load_startup_market'),
                        patch.object(MainWindow, '_start_adjust_initialize'),
                        patch.object(MainWindow, '_restore_session'),
                        patch.object(MainWindow, '_show_storage_notices')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.window = MainWindow()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window.close()
        QThreadPool.globalInstance().waitForDone(10000)
        self.window.deleteLater()
        self.app.processEvents()

    def test_page_round_trip_preserves_account_engine_and_phase(self):
        w = self.window
        engine = create_sample_engine()
        w._activate_engine(engine, 'test')
        state = (engine.cash, list(engine.trades), w.current_node, w.reveal_current_full)
        w.sector_integration.show_sectors()
        self.assertIs(w.engine, engine)
        self.assertEqual(w.sector_integration.page.context.date, engine.current_bar.date)
        self.assertTrue(w.sector_integration.page.context.locked)
        w.sector_integration.show_stock()
        self.assertIs(w.engine, engine)
        self.assertEqual((engine.cash, list(engine.trades), w.current_node, w.reveal_current_full), state)

    def test_new_page_keys_do_not_trade_or_advance_hidden_engine(self):
        w = self.window
        w._activate_engine(create_sample_engine(), 'test')
        w.sector_integration.show_sectors()
        old_index = w.engine.current_index
        with patch.object(w, 'buy_at') as buy, patch.object(w, '_advance_training_phase') as advance:
            QTest.keyClick(w.sector_integration.page.search, Qt.Key.Key_B)
            QTest.keyClick(w.sector_integration.page.search, Qt.Key.Key_Down)
        buy.assert_not_called()
        advance.assert_not_called()
        self.assertEqual(w.engine.current_index, old_index)

    def test_close_selection_starts_at_close_and_preserves_exact_date(self):
        w = self.window
        source = create_sample_engine()
        w.engine = source
        w.training_mode = False
        w.reveal_current_full = True
        w.sector_integration.show_sectors()
        request = TrainingRequest(source.current_bar.code, w.sector_integration.page.context)
        with patch.object(w.reader, 'read_daily_bars', return_value=source.bars), patch.object(w.info_reader, 'name_for', return_value='测试'):
            self.assertTrue(w.sector_integration.open_training(request))
        self.assertEqual(w.engine.current_bar.date, request.context.date)
        self.assertEqual(w.current_node, TradeNode.CLOSE)
        self.assertTrue(w.reveal_current_full)
        self.assertFalse(w.sector_integration.active)

    def test_reject_stale_request_and_holdings_without_mutation(self):
        w = self.window
        w._activate_engine(create_sample_engine(), 'test')
        w.sector_integration.show_sectors()
        engine = w.engine
        context = w.sector_integration.page.context
        with patch.object(QMessageBox, 'warning'):
            self.assertFalse(w.sector_integration.open_training(TrainingRequest('sz000001', replace(context, date='2010-01-01'))))
            with patch.object(w, '_has_position', return_value=True):
                self.assertFalse(w.sector_integration.open_training(TrainingRequest('sz000001', context)))
        self.assertIs(w.engine, engine)

    def test_historical_sector_date_can_enter_training_without_future_data(self):
        w = self.window
        engine = create_sample_engine()
        w._activate_engine(engine, 'test')
        w.sector_integration.show_sectors()
        page = w.sector_integration.page
        page.context = replace(page.context, date=engine.bars[5].date, closed=True, locked=False)
        request = TrainingRequest('sz000001', page.context)
        with patch.object(w.reader, 'read_daily_bars', return_value=engine.bars), \
                patch.object(w.info_reader, 'name_for', return_value='测试'):
            self.assertTrue(w.sector_integration.open_training(request))
        self.assertEqual(w.engine.current_bar.date, request.context.date)

    def test_board_date_is_not_clamped_by_training_date(self):
        w = self.window
        engine = create_sample_engine()
        w._activate_engine(engine, 'test')
        w.sector_integration.show_sectors()
        page = w.sector_integration.page
        page.context = replace(page.context, date='2099-01-01', locked=False)
        w.sector_integration.sync()
        self.assertEqual(page.context.date, '2099-01-01')

    def test_stale_worker_result_is_ignored(self):
        page = SectorPage()
        try:
            page._finished('sectors', 9999, ([], []), 'old error')
            self.assertNotEqual(page.status.text(), 'old error')
        finally:
            page.cancel_pending()
            page.deleteLater()

    def test_sector_entry_cancels_previous_random_switch_intent(self):
        w = self.window
        w._random_switch_pending = True
        w._continuation_switch_pending = True
        w._independent_switch_pending = True
        w.sector_integration.show_sectors()
        self.assertFalse(w._random_switch_pending)
        self.assertFalse(w._continuation_switch_pending)
        self.assertFalse(w._independent_switch_pending)
        candidate = create_sample_engine()
        payload = (w._random_prefetch_generation, 'ordinary', w._random_prefetch_root, 'qfq', '', '',
                   w._random_training_forward_bars(), candidate.bars, candidate.current_index,
                   candidate.current_bar.code, 'test', {'qfq': candidate.bars}, '')
        with patch.object(w, '_consume_random_prefetch') as consume:
            w._finish_random_prefetch(payload)
        consume.assert_not_called()

    def test_same_stock_returns_to_existing_training_even_with_holdings(self):
        w = self.window
        w._activate_engine(create_sample_engine(), 'test')
        engine = w.engine
        w.sector_integration.show_sectors()
        request = TrainingRequest(engine.current_bar.code, w.sector_integration.page.context)
        with patch.object(w, '_has_position', return_value=True):
            self.assertTrue(w.sector_integration.open_training(request))
        self.assertIs(w.engine, engine)

    def test_numeric_sort_uses_numbers(self):
        self.assertLess(NumericItem('+2%', 2), NumericItem('+10%', 10))
        self.assertLess(NumericItem('—'), NumericItem('-10%', -10))

    def test_chart_boundary_keys_and_short_date_input(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        with patch.object(page, '_navigate_date') as navigate:
            QTest.keyClick(page.chart, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
            navigate.assert_called_with('first')
            QTest.keyClick(page.chart, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
            navigate.assert_called_with('last')
        page.context = MarketContext('', '2020-01-06', True)
        with patch.object(page, '_submit') as submit:
            page.date_edit.setText('201802')
            QTest.keyClick(page.date_edit, Qt.Key.Key_Return)
            self.assertEqual(submit.call_args.args[0], 'navigate')

    def test_sector_navigation_uses_unlocked_browsing_context(self):
        import threading
        from unittest.mock import Mock
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True, True)
        page.service = Mock()
        page._selected_stock = 'sz300617'
        page._sector_code = 'sh880501'
        page._history = create_sample_engine().bars[:2]
        with patch.object(page, '_submit') as submit:
            page._navigate_date('random')
            submit.call_args.args[1]()
        _query, context, _code, _boundary, _upper, _fallback = page.service.resolve_date.call_args.args
        self.assertEqual(context.date, '2020-01-06')
        self.assertFalse(context.locked)
        self.assertEqual(_code, 'sh880501')
        page._requests['navigate'] = (1, threading.Event())
        with patch.object(page, 'reload'):
            page._finished('navigate', 1, '2020-01-02', '')
        self.assertEqual(page.context.date, '2020-01-02')
        self.assertFalse(page.context.locked)

    def test_random_without_selection_uses_real_market_index_code(self):
        from unittest.mock import Mock
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True)
        page.service = Mock()
        with patch.object(page, '_submit') as submit:
            page._navigate_date('random')
            submit.call_args.args[1]()
        _query, _context, code, _boundary, _upper, _fallback = page.service.resolve_date.call_args.args
        self.assertEqual(code, 'sh000001')

    def test_random_ignores_training_date_limit(self):
        from unittest.mock import Mock
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True, True)
        page._training_date_limit = '2021-08-13'
        page.service = Mock()
        with patch.object(page, '_submit') as submit:
            page._navigate_date('random')
            submit.call_args.args[1]()
        _query, context, _code, _boundary, _upper, _fallback = page.service.resolve_date.call_args.args
        self.assertEqual(context.date, '2020-01-06')
        self.assertFalse(context.locked)

    def test_random_for_other_sector_uses_latest_minus_training_horizon(self):
        from unittest.mock import Mock
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True, True)
        page._sector_code = 'sh880501'
        page._training_stock_code = 'sz000001'
        page._random_horizon_bars = 120
        page.service = Mock()
        page.service.latest_date_with_forward_bars.return_value = '2026-04-01'
        with patch.object(page, '_is_current_training_sector', return_value=False), \
                patch.object(page, '_submit') as submit:
            page._navigate_date('random')
            submit.call_args.args[1]()
        _query, context, code, _boundary, upper, _fallback = page.service.resolve_date.call_args.args
        self.assertEqual(code, 'sh880501')
        self.assertEqual(context.date, '2020-01-06')
        self.assertFalse(context.locked)
        self.assertEqual(upper, '2026-04-01')

    def test_latest_without_selection_ignores_random_horizon_cap(self):
        from unittest.mock import Mock
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True)
        page._random_horizon_bars = 120
        page.service = Mock()
        with patch.object(page, '_submit') as submit:
            page._navigate_date('last')
            submit.call_args.args[1]()
        _query, _context, code, boundary, upper, _fallback = page.service.resolve_date.call_args.args
        self.assertEqual(code, 'sh000001')
        self.assertEqual(boundary, 'last')
        self.assertIsNone(upper)

    def test_first_bar_macd_renders_with_zero_indicator_range(self):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage, QPainter
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        engine = create_sample_engine()
        page._history = [engine.current_bar]
        page._draw()
        canvas = QImage(600, 160, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.black)
        painter = QPainter(canvas)
        try:
            page.chart._draw_macd(painter, QRectF(0, 0, 600, 160), 0)
        finally:
            painter.end()

    def test_chart_title_is_single_line_with_large_name_and_code(self):
        import threading
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2026-09-11', True)
        bar = create_sample_engine().current_bar
        bars = [bar, replace(bar, date='2026-09-12')]
        page._requests['chart'] = (1, threading.Event())
        page._finished('chart', 1, (bar.code, '6G概念', bars, '日K'), '')
        title = page.chart_title.text()
        self.assertNotIn('\n', title)
        self.assertIn('6G概念', title)
        self.assertIn(bar.code[2:], title)
        self.assertIn('font-weight:700', title)
        self.assertIn(bar.date, title)
        self.assertIn('2026-09-12', title)
        self.assertIn('共2根K线', title)
        page.set_dates_visible(False)
        hidden_title = page.chart_title.text()
        self.assertNotIn(bar.date, hidden_title)
        self.assertNotIn('2026-09-12', hidden_title)
        self.assertIn('共2根K线', hidden_title)

    def test_short_sector_history_keeps_zoom_width(self):
        import threading
        from unittest.mock import Mock

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2026-09-11', True)
        bars = create_sample_engine().bars[:70]
        page._window = 120
        spy = Mock()
        page.chart.set_data = spy
        page._requests['chart'] = (1, threading.Event())
        page._finished('chart', 1, ('sh880588', 'MLCC概念', bars, '日K'), '')
        # 历史不足时仍按用户设定的 120 根绘制：K 线保持正常宽度、右对齐，不被拉伸。
        self.assertEqual(page._window, 120)
        self.assertEqual(spy.call_args.args[5], 120)

    def test_zoom_survives_switching_sector_or_stock(self):
        import threading

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2026-09-11', True)
        bars = create_sample_engine().bars[:400]
        page._window = 200
        for serial, code in ((1, 'sh880588'), (2, 'sh880589'), (3, 'sz000001')):
            page._requests['chart'] = (serial, threading.Event())
            page._finished('chart', serial, (code, '名称', bars, '日K'), '')
            self.assertEqual(page._window, 200)
            self.assertEqual(page._offset, 0)

    def test_initial_auto_select_prefers_sector_with_enough_bars(self):
        import threading
        from stock_simulator.sectors.service import Quote
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2026-09-11', True)
        page._auto_select_first = True
        page._requests['sectors'] = (1, threading.Event())
        quotes = [
            Quote('sh880001', '少K线', price=1, change=1, bar_count=10),
            Quote('sh880002', '多K线', price=1, change=1, bar_count=80),
        ]
        with patch.object(page, '_restore_selection') as restore:
            page._finished('sectors', 1, (quotes, ()), '')
        restore.assert_called_once_with(page.sector_table, 'sh880002')

    def test_board_filter_checkboxes_hide_other_boards(self):
        from stock_simulator.sectors.service import Quote
        from stock_simulator.stock_info import stock_category

        self.assertEqual(stock_category('sh600000', '浦发银行'), 'main')
        self.assertEqual(stock_category('sz000001', '平安银行'), 'main')
        self.assertEqual(stock_category('sz300750', '宁德时代'), 'gem')
        self.assertEqual(stock_category('sh688111', '金山办公'), 'star')
        self.assertEqual(stock_category('bj920138', '杰瑞科技'), 'bj')
        self.assertEqual(stock_category('sz000001', 'ST某某'), 'st')

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        quotes = [
            Quote('sh600000', '沪主板', price=10.0, change=1.0),
            Quote('sz300750', '创业板', price=10.0, change=2.0),
            Quote('sh688111', '科创板', price=10.0, change=3.0),
            Quote('bj920138', '北交所', price=10.0, change=4.0),
            Quote('sz000004', 'ST某某', price=10.0, change=5.0),
        ]
        page._fill(page.stock_table, quotes, False)

        def visible():
            return {
                page.stock_table.item(row, 1).text()
                for row in range(page.stock_table.rowCount())
                if not page.stock_table.isRowHidden(row)
            }

        self.assertEqual(visible(), {'600000', '300750', '688111', '920138', '000004'})
        page.board_filters['gem'].setChecked(False)
        self.assertEqual(visible(), {'600000', '688111', '920138', '000004'})
        page.board_filters['st'].setChecked(False)
        self.assertEqual(visible(), {'600000', '688111', '920138'})
        page.board_filters['main'].setChecked(False)
        page.board_filters['star'].setChecked(False)
        self.assertEqual(visible(), {'920138'})
        self.assertEqual(page.board_filter_keys(), ['bj'])

    def test_switching_sector_keeps_selected_member_pending_restore(self):
        from unittest.mock import Mock

        from PySide6.QtWidgets import QTableWidgetItem

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.service = Mock()
        page.context = MarketContext('', '2026-09-11', True)
        code_item = QTableWidgetItem('1')
        code_item.setData(Qt.ItemDataRole.UserRole, 'sh880302')
        page.sector_table.setRowCount(1)
        page.sector_table.setItem(0, 0, code_item)
        page.sector_table.setItem(0, 1, QTableWidgetItem('电力'))
        with patch.object(page, '_load_chart'), patch.object(page, '_submit'):
            page.sector_table.selectRow(0)
            page._selected_stock = 'sz000001'
            page._select_sector()
        # 记住原个股，等成员返回时若仍在新板块成员里就重新选中
        self.assertEqual(page._restore_stock, 'sz000001')
        self.assertEqual(page._selected_stock, '')

    def test_header_sort_scrolls_table_back_to_top(self):
        from PySide6.QtWidgets import QTableWidgetItem

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.resize(600, 300)
        page.sector_table.resize(400, 150)
        page.sector_table.setRowCount(60)
        for row in range(60):
            page.sector_table.setItem(row, 0, QTableWidgetItem(str(60 - row)))
            page.sector_table.setItem(row, 1, QTableWidgetItem('板块%d' % row))
        page.show()
        self.app.processEvents()
        bar = page.sector_table.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(40)
        page._header_clicked(page.sector_table, 1)
        self.assertEqual(bar.value(), 0)

    def test_double_click_category_scrolls_sector_list_to_top(self):
        from PySide6.QtWidgets import QTableWidgetItem

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.resize(600, 300)
        page.sector_table.resize(400, 150)
        page.sector_table.setRowCount(60)
        for row in range(60):
            page.sector_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        page.show()
        self.app.processEvents()
        bar = page.sector_table.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)

        bar.setValue(40)
        QTest.mouseDClick(page.category_buttons['concept'], Qt.MouseButton.LeftButton)
        self.assertEqual(bar.value(), 0)

        bar.setValue(40)
        page.level_tabs.tabBarDoubleClicked.emit(0)
        self.assertEqual(bar.value(), 0)

    def test_favorites_follow_saved_configuration(self):
        import tempfile
        from pathlib import Path

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.apply_configured_favorites(['sh881901'], ['sz000001'])
        self.assertEqual(page.favorite_codes(), (['sh881901'], ['sz000001']))

        # 本地已有收藏文件时，以文件为准，不再被旧配置覆盖。
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        cached = SectorPage(cache_dir=Path(temporary.name))
        self.addCleanup(cached.deleteLater)
        cached._favorite_sectors = {'sh880301'}
        cached._save_favorites()
        cached.apply_configured_favorites(['sh881901'], ['sz000001'])
        self.assertEqual(cached.favorite_codes(), (['sh880301'], []))

    def test_index_click_toggles_favorite_and_pins_rows(self):
        import tempfile
        from pathlib import Path

        from stock_simulator.sectors.service import Quote

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        cache = Path(temporary.name)
        page = SectorPage(cache_dir=cache)
        self.addCleanup(page.deleteLater)
        quotes = [
            Quote('sh880301', '煤炭', change=1.0),
            Quote('sh880302', '石油', change=2.0),
            Quote('sh880303', '银行', change=3.0),
        ]
        page._fill(page.sector_table, quotes, True)

        def order():
            return [
                page.sector_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                for row in range(page.sector_table.rowCount())
            ]

        self.assertEqual(order(), ['sh880303', 'sh880302', 'sh880301'])
        page._toggle_favorite(page.sector_table, page.sector_table.item(2, 0))
        self.assertEqual(order(), ['sh880301', 'sh880303', 'sh880302'])
        self.assertEqual(page.sector_table.item(0, 0).text(), '★1')
        self.assertIn('sh880301', page._favorite_sectors)
        page._toggle_favorite(page.sector_table, page.sector_table.item(0, 0))
        self.assertEqual(order(), ['sh880303', 'sh880302', 'sh880301'])
        self.assertEqual(page.sector_table.item(2, 0).text(), '3')
        self.assertNotIn('sh880301', page._favorite_sectors)

        page._favorite_stocks.add('sz000001')
        page._save_favorites()
        reloaded = SectorPage(cache_dir=cache)
        self.addCleanup(reloaded.deleteLater)
        self.assertIn('sz000001', reloaded._favorite_stocks)

    def test_today_style_sector_skips_index_chart(self):
        from unittest.mock import Mock

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.service = Mock()
        page.service.is_virtual_style.return_value = True
        page.context = MarketContext('', '2026-09-11', True)
        with patch.object(page, '_submit') as submit:
            page._load_chart('sh881901', '今日涨停')
            submit.assert_not_called()
        self.assertIn('今日涨停', page.chart_title.text())
        self.assertIn('最新交易日', page.status.text())

    def test_member_name_shows_limit_up_badge_only_from_two_boards(self):
        from stock_simulator.sectors.page import LIMIT_UP_BADGE_ROLE
        from stock_simulator.sectors.service import Quote

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        quotes = [
            Quote('sz000001', '连板股', price=11.0, change=10.0, limit_up_streak=2),
            Quote('sz000002', '首板股', price=10.0, change=10.0, limit_up_streak=1),
        ]
        page._fill(page.stock_table, quotes, False)
        cells = {
            page.stock_table.item(row, 1).text(): page.stock_table.item(row, 2)
            for row in range(page.stock_table.rowCount())
        }
        # 名称保持原样，连板角标单独放在自定义角色里由名称列自绘（红字、放大）。
        self.assertEqual(cells['000001'].text(), '连板股')
        self.assertEqual(cells['000001'].data(LIMIT_UP_BADGE_ROLE), '²')
        self.assertIn('2连板', cells['000001'].toolTip())
        self.assertEqual(cells['000002'].text(), '首板股')
        self.assertIsNone(cells['000002'].data(LIMIT_UP_BADGE_ROLE))

    def test_enter_key_moves_selection_down_like_arrow_key(self):
        from PySide6.QtWidgets import QTableWidgetItem

        page = SectorPage()
        self.addCleanup(page.deleteLater)
        for table in (page.sector_table, page.stock_table):
            table.blockSignals(True)
            table.setRowCount(3)
            for row in range(3):
                code_item = QTableWidgetItem(str(row + 1))
                code_item.setData(Qt.ItemDataRole.UserRole, 'sh8803%02d' % row)
                table.setItem(row, 0, code_item)
                table.setItem(row, 1, QTableWidgetItem('名称%d' % row))
            table.selectRow(0)
            QTest.keyClick(table, Qt.Key.Key_Return)
            self.assertEqual(table.currentRow(), 1)
            QTest.keyClick(table, Qt.Key.Key_Enter)
            self.assertEqual(table.currentRow(), 2)
            # 到最后一行的回车不再继续下移。
            QTest.keyClick(table, Qt.Key.Key_Return)
            self.assertEqual(table.currentRow(), 2)

    def test_ten_day_columns_sort_without_resizing_and_align_values(self):
        from stock_simulator.sectors.service import Quote
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        quotes = [Quote('sh600001', '甲', change10=2), Quote('sh600002', '乙', change10=10)]
        for table, sectors, column in ((page.sector_table, True, 4), (page.stock_table, False, 7)):
            page._fill(table, quotes, sectors)
            widths = [table.columnWidth(i) for i in range(table.columnCount())]
            table.sortItems(column, Qt.SortOrder.DescendingOrder)
            self.assertEqual(table.item(0, column).value, 10)
            self.assertEqual(table.item(0, column).textAlignment(), Qt.AlignmentFlag.AlignCenter)
            self.assertEqual([table.columnWidth(i) for i in range(table.columnCount())], widths)
            table.sortItems(column, Qt.SortOrder.AscendingOrder)
            self.assertEqual(table.item(0, column).value, 2)
            self.assertEqual([table.columnWidth(i) for i in range(table.columnCount())], widths)

    def test_stock_table_lists_today_turnover_and_keeps_industry_column(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        headers = [
            page.stock_table.horizontalHeaderItem(column).text()
            for column in range(page.stock_table.columnCount())
        ]
        self.assertEqual(headers[0], '序号')
        self.assertIn('所属行业', headers)
        self.assertIn('当日换手', headers)
        self.assertNotIn('数据状态', headers)
        self.assertEqual(headers.index('当日换手') + 1, headers.index('5日换手'))

    def test_save_current_config_persists_window_and_layout(self):
        import tempfile
        from pathlib import Path
        from stock_simulator import config
        from stock_simulator.config import load_settings
        w = self.window
        w.sector_integration.show_sectors()
        page = w.sector_integration.page
        w.main_splitter.setSizes([1000, 500])
        page.sector_splitter.setSizes([500, 800])
        page.sector_chart_splitter.setSizes([500, 300])
        page.sector_table.setColumnWidth(0, 150)
        page.stock_table.setColumnWidth(0, 96)
        page.chart.sub_pane_indicators = ["volume", "macd", "kdj"]
        page.chart.pane_height_ratios = [0.5, 0.2, 0.15, 0.15]
        page._window = 55
        expected = {
            "window": (w.width(), w.height()),
            "main": list(w.main_splitter.sizes()),
            "sector": list(page.sector_splitter.sizes()),
            "chart": list(page.sector_chart_splitter.sizes()),
            "sector_widths": [page.sector_table.columnWidth(i) for i in range(page.sector_table.columnCount())],
            "stock_widths": [page.stock_table.columnWidth(i) for i in range(page.stock_table.columnCount())],
        }
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(config, "CONFIG_PATH", Path(temporary) / "settings.json"):
                w.save_current_config()
                saved = load_settings()
        self.assertEqual((saved.window_width, saved.window_height), expected["window"])
        self.assertEqual(saved.main_splitter_sizes, expected["main"])
        self.assertEqual(saved.sector_splitter_sizes, expected["sector"])
        self.assertEqual(saved.sector_chart_splitter_sizes, expected["chart"])
        self.assertEqual(saved.sector_table_widths, expected["sector_widths"])
        self.assertEqual(saved.stock_table_widths, expected["stock_widths"])
        self.assertEqual(saved.sector_sub_pane_indicators, ["volume", "macd", "kdj"])
        self.assertEqual(saved.sector_pane_height_ratios, [0.5, 0.2, 0.15, 0.15])
        self.assertEqual(saved.sector_chart_window_size, 55)

    def test_member_rows_without_market_numbers_are_hidden(self):
        import threading
        from stock_simulator.sectors.service import Quote
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True)
        page._requests['members'] = (1, threading.Event())
        page._finished('members', 1, [
            Quote('sz000001', '有效', price=10.0, change=1.0),
            Quote('sz000002', '无行情', status='截止日之前无行情'),
        ], '')
        self.assertEqual(page.stock_table.rowCount(), 1)
        self.assertEqual(page.stock_table.item(0, 1).text(), '000001')

    def test_actual_header_click_sorts_every_column_both_directions(self):
        from stock_simulator.sectors.service import Quote
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        quotes = [Quote('sh60000'+str(n), name, price=n, change=n, change5=n,
                        change10=n, change20=n, amount=n, status=name)
                  for n, name in ((3, 'C'), (1, 'A'), (2, 'B'))]
        for table, sectors in ((page.sector_table, True), (page.stock_table, False)):
            table.setParent(None)
            self.addCleanup(table.deleteLater)
            page._fill(table, quotes, sectors)
            table.resize(1500, 250)
            table.show()
            self.app.processEvents()
            header = table.horizontalHeader()
            widths = [table.columnWidth(i) for i in range(table.columnCount())]
            for column in range(table.columnCount()):
                for _ in range(2):
                    previous_order = header.sortIndicatorOrder() if header.sortIndicatorSection() == column else None
                    QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(
                        header.sectionViewportPosition(column) + header.sectionSize(column)//2, header.height()//2))
                    self.assertEqual(header.sortIndicatorSection(), column)
                    if previous_order is not None:
                        self.assertNotEqual(header.sortIndicatorOrder(), previous_order)
                    items = [table.item(row, column) for row in range(table.rowCount())]
                    values = [item.value if isinstance(item, NumericItem) else item.text() for item in items]
                    sortable = [value if value is not None else float('-inf') for value in values]
                    self.assertEqual(
                        sortable,
                        sorted(sortable, reverse=header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder),
                    )
                    self.assertEqual([table.columnWidth(i) for i in range(table.columnCount())], widths)
            table.hide()

    def test_sector_subpane_menu_add_remove_and_bounds_are_independent(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        original = list(self.window.kline_widget.sub_pane_indicators)

        def trigger(text):
            menu = page.chart._build_sub_pane_count_menu()
            try:
                next(action for action in menu.actions() if action.text() == text).trigger()
            finally:
                menu.deleteLater()

        trigger('增加一个副图')
        self.assertEqual(len(page.chart.sub_pane_indicators), 3)
        trigger('增加一个副图')
        self.assertEqual(len(page.chart.sub_pane_indicators), 4)
        menu = page.chart._build_sub_pane_count_menu()
        self.assertNotIn('增加一个副图', [action.text() for action in menu.actions()])
        menu.deleteLater()
        for expected in (3, 2, 1):
            trigger('减少一个副图')
            self.assertEqual(len(page.chart.sub_pane_indicators), expected)
        menu = page.chart._build_sub_pane_count_menu()
        self.assertNotIn('减少一个副图', [action.text() for action in menu.actions()])
        menu.deleteLater()
        page._draw()
        self.assertEqual(len(page.chart.sub_pane_indicators), 1)
        self.assertEqual(self.window.kline_widget.sub_pane_indicators, original)

    def test_advance_uses_viewed_date_after_panning(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        engine = create_sample_engine()
        page.context = MarketContext('', '2099-01-01', True)
        page._history = [engine.current_bar, replace(engine.current_bar, date='2099-01-01')]
        page._offset = 1
        from unittest.mock import Mock
        page.service = Mock()
        with patch.object(page, '_submit') as submit:
            page._advance()
            submit.call_args.args[1]()
        page.service.next_date.assert_called_once_with(engine.current_bar.date, 'sh000001')

    def test_stock_entry_always_requests_industry_location(self):
        w = self.window
        engine = create_sample_engine()
        w._activate_engine(engine, 'test')
        from types import SimpleNamespace
        code = 'sz000630'
        with patch.object(w.sector_integration, 'market_context', return_value=MarketContext('', '2020-01-06', True)):
            original = w.engine
            w.engine = SimpleNamespace(current_bar=SimpleNamespace(code=code))
            try:
                with patch.object(SectorPage, 'focus_stock') as focus:
                    w.sector_integration.show_sectors()
                    focus.assert_called_once_with(code)
                    w.sector_integration.show_stock()
                    w.sector_integration.show_sectors()
                    self.assertEqual(focus.call_count, 2)
            finally:
                w.engine = original

    def test_return_to_loaded_stock_does_not_reload(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.service = object()
        page.context = page._loaded_context = MarketContext('', '2020-01-06', True)
        page._selected_stock = page._chart_code = 'sz000630'
        page._history = [create_sample_engine().current_bar]
        with patch.object(page, '_submit') as submit:
            page.focus_stock('sz000630')
            submit.assert_not_called()

    def test_top_inputs_belong_only_to_left_chart_column(self):
        w = self.window
        self.assertIs(w.simulation_settings_panel.parentWidget(), w.main_splitter.widget(0))
        # 个股页最上面一行 = 标签栏 + 三个输入框，标签栏横跨图表列。
        self.assertEqual(w.chart_panel_layout.indexOf(w.sector_integration.nav), 0)
        self.assertIs(w.top_bar_fields.parentWidget(), w.sector_integration.nav)
        self.assertGreater(w.sector_integration.nav.layout().indexOf(w.top_bar_fields), 0)
        self.assertFalse(w.simulation_settings_panel.isVisible())

    def test_default_concept_and_double_space_current_sector_overlay(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        self.assertEqual(page._category, 'concept')
        page.context = MarketContext('', '2020-01-06', False)
        bar = replace(create_sample_engine().current_bar, date='2020-01-06')
        page._history = [bar]
        page._chart_code = 'sz000630'
        page._sector_code = 'sh880550'
        page._index_code = 'sh880550'
        page._index_bars = [replace(bar, code='sh880550'), replace(bar, code='sh880550', date='2020-01-07')]
        QTest.keyClick(page.chart, Qt.Key.Key_Space)
        QTest.keyClick(page.chart, Qt.Key.Key_Space)
        self.assertTrue(page._index_enabled)
        self.assertEqual(len(page.chart.index_overlay_bars), 1)
        self.assertEqual(page.chart.index_overlay_bars[0].code, 'sh880550')
        self.assertEqual(page.chart.index_overlay_bars[0].high, bar.open)
        QTest.keyClick(page.stock_table, Qt.Key.Key_Space)
        QTest.keyClick(page.stock_table, Qt.Key.Key_Space)
        self.assertFalse(page._index_enabled)
        self.assertFalse(page.chart.index_overlay_bars)

    def test_sector_help_lists_today_features(self):
        with patch('stock_simulator.app.QMessageBox.information') as message:
            self.window._show_sector_help()
        text = message.call_args.args[2]
        for word in ('概念', '风格', '前复权', '当前所属板块指数', '201802', '10日'):
            self.assertIn(word, text)

    def test_industry_tabs_reselect_correctly_from_concept(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        with patch.object(page, 'reload'):
            page._level_changed(1)
            self.assertEqual(page.level_tabs.currentIndex(), 1)
            self.assertIn('font-weight: bold', page.level_tabs.styleSheet())
            page._choose_category('concept')
            page._level_changed(0)
            self.assertEqual(page.level_tabs.currentIndex(), 0)
            self.assertEqual(page._category, 'industry')
            self.assertFalse(page.category_buttons['concept'].isChecked())
            self.assertFalse(page.category_buttons['style'].isChecked())

    def test_date_privacy_links_training_and_masks_refreshed_labels(self):
        from PySide6.QtWidgets import QLineEdit
        w = self.window
        w.sector_integration.show_sectors()
        page = w.sector_integration.page
        page._request_visibility(False)
        self.assertFalse(w.identity_toggle.isChecked())
        self.assertFalse(page.chart.show_time_marks)
        self.assertEqual(page.date_edit.echoMode(), QLineEdit.EchoMode.Password)
        page.chart_title.setText('测试 日K\n可见历史 2020-01-02 至 2020-01-06 · 3 根')
        page.status.setText('当日无行情 2020-01-06')
        self.assertNotIn('2020', page.chart_title.text())
        self.assertNotIn('2020', page.status.text())
        w.identity_toggle.setChecked(True)
        w.save_display_preferences()
        self.assertTrue(page.chart.show_time_marks)
        self.assertEqual(page.date_edit.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertIn('2020-01-06', page.status.text())

    def test_random_button_requests_random_navigation(self):
        page = SectorPage()
        self.addCleanup(page.close)
        with patch.object(page, '_navigate_date') as navigate:
            page.random_date.click()
            navigate.assert_called_once_with('random')
        self.assertFalse(page.date_visibility.icon().isNull())

    def test_explicit_date_changes_entire_locked_page_context(self):
        import threading
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2021-08-13', True, True)
        page._requests['navigate'] = (100, threading.Event())
        with patch.object(page, 'reload') as reload:
            page._finished('navigate', 100, '2020-08-18', '')
            self.assertEqual(page.context.date, '2020-08-18')
            self.assertFalse(page.context.locked)
            reload.assert_called_once()

    def test_loading_older_history_keeps_selected_date(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        bar = create_sample_engine().current_bar
        page.context = MarketContext('', '2099-01-01', True)
        page.date_edit.setText(page.context.date)
        page._history = [bar]
        page._draw()
        self.assertEqual(page.date_edit.text(), '2099-01-01')

    def test_return_to_training_date_uses_training_limit(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True)
        page._training_date_limit = '2020-01-10'
        with patch.object(page, 'reload'):
            page.return_to_training_date()
        self.assertEqual(page.context.date, '2020-01-10')
        self.assertTrue(page.context.locked)

    def test_return_to_training_date_reloads_when_already_there(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True)
        with patch.object(page, 'reload') as reload:
            page.return_to_training_date()
        reload.assert_called_once()
        self.assertIn('当前已是模拟日期', page.status.text())

    def test_return_training_button_enabled_when_host_engine_exists(self):
        w = self.window
        engine = create_sample_engine()
        w.engine = engine
        w.training_mode = False
        w.sector_integration.show_sectors()
        self.assertTrue(w.sector_integration.page.return_training_btn.isEnabled())

    def test_host_refresh_does_not_reset_independent_sector_date(self):
        w = self.window
        engine = create_sample_engine()
        w._activate_engine(engine, 'test')
        w.sector_integration.show_sectors()
        page = w.sector_integration.page
        with patch.object(page, 'reload'):
            page.set_context(replace(page.context, date='2015-01-05', locked=False))
            w.sector_integration.sync()
            self.assertEqual(page.context.date, '2015-01-05')

    def test_sector_menus_are_enabled_and_zoom_targets_visible_chart(self):
        w = self.window
        w.sector_integration.show_sectors()
        page = w.sector_integration.page
        page._history = [create_sample_engine().current_bar]
        w._sync_menu_actions()
        self.assertTrue(all(a.isEnabled() for a in w.menuBar().actions()))
        with patch.object(page, 'zoom_in') as sector_zoom, patch.object(w, 'zoom_in') as stock_zoom:
            w.view_zoom_in_action.trigger()
            sector_zoom.assert_called_once()
            stock_zoom.assert_not_called()
        w.sector_integration.show_stock()
        with patch.object(w, 'zoom_in') as stock_zoom:
            w.view_zoom_in_action.setEnabled(True)
            w.view_zoom_in_action.trigger()
            stock_zoom.assert_called_once()

    def test_sector_menu_advance_and_draw_do_not_touch_hidden_account(self):
        w = self.window
        w.sector_integration.show_sectors()
        page = w.sector_integration.page
        page._history = [create_sample_engine().current_bar]
        w._sync_menu_actions()
        with patch.object(page, '_advance') as advance, patch.object(w, 'advance_playback') as hidden:
            w.simulation_advance_action.trigger()
            advance.assert_called_once()
            hidden.assert_not_called()
        with patch.object(page.chart, 'add_user_line_at_center') as draw:
            w.drawing_add_line_action.trigger()
            draw.assert_called_once()

    def test_initial_sector_load_waits_for_click_and_hides_main_overlay(self):
        import threading
        from stock_simulator.sectors.service import Quote
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        self.assertEqual(page.chart.main_overlay_mode, 'none')
        page.context = MarketContext('', '2020-01-06', True)
        page._requests['sectors'] = (1, threading.Event())
        with patch.object(page, '_restore_selection') as restore:
            page._finished('sectors', 1, ([Quote('sh880301', '煤炭', change=1)], ()), '')
        restore.assert_not_called()
        self.assertEqual(page.sector_table.currentRow(), -1)
        self.assertEqual(page.chart_title.text(), '选择行业，查看日K')
        self.assertEqual(page.stock_table.rowCount(), 0)

    def test_blank_table_or_chart_click_clears_sector_selection(self):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True)
        page._sector_code = 'sh880501'
        page._selected_stock = 'sz000001'
        page.resize(900, 600)
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        with patch.object(page, '_clear_focus_frame') as clear:
            page.eventFilter(page.sector_table.viewport(), event)
            clear.assert_called_once()
        with patch.object(page, '_clear_focus_frame') as clear:
            page.eventFilter(page.chart, event)
            clear.assert_called_once()
        self.assertEqual(page._sector_code, 'sh880501')
        self.assertEqual(page._selected_stock, 'sz000001')

    def test_sector_reload_with_existing_selection_restores_first_load(self):
        import threading
        from stock_simulator.sectors.service import Quote
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page.context = MarketContext('', '2020-01-06', True)
        page._sector_code = 'sh880301'
        page._requests['sectors'] = (1, threading.Event())
        with patch.object(page, '_restore_selection') as restore:
            page._finished('sectors', 1, ([Quote('sh880301', '煤炭', change=1)], ()), '')
        restore.assert_called_once()

    def test_sector_zoom_limits_match_stock_chart_range(self):
        page = SectorPage()
        self.addCleanup(page.deleteLater)
        page._history = create_sample_engine().bars
        for _ in range(20):
            page.zoom_out()
        self.assertEqual(page._window, 750)
        for _ in range(20):
            page.zoom_in()
        self.assertEqual(page._window, 55)
        page.reset_zoom()
        self.assertEqual(page._window, 70)
