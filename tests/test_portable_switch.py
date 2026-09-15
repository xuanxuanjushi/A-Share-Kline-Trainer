import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from stock_simulator.app import MainWindow


class PortableSwitchTests(unittest.TestCase):
    def test_old_adjustment_completion_initializes_new_source(self):
        current_provider = object()
        window = SimpleNamespace(
            adjust_worker=SimpleNamespace(provider=object()),
            adjust_provider=current_provider,
            _start_adjust_initialize=Mock(),
            _update_status=Mock(),
            _session_restore_pending=False,
            _reload_current_stock_adjusted=Mock(),
            tdx_path=SimpleNamespace(text=lambda: ''),
        )
        MainWindow._finish_adjust_initialize(window, (True, ''))
        window._start_adjust_initialize.assert_called_once()
        window._reload_current_stock_adjusted.assert_not_called()
