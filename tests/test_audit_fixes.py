from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from stock_simulator import config, persistence
from stock_simulator.app import MainWindow
from stock_simulator.data_migration import export_migration_package
from stock_simulator.engine import DailySimulationEngine
from stock_simulator.models import DailyBar, TradeNode


class AuditFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="audit-regression-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings_path = self.root / "settings.json"
        for target in ("stock_simulator.config.CONFIG_PATH", "stock_simulator.app.CONFIG_PATH"):
            patcher = patch(target, self.settings_path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def window(self):
        for name in ("_load_startup_market", "_start_adjust_initialize"):
            patcher = patch.object(MainWindow, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        window = MainWindow()
        def dispose():
            window._persist_timer.stop()
            window._migration_restore_pending_restart = True
            window.close()
            window.deleteLater()
        self.addCleanup(dispose)
        return window

    @staticmethod
    def engine(price=10):
        return DailySimulationEngine([
            DailyBar("sh600000", "2024-01-02", price, 11, 9, 10, 1000, 100),
            DailyBar("sh600000", "2024-01-03", 10, 11, 9, 10, 1000, 100),
        ], 10000, 1)

    def test_config_rejects_invalid_indicator_elements(self):
        self.settings_path.write_text('{"sub_pane_indicators":[{},[],null,"macd"]}', encoding="utf-8")
        self.assertEqual(config.load_settings().sub_pane_indicators, ["macd"])

    def test_corrupt_history_keeps_original_before_future_save(self):
        path = persistence.performance_history_path()
        original = b'{"ordinary_records":null}'
        path.write_bytes(original)
        self.assertEqual(persistence.load_performance_history(), [])
        persistence.save_performance_history([])
        self.assertTrue(any(p.read_bytes() == original for p in self.root.glob("*.invalid-*.bak")))

    def test_corrupt_session_does_not_stop_window_startup(self):
        for document in ([1], {"version": 1, "active": None}):
            with self.subTest(document=document):
                persistence.session_path().write_text(json.dumps(document), encoding="utf-8")
                self.window()
                self.assertTrue(list(self.root.glob("session_state.json.invalid-*.bak")))

    def test_invalid_session_does_not_partially_replace_account(self):
        window = self.window()
        original = self.engine()
        window.engine = original
        payload = {"version": 1, "active": {"code": "sh600000", "current_date": "2024-01-02", "current_node": "broken"}}
        persistence.save_document(payload)
        with patch.object(window, "_load_stock_bars", return_value=(original.bars, "stock")):
            self.assertFalse(window._restore_session())
        self.assertIs(window.engine, original)

    def test_valid_session_round_trip(self):
        window = self.window()
        window.engine = self.engine()
        window.engine.buy_quantity(0, TradeNode.OPEN, 100)
        window.training_mode = True
        window.trade_started = True
        window.account_initial_cash = 10000
        window.round_start_cash = 10000
        window.round_start_date = "2024-01-02"
        window._persist_session()
        with patch.object(window, "_load_stock_bars", return_value=(window.engine.bars, "stock")):
            self.assertTrue(window._restore_session())
        self.assertEqual(window.engine.cash, 8995)
        self.assertEqual(window.engine.slots[0].today_quantity, 100)

    def test_import_waiting_dialog_cannot_overwrite_new_session(self):
        window = self.window()
        window.engine = self.engine()
        window.trade_started = True
        window.training_mode = True
        source = self.root / "source"
        source.mkdir()
        imported = {"version": 1, "active": {"code": "IMPORTED"}}
        (source / "session_state.json").write_text(json.dumps(imported), encoding="utf-8")
        package = export_migration_package(self.root / "migration.zip", source)
        window._persist_timer.start(1)
        def wait_in_dialog(*args):
            loop = QEventLoop()
            QTimer.singleShot(30, loop.quit)
            loop.exec()
        with (
            patch("stock_simulator.app.QFileDialog.getOpenFileName", return_value=(str(package), "")),
            patch("stock_simulator.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
            patch("stock_simulator.app.QMessageBox.information", side_effect=wait_in_dialog),
        ):
            self.assertTrue(window.import_user_data_package())
        self.assertEqual(json.loads(persistence.session_path().read_text()), imported)

    def test_pending_restart_blocks_direct_and_scheduled_persistence(self):
        window = self.window()
        window.engine = self.engine()
        window.trade_started = True
        window._migration_restore_pending_restart = True
        original = b'{"version":1,"active":{"code":"IMPORTED"}}'
        persistence.session_path().write_bytes(original)
        window._persist_session()
        window._schedule_persist()
        self.assertEqual(persistence.session_path().read_bytes(), original)
        self.assertFalse(window._persist_timer.isActive())

    def test_engine_invalid_prices_never_change_account(self):
        for price in (-10, 0, float("nan"), float("inf")):
            with self.subTest(price=price):
                engine = self.engine(price)
                self.assertFalse(engine.buy_quantity(0, TradeNode.OPEN, 100).accepted)
                self.assertEqual((engine.cash, engine.slots[0].quantity, engine.trades), (10000, 0, []))

    def test_engine_rejects_fractional_quantity_and_unknown_node(self):
        for node, quantity in ((TradeNode.OPEN, 100.9), ("invalid", 100), (TradeNode.OPEN, float("nan"))):
            with self.subTest(node=node, quantity=quantity):
                engine = self.engine()
                self.assertFalse(engine.buy_quantity(0, node, quantity).accepted)
                self.assertEqual(engine.cash, 10000)

    def test_t_plus_one_and_normal_sell_remain_correct(self):
        engine = self.engine()
        self.assertTrue(engine.buy_quantity(0, TradeNode.OPEN, 100).accepted)
        self.assertFalse(engine.sell(0, TradeNode.CLOSE).accepted)
        engine.next_day()
        self.assertTrue(engine.sell(0, TradeNode.OPEN).accepted)
        self.assertEqual(engine.cash, 9989.5)

    def test_failed_import_resumes_pending_save_without_changing_file(self):
        window = self.window()
        window.engine = self.engine()
        original = b'{"version":1,"active":{"code":"OLD"}}'
        persistence.session_path().write_bytes(original)
        window._persist_timer.start()
        with (
            patch("stock_simulator.app.QFileDialog.getOpenFileName", return_value=(str(self.root / "missing.zip"), "")),
            patch("stock_simulator.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
            patch("stock_simulator.app.QMessageBox.warning"),
        ):
            self.assertFalse(window.import_user_data_package())
        self.assertFalse(window._migration_restore_pending_restart)
        self.assertTrue(window._persist_timer.isActive())
        self.assertEqual(persistence.session_path().read_bytes(), original)

    def test_corrupt_history_row_does_not_hide_valid_record(self):
        persistence.performance_history_path().write_text(json.dumps({"ordinary_records": [
            {"index": 7, "code": "sh600000", "profit": 50},
            {"trades": [None]},
        ]}), encoding="utf-8")
        records = persistence.load_performance_history()
        self.assertEqual([(r.index, r.profit) for r in records], [(7, 50)])

    def test_invalid_sell_does_not_change_holdings(self):
        engine = self.engine()
        engine.buy_quantity(0, TradeNode.OPEN, 100)
        engine.next_day()
        self.assertFalse(engine.sell(0, TradeNode.OPEN, quantity=100.9).accepted)
        self.assertFalse(engine.sell(0, TradeNode.OPEN, budget=float("nan")).accepted)
        self.assertEqual((engine.cash, engine.slots[0].quantity, len(engine.trades)), (8995, 100, 1))

    def test_unbacked_corrupt_file_cannot_be_overwritten(self):
        path = persistence.performance_history_path()
        original = b'{"ordinary_records":null}'
        path.write_bytes(original)
        with patch("stock_simulator.storage_safety.shutil.copy2", side_effect=PermissionError("read only")):
            self.assertEqual(persistence.load_performance_history(), [])
        with self.assertRaises(OSError):
            persistence.save_performance_history([])
        self.assertEqual(path.read_bytes(), original)

    def test_legacy_null_initial_cash_uses_configured_default(self):
        window = self.window()
        bars = self.engine().bars
        persistence.save_document({"version": 1, "account_initial_cash": None,
                                   "active": {"code": "sh600000", "current_date": "2024-01-02"}})
        with patch.object(window, "_load_stock_bars", return_value=(bars, "stock")):
            self.assertTrue(window._restore_session())
        self.assertEqual(window.engine.initial_cash, 100000)

    def test_corrupt_configuration_displays_recovery_notice(self):
        self.settings_path.write_text('{"sub_pane_indicators":[{}]}', encoding="utf-8")
        window = self.window()
        self.application.processEvents()
        self.assertIn("settings.json", window.status_label.text())
        self.assertIn("备份", window.status_label.text())
