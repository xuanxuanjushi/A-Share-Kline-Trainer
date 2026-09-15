from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from stock_simulator.app import MainWindow


class TdxPathInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _window(self) -> MainWindow:
        with (
            patch("stock_simulator.app.load_document", return_value=None),
            patch.object(MainWindow, "_start_adjust_initialize"),
        ):
            return MainWindow()

    def test_tdx_path_rejects_keyboard_input(self) -> None:
        window = self._window()
        original = window.tdx_path.text()
        window.tdx_path.setFocus()

        with patch.object(window, "_save_settings"):
            QTest.keyClicks(window.tdx_path, "C:/Wrong/Path")

        self.assertEqual(window.tdx_path.text(), original)
        window.close()
        window.deleteLater()
        self.application.processEvents()

    def test_tdx_path_rejects_clipboard_paste(self) -> None:
        window = self._window()
        original = window.tdx_path.text()
        self.application.clipboard().setText("C:/Pasted/Wrong/Path")
        window.tdx_path.setFocus()

        with patch.object(window, "_save_settings"):
            QTest.keyClick(
                window.tdx_path,
                Qt.Key.Key_V,
                Qt.KeyboardModifier.ControlModifier,
            )

        self.assertEqual(window.tdx_path.text(), original)
        window.close()
        window.deleteLater()
        self.application.processEvents()


if __name__ == "__main__":
    unittest.main()
