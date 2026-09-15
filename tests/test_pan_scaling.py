import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from stock_simulator.kline_widget import KLineWidget


class PanScalingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def drag(self, widget, x):
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, 100), QPointF(x, 100),
                           Qt.MouseButton.NoButton, Qt.MouseButton.RightButton,
                           Qt.KeyboardModifier.NoModifier)
        widget.mouseMoveEvent(event)

    def test_drag_tracks_screen_distance_at_all_zoom_levels(self):
        for count in (30, 120, 1200, 5000):
            for direction in (-1, 1):
                parent = Mock()
                widget = KLineWidget(parent)
                widget.window_size = count
                widget._last_drag_pos = QPointF(300, 100)
                rect = QRectF(0, 0, 1000, 400)
                gap = widget._plot_rect(rect).width() / (count - 1)
                with patch.object(widget, '_areas', return_value=(rect, rect, rect)):
                    self.drag(widget, 300 + direction * 180)
                action = parent.pan_left if direction > 0 else parent.pan_right
                self.assertTrue(action.called)
                moved_pixels = action.call_args.args[0] * gap
                self.assertLessEqual(abs(moved_pixels - 180), gap)
                widget.deleteLater()

    def test_small_moves_accumulate_and_reverse_without_drift(self):
        parent = Mock()
        widget = KLineWidget(parent)
        widget.window_size = 121
        rect = QRectF(0, 0, 1000, 400)
        gap = widget._plot_rect(rect).width() / 120
        widget._last_drag_pos = QPointF(300, 100)
        with patch.object(widget, '_areas', return_value=(rect, rect, rect)):
            for index in range(1, 11):
                self.drag(widget, 300 + gap * index / 4)
            self.assertEqual(sum(c.args[0] for c in parent.pan_left.call_args_list), 2)
            self.drag(widget, 300)
            self.assertEqual(sum(c.args[0] for c in parent.pan_right.call_args_list), 2)
            self.assertAlmostEqual(widget._last_drag_pos.x(), 300)
        widget.deleteLater()
