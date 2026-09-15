from dataclasses import replace
from functools import cmp_to_key
from html import escape
import json
import os
import threading
import time
import re
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal, QRect, QEvent, QTimer, QSize
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPalette
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QApplication, QCheckBox, QLineEdit, QSplitter, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QTabBar, QComboBox)
from PySide6.QtCore import QRectF

from ..kline_widget import KLineWidget
from ..models import TradeNode
from ..stock_info import BOARD_CATEGORY_LABELS, stock_category
from .contracts import MarketContext, TrainingRequest
from .service import SectorService, SectorDataError
from .style import STYLE


# Keep the sector chart's zoom budget aligned with the stock chart. Without
# an upper bound the sector view can expand to thousands of bars and render
# candles as one-pixel lines.
MIN_SECTOR_CHART_BARS = 55
MAX_SECTOR_CHART_BARS = 750
DEFAULT_SECTOR_CHART_BARS = 70
SECTOR_ZOOM_IN_FACTOR = 0.72
SECTOR_ZOOM_OUT_FACTOR = 1.35
MARKET_CALENDAR_CODE = 'sh000001'

# 名称列上的连板角标（红字、比名称大一号）。
LIMIT_UP_BADGE_ROLE = Qt.ItemDataRole.UserRole + 2
LIMIT_UP_BADGE_COLOR = '#ff5252'
# 每行所属的上市板块分类（主板/创业板/科创板/北交所/ST），用于板块筛选。
STOCK_CATEGORY_ROLE = Qt.ItemDataRole.UserRole + 3

# 连板角标：把连板数转成上角标数字，例如 2 → ²（表示连续两个涨停）。
_SUPERSCRIPT_DIGITS = str.maketrans('0123456789', '⁰¹²³⁴⁵⁶⁷⁸⁹')


def limit_up_badge(streak: int) -> str:
    """2 连板及以上返回上角标数字；首板或未涨停返回空字符串。"""
    if not streak or streak < 2:
        return ''
    return str(int(streak)).translate(_SUPERSCRIPT_DIGITS)


def conceal_dates(text):
    lines = [line for line in str(text).splitlines() if '可见历史' not in line]
    return re.sub(r'\b(?:19|20)\d{2}(?:[-/]\d{2}[-/]\d{2}|\d{4})\b', '日期已隐藏', '\n'.join(lines))


class DatePrivateLabel(QLabel):
    def __init__(self, text=''):
        super().__init__(text)
        self.original_text = text
        self.dates_visible = True

    def setText(self, text):
        self.original_text = text
        super().setText(text if self.dates_visible else conceal_dates(text))

    def set_dates_visible(self, visible):
        self.dates_visible = visible
        self.setText(self.original_text)


class _Signals(QObject):
    finished = Signal(str, int, object, str)


class _Job(QRunnable):
    def __init__(self, kind, serial, function, cancelled):
        super().__init__()
        self.kind, self.serial, self.function = kind, serial, function
        self.cancelled = cancelled
        self.signals = _Signals()

    def run(self):
        if self.cancelled.is_set():
            return
        try:
            result = self.function()
            error = ''
        except Exception as exc:
            result, error = None, str(exc)
        if not self.cancelled.is_set():
            self.signals.finished.emit(self.kind, self.serial, result, error)


class NumericItem(QTableWidgetItem):
    def __init__(self, text, value=None):
        super().__init__(text)
        self.value = value

    def __lt__(self, other):
        if isinstance(other, NumericItem):
            return (self.value if self.value is not None else -float('inf')) < (other.value if other.value is not None else -float('inf'))
        return super().__lt__(other)


class LimitUpBadgeDelegate(QStyledItemDelegate):
    """名称列自绘：名称照常居中显示，连板角标单独放大并画成红色。"""

    def paint(self, painter, option, index):
        badge = index.data(LIMIT_UP_BADGE_ROLE)
        if not badge:
            super().paint(painter, option, index)
            return
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)
        view_option.text = ''
        widget = view_option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, view_option, painter, widget)

        name = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
        name_metrics = QFontMetrics(option.font)
        badge_font = QFont(option.font)
        if badge_font.pixelSize() > 0:
            badge_font.setPixelSize(badge_font.pixelSize() + 4)
        elif badge_font.pointSizeF() > 0:
            badge_font.setPointSizeF(badge_font.pointSizeF() + 3)
        badge_font.setBold(True)
        badge_metrics = QFontMetrics(badge_font)

        gap = 2.0
        name_width = name_metrics.horizontalAdvance(name)
        badge_width = badge_metrics.horizontalAdvance(str(badge))
        left = option.rect.center().x() - (name_width + gap + badge_width) / 2
        top = option.rect.top()
        height = option.rect.height()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        painter.setFont(option.font)
        painter.setPen(
            option.palette.color(
                QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
            )
        )
        painter.drawText(
            QRectF(left, top, name_width, height),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name,
        )
        painter.setFont(badge_font)
        painter.setPen(QColor(LIMIT_UP_BADGE_COLOR))
        painter.drawText(
            QRectF(left + name_width + gap, top, badge_width + 2, height),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            str(badge),
        )
        painter.restore()


class StableTableHeader(QHeaderView):
    """Keep captions centered while the sort marker occupies a fixed gutter."""
    def paintSection(self, painter, rect, logical_index):
        painter.save()
        painter.fillRect(rect, QColor('#1d2125'))
        painter.setPen(QColor('#a7afb7'))
        painter.setFont(self.font())
        text = str(self.model().headerData(logical_index, self.orientation(), Qt.ItemDataRole.DisplayRole) or '')
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        if self.isSortIndicatorShown() and self.sortIndicatorSection() == logical_index:
            arrow = '▴' if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else '▾'
            painter.drawText(QRect(rect.right()-12, rect.top(), 12, rect.height()), Qt.AlignmentFlag.AlignCenter, arrow)
        painter.restore()


class SectorPage(QWidget):
    visibility_requested = Signal(bool)
    training_requested = Signal(object)
    advance_requested = Signal()
    context_changed = Signal(object)
    readiness_changed = Signal()

    def __init__(self, cache_dir=None):
        super().__init__()
        self.setObjectName('SectorPage')
        self.setStyleSheet(STYLE)
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self.context = None
        self.service = None
        self._lock = threading.Lock()
        self._serial = 0
        self._requests = {}
        self._jobs = {}
        self._sector_code = ''
        self._sector_name = ''
        self._selected_stock = ''
        self._chart_code = ''
        self._loaded_context = None
        self._history = []
        self._window = DEFAULT_SECTOR_CHART_BARS
        self._offset = 0
        self._catalog_rows = ()
        self._category = 'concept'
        self._focus_stock = ''
        self.adjust_provider = None
        self._adjust_signature = None
        self._index_enabled = False
        self._index_bars = []
        self._index_code = ''
        self._space_tap = 0.0
        self._dates_visible = True
        self.adjust_type = "qfq"
        self._restore_stock = ''
        self._member_total = 0
        self._auto_select_first = False
        self._search_result = None
        self._training_date_limit = None
        self._training_stock_code = ''
        self._random_horizon_bars = 0
        # 收藏：点击表格“序号”列切换，收藏的板块/个股排在最前面。
        self._favorite_sectors: set[str] = set()
        self._favorite_stocks: set[str] = set()
        self._favorites_path = (
            self._cache_dir / 'favorites.json' if self._cache_dir else None
        )
        self._load_favorites()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        toolbar = QHBoxLayout()
        date_label = QLabel('模拟日期')
        date_label.setObjectName('SectorDateLabel')
        toolbar.addWidget(date_label)
        self.date_edit = QLineEdit()
        self.date_edit.setFixedWidth(155)
        self.date_edit.setPlaceholderText('2018 / 201802 / 20180603')
        self.date_edit.setToolTip('输入年、年月或完整日期后回车；定位到该日期起首个交易日。')
        self.date_edit.returnPressed.connect(self._navigate_date)
        toolbar.addWidget(self.date_edit)
        self.random_date = QPushButton('R')
        self.random_date.setFixedSize(30, 28)
        self.random_date.setStyleSheet('QPushButton {border-radius: 6px; padding: 0px;}')
        self.random_date.setToolTip('随机选择交易日，整个板块页跟随该日期；不改变原训练账户')
        self.random_date.clicked.connect(lambda: self._navigate_date('random'))
        toolbar.addWidget(self.random_date)
        self.date_visibility = QPushButton()
        self.date_visibility.setCheckable(True)
        self.date_visibility.setChecked(True)
        self.date_visibility.setFixedSize(30, 28)
        self.date_visibility.setIconSize(QSize(20, 20))
        self.date_visibility.setStyleSheet('QPushButton {border-radius: 6px; padding: 0px;}')
        self.date_visibility.clicked.connect(self._request_visibility)
        toolbar.addWidget(self.date_visibility)
        self.advance = QPushButton('下一交易日')
        self.advance.clicked.connect(self._advance)
        self.search = QLineEdit()
        self.search.setPlaceholderText('板块 / 个股名称、首字母或代码')
        self.search.setMinimumWidth(320)
        self.search.setClearButtonEnabled(True)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search_timer.timeout.connect(self._filter)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        toolbar.addWidget(self.search, 1)
        self.return_training_btn = QPushButton('返回模拟日期')
        self.return_training_btn.setToolTip('回到当前模拟日期')
        self.return_training_btn.clicked.connect(self.return_to_training_date)
        self.advance = QPushButton('下一交易日')
        self.advance.clicked.connect(self._advance)
        toolbar.addWidget(self.advance)
        layout.addLayout(toolbar)
        self.date_warning = QLabel('')
        self.date_warning.setObjectName('SectorDateWarning')
        self.date_warning.setWordWrap(True)
        self.date_warning.hide()
        layout.addWidget(self.date_warning)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.sector_splitter = split
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.sector_label = QLabel('一级行业')
        ll.addWidget(self.sector_label)
        self.level_tabs = QTabBar()
        self.level_tabs.setFixedHeight(30)
        for label in ('一级行业', '二级行业'):
            self.level_tabs.addTab(label)
        self.level_tabs.setToolTip('双击把板块列表拉回顶部')
        self.level_tabs.tabBarDoubleClicked.connect(
            lambda _index: self.scroll_sectors_to_top()
        )
        categories = QHBoxLayout()
        categories.setContentsMargins(0, 0, 0, 0)
        categories.setSpacing(0)
        categories.addWidget(self.level_tabs, 2)
        self.category_buttons = {}
        for title, category in (('概念', 'concept'), ('风格', 'style')):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setToolTip('双击把板块列表拉回顶部')
            button.installEventFilter(self)
            button.setStyleSheet('QPushButton {border: none; border-bottom: 2px solid transparent; border-radius: 0; font-weight: normal;} QPushButton:checked {background: #262d32; color: #e0e5e9; font-weight: bold; border-bottom: 2px solid #8c9eab;}')
            button.clicked.connect(lambda checked=False, c=category: self._choose_category(c))
            self.category_buttons[category] = button
            button.setFixedHeight(30)
            categories.addWidget(button, 1)
        ll.addLayout(categories)
        self.level_tabs.tabBarClicked.connect(lambda i: self._level_changed(i) if self._category != 'industry' else None)
        self.parent_filter = QComboBox()
        self.parent_filter.addItem('全部上级行业', '')
        self.parent_filter.setVisible(False)
        ll.addWidget(self.parent_filter)
        self.level_tabs.currentChanged.connect(self._level_changed)
        self.parent_filter.currentIndexChanged.connect(self.reload)
        self.sector_table = self._table(['序号', '板块名称', '涨幅', '5日', '10日', '20日', '量比'])
        ll.addWidget(self.sector_table)
        split.addWidget(left)
        right = QSplitter(Qt.Orientation.Vertical)
        self.sector_chart_splitter = right
        chart_panel = QWidget()
        cl = QVBoxLayout(chart_panel)
        cl.setContentsMargins(0, 0, 0, 0)
        chart_tools = QHBoxLayout()
        chart_tools.setContentsMargins(10, 0, 0, 0)
        self.chart_title = DatePrivateLabel('选择行业，查看日K')
        self.chart_title.setWordWrap(True)
        chart_tools.addWidget(self.chart_title, 1)
        chart_tools.addWidget(self.return_training_btn)
        back = QPushButton('返回板块走势')
        back.setObjectName('SectorBackButton')
        back.setToolTip('点击查看当前板块的指数走势（再点个股即回到个股K线）')
        back.clicked.connect(self._back_to_sector)
        chart_tools.addWidget(back)
        for text, fn in [('−', self.zoom_out), ('+', self.zoom_in), ('最近', self.latest)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            chart_tools.addWidget(b)
        cl.addLayout(chart_tools)
        self.chart = KLineWidget(self)
        self.chart.main_overlay_mode = "none"
        self.chart.installEventFilter(self)
        self.chart.setMinimumSize(360, 210)
        cl.addWidget(self.chart, 1)
        right.addWidget(chart_panel)
        stocks_panel = QWidget()
        sl = QVBoxLayout(stocks_panel)
        sl.setContentsMargins(0, 0, 0, 0)
        stock_tools = QHBoxLayout()
        self.member_label = QLabel('板块内个股 · 单击预览，双击进入训练')
        self.member_label.setStyleSheet('padding-left: 10px;')
        stock_tools.addWidget(self.member_label, 1)
        # 按上市板块筛选成分股：主板 / 创业板 / 科创板 / 北交所。
        self.board_filters = {}
        for key, title in BOARD_CATEGORY_LABELS:
            box = QCheckBox(title)
            box.setChecked(True)
            box.setToolTip('勾选后显示该板块的个股；取消勾选即从成分股列表隐藏')
            box.stateChanged.connect(lambda _state: self._apply_filter())
            self.board_filters[key] = box
            stock_tools.addWidget(box)
        # 和右边"进入个股训练"按钮拉开距离，筛选项整体往左挪一点。
        stock_tools.addSpacing(26)
        self.train = QPushButton('进入个股训练 →')
        self.train.setObjectName('SectorTrain')
        self.train.setCursor(Qt.CursorShape.PointingHandCursor)
        self.train.setEnabled(False)
        self.train.clicked.connect(self._train)
        stock_tools.addWidget(self.train)
        sl.addLayout(stock_tools)
        self.stock_table = self._table([
            '序号', '代码', '名称', '现价', '涨幅', '竞价涨幅', '5日涨幅', '10日涨幅', '20日涨幅',
            '近一年涨幅', '当日换手', '5日换手', '10日换手', '20日换手', '60日换手', '成交额', '量比', '所属行业',
        ])
        self.stock_table.horizontalHeader().setStretchLastSection(True)
        self.stock_table.setItemDelegateForColumn(2, LimitUpBadgeDelegate(self.stock_table))
        sl.addWidget(self.stock_table)
        right.addWidget(stocks_panel)
        right.setSizes([470, 270])
        split.addWidget(right)
        split.setSizes([520, 830])
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.status = DatePrivateLabel('等待通达信数据')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.sector_table.itemSelectionChanged.connect(self._select_sector)
        self.stock_table.installEventFilter(self)
        self.sector_table.installEventFilter(self)
        self.stock_table.viewport().installEventFilter(self)
        self.sector_table.viewport().installEventFilter(self)
        self.stock_table.itemSelectionChanged.connect(self._select_stock)
        self.stock_table.itemDoubleClicked.connect(lambda _: self._train())
        self.sector_table.itemClicked.connect(
            lambda item: self._toggle_favorite(self.sector_table, item)
        )
        self.stock_table.itemClicked.connect(
            lambda item: self._toggle_favorite(self.stock_table, item)
        )
        for table in (self.sector_table, self.stock_table):
            table.horizontalHeader().sectionClicked.connect(
                lambda column, _table=table: self._header_clicked(_table, column)
            )
        self._set_category('concept')
        self.sector_label.setText('概念板块')
        self.set_dates_visible(True)

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeader(StableTableHeader(Qt.Orientation.Horizontal, table))
        table.horizontalHeader().setSectionsClickable(True)
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(27)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(False)
        widths = (
            [48, 122, 68, 68, 68, 68, 68]
            if '板块名称' in headers
            else [48, 78, 108, 78, 78, 84, 88, 88, 88, 84, 84, 84, 84, 84, 84, 110, 84, 140]
        )
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)
        # 排序由页面自己做（收藏行始终靠前），这里只设置初始的排序标记。
        table.setSortingEnabled(False)
        header = table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(2 if '板块名称' in headers else 4, Qt.SortOrder.DescendingOrder)
        return table

    def set_context(self, context, *, reload=True):
        if context == self.context:
            return
        source_changed = not self.context or self.context.root != context.root
        self.context = context
        if source_changed:
            self.service = SectorService(context.root, cache_dir=self._cache_dir)
            self._index_bars = []
            self._index_enabled = False
            self._sector_code = self._selected_stock = ''
        self.date_edit.blockSignals(True)
        self.date_edit.setText(context.date)
        self.date_edit.blockSignals(False)
        self.date_edit.setEnabled(True)
        self.advance.setText(('推进至收盘' if not context.closed else '下一日开盘') if context.locked else '下一交易日')
        self.context_changed.emit(context)
        if reload:
            self.reload()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._fit_table_columns(self.sector_table, True))
        QTimer.singleShot(0, lambda: self._fit_table_columns(self.stock_table, False))

    def _request_visibility(self, visible):
        self.set_dates_visible(visible)
        self.visibility_requested.emit(visible)

    def show_date_warning(self, text):
        self.date_warning.setText(text)
        self.date_warning.show()

    def hide_date_warning(self):
        self.date_warning.hide()

    def set_training_date_limit(self, limit):
        self._training_date_limit = limit or None

    def set_training_context(self, limit, stock_code, horizon_bars):
        self._training_date_limit = limit or None
        self._training_stock_code = stock_code or ''
        self._random_horizon_bars = max(0, int(horizon_bars or 0))
        self.return_training_btn.setEnabled(True)

    def apply_layout_sizes(self, sector_sizes=None, chart_sizes=None,
                           sector_widths=None, stock_widths=None):
        if isinstance(sector_sizes, (list, tuple)) and len(sector_sizes) == 2:
            self.sector_splitter.setSizes([max(1, int(v)) for v in sector_sizes])
        if isinstance(chart_sizes, (list, tuple)) and len(chart_sizes) == 2:
            self.sector_chart_splitter.setSizes([max(1, int(v)) for v in chart_sizes])
        if isinstance(sector_widths, (list, tuple)) and len(sector_widths) == self.sector_table.columnCount():
            for column, width in enumerate(sector_widths):
                self.sector_table.setColumnWidth(column, max(20, int(width)))
        if isinstance(stock_widths, (list, tuple)) and len(stock_widths) == self.stock_table.columnCount():
            for column, width in enumerate(stock_widths):
                self.stock_table.setColumnWidth(column, max(20, int(width)))

    def apply_chart_preferences(self, indicators=None, pane_ratios=None, window_size=None):
        valid_indicators = [
            value for value in (indicators or [])
            if value in {"volume", "macd", "kdj"}
        ]
        if valid_indicators:
            self.chart.sub_pane_indicators = valid_indicators[:4]
        if (
            isinstance(pane_ratios, (list, tuple))
            and len(pane_ratios) == len(self.chart.sub_pane_indicators) + 1
            and all(isinstance(value, (int, float)) and float(value) >= 0 for value in pane_ratios)
            and sum(float(value) for value in pane_ratios) > 0
        ):
            self.chart.pane_height_ratios = [float(value) for value in pane_ratios]
        if isinstance(window_size, int) or (isinstance(window_size, float) and window_size.is_integer()):
            self._window = max(1, min(MAX_SECTOR_CHART_BARS, int(window_size)))

    def set_dates_visible(self, visible):
        if getattr(self, "_visibility_applied", None) == bool(visible):
            return
        self._visibility_applied = bool(visible)
        self._dates_visible = bool(visible)
        self.date_visibility.setChecked(visible)
        icon = 'eye_white.svg' if visible else 'eye_white_off.svg'
        self.date_visibility.setIcon(QIcon(str(Path(__file__).resolve().parents[1] / 'assets' / icon)))
        self.date_visibility.setToolTip('隐藏所有日期（与个股训练联动）' if visible else '显示所有日期（与个股训练联动）')
        self.date_edit.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self.chart.show_time_marks = visible
        self.chart_title.set_dates_visible(visible)
        self.status.set_dates_visible(visible)
        for table in (self.sector_table, self.stock_table):
            for row in range(table.rowCount()):
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item is not None:
                        raw = item.data(Qt.ItemDataRole.UserRole+1)
                        if raw is not None:
                            item.setToolTip(raw if visible else conceal_dates(raw))
        self.chart.update()

    def set_adjust_provider(self, provider):
        signature = (id(provider), bool(provider and provider.ready))
        self.adjust_provider = provider
        if signature != self._adjust_signature:
            self._adjust_signature = signature
            self._loaded_context = None
            if self._chart_code and self._history:
                self._load_chart(self._chart_code, '')

    def focus_stock(self, code):
        """Locate a host stock through the sector API, without touching its account."""
        self._focus_stock = code
        if not self.service:
            return
        self.cancel_pending()
        self.search_timer.stop()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._search_result = None
        if self._loaded_context == self.context and self._selected_stock == code and self._chart_code == code and self._history:
            self._apply_filter()
            for table in (self.sector_table, self.stock_table):
                item = table.item(table.currentRow(), 0)
                if item is not None:
                    table.scrollToItem(item)
            return
        service = self.service
        category, level = self._category, self.level_tabs.currentIndex()+1
        self._submit('locate', lambda: (code, service.memberships_for_stock(code, category, level)))

    def _submit(self, kind, function, *, cancellable=False):
        old = self._requests.get(kind)
        if old:
            old[1].set()
        self._serial += 1
        serial, cancelled = self._serial, threading.Event()
        self._requests[kind] = (serial, cancelled)
        lock = self._lock
        def guarded():
            with lock:
                if cancelled.is_set():
                    return None
                return function(cancelled.is_set) if cancellable else function()
        job = _Job(kind, serial, guarded, cancelled)
        job.signals.finished.connect(self._finished)
        # Keep the current job alive until its queued signal is delivered.
        self._jobs[kind] = job
        QThreadPool.globalInstance().start(job)

    def cancel_pending(self):
        for _, cancel in self._requests.values():
            cancel.set()
        self._requests.clear()

    def reload(self):
        if not self.context:
            return
        self.cancel_pending()
        self._restore_stock = self._selected_stock
        self._clear_chart()
        self._selected_stock = ''
        self.train.setEnabled(False)
        self.stock_table.blockSignals(True)
        self.stock_table.setRowCount(0)
        self.stock_table.blockSignals(False)
        self.sector_table.blockSignals(True)
        self.sector_table.setRowCount(0)
        self.sector_table.blockSignals(False)
        self.status.setText('正在读取行业日线…')
        service, context = self.service, self.context
        level, parent = self.level_tabs.currentIndex() + 1, self.parent_filter.currentData() or ''
        category = self._category
        self._submit('sectors', lambda stopped: (service.sector_quotes(context, level, parent, category, stopped), service.sectors(level-1) if category == 'industry' and level > 1 else ()), cancellable=True)

    def _finished(self, kind, serial, result, error):
        request = self._requests.get(kind)
        if not request or request[0] != serial:
            return
        if error:
            self.status.setText(error)
            if kind == 'navigate':
                self.show_date_warning(error)
            return
        if kind == 'index':
            code, bars = result
            if code == self._sector_code:
                self._index_code, self._index_bars = code, bars
                self._sync_index_overlay()
            self.readiness_changed.emit()
        elif kind == 'locate':
            code, industries = result
            if not industries:
                self._sector_code = self._selected_stock = ''
                self.reload()
                self.status.setText(f'{code[2:]} 在当前分类没有对应板块，显示全部板块。')
                return
            sector = next((s for s in industries if s.code == self._sector_code), None)
            if sector is None:
                sector = next((s for s in industries if s.level == self.level_tabs.currentIndex()+1), industries[0])
            self._set_category(sector.category)
            self.level_tabs.blockSignals(True)
            self.level_tabs.setCurrentIndex(sector.level-1)
            self.level_tabs.blockSignals(False)
            self.parent_filter.blockSignals(True)
            self.parent_filter.setCurrentIndex(0)
            self.parent_filter.blockSignals(False)
            self.parent_filter.setVisible(sector.category == 'industry' and sector.level > 1)
            self._sector_code = sector.code
            self._sector_name = sector.name
            self._selected_stock = code
            self._restore_stock = code
            self.reload()
            # 定位链路上板块表正在重建，不能只靠选中回调；这里直接加载该板块成员
            # 和这只股票的K线，保证"个股页 → 板块页"一进来就是完整状态。
            service, context = self.service, self.context
            self.status.setText('正在读取板块成员…')
            self._load_chart(code, sector.name)
            self._submit(
                'members',
                lambda stopped: service.member_quotes(sector.code, context, stopped),
                cancellable=True,
            )
            self.readiness_changed.emit()
        elif kind == 'search':
            query, sectors, stocks = result
            if query != self.search.text().strip():
                return
            self._search_result = (sectors, stocks)
            self._apply_filter()
            self._restore_selection(self.sector_table, self._sector_code)
            self.readiness_changed.emit()
        elif kind == 'sectors':
            quotes, parents = result
            quotes = [q for q in quotes if self._has_market_numbers(q)]
            selected_parent = self.parent_filter.currentData()
            self.parent_filter.blockSignals(True)
            self.parent_filter.clear()
            self.parent_filter.addItem('全部上级行业', '')
            for sector in parents:
                self.parent_filter.addItem(sector.path, sector.code)
            self.parent_filter.setCurrentIndex(max(0, self.parent_filter.findData(selected_parent)))
            self.parent_filter.blockSignals(False)
            self._fill(self.sector_table, quotes, True)
            level_name = self.level_tabs.tabText(self.level_tabs.currentIndex()) if self._category == 'industry' else ('概念板块' if self._category == 'concept' else '风格板块')
            self.sector_label.setText(f'{level_name} · {len(quotes)} 个')
            if self._sector_code or self._selected_stock:
                self.status.setText('日线和排名均截止模拟日期；拖动 / 滚轮查看已有历史。')
                self._restore_selection(self.sector_table, self._sector_code)
            elif self._auto_select_first:
                self._auto_select_first = False
                self.status.setText('日线和排名均截止模拟日期；拖动 / 滚轮查看已有历史。')
                target = next(
                    (q.code for q in quotes if q.bar_count >= DEFAULT_SECTOR_CHART_BARS),
                    None,
                )
                if target is None and quotes:
                    target = max(quotes, key=lambda q: q.bar_count).code
                self._restore_selection(self.sector_table, target or '')
            else:
                self.sector_table.blockSignals(True)
                self.sector_table.clearSelection()
                self.sector_table.setCurrentCell(-1, -1)
                self.sector_table.blockSignals(False)
                self.member_label.setText('板块内个股 · 选择左侧板块后加载')
                self.chart_title.setText('选择行业，查看日K')
                self.status.setText(
                    '选择左侧板块查看成分股和走势；列表已按模拟日期排序。'
                    if quotes else f'本地资料未提供该范围的{level_name}，可切换其他层级或上级行业。'
                )
            self._filter()
            self.readiness_changed.emit()
        elif kind == 'members':
            rows = [q for q in result if self._has_market_numbers(q)]
            self._fill(self.stock_table, rows, False)
            self._member_total = len(rows)
            self._update_member_label()
            self.status.setText(f'已读取 {len(rows)} 只成员；没有有效行情的股票不显示。')
            if self._restore_stock:
                code, self._restore_stock = self._restore_stock, ''
                for row in range(self.stock_table.rowCount()):
                    if self.stock_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == code:
                        self.stock_table.selectRow(row)
                        self.stock_table.scrollToItem(self.stock_table.item(row, 0))
                        break
                # 选中不等于换图：如果主图还停在板块指数上，这里强制切回该股K线。
                if self._chart_code != code:
                    self._load_chart(code, '')
            self.readiness_changed.emit()
        elif kind == 'chart':
            code, name, bars, price_label = result
            self._chart_code = code
            self._loaded_context = self.context
            self._history = bars
            self._offset = 0
            self.chart.clear_user_annotations()
            self._draw()
            if bars:
                title = (
                    f'<span style="font-size:15px;font-weight:700;color:#e6edf3">'
                    f'{escape(name)} {code[2:]}</span>'
                    f' <span style="font-size:12px;color:#9fb2c8">{bars[0].date} 至 '
                    f'{bars[-1].date} 共{len(bars)}根K线</span>'
                )
            else:
                title = (
                    f'<span style="font-size:15px;font-weight:700;color:#e6edf3">'
                    f'{escape(name)} {code[2:]}</span>'
                    f' <span style="font-size:12px;color:#9fb2c8">截止日之前无行情</span>'
                )
            self.chart_title.setText(title)
            self.chart_title.setToolTip(price_label)
            self.readiness_changed.emit()
        elif kind == 'next':
            if result == self.context.date:
                self._offset = 0
                self._draw()
                return
            self.set_context(replace(self.context, date=result, closed=True))
        elif kind == 'navigate':
            # Explicit navigation changes the whole browsing snapshot, never the account.
            self._offset = 0
            self.set_context(replace(self.context, date=result, closed=True, locked=False))
            self.hide_date_warning()
            self._draw()
            self.chart.setFocus()

    def _set_category(self, category):
        self._category = category
        self.sector_label.setText(self.level_tabs.tabText(self.level_tabs.currentIndex()) if category == 'industry' else ('概念板块' if category == 'concept' else '风格板块'))
        for key, button in self.category_buttons.items():
            button.setChecked(key == category)
        base = 'QTabBar::tab {background: #191d20; color: #a7afb7; border: none; border-bottom: 2px solid transparent; font-weight: normal; padding: 5px 8px;}'
        selected = 'QTabBar::tab:selected {background: #262d32; color: #e0e5e9; border-bottom: 2px solid #8c9eab; font-weight: bold;}' if category == 'industry' else 'QTabBar::tab:selected {background: #191d20; border-bottom: 2px solid transparent; font-weight: normal;}'
        self.level_tabs.setStyleSheet(base + selected)

    def _choose_category(self, category):
        if category == self._category:
            self._set_category(category)
            return
        code = self._selected_stock or self._focus_stock
        self._set_category(category)
        self._sector_code = self._selected_stock = ''
        self._loaded_context = None
        self.parent_filter.setVisible(False)
        self._search_result = None
        if code:
            self.focus_stock(code)
        else:
            self.reload()

    def _level_changed(self, index):
        self.level_tabs.blockSignals(True)
        self.level_tabs.setCurrentIndex(index)
        self.level_tabs.blockSignals(False)
        code = self._selected_stock or self._focus_stock
        self._selected_stock = ''
        self._loaded_context = None
        self._set_category('industry')
        self._sector_code = ''
        self.parent_filter.blockSignals(True)
        self.parent_filter.clear()
        self.parent_filter.addItem('全部上级行业', '')
        self.parent_filter.blockSignals(False)
        self.parent_filter.setVisible(index > 0)
        if code:
            self.focus_stock(code)
        else:
            self.reload()

    @staticmethod
    def _restore_selection(table, code):
        for row in range(table.rowCount()):
            if table.item(row, 0).data(Qt.ItemDataRole.UserRole) == code and not table.isRowHidden(row):
                table.selectRow(row)
                table.scrollToItem(table.item(row, 0))
                return
        for row in range(table.rowCount()):
            if not table.isRowHidden(row):
                table.selectRow(row)
                table.scrollToItem(table.item(row, 0))
                return

    @staticmethod
    def _has_market_numbers(quote):
        return any(
            value is not None
            for value in (
                quote.price,
                quote.change,
                quote.open_change,
                quote.change5,
                quote.change10,
                quote.change20,
                quote.change_year,
                quote.turnover1,
                quote.turnover5,
                quote.turnover10,
                quote.turnover20,
                quote.turnover60,
                quote.volume_ratio,
                quote.amount,
            )
        )

    def _favorites_for(self, table):
        return self._favorite_sectors if table is self.sector_table else self._favorite_stocks

    def _load_favorites(self):
        path = self._favorites_path
        if path is None or not path.exists():
            return
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if not isinstance(document, dict):
            return
        self._favorite_sectors = {
            str(value) for value in document.get('sectors', []) if isinstance(value, str)
        }
        self._favorite_stocks = {
            str(value) for value in document.get('stocks', []) if isinstance(value, str)
        }

    def _save_favorites(self):
        path = self._favorites_path
        if path is None:
            return
        payload = {
            'version': 1,
            'sectors': sorted(self._favorite_sectors),
            'stocks': sorted(self._favorite_stocks),
        }
        temporary = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8'
            )
            os.replace(temporary, path)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass

    def favorite_codes(self):
        """返回当前收藏的板块与个股代码，供“保存配置”写入设置。"""
        return sorted(self._favorite_sectors), sorted(self._favorite_stocks)

    def apply_configured_favorites(self, sectors, stocks):
        """用配置里保存的收藏作为初始值（本地还没有收藏文件时）。"""
        if self._favorites_path is not None and self._favorites_path.exists():
            return
        self._favorite_sectors = {value for value in sectors if isinstance(value, str)}
        self._favorite_stocks = {value for value in stocks if isinstance(value, str)}

    def _toggle_favorite(self, table, item):
        """点击“序号”列切换收藏；收藏的板块/个股排在列表最前面。"""
        if item is None or item.column() != 0:
            return
        code = item.data(Qt.ItemDataRole.UserRole)
        if not code:
            return
        favorites = self._favorites_for(table)
        if code in favorites:
            favorites.discard(code)
        else:
            favorites.add(code)
        self._save_favorites()
        self._pin_favorites(table)
        self._renumber_table(table)

    def _permute_rows(self, table, order):
        """按给定顺序重排现有行，尽量不动控件、不触发选中变化。"""
        count = table.rowCount()
        if not count or order == list(range(count)):
            return
        rows = [
            [table.takeItem(row, column) for column in range(table.columnCount())]
            for row in range(count)
        ]
        table.blockSignals(True)
        try:
            for target, source in enumerate(order):
                for column, item in enumerate(rows[source]):
                    table.setItem(target, column, item)
            selected = self._sector_code if table is self.sector_table else self._selected_stock
            if selected:
                for row in range(count):
                    item = table.item(row, 0)
                    if item is not None and item.data(Qt.ItemDataRole.UserRole) == selected:
                        table.selectRow(row)
                        break
        finally:
            table.blockSignals(False)

    def _sort_table(self, table, column, order):
        """按当前排序列排序；收藏的行（板块或个股）始终排在最前面。"""
        count = table.rowCount()
        if not count or column is None or column < 0:
            return
        favorites = self._favorites_for(table)
        descending = order == Qt.SortOrder.DescendingOrder
        codes = [
            (table.item(row, 0).data(Qt.ItemDataRole.UserRole) if table.item(row, 0) is not None else None)
            for row in range(count)
        ]
        # 收藏标记只算一次，比较函数里不再反复取数据。
        marked_rows = {row for row, code in enumerate(codes) if code in favorites}

        def marked(row):
            return row in marked_rows

        def compare(row_a, row_b):
            marked_a, marked_b = marked(row_a), marked(row_b)
            if marked_a != marked_b:
                return -1 if marked_a else 1
            item_a = table.item(row_a, column)
            item_b = table.item(row_b, column)
            if item_a is None or item_b is None:
                return 0
            if item_a < item_b:
                base = -1
            elif item_b < item_a:
                base = 1
            else:
                base = 0
            return -base if descending else base

        self._permute_rows(table, sorted(range(count), key=cmp_to_key(compare)))

    def _pin_favorites(self, table):
        header = table.horizontalHeader()
        self._sort_table(table, header.sortIndicatorSection(), header.sortIndicatorOrder())

    def _header_clicked(self, table, column):
        """点表头排序：排序标记由表头自身翻转，这里按标记重排数据。"""
        header = table.horizontalHeader()
        order = header.sortIndicatorOrder()
        if header.sortIndicatorSection() != column:
            header.setSortIndicator(column, order)
        header.setSortIndicatorShown(True)
        self._sort_table(table, column, order)
        # 排序后回到列表顶部，才能立刻看到排在最前面的结果。
        table.scrollToTop()
        table.verticalScrollBar().setValue(0)
        # 序号和收藏角标等事件循环下一拍再刷新，保持原有节奏。
        QTimer.singleShot(0, lambda: self._renumber_table(table))

    def _renumber_table(self, table):
        favorites = self._favorites_for(table)
        number = 0
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            if table.isRowHidden(row):
                # 被筛选隐藏的行不参与编号，可见行重新从 1 连续编号。
                continue
            number += 1
            code = item.data(Qt.ItemDataRole.UserRole)
            if code in favorites:
                item.setText(f'★{number}')
                item.setForeground(QColor('#ffcc33'))
                item.setToolTip('已收藏；再点一次序号取消收藏')
            else:
                item.setText(str(number))
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
                item.setToolTip('点击序号收藏')
            if isinstance(item, NumericItem):
                item.value = number

    def scroll_sectors_to_top(self):
        """把板块列表拉回顶部（双击分类标签触发）。"""
        if self.sector_table.rowCount() <= 0:
            return
        self.sector_table.scrollToTop()
        self.sector_table.verticalScrollBar().setValue(0)

    @staticmethod
    def _select_next_row(table):
        """把选中行往下移一格（回车键用），到末尾后停住。"""
        rows = [row for row in range(table.rowCount()) if not table.isRowHidden(row)]
        if not rows:
            return
        current = table.currentRow()
        position = rows.index(current) if current in rows else -1
        target = rows[min(len(rows) - 1, position + 1)]
        table.setCurrentCell(target, max(0, table.currentColumn()))
        table.selectRow(target)
        item = table.item(target, 0)
        if item is not None:
            table.scrollToItem(item)

    def _fit_table_columns(self, table, sectors):
        minimums = (
            [40, 108, 54, 54, 54, 54, 54]
            if sectors
            else [36, 54, 62, 46, 56, 56, 56, 56, 56, 60, 56, 56, 56, 56, 56, 68, 46, 76]
        )
        available = max(1, table.viewport().width())
        total_minimum = sum(minimums)
        if available <= total_minimum:
            widths = minimums
        else:
            extra = available - total_minimum
            base, remainder = divmod(extra, len(minimums))
            widths = [
                value + base + (1 if index < remainder else 0)
                for index, value in enumerate(minimums)
            ]
        for column, width in enumerate(widths[:table.columnCount()]):
            table.setColumnWidth(column, width)

    def _fill(self, table, quotes, sectors):
        selected = self._selected_stock if not sectors else self._sector_code
        position = table.verticalScrollBar().value()
        if not sectors:
            # 新板块的成员列表：先清掉上一次的搜索过滤，否则旧结果会把新成员全挡住。
            if self._search_result is not None or self.search.text().strip():
                self.search.blockSignals(True)
                self.search.clear()
                self.search.blockSignals(False)
                self._search_result = None
        table.blockSignals(True)
        # 整表一次性刷新，避免每加一格就重绘一次。
        table.setUpdatesEnabled(False)
        try:
            self._fill_rows(table, quotes, sectors, selected)
        finally:
            # 无论中途是否出错，都要恢复刷新和信号，否则表格会一直空白。
            table.setUpdatesEnabled(True)
            table.blockSignals(False)
        table.verticalScrollBar().setValue(position)

    def _fill_rows(self, table, quotes, sectors, selected):
        table.setSortingEnabled(False)
        table.setRowCount(len(quotes))
        for row, q in enumerate(quotes):
            values = (
                [(str(row + 1), row + 1), (q.name, None)]
                if sectors else [
                    (str(row + 1), row + 1),
                    (q.code[2:], None),
                    (q.name, None),
                    ('—' if q.price is None else f'{q.price:.2f}', q.price),
                ]
            )
            changes = (
                (q.change, q.open_change, q.change5, q.change10, q.change20, q.change_year)
                if not sectors else (q.change, q.change5, q.change10, q.change20)
            )
            values += [('—' if n is None else f'{n:+.2f}%', n) for n in changes]
            if not sectors:
                turnovers = (q.turnover1, q.turnover5, q.turnover10, q.turnover20, q.turnover60)
                values += [('—' if n is None else f'{n:.2f}%', n) for n in turnovers]
                amount = '—' if q.amount is None else f'{q.amount / 1e8:.2f}亿' if q.amount >= 1e8 else f'{q.amount / 1e4:.2f}万'
                values += [
                    (amount, q.amount),
                    ('—' if q.volume_ratio is None else f'{q.volume_ratio:.2f}', q.volume_ratio),
                    (q.industry or '—', None),
                ]
            else:
                values += [
                    ('—' if q.volume_ratio is None else f'{q.volume_ratio:.2f}', q.volume_ratio)
                ]
            for col, (text, value) in enumerate(values):
                item = NumericItem(text, value) if col in ((2, 3, 4, 5, 6) if sectors else range(3, 17)) else QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, q.code)
                if col == 0:
                    item.setData(STOCK_CATEGORY_ROLE, stock_category(q.code, q.name))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # 只有缺失值才挂状态提示，避免给上万个单元格重复设置 tooltip。
                if text == '—':
                    item.setData(Qt.ItemDataRole.UserRole+1, q.status)
                    item.setToolTip(q.status if self._dates_visible else conceal_dates(q.status))
                if not sectors and col == 2 and q.limit_up_streak >= 2:
                    item.setData(LIMIT_UP_BADGE_ROLE, limit_up_badge(q.limit_up_streak))
                    item.setToolTip(
                        f'{q.limit_up_streak}连板：连续 {q.limit_up_streak} 个交易日涨停'
                    )
                if col in ((2, 3, 4, 5) if sectors else (4, 5, 6, 7, 8, 9)) and value is not None:
                    item.setForeground(QColor('#ff666c' if value > 0 else '#2dd0ad' if value < 0 else '#a5b4c8'))
                table.setItem(row, col, item)
        self._pin_favorites(table)
        self._renumber_table(table)
        self._fit_table_columns(table, sectors)
        self._apply_filter()

    def _filter(self):
        query = self.search.text().strip()
        if not query:
            self._search_result = None
            self._apply_filter()
            return
        if self.service is None:
            return
        service = self.service
        level, parent = self.level_tabs.currentIndex()+1, self.parent_filter.currentData() or ''
        category = self._category
        self._submit('search', lambda: (query, *service.search(query, level, parent, category)))

    def _apply_filter(self):
        result = self._search_result if self.search.text().strip() else None
        for table in (self.sector_table, self.stock_table):
            allowed = (result[0] if table is self.sector_table else result[1]) if result else None
            visible = 0
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                code = item.data(Qt.ItemDataRole.UserRole)
                hidden = allowed is not None and code not in allowed
                if not hidden and table is self.stock_table and not self._category_allowed(
                    item.data(STOCK_CATEGORY_ROLE)
                ):
                    hidden = True
                table.setRowHidden(row, hidden)
                if not hidden:
                    visible += 1
            if (
                table is self.stock_table
                and table.rowCount()
                and visible == 0
                and allowed is None
            ):
                # 兜底：没有搜索条件却一只都看不到时，放宽过滤，避免整表空白。
                for row in range(table.rowCount()):
                    table.setRowHidden(row, False)
        # 取消/增加筛选后，可见行的序号和"多少只"的总数都要重算。
        self._renumber_table(self.stock_table)
        self._update_member_label()

    def _update_member_label(self) -> None:
        if not hasattr(self, 'member_label'):
            return
        total = int(getattr(self, '_member_total', 0) or 0)
        visible = sum(
            1 for row in range(self.stock_table.rowCount())
            if not self.stock_table.isRowHidden(row)
        )
        if total and visible != total:
            count_text = f'{visible} 只（共 {total} 只）'
        else:
            count_text = f'{visible or total} 只'
        sector_name = escape(self._sector_name or self._sector_code)
        self.member_label.setText(
            f'<b>所属板块：{sector_name}</b> · {count_text} · 单击预览 / 双击训练'
        )

    def _category_allowed(self, category) -> bool:
        box = self.board_filters.get(category or 'main')
        return box is None or box.isChecked()

    def board_filter_keys(self):
        """当前勾选的上市板块，供“保存配置”写入设置。"""
        return [key for key, box in self.board_filters.items() if box.isChecked()]

    def apply_board_filters(self, keys):
        """按配置恢复上市板块勾选状态。"""
        if keys is None:
            return
        selected = {str(key) for key in keys}
        for key, box in self.board_filters.items():
            box.blockSignals(True)
            box.setChecked(key in selected)
            box.blockSignals(False)

    def _select_sector(self):
        self._cancel_navigation()
        row = self.sector_table.currentRow()
        if row < 0 or not self.sector_table.item(row, 0):
            return
        self._sector_code = self.sector_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self._sector_name = self.sector_table.item(row, 1).text()
        if self._index_enabled:
            self._request_index_overlay()
        # 切换板块时记住原来选中的个股：它如果也在新板块里，成员加载完会自动重新选中。
        keep_stock = self._selected_stock
        self._selected_stock = ''
        self.train.setEnabled(False)
        self.stock_table.blockSignals(True)
        self.stock_table.setRowCount(0)
        self.stock_table.blockSignals(False)
        service, context, code = self.service, self.context, self._sector_code
        self.status.setText('正在读取板块成员…')
        self._load_chart(self._restore_stock or code, '' if self._restore_stock else self.sector_table.item(row, 1).text())
        if keep_stock and not self._restore_stock:
            self._restore_stock = keep_stock
        self._submit('members', lambda stopped: service.member_quotes(code, context, stopped), cancellable=True)

    def _select_stock(self):
        self._cancel_navigation()
        row = self.stock_table.currentRow()
        if row < 0 or not self.stock_table.item(row, 0):
            return
        self._selected_stock = self.stock_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self._focus_stock = self._selected_stock
        self.train.setEnabled(self.stock_table.item(row, 3).value is not None)
        if self._chart_code != self._selected_stock or self._loaded_context != self.context or not self._history:
            self._load_chart(self._selected_stock, self.stock_table.item(row, 2).text())

    def _clear_focus_frame(self):
        self.sector_table.clearFocus()
        self.stock_table.clearFocus()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _clear_chart(self):
        self._history = []
        self._chart_code = ''
        self.chart_title.setText('日K · 正在加载或等待选择')
        self._draw()

    def _load_chart(self, code, name):
        self._clear_chart()
        service, context = self.service, self.context
        if service is not None and service.is_virtual_style(code):
            # 程序自己统计的清单（今日涨停/连板/跌停、腰斩等）没有指数日线。
            label = name or code
            self.chart_title.setText(f'{label} · 实时清单（无指数日线）')
            self.status.setText(f'{label}：按本地最新交易日统计，单击预览、双击进入训练。')
            self._draw()
            return
        provider = self.adjust_provider
        adjust_type = self.adjust_type
        self._submit('chart', lambda: (code, name or service.info.name_for(code) or code, *service.chart_history(code, context, provider, adjust_type)))

    def _back_to_sector(self):
        self._selected_stock = ''
        self.train.setEnabled(False)
        self.stock_table.blockSignals(True)
        self.stock_table.clearSelection()
        self.stock_table.blockSignals(False)
        row = self.sector_table.currentRow()
        if row >= 0:
            self._load_chart(self._sector_code, self.sector_table.item(row, 1).text())

    def _train(self):
        if self._selected_stock and self.train.isEnabled():
            self.training_requested.emit(TrainingRequest(self._selected_stock, self.context))

    def _navigate_date(self, boundary=None):
        if not self.context:
            return
        service = self.service
        selected_sector = self._sector_code
        upper_date = None
        if boundary == 'random' and self._random_horizon_bars:
            try:
                upper_date = service.latest_date_with_forward_bars(
                    self._random_horizon_bars,
                    MARKET_CALENDAR_CODE,
                )
            except Exception:
                upper_date = None
        context = replace(self.context, locked=False)
        code = selected_sector or MARKET_CALENDAR_CODE
        # A changed board date must not restore a stock that has no data on
        # that date. Keep the sector selection; reload will drop it if the
        # sector itself is unavailable on the new date.
        self._selected_stock = ''
        self._restore_stock = ''
        self._focus_stock = ''
        query = self.date_edit.text()
        self._submit(
            'navigate',
            lambda: service.resolve_date(
                query,
                context,
                code,
                boundary,
                upper_date,
                MARKET_CALENDAR_CODE,
            ),
        )

    def _cancel_navigation(self):
        request = self._requests.pop('navigate', None)
        if request:
            request[1].set()

    def return_to_training_date(self):
        if not self.context:
            return
        target = self._training_date_limit or self.context.date
        if target == self.context.date:
            self.reload()
            self.status.setText(f'当前已是模拟日期 {target}。')
            return
        self.set_context(replace(
            self.context,
            date=target,
            closed=True,
            locked=True,
        ))

    def _is_current_training_sector(self):
        if not self._training_stock_code or not self._sector_code or not self.service:
            return False
        try:
            memberships = self.service.memberships_for_stock(
                self._training_stock_code,
                self._category,
                self.level_tabs.currentIndex() + 1,
            )
        except Exception:
            return False
        return any(sector.code == self._sector_code for sector in memberships)

    def _toggle_index_overlay(self):
        if not self._history or self._chart_code.startswith('sh880'):
            return
        self._index_enabled = not self._index_enabled
        if self._index_enabled and (not self._index_bars or self._index_code != self._sector_code):
            self._request_index_overlay()
        else:
            self._sync_index_overlay()

    def _request_index_overlay(self):
        service, code = self.service, self._sector_code
        self.chart.clear_index_overlay()
        if code:
            self._submit('index', lambda: (code, service.index_history(code)))

    def _sync_index_overlay(self):
        if not self._index_enabled or not self._history or self._chart_code.startswith('sh880') or self._index_code != self._sector_code:
            self.chart.clear_index_overlay()
            return
        day = self._history[len(self._history)-1-self._offset].date
        closed = day < self.context.date or self.context.closed
        bars = [b for b in self._index_bars if b.date <= day]
        if bars and not closed and bars[-1].date == day:
            last = bars[-1]
            bars[-1] = replace(last, high=last.open, low=last.open, close=last.open, amount=0, volume=0)
        self.chart.set_index_overlay(bars, day, closed)

    def eventFilter(self, watched, event):
        # 事件过滤器也装在分类按钮上，构造期这类控件还没有 chart，统一用安全取值。
        chart = getattr(self, 'chart', None)
        sector_table = getattr(self, 'sector_table', None)
        stock_table = getattr(self, 'stock_table', None)
        if (
            event.type() == QEvent.Type.MouseButtonDblClick
            and watched in self.category_buttons.values()
        ):
            # 双击分类标签：板块列表强制回到顶部，方便从第 1 名往下看。
            self.scroll_sectors_to_top()
            return True
        if event.type() == QEvent.Type.Resize:
            if sector_table is not None and watched is sector_table.viewport():
                QTimer.singleShot(0, lambda: self._fit_table_columns(sector_table, True))
            elif stock_table is not None and watched is stock_table.viewport():
                QTimer.singleShot(0, lambda: self._fit_table_columns(stock_table, False))
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint() if hasattr(event, 'position') else event.pos()
            table = None
            if sector_table is not None and watched is sector_table.viewport():
                table = sector_table
            elif stock_table is not None and watched is stock_table.viewport():
                table = stock_table
            if table is not None:
                if table.itemAt(position) is None:
                    self._clear_focus_frame()
                    return True
            if chart is not None and watched is chart:
                chart_rect, _volume_rect, _macd_rect = chart._areas()
                if chart_rect.contains(position) and chart._hit_candle_slot(
                    chart_rect, position.x(), position.y()
                ) is None:
                    self._clear_focus_frame()
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space and watched in (chart, stock_table, sector_table):
            if not event.isAutoRepeat():
                now = time.monotonic()
                if self._space_tap and now-self._space_tap <= .36:
                    self._space_tap = 0.0
                    self._toggle_index_overlay()
                else:
                    self._space_tap = now
            return True
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and watched in (stock_table, sector_table)
        ):
            # 回车等同于向下方向键：选中一行后可以连续按回车往下浏览。
            if not event.isAutoRepeat():
                self._select_next_row(watched)
            return True
        if chart is not None and watched is chart and event.type() == QEvent.Type.KeyPress:
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if (ctrl and event.key() == Qt.Key.Key_Left) or event.key() == Qt.Key.Key_End:
                self._navigate_date('first')
                return True
            if (ctrl and event.key() == Qt.Key.Key_Right) or event.key() == Qt.Key.Key_Home:
                self._navigate_date('last')
                return True
            if event.text().isdigit() and not ctrl:
                self.date_edit.setFocus()
                self.date_edit.setText(event.text())
                return True
        return super().eventFilter(watched, event)

    def _advance(self):
        if self.context.locked:
            self.advance_requested.emit()
        else:
            service = self.service
            day = self.date_edit.text().strip()
            if self._history and self._offset:
                day = self._history[len(self._history)-1-self._offset].date
            code = self._sector_code or MARKET_CALENDAR_CODE
            self._submit('next', lambda: service.next_date(day, code))

    def _draw(self):
        bars = self._history
        self._offset = max(0, min(self._offset, max(0, len(bars) - 1)))
        end = len(bars) - self._offset
        visible = bars[max(0, end - self._window):end]
        # 始终按用户设定的缩放绘制：新股等历史不足时 K 线保持正常宽度并右对齐，
        # 不会为了铺满整屏被横向拉伸。
        self.chart.set_data(bars, visible, [], max(0, len(bars)-1), self._offset, self._window, True,
                            current_node=TradeNode.CLOSE if not self.context or self.context.closed else TradeNode.OPEN)
        self._sync_index_overlay()

    def _change_subpane_count(self, delta):
        """Handle the shared chart menu using only this page's chart state."""
        self.chart.set_sub_pane_count(len(self.chart.sub_pane_indicators) + delta)

    def pan_left(self, steps=1):
        self._offset += steps
        self._draw()

    def pan_right(self, steps=1):
        self._offset -= steps
        self._draw()

    def zoom_in(self):
        self._window = max(MIN_SECTOR_CHART_BARS, int(self._window * SECTOR_ZOOM_IN_FACTOR))
        self._draw()

    def zoom_out(self):
        self._window = min(MAX_SECTOR_CHART_BARS, int(self._window * SECTOR_ZOOM_OUT_FACTOR))
        self._draw()

    def zoom_in_fully(self):
        self._window = MIN_SECTOR_CHART_BARS
        self._draw()

    def zoom_out_fully(self):
        self._window = MAX_SECTOR_CHART_BARS
        self._draw()

    def latest(self):
        self._navigate_date('last')

    def set_adjust_type(self, mode):
        if mode not in ('none', 'qfq', 'hfq') or mode == self.adjust_type:
            return
        self.adjust_type = mode
        if self._chart_code:
            self._load_chart(self._chart_code, '')

    def reset_zoom(self):
        self._window = DEFAULT_SECTOR_CHART_BARS
        self._draw()
