import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from stock_simulator.app import MainWindow, PortableBuildWorker
from stock_simulator.portable_builder import PortableBuildResult


class PortableMenuTests(unittest.TestCase):
    def window(self):
        return SimpleNamespace(
            _portable_build_worker=None, _save_all_manual_settings=Mock(),
            _persist_session=Mock(), _persist_timer=Mock(),
            _desktop_directory=lambda: Path('.'), _update_status=Mock(),
            file_build_portable_action=Mock(), file_build_tdx_portable_action=Mock(),
            portable_build_completed=Mock(), tdx_path=Mock())

    def test_both_modes_reach_worker_and_block_both_actions(self):
        for include in (True, False):
            window = self.window()
            window.tdx_path.text.return_value = ''
            with patch('stock_simulator.app.QFileDialog.getExistingDirectory', return_value='output'), patch('stock_simulator.app.QThreadPool.globalInstance'):
                self.assertTrue(MainWindow.build_portable_package(window, include_market_data=include))
            with patch('stock_simulator.app.build_portable_folder') as build:
                window._portable_build_worker.run()
                self.assertEqual(build.call_args.kwargs['include_market_data'], include)
            window.file_build_portable_action.setEnabled.assert_called_with(False)
            window.file_build_tdx_portable_action.setEnabled.assert_called_with(False)

    def test_cancel_and_busy_do_not_start_another_worker(self):
        window = self.window()
        with patch('stock_simulator.app.QFileDialog.getExistingDirectory', return_value=''):
            self.assertFalse(MainWindow.build_portable_package(window, include_market_data=False))
        self.assertIsNone(window._portable_build_worker)
        window.file_build_tdx_portable_action.setEnabled.assert_not_called()
        window._portable_build_worker = object()
        with patch('stock_simulator.app.QMessageBox.information'):
            self.assertFalse(MainWindow.build_portable_package(window, include_market_data=False))

    def test_completion_and_failure_restore_actions_and_explain_mode(self):
        for include in (True, False):
            window = self.window()
            payload = {'result': PortableBuildResult(Path('output'), (), 'exe'), 'include_market_data': include}
            with patch('stock_simulator.app.QMessageBox.information') as message:
                MainWindow._finish_portable_build(window, payload)
                self.assertIn('内置历史数据' if include else '选择通达信目录', message.call_args.args[2])
                if not include:
                    self.assertNotIn('包含当前数据源的日K', message.call_args.args[2])
            window.file_build_tdx_portable_action.setEnabled.assert_called_with(True)
        with patch('stock_simulator.app.QMessageBox.warning'):
            MainWindow._finish_portable_build(window, {'error': 'disk full'})
        window.file_build_portable_action.setEnabled.assert_called_with(True)
        window.file_build_tdx_portable_action.setEnabled.assert_called_with(True)
