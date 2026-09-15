from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from stock_simulator.app import (
    MainWindow,
    TRAINING_MODE_CONTINUOUS,
    TRAINING_MODE_INDEPENDENT,
    TRAINING_MODE_SINGLE,
)
from stock_simulator.engine import DailySimulationEngine
from stock_simulator.kline_widget import KLineWidget
from stock_simulator.models import DailyBar, TradeNode
from stock_simulator.test_trade import (
    EXIT_TEST_TRADE_MENU_TEXT,
    TEST_TRADE_MENU_TEXT,
    menu_presentation,
    point_hits_candle_body,
    test_window_anchor,
)


class _GestureParent:
    def __init__(self) -> None:
        self.started_dates: list[str] = []

    def start_test_trade_from_bar(self, date: str) -> None:
        self.started_dates.append(date)


class TestTradeRulesTests(unittest.TestCase):
    def test_inactive_menu_is_grey_and_uses_entry_label(self) -> None:
        self.assertEqual(menu_presentation(False), (TEST_TRADE_MENU_TEXT, False))

    def test_active_menu_is_clickable_and_uses_exit_label(self) -> None:
        self.assertEqual(menu_presentation(True), (EXIT_TEST_TRADE_MENU_TEXT, True))

    def test_test_window_does_not_move_when_selected_bar_was_at_right_edge(self) -> None:
        anchor, future_slots = test_window_anchor(
            selected_index=50,
            previous_anchor=50,
            bar_count=200,
            window_size=60,
        )
        self.assertEqual(anchor, 50)
        self.assertEqual(future_slots, 0)

    def test_test_window_preserves_more_existing_future_space(self) -> None:
        anchor, future_slots = test_window_anchor(
            selected_index=50,
            previous_anchor=75,
            bar_count=200,
            window_size=60,
        )
        self.assertEqual(anchor, 75)
        self.assertEqual(future_slots, 25)

    def test_body_hit_accepts_body_and_rejects_wick_only_area(self) -> None:
        self.assertTrue(
            point_hits_candle_body(
                point_x=102,
                point_y=55,
                candle_x=100,
                candle_width=10,
                body_y_open=40,
                body_y_close=70,
            )
        )
        self.assertFalse(
            point_hits_candle_body(
                point_x=102,
                point_y=25,
                candle_x=100,
                candle_width=10,
                body_y_open=40,
                body_y_close=70,
            )
        )


class TestTradeGestureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_right_double_click_on_candle_body_requests_test_trade_start(self) -> None:
        parent = _GestureParent()
        widget = KLineWidget(parent)
        widget.resize(800, 600)
        bars = [
            DailyBar("sh600000", f"2024-01-{day:02d}", 10 + day, 12 + day, 9 + day, 11 + day, 1.0, 100)
            for day in range(1, 6)
        ]
        widget.set_data(
            all_bars=bars,
            visible_bars=bars,
            trades=[],
            current_index=4,
            pan_offset=0,
            window_size=5,
            reveal_current_full=True,
        )
        widget.show()
        self.application.processEvents()
        chart_rect, _pane_rects = widget._layout_areas()
        slot = 2
        low, high = widget._price_range()
        x = widget._x_for_slot(chart_rect, slot)
        y_open = widget._price_y(chart_rect, bars[slot].open, low, high)
        y_close = widget._price_y(chart_rect, bars[slot].close, low, high)
        body_center = QPoint(round(x), round((y_open + y_close) / 2))

        QTest.mouseDClick(widget, Qt.MouseButton.RightButton, pos=body_center)
        self.application.processEvents()

        self.assertEqual(parent.started_dates, ["2024-01-03"])
        widget.close()


class TestTradeApplicationTests(unittest.TestCase):
    def test_repeated_test_entry_preserves_viewport(self) -> None:
        with (
            patch("stock_simulator.app.load_document", return_value=None),
            patch.object(MainWindow, "_start_adjust_initialize"),
            patch.object(MainWindow, "_load_startup_market"),
        ):
            window = MainWindow()
        try:
            bars = self._bars(100)
            window._activate_browse_engine(bars, "测试股票", "浏览中")
            window.chart_window_size = 30
            window.viewed_bar_index = 70
            window.pan_offset = len(bars) - 1 - 70
            window._refresh(persist=False)
            before = [bar.date for bar in window.kline_widget.bars]
            self.assertTrue(window.start_test_trade_from_bar(bars[68].date))
            original_context = window._test_trade_browse_context
            for index in (65, 69, 68):
                self.assertTrue(window.start_test_trade_from_bar(bars[index].date))
                self.assertEqual(window.engine.current_index, index)
                self.assertIs(window._test_trade_browse_context, original_context)
                self.assertEqual(window.viewed_bar_index, 70)
                self.assertEqual(window.chart_window_size, 30)
                self.assertEqual([bar.date for bar in window.kline_widget.bars], before)
            engine = window.engine
            self.assertFalse(window.start_test_trade_from_bar('invalid'))
            self.assertIs(window.engine, engine)
            self.assertTrue(engine.buy_quantity(0, TradeNode.OPEN, 100).accepted)
            self.assertFalse(window.start_test_trade_from_bar(bars[65].date))
            self.assertIs(window.engine, engine)
            engine.next_day()
            self.assertTrue(engine.sell(0, TradeNode.OPEN, quantity=100).accepted)
            self.assertFalse(window.start_test_trade_from_bar(bars[65].date))
            self.assertIs(window.engine, engine)
            window.exit_test_trade_mode(update_status=False)
            self.assertEqual(window.viewed_bar_index, 70)
        finally:
            window._persist_timer.stop()
            window.hide()
            window.deleteLater()
            self.application.processEvents()

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    @staticmethod
    def _bars(count: int = 40) -> list[DailyBar]:
        return [
            DailyBar(
                "sh600000",
                f"2024-{1 + (index // 28):02d}-{1 + (index % 28):02d}",
                10.0 + index * 0.1,
                10.8 + index * 0.1,
                9.6 + index * 0.1,
                10.4 + index * 0.1,
                1_000_000.0,
                100_000,
            )
            for index in range(count)
        ]

    def test_windowed_market_strip_height_stays_stable_when_text_wraps(self) -> None:
        with (
            patch("stock_simulator.app.load_document", return_value=None),
            patch.object(MainWindow, "_start_adjust_initialize"),
            patch.object(MainWindow, "_load_startup_market"),
        ):
            window = MainWindow()
        try:
            window.resize(1090, 710)
            window.show()
            self.application.processEvents()
            self.assertFalse(window.isMaximized())
            self.assertFalse(window.isFullScreen())
            self.assertEqual(window._layout_density, "low")

            long_values = {
                name: ("站上5、10、20、60日线" if name == "均线位置" else "3009 / 2395", "neutral")
                for name in window.index_market_labels
            }
            window._apply_metric_values(window.index_market_labels, long_values)
            self.application.processEvents()
            long_heights = {label.height() for label in window.index_market_labels.values()}

            short_values = {name: ("--", "neutral") for name in window.index_market_labels}
            window._apply_metric_values(window.index_market_labels, short_values)
            self.application.processEvents()
            short_heights = {label.height() for label in window.index_market_labels.values()}

            self.assertEqual(short_heights, long_heights)
        finally:
            window.hide()
            window.deleteLater()
            self.application.processEvents()

    def test_help_menu_explains_test_trade_usage_and_conditions(self) -> None:
        window = MainWindow()
        try:
            action = next(
                (item for item in window.help_menu.actions() if item.text() == "测试交易模式说明"),
                None,
            )
            self.assertIsNotNone(action)
            with patch("stock_simulator.app.QMessageBox.information") as information:
                action.trigger()
            help_text = information.call_args.args[2]
            for phrase in (
                "个股行情浏览模式",
                "股票代码或拼音首字母",
                "K线实体",
                "快速连续右击",
                "未来K线保持可见",
                "T+1",
                "清空全部",
                "不会保存",
            ):
                self.assertIn(phrase, help_text)
        finally:
            window.hide()
            window.deleteLater()
            self.application.processEvents()

    def test_start_and_menu_exit_restore_browse_session(self) -> None:
        window = MainWindow()
        bars = self._bars()
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        browse_engine = window.engine
        window.viewed_bar_index = 30
        window.pan_offset = len(bars) - 1 - 30
        formal_return_context = {"sentinel": "formal-session"}
        window._return_to_trading_context = formal_return_context

        self.assertEqual(window.simulation_test_trade_action.text(), TEST_TRADE_MENU_TEXT)
        self.assertFalse(window.simulation_test_trade_action.isEnabled())

        started = window.start_test_trade_from_bar(bars[20].date)

        self.assertTrue(started)
        self.assertTrue(window.test_trade_active)
        self.assertIsNot(window.engine, browse_engine)
        self.assertEqual(window.engine.current_index, 20)
        self.assertEqual(window.simulation_test_trade_action.text(), EXIT_TEST_TRADE_MENU_TEXT)
        self.assertTrue(window.simulation_test_trade_action.isEnabled())
        self.assertTrue(window.playback_nav_box.isVisibleTo(window))
        self.assertTrue(window.advance_phase_btn.test_mode_active)
        self.assertGreater(window.kline_widget.bars[-1].date, window.engine.current_bar.date)

        window.simulation_test_trade_action.trigger()

        self.assertFalse(window.test_trade_active)
        self.assertIs(window.engine, browse_engine)
        self.assertIs(window._return_to_trading_context, formal_return_context)
        self.assertEqual(window.viewed_bar_index, 30)
        self.assertEqual(window.simulation_test_trade_action.text(), TEST_TRADE_MENU_TEXT)
        self.assertFalse(window.simulation_test_trade_action.isEnabled())
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_direct_stock_browse_hides_training_mode_panel(self) -> None:
        with (
            patch("stock_simulator.app.load_document", return_value=None),
            patch.object(MainWindow, "_start_adjust_initialize"),
        ):
            window = MainWindow()
        window.training_mode = False
        window._return_to_trading_context = None
        window.round_records = []
        window._activate_browse_engine(self._bars(), "测试股票", "浏览中")
        window.show()
        self.application.processEvents()

        self.assertTrue(
            window.round_log_box.isHidden(),
            f"training={window.training_mode}, records={len(window.round_records)}, "
            f"return_context={window._return_to_trading_context is not None}, "
            f"round_mode={window._uses_round_records()}",
        )
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_test_trade_keeps_training_mode_panel_hidden(self) -> None:
        with (
            patch("stock_simulator.app.load_document", return_value=None),
            patch.object(MainWindow, "_start_adjust_initialize"),
        ):
            window = MainWindow()
        bars = self._bars()
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        self.assertTrue(window.start_test_trade_from_bar(bars[10].date))
        window.show()
        self.application.processEvents()

        self.assertTrue(window.continuous_btn.isHidden())
        self.assertTrue(window.round_log_box.isHidden())
        window.exit_test_trade_mode(update_status=False)
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_browse_with_return_context_keeps_return_controls_but_hides_mode_status(self) -> None:
        with (
            patch("stock_simulator.app.load_document", return_value=None),
            patch.object(MainWindow, "_start_adjust_initialize"),
        ):
            window = MainWindow()
        bars = self._bars()
        formal_engine = DailySimulationEngine(
            bars=bars,
            initial_cash=100_000,
            slot_count=window.settings.slot_count,
            start_index=5,
        )
        formal_engine.start()
        window.engine = formal_engine
        window.training_mode = True
        window.training_mode_kind = TRAINING_MODE_INDEPENDENT
        window.continuous_compound_mode = False

        window._activate_browse_engine(bars, "测试股票", "浏览中")
        window.show()
        self.application.processEvents()

        self.assertIsNotNone(window._return_to_trading_context)
        self.assertTrue(window.continuous_btn.isHidden())
        self.assertFalse(window.round_log_box.isHidden())
        self.assertFalse(window.return_trade_btn.isHidden())
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_current_kline_phase_marker_changes_label_and_price_direction_color(self) -> None:
        window = MainWindow()
        bars = self._bars()
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        self.assertTrue(window.start_test_trade_from_bar(bars[10].date))

        open_text, open_color = window.kline_widget._current_phase_marker_spec()
        self.assertEqual(open_text, "开")
        self.assertEqual(open_color, window.kline_widget.palette.down)

        window.show_close_phase()

        close_text, close_color = window.kline_widget._current_phase_marker_spec()
        self.assertEqual(close_text, "收")
        self.assertEqual(close_color, window.kline_widget.palette.up)
        window.exit_test_trade_mode(update_status=False)
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_playback_button_badge_follows_formal_mode_and_test_override(self) -> None:
        window = MainWindow()
        for mode, expected in (
            (TRAINING_MODE_SINGLE, "单吊\n模式"),
            (TRAINING_MODE_INDEPENDENT, "独立\n模式"),
            (TRAINING_MODE_CONTINUOUS, "复利\n模式"),
        ):
            window.training_mode_kind = mode
            window.test_trade_active = False
            window._sync_menu_actions()
            self.assertEqual(window.advance_phase_btn.mode_badge_text, expected)

        window.test_trade_active = True
        window._sync_menu_actions()
        self.assertEqual(window.advance_phase_btn.mode_badge_text, "测试\n模式")
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_can_buy_immediately_at_selected_test_bar_while_future_bars_remain_visible(self) -> None:
        window = MainWindow()
        bars = self._bars()
        window._activate_browse_engine(bars, "测试股票", "浏览中")

        self.assertTrue(window.start_test_trade_from_bar(bars[10].date))
        self.assertGreater(window.viewed_bar_index, window.engine.current_index)

        with (
            patch("stock_simulator.app.QMessageBox.information") as information,
            patch("stock_simulator.app._play_buy_success_sound"),
        ):
            window.trade_buy_btn.click()
            self.application.processEvents()

        information.assert_not_called()
        self.assertTrue(window.trade_started)
        self.assertEqual(window.first_buy_index, 10)
        self.assertEqual(window.engine.trades[0].date, bars[10].date)
        window.exit_test_trade_mode(update_status=False)
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_held_index_preview_matches_test_trade_visible_dates(self) -> None:
        window = MainWindow()
        bars = self._bars()
        index_bars = [
            DailyBar(
                "sh999999",
                bar.date,
                3_000.0 + index,
                3_010.0 + index,
                2_990.0 + index,
                3_005.0 + index,
                10_000_000.0,
                1_000_000,
            )
            for index, bar in enumerate(bars)
        ]
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        window.shanghai_index_bars = index_bars
        self.assertTrue(window.start_test_trade_from_bar(bars[10].date))
        stock_visible_dates = [bar.date for bar in window.kline_widget.bars]

        window._show_held_index_preview()

        self.assertTrue(window.index_preview_active)
        self.assertEqual(
            [bar.date for bar in window.kline_widget.bars],
            stock_visible_dates,
        )
        window._end_index_preview_hold()
        window.exit_test_trade_mode(update_status=False)
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_held_index_preview_uses_test_trade_viewed_date_and_full_bar(self) -> None:
        window = MainWindow()
        bars = self._bars()
        index_bars = [
            DailyBar(
                "sh999999",
                bar.date,
                3_000.0 + index,
                3_010.0 + index,
                2_990.0 + index,
                3_005.0 + index,
                10_000_000.0,
                1_000_000,
            )
            for index, bar in enumerate(bars)
        ]
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        window.shanghai_index_bars = index_bars
        self.assertTrue(window.start_test_trade_from_bar(bars[10].date))
        viewed_index = window._displayed_bar_index()
        viewed_date = bars[viewed_index].date
        self.assertNotEqual(viewed_date, window.engine.current_bar.date)

        window._show_held_index_preview()

        self.assertIn(viewed_date, window.title_label.text())
        self.assertIn(f"{index_bars[viewed_index].close:.2f}", window.title_label.text())
        self.assertIn(f"收 {index_bars[viewed_index].close:.2f}", window.day_info.text())
        self.assertNotIn("振待收盘", window.index_market_labels["上证涨跌"].text())
        window._end_index_preview_hold()
        window.exit_test_trade_mode(update_status=False)
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_held_index_preview_matches_formal_training_history_view(self) -> None:
        window = MainWindow()
        bars = self._bars()
        index_bars = [
            DailyBar(
                "sh999999",
                bar.date,
                3_000.0 + index,
                3_010.0 + index,
                2_990.0 + index,
                3_005.0 + index,
                10_000_000.0,
                1_000_000,
            )
            for index, bar in enumerate(bars)
        ]
        engine = DailySimulationEngine(
            bars=bars,
            initial_cash=100_000,
            slot_count=window.settings.slot_count,
            start_index=30,
        )
        engine.start()
        window.engine = engine
        window.training_mode = True
        window.current_node = TradeNode.OPEN
        window.reveal_current_full = False
        window.viewed_bar_index = 10
        window.pan_offset = engine.current_index - window.viewed_bar_index
        window.shanghai_index_bars = index_bars
        window._draw_chart()
        stock_visible_dates = [bar.date for bar in window.kline_widget.bars]

        window._show_held_index_preview()

        self.assertIn(bars[10].date, window.title_label.text())
        self.assertEqual(
            [bar.date for bar in window.kline_widget.bars],
            stock_visible_dates,
        )
        self.assertIn(f"收 {index_bars[10].close:.2f}", window.day_info.text())
        window._end_index_preview_hold()
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_held_index_preview_matches_direct_browse_history_view(self) -> None:
        window = MainWindow()
        bars = self._bars()
        index_bars = [
            DailyBar(
                "sh999999",
                bar.date,
                3_000.0 + index,
                3_010.0 + index,
                2_990.0 + index,
                3_005.0 + index,
                10_000_000.0,
                1_000_000,
            )
            for index, bar in enumerate(bars)
        ]
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        window.viewed_bar_index = 10
        window.pan_offset = window.engine.current_index - window.viewed_bar_index
        window.shanghai_index_bars = index_bars
        window._draw_chart()
        stock_visible_dates = [bar.date for bar in window.kline_widget.bars]

        window._show_held_index_preview()

        self.assertIn(bars[10].date, window.title_label.text())
        self.assertEqual(
            [bar.date for bar in window.kline_widget.bars],
            stock_visible_dates,
        )
        window._end_index_preview_hold()
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_index_overlay_uses_the_stock_viewed_date_in_history_view(self) -> None:
        window = MainWindow()
        bars = self._bars()
        index_bars = [
            DailyBar(
                "sh999999",
                bar.date,
                3_000.0 + index,
                3_010.0 + index,
                2_990.0 + index,
                3_005.0 + index,
                10_000_000.0,
                1_000_000,
            )
            for index, bar in enumerate(bars)
        ]
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        window.viewed_bar_index = 10
        window.pan_offset = window.engine.current_index - window.viewed_bar_index
        window.shanghai_index_bars = index_bars
        window.index_overlay_active = True

        self.assertTrue(window._sync_index_overlay())

        self.assertEqual(window.kline_widget.index_overlay_current_date, bars[10].date)
        self.assertTrue(window.kline_widget.index_overlay_reveal_current_full)
        self.assertEqual(window.kline_widget.index_overlay_bars[-1].date, bars[10].date)
        window._disable_index_overlay()
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_right_clicking_completed_profit_strip_exits_test_so_another_start_can_be_chosen(self) -> None:
        window = MainWindow()
        bars = self._bars()
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        browse_engine = window.engine
        window.viewed_bar_index = 30
        window.pan_offset = len(bars) - 1 - 30
        self.assertTrue(window.start_test_trade_from_bar(bars[10].date))
        window.engine.cash = 101_234.0
        window.trade_started = True
        window.completed_trade_ranges = [(10, 11, 1_234.0)]
        window._refresh()
        window.show()
        self.application.processEvents()
        chart_rect, _pane_rects = window.kline_widget._layout_areas()
        strip_rect = window.kline_widget._completed_trade_cycle_result_strip_items(chart_rect)[0][0]
        click_pos = strip_rect.center().toPoint()

        class AutoSelectClearMenu:
            selected_action = object()

            def __init__(self, _parent) -> None:
                pass

            def addAction(self, text: str):
                return self.selected_action if text == "清空全部" else object()

            def exec(self, _global_pos):
                return self.selected_action

        with patch("stock_simulator.kline_widget.QMenu", AutoSelectClearMenu):
            QTest.mouseClick(window.kline_widget, Qt.MouseButton.RightButton, pos=click_pos)
            self.application.processEvents()

        self.assertFalse(window.test_trade_active)
        self.assertIs(window.engine, browse_engine)
        self.assertEqual(window.viewed_bar_index, 30)
        self.assertFalse(window.trade_started)
        self.assertEqual(window.completed_trade_ranges, [])
        self.assertIsNone(window._test_trade_browse_context)

        self.assertTrue(window.start_test_trade_from_bar(bars[20].date))
        self.assertEqual(window.engine.current_index, 20)
        window.exit_test_trade_mode(update_status=False)
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_b_shortcut_can_buy_at_selected_test_bar_while_future_bars_remain_visible(self) -> None:
        window = MainWindow()
        bars = self._bars()
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        self.assertTrue(window.start_test_trade_from_bar(bars[10].date))
        key_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_B,
            Qt.KeyboardModifier.NoModifier,
        )

        with (
            patch("stock_simulator.app.QMessageBox.information") as information,
            patch("stock_simulator.app._play_buy_success_sound"),
        ):
            handled = window._handle_training_keyboard_shortcut(key_event)

        self.assertTrue(handled)
        information.assert_not_called()
        self.assertTrue(window.trade_started)
        self.assertEqual(window.engine.trades[0].date, bars[10].date)
        window.exit_test_trade_mode(update_status=False)
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_test_trades_are_not_persisted_or_archived(self) -> None:
        window = MainWindow()
        bars = self._bars()
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        self.assertTrue(window.start_test_trade_from_bar(bars[10].date))
        result = window.engine.buy(0, window.current_node, 50_000)
        self.assertTrue(result.accepted)
        window.trade_started = True

        with patch("stock_simulator.app.save_document") as save_session:
            window._persist_session(include_ordinary=True)
        with patch("stock_simulator.app.save_performance_history") as save_history:
            before = list(window.ordinary_performance_records)
            window._archive_ordinary_performance()

        save_session.assert_not_called()
        save_history.assert_not_called()
        self.assertEqual(window.ordinary_performance_records, before)
        window.exit_test_trade_mode(update_status=False)
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_return_to_trading_discards_test_state_before_restoring_formal_engine(self) -> None:
        window = MainWindow()
        bars = self._bars()
        formal_engine = DailySimulationEngine(
            bars=bars,
            initial_cash=100_000,
            slot_count=window.settings.slot_count,
            start_index=5,
        )
        formal_engine.start()
        window.engine = formal_engine
        window.training_mode = True
        window.trade_started = False
        formal_context = window._capture_trading_context()
        window._return_to_trading_context = formal_context
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        window._return_to_trading_context = formal_context
        self.assertTrue(window.start_test_trade_from_bar(bars[12].date))

        window._return_to_trading()

        self.assertFalse(window.test_trade_active)
        self.assertIsNone(window._test_trade_browse_context)
        self.assertIs(window.engine, formal_engine)
        window.hide()
        window.deleteLater()
        self.application.processEvents()

    def test_random_switch_from_test_restores_formal_holding_without_clear_prompt(self) -> None:
        window = MainWindow()
        bars = self._bars()
        formal_engine = DailySimulationEngine(
            bars=bars,
            initial_cash=100_000,
            slot_count=window.settings.slot_count,
            start_index=5,
        )
        formal_engine.start()
        self.assertTrue(formal_engine.buy(0, window.current_node, 50_000).accepted)
        window.engine = formal_engine
        window.training_mode = True
        window.trade_started = True
        window._activate_browse_engine(bars, "测试股票", "浏览中")
        self.assertTrue(window.start_test_trade_from_bar(bars[12].date))

        with patch("stock_simulator.app.QMessageBox.information") as information:
            window.random_switch_stock()

        information.assert_not_called()
        self.assertFalse(window.test_trade_active)
        self.assertIs(window.engine, formal_engine)
        self.assertIn("正式账户仍有持仓", window.status_label.text())
        window.hide()
        window.deleteLater()
        self.application.processEvents()


if __name__ == "__main__":
    unittest.main()
