from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QWidget, QWidgetAction

from .models import DailyBar, TradeNode, TradeResult
from .test_trade import point_hits_candle_body
from .ui_state import candle_body_is_filled, candle_state, change_metrics, moving_average, trade_marker_position_for_trade

RIGHT_TRAILING_SLOTS = 6
RIGHT_REFERENCE_AREA_WIDTH = 112
REFERENCE_LABEL_SIZE = (76, 28)
REFERENCE_LINE_WIDTH = 1
AVERAGE_LINE_WIDTH = 0.72
PRICE_AXIS_LABEL_SIZE = (76, 22)
TRADE_MARKER_SIZE = 18
CURRENT_DAY_HIGHLIGHT_ALPHA = 38
HIDDEN_OPEN_LINE_BLINK_MS = 500
LINE_HIT_RADIUS = 8
LINE_SNAP_DEGREES = 15
LINE_SNAP_THRESHOLD = 3
USER_LINE_DEFAULT_WIDTH_RATIO = 2 / 3
USER_LINE_PEN_WIDTH = 1
SELECTED_USER_LINE_PEN_WIDTH = 2
USER_LINE_PASTE_OFFSET_SLOTS = 2
MARQUEE_MIN_SIZE = 8
RECTANGLE_HANDLE_RADIUS = 4
RECTANGLE_ROTATION_HANDLE_RADIUS = 10
RECTANGLE_ROTATION_HANDLE_OFFSET = 16

SUB_PANE_INDICATORS = ("volume", "macd", "kdj")
SUB_PANE_INDICATOR_LABELS = {"volume": "成交量", "macd": "MACD", "kdj": "KDJ"}
VOLUME_MA_PERIODS = (5, 10, 20, 30, 60, 120)
MAIN_MA_PERIODS = (5, 10, 20, 60, 120, 250)
VOLUME_MA_COLOR_30 = QColor("#ff9800")
VOLUME_MA_COLOR_120 = QColor("#2196f3")
VOLUME_LABEL_AREA_HEIGHT = 36
MIDDLE_HOLD_TOGGLE_MS = 450
MIDDLE_HOLD_BACKGROUND = QColor("#0f1620")
HISTORY_OVERLAY_ALPHA = 96
MIDDLE_HOLD_HISTORY_OVERLAY_ALPHA = HISTORY_OVERLAY_ALPHA // 2
MIN_SUB_PANE_COUNT = 1
MAX_SUB_PANE_COUNT = 4
PANE_GAP = 8
PANE_SEPARATOR_HIT_RADIUS = 5


@dataclass
class UserLine:
    start_index: float
    start_price: float
    end_index: float
    end_price: float


@dataclass
class UserRectangle:
    left_index: float
    top_price: float
    right_index: float
    bottom_price: float
    angle_degrees: float = 0.0


@dataclass(frozen=True)
class ReferenceLineSpec:
    label: str
    price: float
    color: QColor


@dataclass(frozen=True)
class ChartPalette:
    background: QColor = field(default_factory=lambda: QColor("#000000"))
    grid: QColor = field(default_factory=lambda: QColor("#171717"))
    axis: QColor = field(default_factory=lambda: QColor("#5d6670"))
    text: QColor = field(default_factory=lambda: QColor("#8d98a5"))
    up: QColor = field(default_factory=lambda: QColor("#ff3b30"))
    down: QColor = field(default_factory=lambda: QColor("#00f0f0"))
    limit_up: QColor = field(default_factory=lambda: QColor("#ffd21f"))
    limit_down: QColor = field(default_factory=lambda: QColor("#7c4dff"))
    ma5: QColor = field(default_factory=lambda: QColor("#ffffff"))
    ma10: QColor = field(default_factory=lambda: QColor("#d8d000"))
    ma20: QColor = field(default_factory=lambda: QColor("#d000d8"))
    ma60: QColor = field(default_factory=lambda: QColor("#00c853"))
    ma120: QColor = field(default_factory=lambda: QColor("#00bcd4"))
    ma250: QColor = field(default_factory=lambda: QColor("#ff9800"))
    boll_mid: QColor = field(default_factory=lambda: QColor("#9aa7b5"))
    boll_upper: QColor = field(default_factory=lambda: QColor("#ff9f43"))
    boll_lower: QColor = field(default_factory=lambda: QColor("#34d399"))
    gma_short: QColor = field(default_factory=lambda: QColor("#c08080"))
    gma_long: QColor = field(default_factory=lambda: QColor("#0080ff"))
    macd_dif: QColor = field(default_factory=lambda: QColor("#f4f4f4"))
    macd_dea: QColor = field(default_factory=lambda: QColor("#d8d000"))
    marker_buy: QColor = field(default_factory=lambda: QColor("#ff3b30"))
    marker_sell: QColor = field(default_factory=lambda: QColor("#00c8b8"))
    marker_t: QColor = field(default_factory=lambda: QColor("#c6a24a"))
    tip_up_background: QColor = field(default_factory=lambda: QColor("#ff3b30"))
    tip_down_background: QColor = field(default_factory=lambda: QColor("#16a34a"))
    tip_text: QColor = field(default_factory=lambda: QColor("#ffffff"))
    average_cost: QColor = field(default_factory=lambda: QColor("#b76cf0"))


class KLineWidget(QWidget):
    RIGHT_REFERENCE_AREA_WIDTH = RIGHT_REFERENCE_AREA_WIDTH
    REFERENCE_LABEL_SIZE = REFERENCE_LABEL_SIZE

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.bars: list[DailyBar] = []
        self.all_bars: list[DailyBar] = []
        self.trades: list[TradeResult] = []
        self.completed_trade_ranges: list[tuple[int, int, float]] = []
        self.active_trade_range: tuple[int, int] | None = None
        self.history_unmask_start_index: int | None = None
        self.max_drawdown_range: tuple[int, int, float, int] | None = None
        self.current_index = 0
        self.current_node: TradeNode | None = None
        self.pan_offset = 0
        self.window_size = 60
        self.reveal_current_full = True
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        self.show_time_marks = True
        self.average_cost_price: float | None = None
        self.palette = ChartPalette()
        self.hidden_ma_periods: set[int] = set()
        self._ma_cache_source: list[DailyBar] | None = None
        self._ma_cache_signature: tuple[int, DailyBar | None, DailyBar | None] | None = None
        self._ma_close_prefix: list[float] = [0.0]
        self._ma_series_cache: dict[int, list[float | None]] = {}
        self._paint_price_range_cache: tuple[float, float] | None = None
        self.sub_pane_indicators: list[str] = ["volume", "macd"]
        self.pane_height_ratios: list[float] = [0.62, 0.20, 0.18]
        self.kdj_n = 9
        self.kdj_k = 3
        self.kdj_d = 3
        self.pane_macd_params: list[tuple[int, int, int]] = [(12, 26, 9) for _ in range(MAX_SUB_PANE_COUNT)]
        self.pane_kdj_params: list[tuple[int, int, int]] = [(9, 3, 3) for _ in range(MAX_SUB_PANE_COUNT)]
        self.main_overlay_mode = "ma"
        self.boll_n = 20
        self.boll_k = 2.0
        self.hidden_volume_ma_periods: set[int] = set(VOLUME_MA_PERIODS)
        self._ma_legend_hits: dict[int, QRectF] = {}
        self._boll_legend_hit: QRectF | None = None
        self._gma_legend_hit: QRectF | None = None
        self._sub_pane_label_hits: dict[int, QRectF] = {}
        self._volume_ma_legend_hits: dict[int, QRectF] = {}
        self._volume_ma_legend_hits_by_pane: dict[int, dict[int, QRectF]] = {}
        self.volume_amount_tip: DailyBar | None = None
        self._label_flash_key: str | None = None
        self._label_flash_timer = QTimer(self)
        self._label_flash_timer.setSingleShot(True)
        self._label_flash_timer.setInterval(180)
        self._label_flash_timer.timeout.connect(self._end_label_flash)
        self._sub_pane_hover: tuple[int, int, float] | None = None
        self.show_middle_hold_background = False
        self._middle_gesture = ""
        self._middle_press_pos: QPointF | None = None
        self._middle_longpress_timer = QTimer(self)
        self._middle_longpress_timer.setSingleShot(True)
        self._middle_longpress_timer.setInterval(MIDDLE_HOLD_TOGGLE_MS)
        self._middle_longpress_timer.timeout.connect(self._on_middle_longpress)
        self._macd_label_hit = QRectF()
        self.selected_bar_date: str = ""
        self._last_drag_pos: QPoint | None = None
        self.user_lines: list[UserLine] = []
        self.user_rectangles: list[UserRectangle] = []
        self.suppress_user_annotations = False
        self.index_overlay_bars: list[DailyBar] = []
        self.index_overlay_current_date = ""
        self.index_overlay_reveal_current_full = True
        self.selected_user_line_index: int | None = None
        self.selected_user_line_indices: set[int] = set()
        self._copied_user_lines: list[UserLine] = []
        self.selected_user_rectangle_index: int | None = None
        self.selected_user_rectangle_indices: set[int] = set()
        self._copied_user_rectangles: list[UserRectangle] = []
        self._line_drag_index: int | None = None
        self._line_drag_indices: set[int] = set()
        self._line_drag_mode = ""
        self._line_drag_last_pos: QPointF | None = None
        self._rectangle_drag_index: int | None = None
        self._rectangle_drag_indices: set[int] = set()
        self._rectangle_drag_mode = ""
        self._rectangle_drag_last_pos: QPointF | None = None
        self._rectangle_rotate_index: int | None = None
        self._rectangle_rotate_start_angle = 0.0
        self._rectangle_rotate_base_degrees = 0.0
        self._rectangle_rotate_requires_both_buttons = False
        self._hover_user_rectangle_index: int | None = None
        self._marquee_start_pos: QPointF | None = None
        self._marquee_current_pos: QPointF | None = None
        self._pending_rectangle_rect: QRectF | None = None
        self._pane_resize_separator_index: int | None = None
        self._pane_resize_start_y = 0.0
        self._pane_resize_start_sizes: list[float] = []
        self._hover_chart_pos: QPointF | None = None
        self._hidden_open_line_visible = True
        self._hidden_open_line_blink_timer = QTimer(self)
        self._hidden_open_line_blink_timer.setInterval(HIDDEN_OPEN_LINE_BLINK_MS)
        self._hidden_open_line_blink_timer.timeout.connect(self._toggle_hidden_open_line_blink)
        self._hidden_open_line_blink_timer.start()
        self.setMinimumHeight(480)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def clear_user_annotations(self) -> None:
        self.user_lines.clear()
        self.user_rectangles.clear()
        self.selected_user_line_index = None
        self.selected_user_line_indices = set()
        self._copied_user_lines = []
        self.selected_user_rectangle_index = None
        self.selected_user_rectangle_indices = set()
        self._copied_user_rectangles = []
        self._line_drag_index = None
        self._line_drag_indices = set()
        self._line_drag_mode = ""
        self._line_drag_last_pos = None
        self._rectangle_drag_index = None
        self._rectangle_drag_indices = set()
        self._rectangle_drag_mode = ""
        self._rectangle_drag_last_pos = None
        self._rectangle_rotate_index = None
        self._rectangle_rotate_start_angle = 0.0
        self._rectangle_rotate_base_degrees = 0.0
        self._rectangle_rotate_requires_both_buttons = False
        self._hover_user_rectangle_index = None
        self._marquee_start_pos = None
        self._marquee_current_pos = None
        self._pending_rectangle_rect = None
        self._hover_chart_pos = None
        self.selected_bar_date = ""
        self.update()

    def add_user_line_at_center(self) -> bool:
        """Add a selected helper line at the center of the visible main chart."""
        if not self.bars or self.suppress_user_annotations:
            return False
        chart_rect, _volume_rect, _macd_rect = self._areas()
        if chart_rect.width() < MARQUEE_MIN_SIZE or chart_rect.height() < MARQUEE_MIN_SIZE:
            return False
        self._set_user_rectangle_selection(set(), update=False)
        self._add_user_line(chart_rect, chart_rect.center())
        self.setFocus()
        self.update()
        return True

    def add_user_rectangle_at_center(self) -> bool:
        """Add a selected annotation rectangle in the visible main chart."""
        if not self.bars or self.suppress_user_annotations:
            return False
        chart_rect, _volume_rect, _macd_rect = self._areas()
        width = max(MARQUEE_MIN_SIZE, chart_rect.width() * 0.36)
        height = max(MARQUEE_MIN_SIZE, chart_rect.height() * 0.24)
        screen_rect = QRectF(
            chart_rect.center().x() - width / 2,
            chart_rect.center().y() - height / 2,
            width,
            height,
        ).intersected(chart_rect)
        if screen_rect.width() < MARQUEE_MIN_SIZE or screen_rect.height() < MARQUEE_MIN_SIZE:
            return False
        self._add_user_rectangle(chart_rect, screen_rect)
        self.setFocus()
        self.update()
        return True

    def select_all_user_annotations(self) -> int:
        """Select all editable helper lines and rectangles."""
        self._set_user_line_selection(set(range(len(self.user_lines))), update=False)
        self._set_user_rectangle_selection(set(range(len(self.user_rectangles))))
        self.setFocus()
        return len(self.selected_user_line_indices) + len(self.selected_user_rectangle_indices)

    def copy_selected_user_annotations(self) -> int:
        count = len(self.selected_user_line_indices) + len(self.selected_user_rectangle_indices)
        if count:
            self._copy_selected_user_lines()
        self.setFocus()
        return count

    def paste_user_annotations(self) -> int:
        before = len(self.user_lines) + len(self.user_rectangles)
        self._paste_user_lines()
        added = len(self.user_lines) + len(self.user_rectangles) - before
        self.setFocus()
        return added

    def delete_selected_user_annotations(self) -> int:
        selected_lines = sorted(self.selected_user_line_indices, reverse=True)
        selected_rectangles = sorted(self.selected_user_rectangle_indices, reverse=True)
        for index in selected_lines:
            if 0 <= index < len(self.user_lines):
                del self.user_lines[index]
        for index in selected_rectangles:
            if 0 <= index < len(self.user_rectangles):
                del self.user_rectangles[index]
        deleted = len(selected_lines) + len(selected_rectangles)
        if deleted:
            self._clear_user_line_selection()
        self.setFocus()
        return deleted

    def user_annotation_count(self) -> int:
        return len(self.user_lines) + len(self.user_rectangles)

    def set_data(
        self,
        all_bars: list[DailyBar],
        visible_bars: list[DailyBar],
        trades: list[TradeResult],
        current_index: int,
        pan_offset: int,
        window_size: int,
        reveal_current_full: bool,
        average_cost_price: float | None = None,
        completed_trade_ranges: list[tuple[int, int, float]] | None = None,
        active_trade_range: tuple[int, int] | None = None,
        max_drawdown_range: tuple[int, int, float, int] | None = None,
        history_unmask_start_index: int | None = None,
        current_node: TradeNode | None = None,
    ) -> None:
        self.all_bars = all_bars
        self.bars = visible_bars
        self.trades = trades
        self.completed_trade_ranges = self._normalize_completed_trade_ranges(completed_trade_ranges or [])
        self.active_trade_range = None if active_trade_range is None else (
            min(int(active_trade_range[0]), int(active_trade_range[1])),
            max(int(active_trade_range[0]), int(active_trade_range[1])),
        )
        self.history_unmask_start_index = (
            None if history_unmask_start_index is None else int(history_unmask_start_index)
        )
        self.max_drawdown_range = None if max_drawdown_range is None else (
            min(int(max_drawdown_range[0]), int(max_drawdown_range[1])),
            max(int(max_drawdown_range[0]), int(max_drawdown_range[1])),
            float(max_drawdown_range[2]),
            max(1, int(max_drawdown_range[3])),
        )
        self.current_index = current_index
        self.current_node = current_node
        self.pan_offset = pan_offset
        self.window_size = window_size
        self.reveal_current_full = reveal_current_full
        self.average_cost_price = average_cost_price
        self.volume_amount_tip = None
        self.update()

    @staticmethod
    def _normalize_completed_trade_ranges(ranges) -> list[tuple[int, int, float]]:
        normalized: list[tuple[int, int, float]] = []
        for item in ranges:
            if len(item) < 2:
                continue
            profit = float(item[2]) if len(item) >= 3 else 0.0
            normalized.append((int(item[0]), int(item[1]), profit))
        return normalized

    def set_macd_parameters(self, fast: int, slow: int, signal: int) -> None:
        self.macd_fast = max(1, int(fast))
        self.macd_slow = max(self.macd_fast + 1, int(slow))
        self.macd_signal = max(1, int(signal))
        params = (self.macd_fast, self.macd_slow, self.macd_signal)
        self.pane_macd_params = list(self.pane_macd_params)
        for index in range(len(self.pane_macd_params)):
            self.pane_macd_params[index] = params
        self.update()

    def set_kdj_parameters(self, n: int, k: int, d: int) -> None:
        self.kdj_n = max(1, int(n))
        self.kdj_k = max(1, int(k))
        self.kdj_d = max(1, int(d))
        params = (self.kdj_n, self.kdj_k, self.kdj_d)
        self.pane_kdj_params = list(self.pane_kdj_params)
        for index in range(len(self.pane_kdj_params)):
            self.pane_kdj_params[index] = params
        self.update()

    def set_pane_macd_parameters(self, pane_index: int, fast: int, slow: int, signal: int) -> None:
        if not 0 <= pane_index < MAX_SUB_PANE_COUNT:
            return
        fast = max(1, int(fast))
        slow = max(fast + 1, int(slow))
        signal = max(1, int(signal))
        self.pane_macd_params = list(self.pane_macd_params)
        while len(self.pane_macd_params) <= pane_index:
            self.pane_macd_params.append((self.macd_fast, self.macd_slow, self.macd_signal))
        self.pane_macd_params[pane_index] = (fast, slow, signal)
        self.macd_fast = fast
        self.macd_slow = slow
        self.macd_signal = signal
        self.update()

    def set_pane_kdj_parameters(self, pane_index: int, n: int, k: int, d: int) -> None:
        if not 0 <= pane_index < MAX_SUB_PANE_COUNT:
            return
        n = max(1, int(n))
        k = max(1, int(k))
        d = max(1, int(d))
        self.pane_kdj_params = list(self.pane_kdj_params)
        while len(self.pane_kdj_params) <= pane_index:
            self.pane_kdj_params.append((self.kdj_n, self.kdj_k, self.kdj_d))
        self.pane_kdj_params[pane_index] = (n, k, d)
        self.kdj_n = n
        self.kdj_k = k
        self.kdj_d = d
        self.update()

    def set_boll_parameters(self, n: int, k: float) -> None:
        self.boll_n = max(2, int(n))
        self.boll_k = max(0.1, float(k))
        self.update()

    def set_sub_pane_indicators(self, indicators) -> None:
        defaults = ["volume", "macd", "kdj", "macd"]
        requested = list(indicators or [])
        target_count = min(MAX_SUB_PANE_COUNT, max(MIN_SUB_PANE_COUNT, len(requested) or 2))
        result: list[str] = []
        for index in range(target_count):
            raw = requested[index] if index < len(requested) else defaults[index]
            result.append(raw if raw in SUB_PANE_INDICATORS else defaults[index])
        self.sub_pane_indicators = result
        if len(self.pane_height_ratios) != target_count + 1:
            self.pane_height_ratios = self._default_pane_height_ratios(target_count)
        self.update()

    def set_sub_pane_indicator(self, pane_index: int, indicator: str) -> None:
        if not 0 <= pane_index < len(self.sub_pane_indicators) or indicator not in SUB_PANE_INDICATORS:
            return
        self.sub_pane_indicators[pane_index] = indicator
        if hasattr(self.parent_window, "save_chart_preferences"):
            self.parent_window.save_chart_preferences()
        self.update()

    @staticmethod
    def _default_pane_height_ratios(pane_count: int) -> list[float]:
        defaults = {
            1: [0.72, 0.28],
            2: [0.62, 0.20, 0.18],
            3: [0.52, 0.17, 0.16, 0.15],
            4: [0.44, 0.15, 0.14, 0.14, 0.13],
        }
        return list(defaults[min(MAX_SUB_PANE_COUNT, max(MIN_SUB_PANE_COUNT, pane_count))])

    def set_pane_height_ratios(self, ratios) -> None:
        values = []
        for value in list(ratios or []):
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = 0.0
            values.append(max(0.0, numeric))
        expected = len(self.sub_pane_indicators) + 1
        if len(values) != expected or sum(values) <= 0:
            values = self._default_pane_height_ratios(len(self.sub_pane_indicators))
        total = sum(values)
        self.pane_height_ratios = [value / total for value in values]
        self.update()

    def set_sub_pane_count(self, pane_count: int) -> None:
        target = min(MAX_SUB_PANE_COUNT, max(MIN_SUB_PANE_COUNT, int(pane_count)))
        current = len(self.sub_pane_indicators)
        if target == current:
            return
        defaults = ["volume", "macd", "kdj", "macd"]
        if target > current:
            self.sub_pane_indicators.extend(defaults[index] for index in range(current, target))
        else:
            self.sub_pane_indicators = self.sub_pane_indicators[:target]
        self.pane_height_ratios = self._default_pane_height_ratios(target)
        self._sub_pane_hover = None
        self.volume_amount_tip = None
        self.update()
        if hasattr(self.parent_window, "save_chart_preferences"):
            self.parent_window.save_chart_preferences()

    def reset_pane_height_ratios(self) -> None:
        self.pane_height_ratios = self._default_pane_height_ratios(len(self.sub_pane_indicators))
        self.update()
        if hasattr(self.parent_window, "save_chart_preferences"):
            self.parent_window.save_chart_preferences()

    def _sub_pane_label_rect(self, rect: QRectF) -> QRectF:
        return QRectF(rect.left() + 4, rect.top() + 1, 128, 20)

    def _sub_pane_label_text(self, pane_index: int) -> str:
        indicator = self.sub_pane_indicators[pane_index]
        if indicator == "macd":
            return self._macd_label_text(pane_index)
        if indicator == "kdj":
            return self._kdj_label_text(pane_index)
        return self._volume_text()

    def _kdj_label_text(self, pane_index: int = 0) -> str:
        n, k, d = self.pane_kdj_params[pane_index]
        return f"KDJ({n},{k},{d})"

    def _open_sub_pane_menu(self, pane_index: int, global_pos) -> None:
        menu = QMenu(self)
        for indicator in ("volume", "kdj", "macd"):
            menu.addAction(self._make_indicator_menu_row(menu, pane_index, indicator))
        menu.exec(global_pos)

    def _build_sub_pane_count_menu(self) -> QMenu:
        menu = QMenu(self)
        pane_count = len(self.sub_pane_indicators)
        if pane_count < MAX_SUB_PANE_COUNT:
            add_action = menu.addAction("增加一个副图")
            if hasattr(self.parent_window, "_change_subpane_count"):
                add_action.triggered.connect(
                    lambda _checked=False: self.parent_window._change_subpane_count(1)
                )
        if pane_count > MIN_SUB_PANE_COUNT:
            remove_action = menu.addAction("减少一个副图")
            if hasattr(self.parent_window, "_change_subpane_count"):
                remove_action.triggered.connect(
                    lambda _checked=False: self.parent_window._change_subpane_count(-1)
                )
        return menu

    def _open_sub_pane_count_menu(self, global_pos) -> None:
        self._build_sub_pane_count_menu().exec(global_pos)

    def _make_indicator_menu_row(self, menu: QMenu, pane_index: int, indicator: str) -> QWidgetAction:
        widget = QWidget(menu)
        row = QHBoxLayout(widget)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(4)
        selected = self.sub_pane_indicators[pane_index] == indicator
        check_label = QLabel("✓" if selected else "")
        check_label.setFixedWidth(16)
        check_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        check_label.setStyleSheet("color: #e6edf3; font-size: 13px;")
        row.addWidget(check_label, 0)
        label_button = QPushButton(SUB_PANE_INDICATOR_LABELS[indicator])
        label_button.setFlat(True)
        label_button.setCursor(Qt.CursorShape.PointingHandCursor)
        label_button.setStyleSheet("QPushButton { border: none; background: transparent; color: #e6edf3; font-size: 13px; text-align: left; padding: 0; }")
        label_button.clicked.connect(lambda: (menu.close(), self.set_sub_pane_indicator(pane_index, indicator)))
        row.addWidget(label_button, 1)
        if indicator in ("kdj", "macd"):
            gear_button = QToolButton()
            gear_button.setText("⚙")
            gear_button.setToolTip(f"{SUB_PANE_INDICATOR_LABELS[indicator]} 参数设置")
            gear_button.setAutoRaise(True)
            gear_button.setCursor(Qt.CursorShape.PointingHandCursor)
            gear_button.setStyleSheet("QToolButton { border: none; background: transparent; color: #8d98a5; font-size: 14px; }")
            if indicator == "macd":
                gear_button.clicked.connect(lambda: (menu.close(), self._edit_macd_parameters(pane_index)))
            else:
                gear_button.clicked.connect(lambda: (menu.close(), self._edit_kdj_parameters(pane_index)))
            row.addWidget(gear_button, 0)
        action = QWidgetAction(menu)
        action.setDefaultWidget(widget)
        return action

    def _edit_macd_parameters(self, pane_index: int = 0) -> None:
        if hasattr(self.parent_window, "edit_macd_parameters"):
            try:
                self.parent_window.edit_macd_parameters(pane_index)
            except TypeError:
                self.parent_window.edit_macd_parameters()

    def _edit_kdj_parameters(self, pane_index: int = 0) -> None:
        if hasattr(self.parent_window, "edit_kdj_parameters"):
            try:
                self.parent_window.edit_kdj_parameters(pane_index)
            except TypeError:
                self.parent_window.edit_kdj_parameters()

    def _flash_label(self, key: str) -> None:
        self._label_flash_key = key
        self._label_flash_timer.start()
        self.update()

    def _end_label_flash(self) -> None:
        self._label_flash_key = None
        self.update()

    def _is_label_flashing(self, key: str) -> bool:
        return self._label_flash_key == key

    def set_index_overlay(self, bars: list[DailyBar], current_date: str, reveal_current_full: bool) -> None:
        self.index_overlay_bars = list(bars)
        self.index_overlay_current_date = current_date
        self.index_overlay_reveal_current_full = reveal_current_full
        self.update()

    def clear_index_overlay(self) -> None:
        self.index_overlay_bars = []
        self.index_overlay_current_date = ""
        self.index_overlay_reveal_current_full = True
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_press_pos = event.position()
            self._middle_gesture = ""
            self._middle_longpress_timer.start()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._pending_rectangle_rect = None
            separator_index = self._separator_hit_index(event.position())
            if separator_index is not None:
                chart_rect, pane_rects = self._layout_areas()
                self._pane_resize_separator_index = separator_index
                self._pane_resize_start_y = event.position().y()
                self._pane_resize_start_sizes = [chart_rect.height(), *[rect.height() for rect in pane_rects]]
                self.setCursor(Qt.CursorShape.SizeVerCursor)
                event.accept()
                return
            chart_rect, pane_rects = self._layout_areas()
            for pane_index, pane_rect in enumerate(pane_rects):
                if self._sub_pane_label_rect(pane_rect).contains(event.pos()):
                    self._flash_label(f"subpane_{pane_index}")
                    self._open_sub_pane_menu(pane_index, event.globalPos())
                    event.accept()
                    return
            for pane_index, pane_rect in enumerate(pane_rects):
                if self.sub_pane_indicators[pane_index] != "volume" or not pane_rect.contains(event.pos()):
                    continue
                legend_hits = self._volume_ma_legend_hits_by_pane.get(pane_index, {})
                for period, rect in legend_hits.items():
                    if rect.contains(event.pos()):
                        self._flash_label(f"vma_{period}")
                        if period in self.hidden_volume_ma_periods:
                            self.hidden_volume_ma_periods.remove(period)
                        else:
                            self.hidden_volume_ma_periods.add(period)
                        if hasattr(self.parent_window, "save_chart_preferences"):
                            self.parent_window.save_chart_preferences()
                        self.update()
                        event.accept()
                        return
                hit_slot = self._hit_volume_bar(pane_rect, event.position())
                if hit_slot is not None:
                    self.volume_amount_tip = self.bars[hit_slot]
                    self.update()
                    event.accept()
                    return
                if self.volume_amount_tip is not None:
                    self.volume_amount_tip = None
                    self.update()
                    event.accept()
                    return
            if self._boll_legend_hit is not None and self._boll_legend_hit.contains(event.pos()):
                self._flash_label("boll")
                self.main_overlay_mode = "none" if self.main_overlay_mode == "boll" else "boll"
                if hasattr(self.parent_window, "save_chart_preferences"):
                    self.parent_window.save_chart_preferences()
                self.update()
                event.accept()
                return
            if self._gma_legend_hit is not None and self._gma_legend_hit.contains(event.pos()):
                self._flash_label("gma")
                self.main_overlay_mode = "none" if self.main_overlay_mode == "gma" else "gma"
                if hasattr(self.parent_window, "save_chart_preferences"):
                    self.parent_window.save_chart_preferences()
                self.update()
                event.accept()
                return
            for period, rect in self._ma_legend_hits.items():
                if rect.contains(event.pos()):
                    self._flash_label(f"ma_{period}")
                    if self.main_overlay_mode != "ma":
                        self.main_overlay_mode = "ma"
                        if hasattr(self.parent_window, "save_chart_preferences"):
                            self.parent_window.save_chart_preferences()
                    else:
                        if period in self.hidden_ma_periods:
                            self.hidden_ma_periods.remove(period)
                        else:
                            self.hidden_ma_periods.add(period)
                        if hasattr(self.parent_window, "save_chart_preferences"):
                            self.parent_window.save_chart_preferences()
                    self.update()
                    event.accept()
                    return
            if self.bars:
                if chart_rect.contains(event.pos()):
                    self.volume_amount_tip = None
                    rotation_handle_index = self._hit_user_rectangle_rotation_handle(chart_rect, event.position())
                    if rotation_handle_index is not None:
                        self._set_user_line_selection(set(), update=False)
                        self._set_user_rectangle_selection({rotation_handle_index}, update=False)
                        self._begin_user_rectangle_rotation(chart_rect, rotation_handle_index, event.position())
                        self._rectangle_rotate_requires_both_buttons = False
                        self._hover_user_rectangle_index = None
                        self.update()
                        event.accept()
                        return
                    hit_rectangle = self._hit_user_rectangle(chart_rect, event.position())
                    if hit_rectangle:
                        rectangle_index, self._rectangle_drag_mode = hit_rectangle
                        duplicate_drag = bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
                        if duplicate_drag and self._rectangle_drag_mode == "move":
                            if rectangle_index not in self.selected_user_rectangle_indices:
                                self._clear_user_line_selection(update=False)
                                self._set_user_rectangle_selection({rectangle_index}, update=False)
                            _copied_lines, copied_rectangles = self._duplicate_selected_annotations(offset_slots=0)
                            self._rectangle_drag_indices = set(copied_rectangles)
                            self._rectangle_drag_index = copied_rectangles[-1] if copied_rectangles else rectangle_index
                        else:
                            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                                self._toggle_user_rectangle_selection(rectangle_index)
                            else:
                                self._set_user_line_selection(set(), update=False)
                                self._set_user_rectangle_selection({rectangle_index}, update=False)
                            self._rectangle_drag_indices = (
                                set(self.selected_user_rectangle_indices)
                                if self._rectangle_drag_mode == "move"
                                else {rectangle_index}
                            )
                            self._rectangle_drag_index = rectangle_index
                        self._rectangle_drag_last_pos = event.position()
                        self.selected_bar_date = ""
                        self.update()
                        event.accept()
                        return
                    hit_line = self._hit_user_line(chart_rect, event.position())
                    if hit_line:
                        line_index, self._line_drag_mode = hit_line
                        duplicate_drag = bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
                        if duplicate_drag and self._line_drag_mode == "move":
                            if line_index not in self.selected_user_line_indices:
                                self._clear_user_line_selection(update=False)
                                self._set_user_line_selection({line_index}, update=False)
                            copied_indices, _copied_rectangles = self._duplicate_selected_annotations(offset_slots=0)
                            self._line_drag_indices = set(copied_indices)
                            self._line_drag_index = copied_indices[-1] if copied_indices else line_index
                        else:
                            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                                self._toggle_user_line_selection(line_index)
                            else:
                                self._set_user_rectangle_selection(set(), update=False)
                                self._set_user_line_selection({line_index}, update=False)
                            self._line_drag_indices = set(self.selected_user_line_indices) if self._line_drag_mode == "move" else {line_index}
                            self._line_drag_index = line_index
                        self._line_drag_last_pos = event.position()
                        self.selected_bar_date = ""
                        self.update()
                        event.accept()
                        return
                    slot = self._hit_candle_slot(chart_rect, event.pos().x(), event.pos().y())
                    if slot is None:
                        self.selected_bar_date = ""
                        self._clear_user_line_selection(update=False)
                        self._marquee_start_pos = event.position()
                        self._marquee_current_pos = event.position()
                    else:
                        self.selected_bar_date = self.bars[slot].date
                        self._clear_user_line_selection(update=False)
                    self.update()
                    event.accept()
                    return
        if event.button() == Qt.MouseButton.RightButton:
            chart_rect, pane_rects = self._layout_areas()
            if chart_rect.contains(event.pos()) and self._open_test_trade_reset_menu(
                chart_rect,
                event.position(),
                event.globalPos(),
            ):
                event.accept()
                return
            if any(pane_rect.contains(event.pos()) for pane_rect in pane_rects):
                self._open_sub_pane_count_menu(event.globalPos())
                event.accept()
                return
            if self.bars and self._marquee_start_pos is not None and self._marquee_current_pos is not None:
                chart_rect, _volume_rect, _macd_rect = self._areas()
                marquee_rect = self._marquee_rect()
                if marquee_rect is not None and marquee_rect.width() >= MARQUEE_MIN_SIZE and marquee_rect.height() >= MARQUEE_MIN_SIZE:
                    rectangle_index = self._add_user_rectangle(chart_rect, marquee_rect.intersected(chart_rect))
                    self._marquee_start_pos = None
                    self._marquee_current_pos = None
                    self._pending_rectangle_rect = None
                    self._begin_user_rectangle_rotation(chart_rect, rectangle_index, event.position())
                    self._rectangle_rotate_requires_both_buttons = True
                    self.update()
                    event.accept()
                    return
            if self.bars and self._pending_rectangle_rect is not None:
                chart_rect, _volume_rect, _macd_rect = self._areas()
                if chart_rect.contains(event.pos()):
                    pending_rect = self._pending_rectangle_rect.intersected(chart_rect)
                    self._pending_rectangle_rect = None
                    if pending_rect.width() >= MARQUEE_MIN_SIZE and pending_rect.height() >= MARQUEE_MIN_SIZE:
                        self._add_user_rectangle(chart_rect, pending_rect)
                    self.update()
                    event.accept()
                    return
            self._last_drag_pos = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def _open_test_trade_reset_menu(
        self,
        chart_rect: QRectF,
        point: QPointF,
        global_pos: QPoint,
    ) -> bool:
        if not getattr(self.parent_window, "test_trade_active", False):
            return False
        if not any(
            strip_rect.contains(point)
            for strip_rect, _text, _color in self._completed_trade_cycle_result_strip_items(chart_rect)
        ):
            return False
        menu = QMenu(self)
        clear_action = menu.addAction("清空全部")
        selected_action = menu.exec(global_pos)
        if selected_action == clear_action and hasattr(self.parent_window, "exit_test_trade_mode"):
            self.parent_window.exit_test_trade_mode()
        return True

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pane_resize_separator_index is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._resize_panes_to(event.position().y())
            event.accept()
            return
        if event.buttons() == Qt.MouseButton.NoButton:
            if self._separator_hit_index(event.position()) is not None:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.unsetCursor()
        hover_changed = self._update_hover_price_position(event.position())
        hover_changed = self._update_sub_pane_hover(event.position()) or hover_changed
        if event.buttons() & Qt.MouseButton.MiddleButton and self._middle_press_pos is not None:
            if self._middle_gesture == "" and (event.position() - self._middle_press_pos).manhattanLength() >= 8:
                self._middle_gesture = "moved"
                self._middle_longpress_timer.stop()
        if event.buttons() == Qt.MouseButton.NoButton:
            hover_changed = self._update_hover_user_rectangle(event.position()) or hover_changed
        both_buttons = Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton
        rotate_buttons_held = (
            event.buttons() & both_buttons == both_buttons
            if self._rectangle_rotate_requires_both_buttons
            else bool(event.buttons() & Qt.MouseButton.LeftButton)
        )
        if self._rectangle_rotate_index is not None and rotate_buttons_held:
            chart_rect, _volume_rect, _macd_rect = self._areas()
            self._rotate_user_rectangle(chart_rect, event.position())
            self.update()
            event.accept()
            return
        if self._rectangle_drag_index is not None and event.buttons() & Qt.MouseButton.LeftButton:
            chart_rect, _volume_rect, _macd_rect = self._areas()
            self._drag_user_rectangle(chart_rect, event.position())
            self.update()
            event.accept()
            return
        if self._line_drag_index is not None and event.buttons() & Qt.MouseButton.LeftButton:
            chart_rect, _volume_rect, _macd_rect = self._areas()
            self._drag_user_line(chart_rect, event.position())
            self.update()
            event.accept()
            return
        if self._marquee_start_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._marquee_current_pos = event.position()
            self.update()
            event.accept()
            return
        if self._last_drag_pos is not None and event.buttons() & Qt.MouseButton.RightButton:
            delta = event.position().x() - self._last_drag_pos.x()
            chart_rect, _volume_rect, _macd_rect = self._areas()
            # Match the horizontal spacing used by _x_for_slot at every zoom.
            slot_width = self._plot_rect(chart_rect).width() / max(1, self._slot_axis_count() - 1)
            steps = int(abs(delta) / slot_width + 1e-9)
            if steps:
                if delta > 0:
                    self.parent_window.pan_left(steps)
                else:
                    self.parent_window.pan_right(steps)
                # Keep sub-candle movement so frequent small events accumulate.
                consumed = steps * slot_width * (1 if delta > 0 else -1)
                self._last_drag_pos = QPointF(self._last_drag_pos.x() + consumed, event.position().y())
            elif hover_changed:
                self.update()
            event.accept()
            return
        if hover_changed:
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._pane_resize_separator_index is None:
            self.unsetCursor()
        if self._hover_chart_pos is not None or self._hover_user_rectangle_index is not None or self._sub_pane_hover is not None:
            self._hover_chart_pos = None
            self._hover_user_rectangle_index = None
            self._sub_pane_hover = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_press_pos = None
            self._middle_gesture = ""
            self._middle_longpress_timer.stop()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pane_resize_separator_index is not None:
            self._pane_resize_separator_index = None
            self._pane_resize_start_y = 0.0
            self._pane_resize_start_sizes = []
            self.unsetCursor()
            if hasattr(self.parent_window, "save_chart_preferences"):
                self.parent_window.save_chart_preferences()
            event.accept()
            return
        if self._rectangle_rotate_index is not None and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        ):
            self._rectangle_rotate_index = None
            self._rectangle_rotate_start_angle = 0.0
            self._rectangle_rotate_base_degrees = 0.0
            self._rectangle_rotate_requires_both_buttons = False
            self._hover_user_rectangle_index = None
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._rectangle_drag_index is not None:
            self._rectangle_drag_index = None
            self._rectangle_drag_indices = set()
            self._rectangle_drag_mode = ""
            self._rectangle_drag_last_pos = None
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._line_drag_index is not None:
            self._line_drag_index = None
            self._line_drag_indices = set()
            self._line_drag_mode = ""
            self._line_drag_last_pos = None
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._marquee_start_pos is not None:
            chart_rect, _volume_rect, _macd_rect = self._areas()
            marquee_rect = self._marquee_rect()
            self._marquee_start_pos = None
            self._marquee_current_pos = None
            if marquee_rect is not None and marquee_rect.width() >= MARQUEE_MIN_SIZE and marquee_rect.height() >= MARQUEE_MIN_SIZE:
                self._pending_rectangle_rect = marquee_rect.intersected(chart_rect)
                self._select_user_annotations_in_rect(chart_rect, marquee_rect)
            else:
                self._pending_rectangle_rect = None
                self._clear_user_line_selection(update=False)
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._last_drag_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            chart_rect, _pane_rects = self._layout_areas()
            if chart_rect.contains(event.pos()):
                slot = self._hit_candle_body_slot(
                    chart_rect,
                    event.position().x(),
                    event.position().y(),
                )
                if slot is not None and hasattr(self.parent_window, "start_test_trade_from_bar"):
                    self.parent_window.start_test_trade_from_bar(self.bars[slot].date)
                    event.accept()
                    return
        if event.button() == Qt.MouseButton.LeftButton:
            _chart_rect, pane_rects = self._layout_areas()
            for pane_index, pane_rect in enumerate(pane_rects):
                if self._sub_pane_label_rect(pane_rect).contains(event.pos()):
                    indicator = self.sub_pane_indicators[pane_index]
                    if indicator == "macd":
                        self._edit_macd_parameters(pane_index)
                        event.accept()
                        return
                    if indicator == "kdj":
                        self._edit_kdj_parameters(pane_index)
                        event.accept()
                        return
            if _chart_rect.contains(event.pos()):
                hit_rectangle = self._hit_user_rectangle(_chart_rect, event.position())
                if hit_rectangle:
                    rectangle_index, _mode = hit_rectangle
                    del self.user_rectangles[rectangle_index]
                    self._clear_user_line_selection()
                    event.accept()
                    return
                hit_line = self._hit_user_line(_chart_rect, event.position())
                if hit_line:
                    line_index, _mode = hit_line
                    del self.user_lines[line_index]
                    self._clear_user_line_selection()
                    event.accept()
                    return
                slot = self._hit_candle_slot(_chart_rect, event.pos().x(), event.pos().y())
                if slot is None:
                    self._add_user_line(_chart_rect, event.position())
                    self.update()
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Left:
            self.parent_window.pan_left(1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self.parent_window.pan_right(1)
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Up:
            self.parent_window.zoom_in_fully()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Down:
            self.parent_window.zoom_out_fully()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_A:
            self.select_all_user_annotations()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and (self.selected_user_line_indices or self.selected_user_rectangle_indices):
            self.delete_selected_user_annotations()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            self.copy_selected_user_annotations()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_V:
            self.paste_user_annotations()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.parent_window.zoom_in()
            else:
                self.parent_window.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        background = MIDDLE_HOLD_BACKGROUND if self.show_middle_hold_background else self.palette.background
        painter.fillRect(self.rect(), background)
        if not self.bars:
            painter.setPen(self.palette.text)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "开始模拟后显示K线")
            return

        chart_rect, pane_rects = self._layout_areas()
        self._paint_price_range_cache = self._calculate_price_range()
        self._draw_grid(painter, chart_rect, rows=7, show_time_marks=True)
        for pane_rect in pane_rects:
            self._draw_grid(painter, pane_rect, rows=3)
        self._draw_price_axis(painter, chart_rect)
        self._draw_current_day_highlight(painter, chart_rect)
        self._draw_candles(painter, chart_rect)
        self._draw_index_overlay(painter, chart_rect)
        self._draw_main_overlay(painter, chart_rect)
        self._sub_pane_label_hits = {}
        self._volume_ma_legend_hits_by_pane = {}
        for pane_index, pane_rect in enumerate(pane_rects):
            self._draw_sub_pane(painter, pane_rect, pane_index)
        self._draw_pre_trade_history_overlay(painter, chart_rect)
        for pane_rect in pane_rects:
            self._draw_pre_trade_history_overlay(painter, pane_rect)
        self._draw_completed_trade_cycle_overlays(painter, chart_rect)
        for pane_rect in pane_rects:
            self._draw_completed_trade_cycle_overlays(painter, pane_rect)
        self._draw_max_drawdown_overlay(painter, chart_rect, pane_rects)
        self._draw_pre_trade_history_boundary(painter, chart_rect)
        for pane_rect in pane_rects:
            self._draw_pre_trade_history_boundary(painter, pane_rect)
        self._draw_completed_trade_cycle_boundaries(painter, chart_rect)
        for pane_rect in pane_rects:
            self._draw_completed_trade_cycle_boundaries(painter, pane_rect)
        self._draw_completed_trade_cycle_result_strips(painter, chart_rect)
        self._draw_active_trade_holding_strip(painter, chart_rect)
        self._draw_completed_trade_cycle_hold_tip(painter, chart_rect)
        self._draw_reference_lines(painter, chart_rect)
        self._draw_trade_markers(painter, chart_rect)
        self._draw_selected_bar_tip(painter, chart_rect)
        self._draw_current_phase_marker(painter, chart_rect)
        self._draw_user_lines(painter, chart_rect)
        self._draw_user_rectangles(painter, chart_rect)
        self._draw_marquee(painter)
        self._draw_hover_price_tag(painter, chart_rect)
        self._draw_sub_pane_separators(painter)
        self._paint_price_range_cache = None

    def _draw_sub_pane_separators(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#243447"), 1, Qt.PenStyle.SolidLine))
        right = int(self.width())
        for boundary in self._separator_y_positions():
            painter.drawLine(0, int(boundary), right, int(boundary))

    def _on_middle_longpress(self) -> None:
        if self._middle_gesture == "":
            self._middle_gesture = "solid_background"
            self.show_middle_hold_background = not self.show_middle_hold_background
            self.update()

    def _layout_areas(self) -> tuple[QRectF, list[QRectF]]:
        width = self.width()
        height = self.height()
        left = 0
        right_axis = 86
        top = 0
        bottom = 0
        pane_count = len(self.sub_pane_indicators)
        usable_height = max(1.0, height - top - bottom - PANE_GAP * pane_count)
        ratios = list(self.pane_height_ratios)
        if len(ratios) != pane_count + 1 or sum(ratios) <= 0:
            ratios = self._default_pane_height_ratios(pane_count)
        sizes = [usable_height * ratio / sum(ratios) for ratio in ratios]
        minimums = [min(150.0, max(90.0, usable_height * 0.24))]
        minimums.extend(min(88.0, max(52.0, usable_height * 0.10)) for _ in range(pane_count))
        sizes = self._constrain_pane_sizes(sizes, minimums, usable_height)
        chart_width = max(1.0, width - left - right_axis)
        chart = QRectF(left, top, chart_width, sizes[0])
        panes: list[QRectF] = []
        y = chart.bottom() + PANE_GAP
        for pane_height in sizes[1:]:
            panes.append(QRectF(left, y, chart_width, pane_height))
            y += pane_height + PANE_GAP
        return chart, panes

    @staticmethod
    def _constrain_pane_sizes(sizes: list[float], minimums: list[float], total: float) -> list[float]:
        if not sizes:
            return []
        minimum_total = sum(minimums)
        if minimum_total > total:
            scale = total / minimum_total if minimum_total else 1.0
            return [value * scale for value in minimums]
        result = list(sizes)
        fixed: set[int] = set()
        while True:
            newly_fixed = {index for index, value in enumerate(result) if index not in fixed and value < minimums[index]}
            if not newly_fixed:
                break
            fixed.update(newly_fixed)
            for index in newly_fixed:
                result[index] = minimums[index]
            remaining_indices = [index for index in range(len(result)) if index not in fixed]
            remaining_total = total - sum(result[index] for index in fixed)
            current_total = sum(max(0.0, sizes[index]) for index in remaining_indices)
            if not remaining_indices:
                break
            if current_total <= 0:
                share = remaining_total / len(remaining_indices)
                for index in remaining_indices:
                    result[index] = share
            else:
                for index in remaining_indices:
                    result[index] = remaining_total * max(0.0, sizes[index]) / current_total
        difference = total - sum(result)
        result[0] += difference
        return result

    def _areas(self) -> tuple[QRectF, QRectF, QRectF]:
        """Compatibility helper for callers that still expect the original two panes."""
        chart, panes = self._layout_areas()
        empty = QRectF(chart.left(), chart.bottom() + PANE_GAP, chart.width(), 0)
        first = panes[0] if panes else empty
        second = panes[1] if len(panes) > 1 else empty
        return chart, first, second

    def _separator_y_positions(self) -> list[float]:
        _chart, panes = self._layout_areas()
        return [pane.top() - PANE_GAP / 2 for pane in panes]

    def _separator_hit_index(self, point: QPointF) -> int | None:
        if point.x() < 0 or point.x() > self.width():
            return None
        for index, y in enumerate(self._separator_y_positions()):
            if abs(point.y() - y) <= PANE_SEPARATOR_HIT_RADIUS:
                return index
        return None

    def _resize_panes_to(self, cursor_y: float) -> None:
        index = self._pane_resize_separator_index
        if index is None or len(self._pane_resize_start_sizes) != len(self.sub_pane_indicators) + 1:
            return
        sizes = list(self._pane_resize_start_sizes)
        delta = cursor_y - self._pane_resize_start_y
        total = sum(sizes)
        main_minimum = min(150.0, max(90.0, total * 0.24))
        sub_minimum = min(88.0, max(52.0, total * 0.10))
        upper_minimum = main_minimum if index == 0 else sub_minimum
        lower_minimum = sub_minimum
        delta = max(upper_minimum - sizes[index], min(delta, sizes[index + 1] - lower_minimum))
        sizes[index] += delta
        sizes[index + 1] -= delta
        if total > 0:
            self.pane_height_ratios = [value / total for value in sizes]
            self.update()

    def _plot_rect(self, rect: QRectF) -> QRectF:
        reserve = min(RIGHT_REFERENCE_AREA_WIDTH, max(70, int(rect.width() * 0.28)))
        return QRectF(rect.left(), rect.top(), max(1.0, rect.width() - reserve), rect.height())

    def _draw_grid(self, painter: QPainter, rect: QRectF, rows: int, show_time_marks: bool = False) -> None:
        painter.setPen(QPen(self.palette.grid, 1, Qt.PenStyle.DotLine))
        for row in range(rows + 1):
            y = rect.top() + rect.height() * row / rows
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
        if show_time_marks:
            self._draw_time_grid(painter, rect)
            return
        step = max(10, len(self.bars) // 8 or 1)
        for col in range(0, len(self.bars), step):
            x = self._x_for_slot(rect, col)
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))

    def _draw_time_grid(self, painter: QPainter, rect: QRectF) -> None:
        if len(self.bars) < 2:
            return
        painter.setFont(QFont("Consolas", 9))
        last_label_x = -999.0
        for slot, bar in enumerate(self.bars):
            previous = self.bars[slot - 1] if slot > 0 else None
            is_year = previous is None or bar.date[:4] != previous.date[:4]
            is_month = previous is None or bar.date[:7] != previous.date[:7]
            if not is_month:
                continue
            x = self._x_for_slot(rect, slot)
            painter.setPen(self._time_grid_pen(is_year))
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            if x - last_label_x < 42:
                continue
            if not self.show_time_marks:
                continue
            label = bar.date[:4] if is_year else bar.date[5:7]
            painter.setPen(self.palette.text)
            painter.drawText(int(x + 3), int(rect.bottom() - 6), label)
            last_label_x = x

    @staticmethod
    def _time_grid_pen(is_year: bool) -> QPen:
        color = QColor("#404040") if is_year else QColor("#2b2b2b")
        return QPen(color, 1, Qt.PenStyle.DotLine)

    @staticmethod
    def _average_line_pen(color: QColor) -> QPen:
        pen = QPen(color)
        pen.setWidthF(AVERAGE_LINE_WIDTH)
        return pen

    @staticmethod
    def _completed_trade_cycle_boundary_pen() -> QPen:
        return QPen(QColor(255, 255, 255, 72), 1, Qt.PenStyle.SolidLine)

    def _draw_price_axis(self, painter: QPainter, rect: QRectF) -> None:
        low, high = self._price_range()
        painter.setFont(QFont("Consolas", 10))
        painter.setPen(self.palette.text)
        for row in range(7):
            price = high - (high - low) * row / 6
            y = rect.top() + rect.height() * row / 6
            painter.drawText(self._price_axis_label_rect(rect, y).toRect(), Qt.AlignmentFlag.AlignCenter, f"{price:.2f}")

    def _price_axis_label_rect(self, rect: QRectF, center_y: float) -> QRectF:
        width, height = PRICE_AXIS_LABEL_SIZE
        left = rect.right() + 4
        available_width = max(1, self.width() - left - 4)
        width = min(width, available_width)
        top = center_y - height / 2
        top = max(rect.top() + 2, min(rect.bottom() - height - 2, top))
        return QRectF(left, top, width, height)

    def _draw_hover_price_tag(self, painter: QPainter, rect: QRectF) -> None:
        tag_rect = self._hover_price_tag_rect(rect)
        text = self._hover_price_text(rect)
        if tag_rect is None or text is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b2634"))
        painter.drawRoundedRect(tag_rect, 4, 4)
        painter.setFont(self._hover_price_font())
        painter.setPen(QColor("#e6edf3"))
        painter.drawText(tag_rect.toRect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _draw_candles(self, painter: QPainter, rect: QRectF) -> None:
        low, high = self._price_range()
        candle_width = self._candle_width(rect)
        full_bars_by_date = self._date_indices()
        for slot, bar in enumerate(self.bars):
            x = self._x_for_slot(rect, slot)
            is_current_hidden = self._is_current_hidden(bar)
            display_high, display_low, display_close = self._display_prices(bar)
            y_high = self._price_y(rect, display_high, low, high)
            y_low = self._price_y(rect, display_low, low, high)
            y_open = self._price_y(rect, bar.open, low, high)
            y_close = self._price_y(rect, display_close, low, high)
            prev_index = full_bars_by_date.get(bar.date, 0) - 1
            prev_close = self.all_bars[prev_index].close if prev_index >= 0 else None
            color = self._bar_color(bar, prev_close, is_current_hidden)
            if self._should_draw_candle_body(is_current_hidden):
                painter.setPen(QPen(color, 1))
                painter.drawLine(int(x), int(y_high), int(x), int(y_low))
                body_top = min(y_open, y_close)
                body_bottom = max(y_open, y_close)
                body_height = max(2, body_bottom - body_top)
                body_rect = QRectF(x - candle_width / 2, body_top, candle_width, body_height)
                state = candle_state(bar, prev_close)
                if candle_body_is_filled(state):
                    painter.fillRect(body_rect, color)
                else:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(body_rect)
            if is_current_hidden and self._hidden_open_line_visible:
                painter.setPen(self._hidden_open_line_pen(bar, prev_close))
                start_x, end_x = self._hidden_open_line_segment(rect, slot, x, candle_width)
                painter.drawLine(int(start_x), int(y_open), int(end_x), int(y_open))

    def _draw_index_overlay(self, painter: QPainter, rect: QRectF) -> None:
        if not self.index_overlay_bars or not self.bars:
            return
        overlay_by_date = {bar.date: bar for bar in self.index_overlay_bars}
        visible = [(slot, overlay_by_date.get(stock_bar.date)) for slot, stock_bar in enumerate(self.bars)]
        visible = [(slot, bar) for slot, bar in visible if bar is not None]
        if not visible:
            return
        low = min(bar.low for _slot, bar in visible)
        high = max(bar.high for _slot, bar in visible)
        span = max(0.01, high - low)
        low -= span * 0.04
        high += span * 0.04
        candle_width = max(2.0, self._candle_width(rect) * 0.72)
        all_indices = {bar.date: index for index, bar in enumerate(self.index_overlay_bars)}
        for slot, bar in visible:
            index = all_indices[bar.date]
            previous_close = self.index_overlay_bars[index - 1].close if index > 0 else None
            color = self._index_overlay_color(bar, previous_close)
            x = self._x_for_slot(rect, slot)
            y_open = self._price_y(rect, bar.open, low, high)
            if bar.date == self.index_overlay_current_date and not self.index_overlay_reveal_current_full:
                painter.setPen(QPen(color, 2))
                painter.drawLine(int(x - candle_width / 2), int(y_open), int(x + candle_width / 2), int(y_open))
                continue
            y_high = self._price_y(rect, bar.high, low, high)
            y_low = self._price_y(rect, bar.low, low, high)
            y_close = self._price_y(rect, bar.close, low, high)
            painter.setPen(QPen(color, 1))
            painter.drawLine(int(x), int(y_high), int(x), int(y_low))
            body_top = min(y_open, y_close)
            body_height = max(2.0, abs(y_close - y_open))
            painter.fillRect(QRectF(x - candle_width / 2, body_top, candle_width, body_height), color)

    @staticmethod
    def _index_overlay_color(bar: DailyBar, previous_close: float | None) -> QColor:
        is_up = previous_close is None or bar.close >= previous_close
        return QColor(218, 218, 218, 112) if is_up else QColor(72, 72, 72, 138)

    @staticmethod
    def _should_draw_candle_body(is_current_hidden: bool) -> bool:
        return not is_current_hidden

    def _hidden_open_line_pen(self, bar: DailyBar, prev_close: float | None) -> QPen:
        color = self.palette.down if prev_close is not None and bar.open < prev_close else self.palette.up
        return QPen(color, 2, Qt.PenStyle.SolidLine)

    def _toggle_hidden_open_line_blink(self) -> None:
        self._hidden_open_line_visible = not self._hidden_open_line_visible
        if any(self._is_current_hidden(bar) for bar in self.bars):
            self.update()

    def _draw_main_overlay(self, painter: QPainter, rect: QRectF) -> None:
        low, high = self._price_range()
        if self.main_overlay_mode == "boll":
            self._draw_boll_lines(painter, rect, low, high)
        elif self.main_overlay_mode == "gma":
            self._draw_gma_lines(painter, rect, low, high)
        elif self.main_overlay_mode == "ma":
            self._draw_ma_lines(painter, rect, low, high)
        self._draw_main_legend(painter, rect)

    def _draw_ma_lines(self, painter: QPainter, rect: QRectF, low: float, high: float) -> None:
        self._ensure_ma_cache()
        visible_start = self._visible_start_index()
        slot_count = self._slot_axis_count()
        plot_rect = self._plot_rect(rect)
        leading_slots = self._leading_empty_slots()
        slot_step = plot_rect.width() / (slot_count - 1) if slot_count > 1 else 0.0
        visible_x = [plot_rect.left() + slot_step * (leading_slots + slot) for slot in range(len(self.bars))]
        for period, color in ((5, self.palette.ma5), (10, self.palette.ma10), (20, self.palette.ma20),
                              (60, self.palette.ma60), (120, self.palette.ma120), (250, self.palette.ma250)):
            if period in self.hidden_ma_periods:
                continue
            painter.setPen(self._average_line_pen(color))
            path = QPainterPath()
            has_point = False
            for slot, _bar in enumerate(self.bars):
                index = visible_start + slot
                value = self._ma_value_for_index(period, index)
                if value is None:
                    has_point = False
                    continue
                point = QPointF(visible_x[slot], self._price_y(rect, value, low, high))
                if has_point:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                    has_point = True
            painter.drawPath(path)

    @staticmethod
    def _bar_series_signature(bars: list[DailyBar]) -> tuple[int, DailyBar | None, DailyBar | None]:
        if not bars:
            return 0, None, None
        return len(bars), bars[0], bars[-1]

    def _ensure_ma_cache(self) -> None:
        signature = self._bar_series_signature(self.all_bars)
        if self._ma_cache_source is self.all_bars and self._ma_cache_signature == signature:
            return
        closes = [float(bar.close) for bar in self.all_bars]
        prefix = [0.0]
        running_total = 0.0
        for close in closes:
            running_total += close
            prefix.append(running_total)
        self._ma_cache_source = self.all_bars
        self._ma_cache_signature = signature
        self._ma_close_prefix = prefix
        self._ma_series_cache = {period: moving_average(closes, period) for period in MAIN_MA_PERIODS}

    def _ma_value_for_index(self, period: int, index: int) -> float | None:
        values = self._ma_series_cache.get(period)
        if values is None or index < 0 or index >= len(values):
            return None
        value = values[index]
        if value is None or index != self.current_index or self.pan_offset != 0 or self.reveal_current_full:
            return value
        window_start = index - period + 1
        if window_start < 0:
            return None
        raw_total = self._ma_close_prefix[index + 1] - self._ma_close_prefix[window_start]
        bar = self.all_bars[index]
        return round((raw_total - bar.close + bar.open) / period, 3)

    def _boll_series(self) -> tuple[list[float | None], list[float | None], list[float | None]]:
        return self._cached_series(("boll", self.boll_n, self.boll_k), self._calculate_boll_series)

    def _cached_series(self, key, calculate):
        # DailyBar is immutable. Comparing snapshots also detects replacement
        # of a middle candle, unlike a signature containing only the endpoints.
        hidden = self.current_index if self.pan_offset == 0 and not self.reveal_current_full else None
        context = (tuple(self.all_bars), hidden)
        if getattr(self, "_series_context", None) != context:
            self._series_context = context
            self._series_results = {}
        if key not in self._series_results:
            if len(self._series_results) >= 32:
                self._series_results.clear()
            self._series_results[key] = calculate()
        return self._series_results[key]

    def _date_indices(self):
        return self._cached_series(("dates",), lambda: {bar.date: i for i, bar in enumerate(self.all_bars)})

    def _calculate_boll_series(self):
        closes = [self._display_close(bar) for bar in self.all_bars]
        n = self.boll_n
        k = self.boll_k
        mid: list[float | None] = [None] * len(closes)
        upper: list[float | None] = [None] * len(closes)
        lower: list[float | None] = [None] * len(closes)
        mean = variance_sum = 0.0
        for index, value in enumerate(closes):
            if index >= n:
                previous_mean = mean
                mean += (mean - closes[index - n]) / (n - 1) if n > 1 else -mean
                variance_sum -= (closes[index - n] - previous_mean) * (closes[index - n] - mean)
            count = min(index + 1, n)
            delta = value - mean
            mean += delta / count
            variance_sum += delta * (value - mean)
            if index + 1 < n:
                continue
            sd = math.sqrt(max(0.0, variance_sum / n))
            mid[index] = mean
            upper[index] = mean + k * sd
            lower[index] = mean - k * sd
        return mid, upper, lower

    def _draw_boll_lines(self, painter: QPainter, rect: QRectF, low: float, high: float) -> None:
        mid, upper, lower = self._boll_series()
        indices = self._date_indices()
        x_positions = [self._x_for_slot(rect, slot) for slot in range(len(self.bars))]
        for series, color in ((mid, self.palette.boll_mid), (upper, self.palette.boll_upper), (lower, self.palette.boll_lower)):
            painter.setPen(self._average_line_pen(color))
            last_point = None
            for slot, bar in enumerate(self.bars):
                index = indices.get(bar.date)
                value = series[index] if index is not None else None
                if value is None:
                    last_point = None
                    continue
                point = (x_positions[slot], self._price_y(rect, value, low, high))
                if last_point:
                    painter.drawLine(int(last_point[0]), int(last_point[1]), int(point[0]), int(point[1]))
                last_point = point

    def _gma_period_styles(self) -> list[tuple[int, QColor]]:
        short = (3, 5, 8, 10, 12, 15)
        long = (30, 35, 40, 45, 50, 60)
        return [(period, self.palette.gma_short) for period in short] + [(period, self.palette.gma_long) for period in long]

    def _draw_gma_lines(self, painter: QPainter, rect: QRectF, low: float, high: float) -> None:
        indices = self._date_indices()
        closes = self._cached_series(("closes",), lambda: [self._display_close(bar) for bar in self.all_bars])
        x_positions = [self._x_for_slot(rect, slot) for slot in range(len(self.bars))]
        for period, color in self._gma_period_styles():
            values = self._cached_series(("ema", period), lambda: self._ema(closes, period))
            painter.setPen(self._average_line_pen(color))
            last_point = None
            for slot, bar in enumerate(self.bars):
                index = indices.get(bar.date)
                if index is None:
                    last_point = None
                    continue
                value = values[index]
                point = (x_positions[slot], self._price_y(rect, value, low, high))
                if last_point:
                    painter.drawLine(int(last_point[0]), int(last_point[1]), int(point[0]), int(point[1]))
                last_point = point

    def _draw_main_legend(self, painter: QPainter, rect: QRectF) -> None:
        self._ma_legend_hits = {}
        self._boll_legend_hit = None
        self._gma_legend_hit = None
        x = int(rect.left() + 6)
        y = int(rect.top() + 18)
        line_height = 16
        gap = 12
        right_limit = int(self._plot_rect(rect).right())
        base_font = QFont("Consolas", 9)
        metrics = QFontMetrics(base_font)

        def place(text: str, color: QColor, flashing: bool) -> QRectF:
            nonlocal x, y
            width = metrics.horizontalAdvance(text)
            if x + width > right_limit:
                x = int(rect.left() + 6)
                y += line_height
            hit = QRectF(x, y - 15, width + 6, 20)
            if flashing:
                painter.setPen(QColor("#ffffff"))
                painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            else:
                painter.setPen(color)
                painter.setFont(base_font)
            painter.drawText(x, y, text)
            x += width + gap
            return hit

        ma_active = self.main_overlay_mode == "ma"
        for label, period, color in (("MA5", 5, self.palette.ma5), ("MA10", 10, self.palette.ma10),
                                     ("MA20", 20, self.palette.ma20), ("MA60", 60, self.palette.ma60),
                                     ("MA120", 120, self.palette.ma120), ("MA250", 250, self.palette.ma250)):
            dimmed = (not ma_active) or period in self.hidden_ma_periods
            display_color = self.palette.axis if dimmed else color
            hit = place(label, display_color, self._is_label_flashing(f"ma_{period}"))
            self._ma_legend_hits[period] = hit

        boll_active = self.main_overlay_mode == "boll"
        boll_label = f"BOLL({self.boll_n},{self.boll_k:g})"
        self._boll_legend_hit = place(boll_label, self.palette.boll_upper if boll_active else self.palette.axis, self._is_label_flashing("boll"))

        gma_active = self.main_overlay_mode == "gma"
        self._gma_legend_hit = place("GMA", self.palette.gma_long if gma_active else self.palette.axis, self._is_label_flashing("gma"))

    def _draw_trade_markers(self, painter: QPainter, rect: QRectF) -> None:
        date_to_slot = {bar.date: slot for slot, bar in enumerate(self.bars)}
        date_to_bar = {bar.date: bar for bar in self.bars}
        date_to_trades: dict[str, list[TradeResult]] = {}
        for trade in self.trades:
            if trade.date in date_to_slot:
                date_to_trades.setdefault(trade.date, []).append(trade)
        painter.setFont(self._trade_marker_font())
        for date, trades in date_to_trades.items():
            if self._trade_marker_text_for_trades(trades) == "T":
                self._draw_trade_marker(painter, rect, date_to_slot[date], date_to_bar[date], trades[-1], "T", self.palette.marker_t)
                continue
            for trade in trades:
                text = self._trade_marker_text_for_trades([trade])
                color = self.palette.marker_buy if trade.side == "buy" else self.palette.marker_sell
                self._draw_trade_marker(painter, rect, date_to_slot[date], date_to_bar[date], trade, text, color)

    def _draw_trade_marker(self, painter: QPainter, rect: QRectF, slot: int, bar: DailyBar, trade: TradeResult, text: str, color: QColor) -> None:
        x = self._x_for_slot(rect, slot)
        marker_position = trade_marker_position_for_trade(bar, trade.side, trade.node)
        y = self._trade_marker_y(rect, bar, trade.node, marker_position)
        marker_rect = self._trade_marker_rect(x, y)
        painter.setBrush(color)
        painter.setPen(color)
        painter.drawEllipse(marker_rect)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(marker_rect.toRect(), Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _trade_marker_font() -> QFont:
        return QFont("Consolas", 9, QFont.Weight.DemiBold)

    @staticmethod
    def _trade_marker_rect(x: float, y: float) -> QRectF:
        marker_size = float(TRADE_MARKER_SIZE)
        return QRectF(x - marker_size / 2, y - marker_size / 2, marker_size, marker_size)

    @staticmethod
    def _trade_marker_text_for_trades(trades: list[TradeResult]) -> str:
        sides = {trade.side for trade in trades}
        if "buy" in sides and "sell" in sides:
            return "T"
        if "buy" in sides:
            return "B"
        if "sell" in sides:
            return "S"
        return ""

    def _draw_reference_lines(self, painter: QPainter, rect: QRectF) -> None:
        specs = self._reference_line_specs()
        if not specs:
            return
        low, high = self._price_range()
        plot_rect = self._plot_rect(rect)
        line_start_x = self._reference_line_start_x(rect)
        label_rects = self._reference_label_rects(rect, specs)
        painter.setFont(self._reference_label_font())
        for spec, label_rect in zip(specs, label_rects):
            y = self._price_y(rect, spec.price, low, high)
            line_end_x = max(line_start_x, label_rect.left() - 6)
            painter.setPen(QPen(spec.color, REFERENCE_LINE_WIDTH, Qt.PenStyle.DashLine))
            painter.drawLine(int(line_start_x), int(y), int(line_end_x), int(y))
            if line_end_x < plot_rect.right():
                painter.drawLine(int(label_rect.right() + 6), int(y), int(plot_rect.right()), int(y))
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setBrush(QColor("#05080d"))
            painter.setPen(QPen(spec.color, 1))
            painter.drawRoundedRect(label_rect, 5, 5)
            painter.setPen(spec.color)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, spec.label)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _reference_line_specs(self) -> list[ReferenceLineSpec]:
        if self.average_cost_price is None or self.average_cost_price <= 0:
            return []
        return [
            ReferenceLineSpec("持仓均价", self.average_cost_price, self.palette.average_cost),
        ]

    def _reference_label_size(self) -> tuple[int, int]:
        return REFERENCE_LABEL_SIZE

    @staticmethod
    def _reference_label_font() -> QFont:
        return QFont("Microsoft YaHei", 10, QFont.Weight.Bold)

    def _reference_label_rects(self, rect: QRectF, specs: list[ReferenceLineSpec]) -> list[QRectF]:
        width, height = self._reference_label_size()
        x = rect.right() - width - 8
        low, high = self._price_range()
        centers = [self._price_y(rect, spec.price, low, high) for spec in specs]
        centers = [min(max(center, rect.top() + height / 2 + 4), rect.bottom() - height / 2 - 4) for center in centers]
        if len(centers) == 2 and abs(centers[0] - centers[1]) < height + 8:
            middle = sum(centers) / 2
            centers[0] = min(max(middle - height / 2 - 4, rect.top() + height / 2 + 4), rect.bottom() - height / 2 - 4)
            centers[1] = min(max(middle + height / 2 + 4, rect.top() + height / 2 + 4), rect.bottom() - height / 2 - 4)
        return [QRectF(x, center - height / 2, width, height) for center in centers]

    def _reference_line_start_x(self, rect: QRectF) -> float:
        return rect.left()

    def _trade_marker_y(self, rect: QRectF, bar: DailyBar, node, marker_position: str) -> float:
        low, high = self._price_range()
        anchor_price = bar.open if self._is_current_hidden(bar) or node == TradeNode.OPEN else bar.close
        anchor_y = self._price_y(rect, anchor_price, low, high)
        if marker_position == "below":
            return min(rect.bottom() - 4, anchor_y + 18)
        return max(rect.top() + 12, anchor_y - 10)

    def _draw_selected_bar_tip(self, painter: QPainter, rect: QRectF) -> None:
        if not self.selected_bar_date:
            return
        date_to_slot = {bar.date: slot for slot, bar in enumerate(self.bars)}
        if self.selected_bar_date not in date_to_slot:
            return
        slot = date_to_slot[self.selected_bar_date]
        bar = self.bars[slot]
        try:
            full_index = self.all_bars.index(bar)
        except ValueError:
            return
        change, change_pct = change_metrics(self.all_bars, full_index)
        x = self._x_for_slot(rect, slot)
        y = max(rect.top() + 42, self._price_y(rect, bar.high, *self._price_range()) - 26)
        text = f"{bar.date + '  ' if self.show_time_marks else ''}{change:+.2f}  {change_pct:+.2f}%"
        painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        text_width = painter.fontMetrics().horizontalAdvance(text) + 14
        tip_x = min(max(rect.left() + 4, x - text_width / 2), rect.right() - text_width - 4)
        tip_rect = QRectF(tip_x, y - 18, text_width, 22)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._selected_bar_tip_background(change))
        painter.drawRoundedRect(tip_rect, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.palette.tip_text)
        painter.drawText(int(tip_x + 7), int(y - 3), text)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _selected_bar_tip_background(self, change: float) -> QColor:
        return self.palette.tip_up_background if change >= 0 else self.palette.tip_down_background

    def _draw_user_lines(self, painter: QPainter, rect: QRectF) -> None:
        if self.suppress_user_annotations or not self.user_lines:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for index, line in enumerate(self.user_lines):
            p1, p2 = self._user_line_points(rect, line)
            selected = index in self.selected_user_line_indices
            width = SELECTED_USER_LINE_PEN_WIDTH if selected else USER_LINE_PEN_WIDTH
            painter.setPen(QPen(QColor("#ffd21f"), width))
            painter.drawLine(int(p1.x()), int(p1.y()), int(p2.x()), int(p2.y()))
            if selected:
                painter.setBrush(QColor("#ffd21f"))
                painter.setPen(QPen(QColor("#ffd21f"), 1))
                painter.drawEllipse(p1, 4, 4)
                painter.drawEllipse(p2, 4, 4)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _draw_user_rectangles(self, painter: QPainter, rect: QRectF) -> None:
        if self.suppress_user_annotations or not self.user_rectangles:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor("#ffd21f")
        for index, rectangle in enumerate(self.user_rectangles):
            corner_points = self._user_rectangle_corner_points(rect, rectangle)
            selected = index in self.selected_user_rectangle_indices
            width = SELECTED_USER_LINE_PEN_WIDTH if selected else USER_LINE_PEN_WIDTH
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine))
            painter.drawPolygon(QPolygonF(list(corner_points.values())))
            if selected:
                painter.setBrush(color)
                painter.setPen(QPen(color, 1))
                for point in corner_points.values():
                    painter.drawEllipse(point, RECTANGLE_HANDLE_RADIUS, RECTANGLE_HANDLE_RADIUS)
            if index == self._hover_user_rectangle_index:
                self._draw_user_rectangle_rotation_handle(painter, rect, rectangle)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _draw_user_rectangle_rotation_handle(
        self,
        painter: QPainter,
        chart_rect: QRectF,
        rectangle: UserRectangle,
    ) -> None:
        handle_rect = self._user_rectangle_rotation_handle_rect(chart_rect, rectangle)
        color = QColor("#ffd21f")
        painter.setBrush(QColor(0, 0, 0, 220))
        painter.setPen(QPen(color, 1))
        painter.drawEllipse(handle_rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(color, 1))
        painter.setFont(QFont("Segoe UI Symbol", 12, QFont.Weight.Bold))
        painter.drawText(handle_rect, Qt.AlignmentFlag.AlignCenter, "↻")

    def _draw_marquee(self, painter: QPainter) -> None:
        rect = self._marquee_rect() or self._pending_rectangle_rect
        if rect is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#ffd21f"), 1, Qt.PenStyle.DashLine))
        painter.drawRect(rect)

    def _draw_current_day_highlight(self, painter: QPainter, rect: QRectF) -> None:
        highlight = self._current_day_highlight_rect(rect)
        if highlight is None:
            return
        painter.fillRect(highlight.intersected(rect), QColor(255, 59, 48, CURRENT_DAY_HIGHLIGHT_ALPHA))

    def _draw_current_phase_marker(self, painter: QPainter, rect: QRectF) -> None:
        marker = self._current_phase_marker_spec()
        slot = self._current_visible_slot()
        if marker is None or slot is None:
            return
        text, color = marker
        x = self._x_for_slot(rect, slot)
        label_rect = QRectF(x - 14.0, rect.bottom() - 42.0, 28.0, 24.0)
        painter.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold))
        painter.setPen(color)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _current_phase_marker_spec(self) -> tuple[str, QColor] | None:
        if (
            self.current_node is None
            or not self.all_bars
            or self.current_index < 0
            or self.current_index >= len(self.all_bars)
            or self._current_visible_slot() is None
        ):
            return None
        bar = self.all_bars[self.current_index]
        previous_close = self.all_bars[self.current_index - 1].close if self.current_index > 0 else None
        price = bar.open if self.current_node == TradeNode.OPEN else bar.close
        if previous_close is None or previous_close <= 0 or abs(price - previous_close) < 0.000001:
            color = self.palette.text
        else:
            color = self.palette.up if price > previous_close else self.palette.down
        text = "开" if self.current_node == TradeNode.OPEN else "收"
        return text, color

    def _draw_pre_trade_history_overlay(self, painter: QPainter, rect: QRectF) -> None:
        shade = self._pre_trade_history_overlay_rect(rect)
        if shade is None:
            return
        painter.fillRect(shade, self._history_overlay_color())

    def _history_overlay_color(self) -> QColor:
        alpha = (
            MIDDLE_HOLD_HISTORY_OVERLAY_ALPHA
            if self.show_middle_hold_background
            else HISTORY_OVERLAY_ALPHA
        )
        return QColor(8, 12, 18, alpha)

    def _draw_pre_trade_history_boundary(self, painter: QPainter, rect: QRectF) -> None:
        boundary_x = self._pre_trade_history_boundary_x(rect)
        if boundary_x is None:
            return
        painter.setPen(QPen(QColor(255, 255, 255, 72), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(boundary_x), int(rect.top()), int(boundary_x), int(rect.bottom()))

    def _draw_completed_trade_cycle_overlays(self, painter: QPainter, rect: QRectF) -> None:
        for shade in self._completed_trade_cycle_overlay_rects(rect):
            painter.fillRect(shade.intersected(rect), self._history_overlay_color())

    def _draw_max_drawdown_overlay(
        self,
        painter: QPainter,
        rect: QRectF,
        pane_rects: list[QRectF],
    ) -> None:
        details = self._max_drawdown_overlay_details(rect)
        if details is None:
            return
        shade, start_visible, end_visible = details
        painter.fillRect(shade.intersected(rect), QColor(34, 197, 94, 36))
        bottom = pane_rects[-1].bottom() if pane_rects else rect.bottom()
        painter.setPen(QPen(QColor(74, 222, 128, 220), 2, Qt.PenStyle.DashLine))
        if start_visible:
            painter.drawLine(int(shade.left()), int(rect.top()), int(shade.left()), int(bottom))
        if end_visible:
            painter.drawLine(int(shade.right()), int(rect.top()), int(shade.right()), int(bottom))

    def _max_drawdown_overlay_details(self, rect: QRectF) -> tuple[QRectF, bool, bool] | None:
        if self.max_drawdown_range is None or not self.bars:
            return None
        start_index, end_index, _drawdown_pct, _days = self.max_drawdown_range
        shade = self._trade_range_rect(rect, start_index, end_index)
        if shade is None:
            return None
        visible_start = self._visible_start_index()
        visible_end = visible_start + len(self.bars) - 1
        return (
            shade,
            visible_start <= start_index <= visible_end,
            visible_start <= end_index <= visible_end,
        )

    def _draw_completed_trade_cycle_boundaries(self, painter: QPainter, rect: QRectF) -> None:
        boundaries = self._completed_trade_cycle_boundary_xs(rect)
        if not boundaries:
            return
        painter.setPen(self._completed_trade_cycle_boundary_pen())
        for boundary_x in boundaries:
            painter.drawLine(int(boundary_x), int(rect.top()), int(boundary_x), int(rect.bottom()))

    def _draw_completed_trade_cycle_result_strips(self, painter: QPainter, rect: QRectF) -> None:
        items = self._completed_trade_cycle_result_strip_items(rect)
        if not items:
            return
        painter.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        for strip_rect, text, color in items:
            painter.fillRect(strip_rect.intersected(rect), color)
            painter.setPen(QColor("#05080d"))
            painter.drawText(strip_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_completed_trade_cycle_hold_tip(self, painter: QPainter, rect: QRectF) -> None:
        item = self._completed_trade_cycle_hold_tip_item(rect)
        if item is None:
            return
        tip_rect, text = item
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(72, 78, 88, 230))
        painter.drawRoundedRect(tip_rect, 5, 5)
        painter.setFont(QFont("Microsoft YaHei", 9))
        painter.setPen(QColor("#f2f4f7"))
        painter.drawText(tip_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _draw_active_trade_holding_strip(self, painter: QPainter, rect: QRectF) -> None:
        item = self._active_trade_holding_strip_item(rect)
        if item is None:
            return
        strip_rect, text, color = item
        painter.fillRect(strip_rect.intersected(rect), color)
        painter.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        painter.setPen(QColor("#10212d"))
        painter.drawText(strip_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_volume(self, painter: QPainter, rect: QRectF) -> None:
        display_volumes = [0 if self._is_current_hidden(bar) else bar.volume for bar in self.bars]
        max_volume = max(display_volumes, default=1) or 1
        candle_width = self._candle_width(rect)
        for slot, bar in enumerate(self.bars):
            x = self._x_for_slot(rect, slot)
            display_volume = 0 if self._is_current_hidden(bar) else bar.volume
            height = rect.height() * display_volume / max_volume
            color = self.palette.up if self._display_close(bar) >= bar.open else self.palette.down
            painter.fillRect(QRectF(x - candle_width / 2, rect.bottom() - height, candle_width, height), color)

    def _volume_text(self) -> str:
        return "成交量"

    def _latest_revealed_volume(self) -> int:
        for bar in reversed(self.bars):
            if not self._is_current_hidden(bar):
                return bar.volume
        return 0

    def _draw_macd(self, painter: QPainter, rect: QRectF, pane_index: int) -> None:
        closes = [self._display_close(bar) for bar in self.bars]
        dif, dea, macd = self._macd(closes, self.pane_macd_params[pane_index])
        max_abs = max([abs(value) for value in macd + dif + dea if value is not None] or [1])
        max_abs = max_abs or 1.0
        zero_y = rect.center().y()
        candle_width = max(1, self._candle_width(rect) / 2)
        for slot, value in enumerate(macd):
            x = self._x_for_slot(rect, slot)
            y = zero_y - value / max_abs * rect.height() * 0.45
            color = self.palette.up if value >= 0 else self.palette.down
            painter.setPen(QPen(color, 1))
            painter.drawLine(int(x), int(zero_y), int(x), int(y))
        for values, color in ((dif, self.palette.macd_dif), (dea, self.palette.macd_dea)):
            painter.setPen(self._average_line_pen(color))
            last_point = None
            for slot, value in enumerate(values):
                x = self._x_for_slot(rect, slot)
                y = zero_y - value / max_abs * rect.height() * 0.45
                if last_point:
                    painter.drawLine(int(last_point[0]), int(last_point[1]), int(x), int(y))
                last_point = (x, y)

    def _macd_label_text(self, pane_index: int = 0) -> str:
        fast, slow, signal = self.pane_macd_params[pane_index]
        return f"MACD({fast},{slow},{signal})"

    def _macd_label_rect(self, rect: QRectF) -> QRectF:
        return QRectF(rect.left() + 4, rect.top() + 1, 128, 20)

    def _draw_sub_pane(self, painter: QPainter, rect: QRectF, pane_index: int) -> None:
        indicator = self.sub_pane_indicators[pane_index]
        label_rect = self._sub_pane_label_rect(rect)
        self._sub_pane_label_hits[pane_index] = label_rect
        if indicator == "macd":
            self._macd_label_hit = label_rect
            self._draw_macd(painter, rect, pane_index)
        elif indicator == "kdj":
            self._draw_kdj(painter, rect, pane_index)
        else:
            bars_rect = self._volume_bars_rect(rect)
            self._draw_volume(painter, bars_rect)
            self._draw_volume_ma(painter, bars_rect)
            self._draw_volume_ma_legend(painter, rect)
            self._volume_ma_legend_hits_by_pane[pane_index] = dict(self._volume_ma_legend_hits)
            self._draw_volume_amount_tip(painter, bars_rect)
        self._draw_sub_pane_axis(painter, rect, indicator, pane_index)
        painter.setPen(QColor("#ffffff") if self._is_label_flashing(f"subpane_{pane_index}") else self.palette.text)
        painter.setFont(QFont("Microsoft YaHei", 10))
        painter.drawText(int(label_rect.left()), int(rect.top() + 15), self._sub_pane_label_text(pane_index))
        if self._sub_pane_hover is not None and self._sub_pane_hover[0] == pane_index:
            self._draw_sub_pane_hover_tag(painter, rect, indicator, self._sub_pane_hover[1], self._sub_pane_hover[2], self._sub_pane_hover[0])

    def _draw_volume_ma(self, painter: QPainter, rect: QRectF) -> None:
        display_volumes = [0 if self._is_current_hidden(bar) else bar.volume for bar in self.bars]
        max_volume = max(display_volumes, default=1) or 1
        indices = self._date_indices()
        for period, color in self._volume_ma_styles():
            if period in self.hidden_volume_ma_periods:
                continue
            values = self._cached_series(("volume", period), lambda: moving_average([0.0 if self._is_current_hidden(bar) else float(bar.volume) for bar in self.all_bars], period))
            painter.setPen(self._average_line_pen(color))
            last_point = None
            for slot, bar in enumerate(self.bars):
                index = indices.get(bar.date)
                value = values[index] if index is not None else None
                if value is None:
                    last_point = None
                    continue
                point = (self._x_for_slot(rect, slot), self._volume_ma_y(rect, value, max_volume))
                if last_point:
                    painter.drawLine(int(last_point[0]), int(last_point[1]), int(point[0]), int(point[1]))
                last_point = point

    def _volume_ma_styles(self) -> tuple[tuple[int, QColor], ...]:
        return (
            (5, self.palette.ma5),
            (10, self.palette.ma10),
            (20, self.palette.ma20),
            (30, VOLUME_MA_COLOR_30),
            (60, self.palette.ma60),
            (120, VOLUME_MA_COLOR_120),
        )

    @staticmethod
    def _volume_ma_y(rect: QRectF, value: float, max_volume: float) -> float:
        return rect.bottom() - rect.height() * value / max_volume

    def _volume_bars_rect(self, rect: QRectF) -> QRectF:
        return QRectF(rect.left(), rect.top() + VOLUME_LABEL_AREA_HEIGHT, rect.width(), rect.height() - VOLUME_LABEL_AREA_HEIGHT)

    def _hit_volume_bar(self, volume_rect: QRectF, point) -> int | None:
        bars_rect = self._volume_bars_rect(volume_rect)
        display_volumes = [0 if self._is_current_hidden(bar) else bar.volume for bar in self.bars]
        max_volume = max(display_volumes, default=1) or 1
        slot = self._slot_for_x(bars_rect, point.x())
        if slot < 0 or slot >= len(self.bars):
            return None
        bar = self.bars[slot]
        bar_x = self._x_for_slot(bars_rect, slot)
        half_width = max(3.0, self._candle_width(bars_rect) / 2)
        if abs(point.x() - bar_x) > half_width:
            return None
        display_volume = 0 if self._is_current_hidden(bar) else bar.volume
        height = bars_rect.height() * display_volume / max_volume
        bar_top = bars_rect.bottom() - height
        if point.y() < bar_top or point.y() > bars_rect.bottom():
            return None
        return slot

    def _draw_volume_ma_legend(self, painter: QPainter, rect: QRectF) -> None:
        self._volume_ma_legend_hits = {}
        painter.setFont(QFont("Consolas", 9))
        x = int(rect.left() + 4)
        y = int(rect.top() + 30)
        for period, color in self._volume_ma_styles():
            text = f"VMA{period:d}"
            if self._is_label_flashing(f"vma_{period}"):
                painter.setPen(QColor("#ffffff"))
                painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            else:
                display_color = self.palette.axis if period in self.hidden_volume_ma_periods else color
                painter.setPen(display_color)
                painter.setFont(QFont("Consolas", 9))
            painter.drawText(x, y, text)
            width = painter.fontMetrics().horizontalAdvance(text) + 10
            self._volume_ma_legend_hits[period] = QRectF(x, y - 15, width, 20)
            x += width

    def _draw_volume_amount_tip(self, painter: QPainter, rect: QRectF) -> None:
        if self.volume_amount_tip is None:
            return
        bar = self.volume_amount_tip
        date_to_slot = {item.date: slot for slot, item in enumerate(self.bars)}
        if bar.date not in date_to_slot:
            self.volume_amount_tip = None
            return
        slot = date_to_slot[bar.date]
        x = self._x_for_slot(rect, slot)
        text = self._volume_amount_tip_text(bar)
        painter.setFont(QFont("Microsoft YaHei", 9))
        text_width = painter.fontMetrics().horizontalAdvance(text) + 16
        tip_x = min(max(rect.left() + 4, x - text_width / 2), rect.right() - text_width - 4)
        tip_rect = QRectF(tip_x, rect.top() + 8, text_width, 24)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b2634"))
        painter.drawRoundedRect(tip_rect, 4, 4)
        painter.setPen(QColor("#e6edf3"))
        painter.drawText(tip_rect.toRect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _volume_amount_tip_text(self, bar: DailyBar) -> str:
        return f"{bar.date + '  ' if self.show_time_marks else ''}成交量 {self._format_amount(bar.volume)}  成交额 {self._format_amount(bar.amount)}"

    @staticmethod
    def _format_amount(amount: float) -> str:
        if amount >= 100000000:
            return f"{amount / 100000000:.2f}亿"
        if amount >= 10000:
            return f"{amount / 10000:.2f}万"
        return f"{amount:.0f}"

    def _kdj(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        n: int | None = None,
        k: int | None = None,
        d: int | None = None,
        params: tuple[int, int, int] | None = None,
    ) -> tuple[list[float], list[float], list[float]]:
        if params is not None:
            n, k, d = params
        n = n or self.kdj_n
        k = k or self.kdj_k
        d = d or self.kdj_d
        length = len(closes)
        k_values = [50.0] * length
        d_values = [50.0] * length
        j_values = [0.0] * length
        prev_k = 50.0
        prev_d = 50.0
        for index in range(length):
            start = max(0, index - n + 1)
            window_low = min(lows[start:index + 1])
            window_high = max(highs[start:index + 1])
            denominator = window_high - window_low
            rsv = (closes[index] - window_low) / denominator * 100 if denominator > 0 else 50.0
            prev_k = (prev_k * (k - 1) + rsv) / k
            prev_d = (prev_d * (d - 1) + prev_k) / d
            k_values[index] = prev_k
            d_values[index] = prev_d
            j_values[index] = 3 * prev_k - 2 * prev_d
        return k_values, d_values, j_values

    def _draw_kdj(self, painter: QPainter, rect: QRectF, pane_index: int) -> None:
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []
        for bar in self.bars:
            display_high, display_low, display_close = self._display_prices(bar)
            highs.append(display_high)
            lows.append(display_low)
            closes.append(display_close)
        k_values, d_values, j_values = self._kdj(highs, lows, closes, params=self.pane_kdj_params[pane_index])
        for values, color in ((k_values, self.palette.macd_dif), (d_values, self.palette.macd_dea), (j_values, self.palette.marker_t)):
            painter.setPen(self._average_line_pen(color))
            last_point = None
            for slot, value in enumerate(values):
                x = self._x_for_slot(rect, slot)
                y = self._kdj_y(rect, value)
                if last_point:
                    painter.drawLine(int(last_point[0]), int(last_point[1]), int(x), int(y))
                last_point = (x, y)

    def _kdj_y(self, rect: QRectF, value: float) -> float:
        clamped = max(0.0, min(100.0, value))
        return rect.bottom() - (clamped / 100.0) * rect.height()

    def _draw_sub_pane_axis(self, painter: QPainter, rect: QRectF, indicator: str, pane_index: int) -> None:
        if indicator == "volume":
            self._draw_volume_axis(painter, self._volume_bars_rect(rect))
        elif indicator == "kdj":
            self._draw_kdj_axis(painter, rect)
        elif indicator == "macd":
            self._draw_macd_axis(painter, rect, pane_index)

    def _draw_volume_axis(self, painter: QPainter, rect: QRectF) -> None:
        display_volumes = [0 if self._is_current_hidden(bar) else bar.volume for bar in self.bars]
        max_volume = max(display_volumes, default=1) or 1
        for value, label in self._volume_axis_items():
            if value == self._latest_revealed_volume() and value > 0:
                latest_slot = self._latest_revealed_slot()
                if latest_slot >= 0:
                    start_x = self._x_for_slot(rect, latest_slot)
                    self._draw_latest_volume_line(painter, rect, self._volume_ma_y(rect, value, max_volume), label, start_x)
                    continue
            y = self._volume_ma_y(rect, value, max_volume)
            self._draw_axis_label(painter, rect, y, label)

    def _draw_latest_volume_line(self, painter: QPainter, rect: QRectF, y: float, label: str, start_x: float) -> None:
        painter.setFont(QFont("Consolas", 9))
        painter.setPen(QPen(QColor("#8d98a5"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(start_x), int(y), int(rect.right()), int(y))
        label_rect = self._price_axis_label_rect(rect, y)
        painter.setPen(QColor("#8d98a5"))
        painter.drawText(label_rect.toRect(), Qt.AlignmentFlag.AlignCenter, label)

    def _volume_axis_items(self) -> list[tuple[float, str]]:
        display_volumes = [0 if self._is_current_hidden(bar) else bar.volume for bar in self.bars]
        max_volume = max(display_volumes, default=1) or 1
        latest_volume = self._latest_revealed_volume()
        items = [(max_volume, self._format_amount(max_volume))]
        if latest_volume not in (max_volume, 0.0):
            items.append((latest_volume, self._format_amount(latest_volume)))
        return items

    def _latest_revealed_slot(self) -> int:
        for slot in range(len(self.bars) - 1, -1, -1):
            if not self._is_current_hidden(self.bars[slot]):
                return slot
        return -1

    def _draw_kdj_axis(self, painter: QPainter, rect: QRectF) -> None:
        for reference in (20, 50, 80):
            self._draw_axis_label(painter, rect, self._kdj_y(rect, reference), f"{reference}")

    def _draw_macd_axis(self, painter: QPainter, rect: QRectF, pane_index: int) -> None:
        closes = [self._display_close(bar) for bar in self.bars]
        dif, dea, macd = self._macd(closes, self.pane_macd_params[pane_index])
        max_abs = max([abs(value) for value in macd + dif + dea if value is not None] or [1])
        if max_abs <= 0:
            max_abs = 1.0

        def y_for(value: float) -> float:
            return rect.center().y() - value / max_abs * rect.height() * 0.45

        for value in (max_abs, 0.0, -max_abs):
            self._draw_axis_label(painter, rect, y_for(value), f"{value:+.2f}")

    def _draw_axis_label(self, painter: QPainter, rect: QRectF, center_y: float, text: str) -> None:
        painter.setPen(QPen(self.palette.grid, 1, Qt.PenStyle.DotLine))
        painter.drawLine(int(rect.left()), int(center_y), int(rect.right()), int(center_y))
        label_rect = self._price_axis_label_rect(rect, center_y)
        painter.setPen(self.palette.text)
        painter.setFont(QFont("Consolas", 9))
        painter.drawText(label_rect.toRect(), Qt.AlignmentFlag.AlignCenter, text)

    def _sub_pane_plot_rect(self, rect: QRectF, indicator: str) -> QRectF:
        if indicator == "volume":
            return self._volume_bars_rect(rect)
        return QRectF(rect.left(), rect.top() + 24, rect.width(), rect.height() - 24)

    def _update_sub_pane_hover(self, point) -> bool:
        old = self._sub_pane_hover
        self._sub_pane_hover = None
        if not self.bars:
            return old is not None
        _chart_rect, pane_rects = self._layout_areas()
        for pane_index, pane_rect in enumerate(pane_rects):
            indicator = self.sub_pane_indicators[pane_index]
            if indicator == "volume":
                continue
            active_rect = self._sub_pane_plot_rect(pane_rect, indicator)
            if active_rect.contains(point):
                slot = self._slot_for_x(active_rect, point.x())
                if 0 <= slot < len(self.bars):
                    self._sub_pane_hover = (pane_index, slot, point.y())
                    break
        return self._sub_pane_hover != old

    def _sub_pane_hover_text(self, indicator: str, slot: int, pane_index: int = 0) -> str:
        if slot < 0 or slot >= len(self.bars):
            return ""
        bar = self.bars[slot]
        if indicator == "kdj":
            highs, lows, closes = [], [], []
            for item in self.bars:
                display_high, display_low, display_close = self._display_prices(item)
                highs.append(display_high)
                lows.append(display_low)
                closes.append(display_close)
            k_values, d_values, j_values = self._kdj(highs, lows, closes, params=self.pane_kdj_params[pane_index])
            k = k_values[slot] if slot < len(k_values) else None
            d = d_values[slot] if slot < len(d_values) else None
            j = j_values[slot] if slot < len(j_values) else None
            fmt = lambda value: "N/A" if value is None else f"{value:.2f}"
            return f"{bar.date + '  ' if self.show_time_marks else ''}K:{fmt(k)}  D:{fmt(d)}  J:{fmt(j)}"
        if indicator == "macd":
            closes = [self._display_close(item) for item in self.bars]
            dif, dea, macd = self._macd(closes, self.pane_macd_params[pane_index])
            fmt = lambda value: "N/A" if value is None else f"{value:+.2f}"
            return f"{bar.date + '  ' if self.show_time_marks else ''}DIF:{fmt(dif[slot])}  DEA:{fmt(dea[slot])}  MACD:{fmt(macd[slot])}"
        return ""

    def _draw_sub_pane_hover_tag(self, painter: QPainter, rect: QRectF, indicator: str, slot: int, cursor_y: float, pane_index: int) -> None:
        active_rect = self._sub_pane_plot_rect(rect, indicator)
        text = self._sub_pane_hover_text(indicator, slot, pane_index)
        if not text:
            return
        x = self._x_for_slot(active_rect, slot)
        painter.setFont(QFont("Consolas", 9))
        text_width = painter.fontMetrics().horizontalAdvance(text) + 14
        box_x = min(max(active_rect.left() + 4, x - text_width / 2), active_rect.right() - text_width - 4)
        box_y = max(active_rect.top() + 2, min(cursor_y - 11, active_rect.bottom() - 26))
        box_rect = QRectF(box_x, box_y, text_width, 22)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b2634"))
        painter.drawRoundedRect(box_rect, 4, 4)
        painter.setPen(QColor("#e6edf3"))
        painter.drawText(box_rect.toRect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _price_range(self) -> tuple[float, float]:
        if self._paint_price_range_cache is not None:
            return self._paint_price_range_cache
        return self._calculate_price_range()

    def _calculate_price_range(self) -> tuple[float, float]:
        display_lows = []
        display_highs = []
        for bar in self.bars:
            display_high, display_low, _display_close = self._display_prices(bar)
            display_lows.append(display_low)
            display_highs.append(display_high)
        if self.main_overlay_mode == "boll":
            _mid, upper, lower = self._boll_series()
            indices = self._date_indices()
            for bar in self.bars:
                index = indices.get(bar.date)
                if index is not None and upper[index] is not None and lower[index] is not None:
                    display_highs.append(upper[index])
                    display_lows.append(lower[index])
        for spec in self._reference_line_specs():
            display_lows.append(spec.price)
            display_highs.append(spec.price)
        low = min(display_lows, default=0)
        high = max(display_highs, default=1)
        padding = max((high - low) * 0.08, 0.1)
        return low - padding, high + padding

    def _price_y(self, rect: QRectF, price: float, low: float, high: float) -> float:
        if high <= low:
            return rect.center().y()
        return rect.bottom() - (price - low) / (high - low) * rect.height()

    def _price_from_y(self, rect: QRectF, y: float, low: float, high: float) -> float:
        if rect.height() <= 0:
            return low
        ratio = (rect.bottom() - y) / rect.height()
        return low + ratio * (high - low)

    def _update_hover_price_position(self, point: QPointF) -> bool:
        chart_rect, _volume_rect, _macd_rect = self._areas()
        next_pos = QPointF(point) if self.bars and chart_rect.contains(point) else None
        changed = (next_pos is None) != (self._hover_chart_pos is None)
        if next_pos is not None and self._hover_chart_pos is not None:
            changed = next_pos != self._hover_chart_pos
        self._hover_chart_pos = next_pos
        return changed

    def _hover_price_value(self, rect: QRectF) -> float | None:
        if self._hover_chart_pos is None:
            return None
        low, high = self._price_range()
        y = max(rect.top(), min(rect.bottom(), self._hover_chart_pos.y()))
        return self._price_from_y(rect, y, low, high)

    def _hover_price_text(self, rect: QRectF) -> str | None:
        price = self._hover_price_value(rect)
        if price is None:
            return None
        return f"{price:.2f}"

    @staticmethod
    def _hover_price_font() -> QFont:
        return QFont("Consolas", 10, QFont.Weight.Bold)

    def _hover_price_tag_rect(self, rect: QRectF) -> QRectF | None:
        if self._hover_chart_pos is None:
            return None
        return self._price_axis_label_rect(rect, self._hover_chart_pos.y())

    def _x_for_slot(self, rect: QRectF, slot: int) -> float:
        count = self._slot_axis_count()
        plot_rect = self._plot_rect(rect)
        if count <= 1:
            return plot_rect.left()
        display_slot = self._leading_empty_slots() + slot
        return plot_rect.left() + plot_rect.width() * display_slot / (count - 1)

    def _slot_for_x(self, rect: QRectF, x: float) -> int:
        count = self._slot_axis_count()
        plot_rect = self._plot_rect(rect)
        if count <= 1:
            return 0
        relative = (x - plot_rect.left()) / plot_rect.width()
        display_slot = round(relative * (count - 1))
        return display_slot - self._leading_empty_slots()

    def _hit_candle_slot(self, rect: QRectF, x: float, y: float) -> int | None:
        slot = self._slot_for_x(rect, x)
        if slot < 0 or slot >= len(self.bars):
            return None
        bar = self.bars[slot]
        low, high = self._price_range()
        candle_x = self._x_for_slot(rect, slot)
        display_high, display_low, display_close = self._display_prices(bar)
        y_high = self._price_y(rect, display_high, low, high)
        y_low = self._price_y(rect, display_low, low, high)
        y_open = self._price_y(rect, bar.open, low, high)
        y_close = self._price_y(rect, display_close, low, high)
        candle_width = max(6, self._candle_width(rect))
        x_margin = candle_width / 2 + 4
        if abs(x - candle_x) > x_margin:
            return None
        body_top = min(y_open, y_close)
        body_bottom = max(y_open, y_close)
        hit_top = min(y_high, body_top) - 4
        hit_bottom = max(y_low, body_bottom) + 4
        if hit_top <= y <= hit_bottom:
            return slot
        return None

    def _hit_candle_body_slot(self, rect: QRectF, x: float, y: float) -> int | None:
        slot = self._slot_for_x(rect, x)
        if slot < 0 or slot >= len(self.bars):
            return None
        bar = self.bars[slot]
        low, high = self._price_range()
        candle_x = self._x_for_slot(rect, slot)
        _display_high, _display_low, display_close = self._display_prices(bar)
        y_open = self._price_y(rect, bar.open, low, high)
        y_close = self._price_y(rect, display_close, low, high)
        if point_hits_candle_body(
            point_x=x,
            point_y=y,
            candle_x=candle_x,
            candle_width=max(6, self._candle_width(rect)),
            body_y_open=y_open,
            body_y_close=y_close,
        ):
            return slot
        return None

    def _hidden_open_line_segment(self, rect: QRectF, _slot: int, x: float, candle_width: float) -> tuple[float, float]:
        half_width = max(3.0, candle_width / 2)
        return max(rect.left(), x - half_width), min(rect.right(), x + half_width)

    def _candle_width(self, rect: QRectF) -> float:
        count = self._slot_axis_count()
        if count <= 1:
            return 5
        return max(1.0, min(18, self._plot_rect(rect).width() / count * 0.62))

    def _base_slot_axis_count(self) -> int:
        return max(1, self.window_size, len(self.bars))

    def _slot_axis_count(self) -> int:
        return self._base_slot_axis_count()

    def _leading_empty_slots(self) -> int:
        return max(0, self._base_slot_axis_count() - len(self.bars))

    def _current_visible_slot(self) -> int | None:
        if not self.all_bars or self.current_index < 0 or self.current_index >= len(self.all_bars):
            return None
        current_date = self.all_bars[self.current_index].date
        for slot, bar in enumerate(self.bars):
            if bar.date == current_date:
                return slot
        return None

    def _current_day_highlight_rect(self, rect: QRectF) -> QRectF | None:
        slot = self._current_visible_slot()
        if slot is None:
            return None
        x = self._x_for_slot(rect, slot)
        count = max(2, self._slot_axis_count())
        slot_gap = rect.width() / (count - 1)
        width = max(18.0, min(48.0, slot_gap * 1.2))
        return QRectF(x - width / 2, rect.top(), width, rect.height())

    def _pre_trade_history_overlay_rect(self, rect: QRectF) -> QRectF | None:
        if not self.bars:
            return None
        first_trade_index = self.history_unmask_start_index
        if first_trade_index is None:
            first_trade_index = self._first_trade_index()
        if first_trade_index is None and self.active_trade_range is not None:
            first_trade_index = min(self.active_trade_range)
        if first_trade_index is None:
            if self.completed_trade_ranges:
                return None
            return QRectF(rect.left(), rect.top(), max(0.0, self.width() - rect.left()), rect.height())
        visible_start = self._visible_start_index()
        visible_end = visible_start + len(self.bars) - 1
        if first_trade_index <= visible_start:
            return None
        if first_trade_index > visible_end:
            return QRectF(rect.left(), rect.top(), max(0.0, self.width() - rect.left()), rect.height())

        first_trade_slot = first_trade_index - visible_start
        if first_trade_slot <= 0:
            return None
        previous_x = self._x_for_slot(rect, first_trade_slot - 1)
        first_trade_x = self._x_for_slot(rect, first_trade_slot)
        right = (previous_x + first_trade_x) / 2
        width = max(0.0, right - rect.left())
        if width <= 0:
            return None
        return QRectF(rect.left(), rect.top(), width, rect.height())

    def _pre_trade_history_boundary_x(self, rect: QRectF) -> float | None:
        shade = self._pre_trade_history_overlay_rect(rect)
        if shade is None or shade.right() >= rect.right() - 0.5:
            return None
        return shade.right()

    def _completed_trade_cycle_overlay_rects(self, rect: QRectF) -> list[QRectF]:
        return [item[0] for item in self._completed_trade_cycle_overlay_items(rect)]

    def _completed_trade_cycle_overlay_items(self, rect: QRectF) -> list[tuple[QRectF, float]]:
        return [(shade, profit) for shade, profit, _start, _end in self._completed_trade_cycle_overlay_details(rect)]

    def _completed_trade_cycle_overlay_details(self, rect: QRectF) -> list[tuple[QRectF, float, int, int]]:
        if not self.completed_trade_ranges or not self.bars:
            return []
        overlays: list[tuple[QRectF, float, int, int]] = []
        for raw_start, raw_end, profit in self.completed_trade_ranges:
            start_index = min(raw_start, raw_end)
            end_index = max(raw_start, raw_end)
            shade = self._trade_range_rect(rect, start_index, end_index)
            if shade is not None:
                overlays.append((shade, profit, start_index, end_index))
        return overlays

    def _trade_range_rect(self, rect: QRectF, start_index: int, end_index: int) -> QRectF | None:
        if not self.bars:
            return None
        visible_start = self._visible_start_index()
        visible_end = visible_start + len(self.bars) - 1
        if end_index < visible_start or start_index > visible_end:
            return None
        slot_gap = self._slot_gap(rect)
        if start_index < visible_start:
            left = rect.left()
        else:
            start_x = self._x_for_slot(rect, start_index - visible_start)
            left = max(rect.left(), start_x - slot_gap / 2)
        if end_index > visible_end:
            right = rect.right()
        else:
            end_x = self._x_for_slot(rect, end_index - visible_start)
            right = min(rect.right(), end_x + slot_gap / 2)
        width = max(0.0, right - left)
        return QRectF(left, rect.top(), width, rect.height()) if width > 0 else None

    def _slot_gap(self, rect: QRectF) -> float:
        count = max(2, self._slot_axis_count())
        return self._plot_rect(rect).width() / (count - 1)

    def _completed_trade_cycle_boundary_xs(self, rect: QRectF) -> list[float]:
        boundaries: list[float] = []
        for shade in self._completed_trade_cycle_overlay_rects(rect):
            if shade.left() > rect.left() + 0.5:
                boundaries.append(shade.left())
            if shade.right() < rect.right() - 0.5:
                boundaries.append(shade.right())
        return boundaries

    def _completed_trade_cycle_result_strip_items(self, rect: QRectF) -> list[tuple[QRectF, str, QColor]]:
        items: list[tuple[QRectF, str, QColor]] = []
        for shade, profit in self._completed_trade_cycle_overlay_items(rect):
            strip_rect = QRectF(shade.left(), rect.top() + 6, shade.width(), 18)
            color = QColor(214, 140, 146, 210) if profit >= 0 else QColor(140, 190, 158, 210)
            items.append((strip_rect, self._format_cycle_profit(profit), color))
        return items

    def _completed_trade_cycle_hold_tip_item(self, rect: QRectF) -> tuple[QRectF, str] | None:
        if self._hover_chart_pos is None:
            return None
        for shade, _profit, start_index, end_index in self._completed_trade_cycle_overlay_details(rect):
            strip_rect = QRectF(shade.left(), rect.top() + 6, shade.width(), 18)
            if not strip_rect.contains(self._hover_chart_pos):
                continue
            holding_days = end_index - start_index + 1
            text = f"本轮持有 {holding_days} 天"
            font = QFont("Microsoft YaHei", 9)
            width = QFontMetrics(font).horizontalAdvance(text) + 22
            plot_rect = self._plot_rect(rect)
            left = strip_rect.center().x() - width / 2
            left = max(plot_rect.left(), min(left, plot_rect.right() - width))
            tip_rect = QRectF(left, strip_rect.bottom() + 5, width, 24)
            return tip_rect, text
        return None

    def _active_trade_holding_strip_item(self, rect: QRectF) -> tuple[QRectF, str, QColor] | None:
        if self.active_trade_range is None:
            return None
        start_index, end_index = self.active_trade_range
        shade = self._trade_range_rect(rect, start_index, end_index)
        if shade is None:
            return None
        holding_days = end_index - start_index + 1
        text = f"已持有 {holding_days} 天"
        font = QFont("Microsoft YaHei", 9, QFont.Weight.Bold)
        minimum_width = QFontMetrics(font).horizontalAdvance(text) + 16
        plot_rect = self._plot_rect(rect)

        # 持仓区间较短时，先从当前 K 线向右延伸提示条；
        # 贴近图表右边界时再向左补足，保证文字完整显示。
        left = shade.left()
        right = min(plot_rect.right(), max(shade.right(), left + minimum_width))
        if right - left < minimum_width:
            left = max(plot_rect.left(), right - minimum_width)
        strip_rect = QRectF(left, rect.top() + 6, right - left, 18)
        return strip_rect, text, QColor(135, 202, 235, 220)

    @staticmethod
    def _format_cycle_profit(value: float) -> str:
        if abs(value) >= 1:
            return f"{value:+,.0f}"
        return f"{value:+.2f}"

    def _first_trade_index(self) -> int | None:
        if not self.trades or not self.all_bars:
            return None
        date_to_index = self._date_indices()
        indices = [date_to_index[trade.date] for trade in self.trades if trade.accepted and trade.date in date_to_index]
        if not indices:
            return None
        return min(indices)

    def _add_user_line(self, rect: QRectF, point: QPointF) -> None:
        center_index, center_price = self._point_to_chart_value(rect, self._clamp_point_to_rect(rect, point))
        start_index, end_index = self._default_user_line_index_range(rect, center_index)
        self.user_lines.append(UserLine(start_index, center_price, end_index, center_price))
        self._set_user_line_selection({len(self.user_lines) - 1}, update=False)

    def _default_user_line_index_range(self, rect: QRectF, center_index: float) -> tuple[float, float]:
        min_index, _price = self._point_to_chart_value(rect, QPointF(rect.left(), rect.center().y()))
        max_index, _price = self._point_to_chart_value(rect, QPointF(rect.right(), rect.center().y()))
        length = (max_index - min_index) * USER_LINE_DEFAULT_WIDTH_RATIO
        half_length = length / 2
        start_index = center_index - half_length
        end_index = center_index + half_length
        if start_index < min_index:
            end_index += min_index - start_index
            start_index = min_index
        if end_index > max_index:
            start_index -= end_index - max_index
            end_index = max_index
        return start_index, end_index

    def _add_user_rectangle(self, chart_rect: QRectF, screen_rect: QRectF) -> int:
        normalized = screen_rect.normalized().intersected(chart_rect)
        top_left = self._point_to_chart_value(chart_rect, normalized.topLeft())
        bottom_right = self._point_to_chart_value(chart_rect, normalized.bottomRight())
        self.user_rectangles.append(
            UserRectangle(
                left_index=top_left[0],
                top_price=top_left[1],
                right_index=bottom_right[0],
                bottom_price=bottom_right[1],
            )
        )
        self._set_user_line_selection(set(), update=False)
        rectangle_index = len(self.user_rectangles) - 1
        self._set_user_rectangle_selection({rectangle_index}, update=False)
        return rectangle_index

    def _begin_user_rectangle_rotation(
        self,
        chart_rect: QRectF,
        rectangle_index: int,
        point: QPointF,
    ) -> None:
        if not 0 <= rectangle_index < len(self.user_rectangles):
            return
        rectangle = self.user_rectangles[rectangle_index]
        center = self._user_rectangle_screen_rect(chart_rect, rectangle).center()
        self._rectangle_rotate_index = rectangle_index
        self._rectangle_rotate_start_angle = math.atan2(point.y() - center.y(), point.x() - center.x())
        self._rectangle_rotate_base_degrees = rectangle.angle_degrees

    def _rotate_user_rectangle(self, chart_rect: QRectF, point: QPointF) -> None:
        if self._rectangle_rotate_index is None or not 0 <= self._rectangle_rotate_index < len(self.user_rectangles):
            return
        rectangle = self.user_rectangles[self._rectangle_rotate_index]
        center = self._user_rectangle_screen_rect(chart_rect, rectangle).center()
        current_angle = math.atan2(point.y() - center.y(), point.x() - center.x())
        delta = math.degrees(current_angle - self._rectangle_rotate_start_angle)
        delta = (delta + 180.0) % 360.0 - 180.0
        target_degrees = self._rectangle_rotate_base_degrees + delta
        snapped_radians = self._snapped_angle(math.radians(target_degrees))
        rectangle.angle_degrees = math.degrees(snapped_radians) % 360.0

    def _drag_user_line(self, rect: QRectF, point: QPointF) -> None:
        if self._line_drag_index is None or not 0 <= self._line_drag_index < len(self.user_lines):
            return
        line = self.user_lines[self._line_drag_index]
        if self._line_drag_mode == "move":
            if self._line_drag_last_pos is None:
                self._line_drag_last_pos = point
                return
            current_index, current_price = self._point_to_chart_value(rect, self._clamp_point_to_rect(rect, point))
            previous_index, previous_price = self._point_to_chart_value(rect, self._clamp_point_to_rect(rect, self._line_drag_last_pos))
            index_delta = current_index - previous_index
            price_delta = current_price - previous_price
            self._move_selected_annotations(index_delta, price_delta)
            self._line_drag_last_pos = point
            return
        if self._line_drag_mode in {"start", "end"}:
            self._drag_user_line_endpoint(rect, line, point, self._line_drag_mode)

    def _drag_user_line_endpoint(self, rect: QRectF, line: UserLine, point: QPointF, mode: str) -> None:
        start, end = self._user_line_points(rect, line)
        fixed = end if mode == "start" else start
        target = self._clamp_point_to_rect(rect, point)
        dx = target.x() - fixed.x()
        dy = target.y() - fixed.y()
        distance = max(1.0, math.hypot(dx, dy))
        angle = self._snapped_angle(math.atan2(dy, dx))
        target = self._clamp_point_to_rect(rect, QPointF(fixed.x() + math.cos(angle) * distance, fixed.y() + math.sin(angle) * distance))
        target_index, target_price = self._point_to_chart_value(rect, target)
        if mode == "start":
            line.start_index, line.start_price = target_index, target_price
        else:
            line.end_index, line.end_price = target_index, target_price

    def _drag_user_rectangle(self, rect: QRectF, point: QPointF) -> None:
        if self._rectangle_drag_index is None or not 0 <= self._rectangle_drag_index < len(self.user_rectangles):
            return
        rectangle = self.user_rectangles[self._rectangle_drag_index]
        if self._rectangle_drag_mode == "move":
            if self._rectangle_drag_last_pos is None:
                self._rectangle_drag_last_pos = point
                return
            current_index, current_price = self._point_to_chart_value(rect, self._clamp_point_to_rect(rect, point))
            previous_index, previous_price = self._point_to_chart_value(
                rect, self._clamp_point_to_rect(rect, self._rectangle_drag_last_pos)
            )
            self._move_selected_annotations(current_index - previous_index, current_price - previous_price)
            self._rectangle_drag_last_pos = point
            return
        if self._rectangle_drag_mode in {"top_left", "top_right", "bottom_right", "bottom_left"}:
            self._resize_user_rectangle_corner(rect, rectangle, point, self._rectangle_drag_mode)

    def _resize_user_rectangle_corner(
        self,
        chart_rect: QRectF,
        rectangle: UserRectangle,
        point: QPointF,
        mode: str,
    ) -> None:
        corners = self._user_rectangle_corner_points(chart_rect, rectangle)
        opposite_modes = {
            "top_left": "bottom_right",
            "top_right": "bottom_left",
            "bottom_right": "top_left",
            "bottom_left": "top_right",
        }
        fixed = corners[opposite_modes[mode]]
        target = self._clamp_point_to_rect(chart_rect, point)
        angle = math.radians(rectangle.angle_degrees)
        dx = target.x() - fixed.x()
        dy = target.y() - fixed.y()
        local_dx = math.cos(angle) * dx + math.sin(angle) * dy
        local_dy = -math.sin(angle) * dx + math.cos(angle) * dy
        local_dx = math.copysign(max(MARQUEE_MIN_SIZE, abs(local_dx)), local_dx or 1.0)
        local_dy = math.copysign(max(MARQUEE_MIN_SIZE, abs(local_dy)), local_dy or 1.0)
        center_offset_x = math.cos(angle) * local_dx / 2 - math.sin(angle) * local_dy / 2
        center_offset_y = math.sin(angle) * local_dx / 2 + math.cos(angle) * local_dy / 2
        center = QPointF(fixed.x() + center_offset_x, fixed.y() + center_offset_y)
        half_width = abs(local_dx) / 2
        half_height = abs(local_dy) / 2
        left_value = self._point_to_chart_value(chart_rect, QPointF(center.x() - half_width, center.y()))[0]
        right_value = self._point_to_chart_value(chart_rect, QPointF(center.x() + half_width, center.y()))[0]
        top_value = self._point_to_chart_value(chart_rect, QPointF(center.x(), center.y() - half_height))[1]
        bottom_value = self._point_to_chart_value(chart_rect, QPointF(center.x(), center.y() + half_height))[1]
        rectangle.left_index, rectangle.right_index = sorted((left_value, right_value))
        rectangle.top_price = max(top_value, bottom_value)
        rectangle.bottom_price = min(top_value, bottom_value)

    def _move_selected_annotations(self, index_delta: float, price_delta: float) -> None:
        for index in sorted(self.selected_user_line_indices):
            if not 0 <= index < len(self.user_lines):
                continue
            line = self.user_lines[index]
            line.start_index += index_delta
            line.end_index += index_delta
            line.start_price += price_delta
            line.end_price += price_delta
        for index in sorted(self.selected_user_rectangle_indices):
            if not 0 <= index < len(self.user_rectangles):
                continue
            rectangle = self.user_rectangles[index]
            rectangle.left_index += index_delta
            rectangle.right_index += index_delta
            rectangle.top_price += price_delta
            rectangle.bottom_price += price_delta

    def _hit_user_line(self, rect: QRectF, point: QPointF) -> tuple[int, str] | None:
        for index in range(len(self.user_lines) - 1, -1, -1):
            start, end = self._user_line_points(rect, self.user_lines[index])
            if self._distance_between_points(point, start) <= LINE_HIT_RADIUS:
                return index, "start"
            if self._distance_between_points(point, end) <= LINE_HIT_RADIUS:
                return index, "end"
            if self._distance_to_segment(point, start, end) <= LINE_HIT_RADIUS:
                return index, "move"
        return None

    def _hit_user_rectangle(self, rect: QRectF, point: QPointF) -> tuple[int, str] | None:
        for index in range(len(self.user_rectangles) - 1, -1, -1):
            corners = self._user_rectangle_corner_points(rect, self.user_rectangles[index])
            for mode, corner in corners.items():
                if self._distance_between_points(point, corner) <= LINE_HIT_RADIUS:
                    return index, mode
            ordered = list(corners.values())
            for start, end in zip(ordered, ordered[1:] + ordered[:1]):
                if self._distance_to_segment(point, start, end) <= LINE_HIT_RADIUS:
                    return index, "move"
        return None

    def _hit_user_rectangle_rotation_handle(self, chart_rect: QRectF, point: QPointF) -> int | None:
        index = self._hover_user_rectangle_index
        if index is None or not 0 <= index < len(self.user_rectangles):
            return None
        handle_rect = self._user_rectangle_rotation_handle_rect(chart_rect, self.user_rectangles[index])
        return index if handle_rect.adjusted(-3, -3, 3, 3).contains(point) else None

    def _update_hover_user_rectangle(self, point: QPointF) -> bool:
        previous = self._hover_user_rectangle_index
        if self.suppress_user_annotations or not self.bars:
            self._hover_user_rectangle_index = None
            return previous is not None
        chart_rect, _volume_rect, _macd_rect = self._areas()
        if previous is not None and 0 <= previous < len(self.user_rectangles):
            handle_rect = self._user_rectangle_rotation_handle_rect(chart_rect, self.user_rectangles[previous])
            corner = self._user_rectangle_corner_points(chart_rect, self.user_rectangles[previous])["top_right"]
            corridor = QRectF(corner, handle_rect.center()).normalized().adjusted(-6, -6, 6, 6)
            if handle_rect.adjusted(-4, -4, 4, 4).contains(point) or corridor.contains(point):
                return False
        hovered: int | None = None
        if chart_rect.contains(point):
            for index in range(len(self.user_rectangles) - 1, -1, -1):
                corners = list(self._user_rectangle_corner_points(chart_rect, self.user_rectangles[index]).values())
                if any(
                    self._distance_to_segment(point, start, end) <= LINE_HIT_RADIUS
                    for start, end in zip(corners, corners[1:] + corners[:1])
                ):
                    hovered = index
                    break
        self._hover_user_rectangle_index = hovered
        return hovered != previous

    def _set_user_line_selection(self, indices: set[int], update: bool = True) -> None:
        self.selected_user_line_indices = {index for index in indices if 0 <= index < len(self.user_lines)}
        self.selected_user_line_index = max(self.selected_user_line_indices) if self.selected_user_line_indices else None
        if update:
            self.update()

    def _toggle_user_line_selection(self, index: int) -> None:
        selected = set(self.selected_user_line_indices)
        if index in selected:
            selected.remove(index)
        else:
            selected.add(index)
        self._set_user_line_selection(selected, update=False)

    def _set_user_rectangle_selection(self, indices: set[int], update: bool = True) -> None:
        self.selected_user_rectangle_indices = {
            index for index in indices if 0 <= index < len(self.user_rectangles)
        }
        self.selected_user_rectangle_index = (
            max(self.selected_user_rectangle_indices) if self.selected_user_rectangle_indices else None
        )
        if update:
            self.update()

    def _toggle_user_rectangle_selection(self, index: int) -> None:
        selected = set(self.selected_user_rectangle_indices)
        if index in selected:
            selected.remove(index)
        else:
            selected.add(index)
        self._set_user_rectangle_selection(selected, update=False)

    def _clear_user_line_selection(self, update: bool = True) -> None:
        self.selected_user_line_index = None
        self.selected_user_line_indices = set()
        self._line_drag_index = None
        self._line_drag_indices = set()
        self._line_drag_mode = ""
        self._line_drag_last_pos = None
        self.selected_user_rectangle_index = None
        self.selected_user_rectangle_indices = set()
        self._rectangle_drag_index = None
        self._rectangle_drag_indices = set()
        self._rectangle_drag_mode = ""
        self._rectangle_drag_last_pos = None
        self._rectangle_rotate_index = None
        self._rectangle_rotate_start_angle = 0.0
        self._rectangle_rotate_base_degrees = 0.0
        self._rectangle_rotate_requires_both_buttons = False
        self._hover_user_rectangle_index = None
        if update:
            self.update()

    def _copy_selected_user_lines(self) -> None:
        self._copied_user_lines = [replace(self.user_lines[index]) for index in sorted(self.selected_user_line_indices) if 0 <= index < len(self.user_lines)]
        self._copied_user_rectangles = [
            replace(self.user_rectangles[index])
            for index in sorted(self.selected_user_rectangle_indices)
            if 0 <= index < len(self.user_rectangles)
        ]

    def _paste_user_lines(self) -> None:
        if not self._copied_user_lines and not self._copied_user_rectangles:
            return
        new_indices: list[int] = []
        new_rectangle_indices: list[int] = []
        for line in self._copied_user_lines:
            self.user_lines.append(
                UserLine(
                    line.start_index + USER_LINE_PASTE_OFFSET_SLOTS,
                    line.start_price,
                    line.end_index + USER_LINE_PASTE_OFFSET_SLOTS,
                    line.end_price,
                )
            )
            new_indices.append(len(self.user_lines) - 1)
        for rectangle in self._copied_user_rectangles:
            self.user_rectangles.append(
                UserRectangle(
                    rectangle.left_index + USER_LINE_PASTE_OFFSET_SLOTS,
                    rectangle.top_price,
                    rectangle.right_index + USER_LINE_PASTE_OFFSET_SLOTS,
                    rectangle.bottom_price,
                    rectangle.angle_degrees,
                )
            )
            new_rectangle_indices.append(len(self.user_rectangles) - 1)
        self._set_user_line_selection(set(new_indices), update=False)
        self._set_user_rectangle_selection(set(new_rectangle_indices))

    def _duplicate_selected_annotations(self, offset_slots: float = USER_LINE_PASTE_OFFSET_SLOTS) -> tuple[list[int], list[int]]:
        new_line_indices = self._duplicate_selected_user_lines(offset_slots=offset_slots)
        source_rectangle_indices = sorted(self.selected_user_rectangle_indices)
        new_rectangle_indices: list[int] = []
        for index in source_rectangle_indices:
            if not 0 <= index < len(self.user_rectangles):
                continue
            rectangle = self.user_rectangles[index]
            self.user_rectangles.append(
                UserRectangle(
                    rectangle.left_index + offset_slots,
                    rectangle.top_price,
                    rectangle.right_index + offset_slots,
                    rectangle.bottom_price,
                    rectangle.angle_degrees,
                )
            )
            new_rectangle_indices.append(len(self.user_rectangles) - 1)
        self._set_user_line_selection(set(new_line_indices), update=False)
        self._set_user_rectangle_selection(set(new_rectangle_indices), update=False)
        return new_line_indices, new_rectangle_indices

    def _duplicate_selected_user_lines(self, offset_slots: float = USER_LINE_PASTE_OFFSET_SLOTS) -> list[int]:
        source_indices = sorted(self.selected_user_line_indices)
        new_indices: list[int] = []
        for index in source_indices:
            if not 0 <= index < len(self.user_lines):
                continue
            line = self.user_lines[index]
            self.user_lines.append(
                UserLine(
                    line.start_index + offset_slots,
                    line.start_price,
                    line.end_index + offset_slots,
                    line.end_price,
                )
            )
            new_indices.append(len(self.user_lines) - 1)
        self._set_user_line_selection(set(new_indices), update=False)
        return new_indices

    def _select_user_lines_in_rect(self, chart_rect: QRectF, selection_rect: QRectF) -> None:
        self._select_user_annotations_in_rect(chart_rect, selection_rect)

    def _select_user_annotations_in_rect(self, chart_rect: QRectF, selection_rect: QRectF) -> None:
        selected: set[int] = set()
        for index, line in enumerate(self.user_lines):
            p1, p2 = self._user_line_points(chart_rect, line)
            line_rect = QRectF(min(p1.x(), p2.x()), min(p1.y(), p2.y()), abs(p1.x() - p2.x()), abs(p1.y() - p2.y())).adjusted(-2, -2, 2, 2)
            if selection_rect.contains(p1) or selection_rect.contains(p2) or selection_rect.intersects(line_rect):
                selected.add(index)
        selected_rectangles: set[int] = set()
        for index, rectangle in enumerate(self.user_rectangles):
            if selection_rect.intersects(self._user_rectangle_screen_rect(chart_rect, rectangle)):
                selected_rectangles.add(index)
        self._set_user_line_selection(selected, update=False)
        self._set_user_rectangle_selection(selected_rectangles, update=False)

    def _marquee_rect(self) -> QRectF | None:
        if self._marquee_start_pos is None or self._marquee_current_pos is None:
            return None
        left = min(self._marquee_start_pos.x(), self._marquee_current_pos.x())
        top = min(self._marquee_start_pos.y(), self._marquee_current_pos.y())
        return QRectF(left, top, abs(self._marquee_current_pos.x() - self._marquee_start_pos.x()), abs(self._marquee_current_pos.y() - self._marquee_start_pos.y()))

    def _user_line_points(self, rect: QRectF, line: UserLine) -> tuple[QPointF, QPointF]:
        return self._chart_value_to_point(rect, line.start_index, line.start_price), self._chart_value_to_point(rect, line.end_index, line.end_price)

    def _user_rectangle_screen_rect(self, rect: QRectF, rectangle: UserRectangle) -> QRectF:
        return QPolygonF(list(self._user_rectangle_corner_points(rect, rectangle).values())).boundingRect()

    def _user_rectangle_unrotated_rect(self, rect: QRectF, rectangle: UserRectangle) -> QRectF:
        first = self._chart_value_to_point(rect, rectangle.left_index, rectangle.top_price)
        second = self._chart_value_to_point(rect, rectangle.right_index, rectangle.bottom_price)
        return QRectF(first, second).normalized()

    def _user_rectangle_corner_points(self, rect: QRectF, rectangle: UserRectangle) -> dict[str, QPointF]:
        screen_rect = self._user_rectangle_unrotated_rect(rect, rectangle)
        center = screen_rect.center()
        angle = math.radians(rectangle.angle_degrees)
        cosine = math.cos(angle)
        sine = math.sin(angle)

        def rotate(point: QPointF) -> QPointF:
            dx = point.x() - center.x()
            dy = point.y() - center.y()
            return QPointF(
                center.x() + cosine * dx - sine * dy,
                center.y() + sine * dx + cosine * dy,
            )

        return {name: rotate(point) for name, point in self._rectangle_corner_points(screen_rect).items()}

    def _user_rectangle_rotation_handle_rect(self, chart_rect: QRectF, rectangle: UserRectangle) -> QRectF:
        corners = self._user_rectangle_corner_points(chart_rect, rectangle)
        corner = corners["top_right"]
        center = self._user_rectangle_unrotated_rect(chart_rect, rectangle).center()
        dx = corner.x() - center.x()
        dy = corner.y() - center.y()
        length = max(1.0, math.hypot(dx, dy))
        handle_center = QPointF(
            corner.x() + dx / length * RECTANGLE_ROTATION_HANDLE_OFFSET,
            corner.y() + dy / length * RECTANGLE_ROTATION_HANDLE_OFFSET,
        )
        margin = RECTANGLE_ROTATION_HANDLE_RADIUS + 2
        handle_center = QPointF(
            min(max(handle_center.x(), chart_rect.left() + margin), chart_rect.right() - margin),
            min(max(handle_center.y(), chart_rect.top() + margin), chart_rect.bottom() - margin),
        )
        radius = RECTANGLE_ROTATION_HANDLE_RADIUS
        return QRectF(handle_center.x() - radius, handle_center.y() - radius, radius * 2, radius * 2)

    @staticmethod
    def _rectangle_corner_points(rect: QRectF) -> dict[str, QPointF]:
        return {
            "top_left": rect.topLeft(),
            "top_right": rect.topRight(),
            "bottom_right": rect.bottomRight(),
            "bottom_left": rect.bottomLeft(),
        }

    def _point_to_chart_value(self, rect: QRectF, point: QPointF) -> tuple[float, float]:
        visible_start = self._visible_start_index()
        count = max(2, self._slot_axis_count())
        plot_rect = self._plot_rect(rect)
        display_slot = (point.x() - plot_rect.left()) / plot_rect.width() * (count - 1)
        slot = display_slot - self._leading_empty_slots()
        low, high = self._price_range()
        price = high - (point.y() - rect.top()) / rect.height() * (high - low)
        return visible_start + slot, price

    def _chart_value_to_point(self, rect: QRectF, index: float, price: float) -> QPointF:
        visible_start = self._visible_start_index()
        count = max(2, self._slot_axis_count())
        display_slot = index - visible_start + self._leading_empty_slots()
        plot_rect = self._plot_rect(rect)
        x = plot_rect.left() + plot_rect.width() * display_slot / (count - 1)
        low, high = self._price_range()
        return QPointF(x, self._price_y(rect, price, low, high))

    def _visible_start_index(self) -> int:
        if not self.bars or not self.all_bars:
            return 0
        return self._date_indices().get(self.bars[0].date, 0)

    def _snapped_angle(self, angle: float) -> float:
        degrees = math.degrees(angle)
        snapped = round(degrees / LINE_SNAP_DEGREES) * LINE_SNAP_DEGREES
        diff = abs((degrees - snapped + 180) % 360 - 180)
        if diff <= LINE_SNAP_THRESHOLD:
            return math.radians(snapped)
        return angle

    def _clamp_point_to_rect(self, rect: QRectF, point: QPointF) -> QPointF:
        return QPointF(min(max(point.x(), rect.left()), rect.right()), min(max(point.y(), rect.top()), rect.bottom()))

    @staticmethod
    def _clamp_ratio(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _distance_between_points(a: QPointF, b: QPointF) -> float:
        return math.hypot(a.x() - b.x(), a.y() - b.y())

    @staticmethod
    def _distance_to_segment(point: QPointF, start: QPointF, end: QPointF) -> float:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            return KLineWidget._distance_between_points(point, start)
        t = ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / length_squared
        t = max(0.0, min(1.0, t))
        projection = QPointF(start.x() + t * dx, start.y() + t * dy)
        return KLineWidget._distance_between_points(point, projection)

    def _bar_color(self, bar: DailyBar, prev_close: float | None, is_current_hidden: bool = False) -> QColor:
        if is_current_hidden:
            if prev_close:
                open_change = (bar.open - prev_close) / prev_close * 100
                if open_change >= 9.8:
                    return self.palette.limit_up
                if open_change <= -9.8:
                    return self.palette.limit_down
            return self.palette.up if prev_close is None or bar.open >= prev_close else self.palette.down
        state = candle_state(bar, prev_close)
        if state == "limit_up":
            return self.palette.limit_up
        if state == "limit_down":
            return self.palette.limit_down
        if state == "up":
            return self.palette.up
        return self.palette.down

    def _is_current_bar(self, bar: DailyBar) -> bool:
        if self.current_index < 0 or self.current_index >= len(self.all_bars):
            return False
        return self.all_bars[self.current_index].date == bar.date

    def _is_current_hidden(self, bar: DailyBar) -> bool:
        return self._is_current_bar(bar) and self.pan_offset == 0 and not self.reveal_current_full

    def _display_prices(self, bar: DailyBar) -> tuple[float, float, float]:
        if self._is_current_hidden(bar):
            return bar.open, bar.open, bar.open
        return bar.high, bar.low, bar.close

    def _display_close(self, bar: DailyBar) -> float:
        if self._is_current_hidden(bar):
            return bar.open
        return bar.close

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        if not values:
            return []
        alpha = 2 / (period + 1)
        result = [values[0]]
        for value in values[1:]:
            result.append(value * alpha + result[-1] * (1 - alpha))
        return result

    def _macd(
        self,
        closes: list[float],
        params: tuple[int, int, int] | None = None,
    ) -> tuple[list[float], list[float], list[float]]:
        fast, slow, signal = params or (self.macd_fast, self.macd_slow, self.macd_signal)
        ema_fast = self._ema(closes, fast)
        ema_slow = self._ema(closes, slow)
        dif = [a - b for a, b in zip(ema_fast, ema_slow)]
        dea = self._ema(dif, signal)
        macd = [(d - e) * 2 for d, e in zip(dif, dea)]
        return dif, dea, macd
