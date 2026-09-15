from __future__ import annotations

import csv
import json
from dataclasses import replace
from html import escape
import math
import os
import random
import re
import sys
import time
from .persistence import validate_session_document, session_path
from .storage_safety import preserve_invalid_file, consume_storage_notices
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRectF, QRunnable, QSize, QStandardPaths, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .adjust import GbbqProvider, locate_gbbq_path
from .config import CONFIG_PATH, AppSettings, ensure_packaged_user_files, load_settings, save_settings
from .config import bundled_market_directory
from .data_migration import (
    DEFAULT_ADJUSTED_CACHE_LIMIT_BYTES,
    MigrationPackageError,
    calculate_storage_usage,
    clear_adjusted_bars_cache,
    export_migration_package,
    import_migration_package,
    run_scheduled_cache_maintenance,
)
from .engine import DailySimulationEngine
from .index_data import (
    SHANGHAI_INDEX_CODE,
    SHANGHAI_INDEX_NAME,
    fetch_shanghai_index_bars,
    is_shanghai_index_query,
    load_index_cache,
    merge_index_bars,
    save_index_cache,
)
from .kline_widget import KLineWidget, MAX_SUB_PANE_COUNT
from .market_sync import LocalMarketUpdate, sync_local_market
from .market_stats import (
    DailyMarketStats,
    MarketStatsBuildResult,
    build_market_stats_cache,
    fetch_public_market_stats,
    format_market_amount,
    index_ma_state,
    load_market_stats_cache,
    load_market_stats_snapshot,
    market_amount_change_pct,
    market_state_text,
    previous_market_stats,
    public_market_stats_date,
    save_public_market_stats,
)
from .models import DailyBar, EquityPoint, PositionSlot, RoundRecord, TradeNode, TradeSegment
from .performance import (
    PerformanceMetrics,
    benchmark_interval_return,
    build_trade_segments,
    calculate_performance_metrics,
)
from .performance_overlay import PerformanceOverlay
from .persistence import (
    delete_document,
    equity_point_from_dict,
    equity_point_to_dict,
    load_performance_history,
    load_document,
    round_from_dict,
    round_to_dict,
    save_document,
    save_performance_history,
    slot_from_dict,
    slot_to_dict,
    trade_from_dict,
    trade_to_dict,
)
from .portable_builder import PortableBuildResult, build_portable_folder
from .sample_data import SAMPLE_KLINE_NAME, create_continued_sample_engine, create_sample_engine, load_sample_bars
from .session import (
    choose_continued_session_data,
    choose_session_data,
    create_continued_engine,
    create_engine,
    normalize_start_date,
)
from .stock_info import (
    BOARD_CATEGORIES,
    BOARD_CATEGORY_LABELS,
    StockInfoReader,
    stock_category,
)
from .tdx_reader import TdxDataError, TdxDataLocation, TdxDayReader, find_tdx_installation, resolve_tdx_location
from .test_trade import menu_presentation, test_window_anchor
from .ui_state import (
    budget_from_ratio,
    change_metrics,
    format_title,
    holding_avg_price,
    maximum_drawdown,
    maximum_drawdown_span,
    open_close_range_amplitude,
    percent_change_from_base,
    post_buy_highest_change_from_base,
    visible_bars,
)


_SYSTEM_INFORMATION_MESSAGE_BOX = QMessageBox.information
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "app_icon.png"
EYE_ICON_PATH = Path(__file__).resolve().parent / "assets" / "eye_white.svg"
EYE_OFF_ICON_PATH = Path(__file__).resolve().parent / "assets" / "eye_white_off.svg"
PLAYBACK_ARROW_ICON_PATH = Path(__file__).resolve().parent / "assets" / "playback_arrow_gold.png"
INVESTMENT_QUOTES_PATH = Path(__file__).resolve().parent / "assets" / "investment_quotes.json"
APP_NAME = "大A日K股票模拟训练器-轩轩居士开发"
MIN_CHART_WINDOW_SIZE = 55
DEFAULT_CHART_WINDOW_SIZE = 120
MAX_CHART_WINDOW_SIZE = 750
ZOOM_IN_FACTOR = 0.72
ZOOM_OUT_FACTOR = 1.35
ACCOUNT_KEY_LABEL_WIDTH = 86
COMPACT_ACCOUNT_KEY_LABEL_WIDTH = 70
COMPACT_SIDE_PANEL_MIN_WIDTH = 292
COMPACT_SIDE_PANEL_MAX_WIDTH = 344
COMPACT_SIDE_PANEL_TARGET_WIDTH = 304
COMPACT_METRIC_HEIGHT = 40
COMPACT_MIN_PHYSICAL_WIDTH = 1700
COMPACT_MAX_PHYSICAL_WIDTH = 2600
COMPACT_MAX_PHYSICAL_HEIGHT = 1250
LOW_RES_MAX_PHYSICAL_WIDTH = 1500
LOW_RES_MAX_PHYSICAL_HEIGHT = 900
LOW_RES_ACCOUNT_KEY_LABEL_WIDTH = 60
LOW_RES_SIDE_PANEL_MIN_WIDTH = 252
LOW_RES_SIDE_PANEL_MAX_WIDTH = 336
LOW_RES_SIDE_PANEL_TARGET_WIDTH = 276
LOW_RES_METRIC_HEIGHT = 36
# 个股页顶部“股票 / 开始日期”输入框统一宽度（两者等宽）；通达信目录略宽一些。
TOP_CODE_FIELD_WIDTH = 120
TOP_TDX_FIELD_WIDTH = 260
RANDOM_SWITCH_COOLDOWN_MS = 35
RANDOM_PREFETCH_TARGET = 5
RANDOM_TRAINING_HORIZONS = (
    ("1m", "1个月", 20),
    ("3m", "3个月", 60),
    ("6m", "半年", 120),
    ("1y", "1年及以上", 240),
)
TRAINING_MODE_SINGLE = "single"
TRAINING_MODE_INDEPENDENT = "independent"
TRAINING_MODE_CONTINUOUS = "continuous"
TRAINING_MODE_LABELS = {
    TRAINING_MODE_SINGLE: "单吊模式",
    TRAINING_MODE_INDEPENDENT: "独立训练模式",
    TRAINING_MODE_CONTINUOUS: "连续复利模式",
}
TRAINING_MODE_BADGES = {
    TRAINING_MODE_SINGLE: "单吊\n模式",
    TRAINING_MODE_INDEPENDENT: "独立\n模式",
    TRAINING_MODE_CONTINUOUS: "复利\n模式",
}
TRAINING_MODE_DESCRIPTIONS = {
    TRAINING_MODE_SINGLE: "只练习和统计当前一只股票；换股或切换模式后使用设置的初始本金。",
    TRAINING_MODE_INDEPENDENT: "每只股票使用相同初始本金，日期互不约束，并汇总各只股票的练习记录。",
    TRAINING_MODE_CONTINUOUS: "上一只股票的期末资金和时间延续到下一只；切换训练模式前必须先清仓。",
}
INDEX_BROWSE_GUIDANCE = (
    "查看个股请先输入股票代码或拼音首字母，再按回车；"
    "随机训练请点击“开启模拟交易”。"
)
INDEX_PREVIEW_HOLD_MS = 500
DOUBLE_SPACE_INTERVAL_SECONDS = 0.36
STOCK_MARKET_ITEMS = (
    "当日涨跌额",
    "当日涨跌幅",
    "持仓均价",
    "第一笔买入价",
    "最大振幅",
    "买入后到目前涨跌幅",
    "买入后最高涨幅",
)
POSITION_MARKET_ITEMS = STOCK_MARKET_ITEMS[2:]
INDEX_MARKET_ITEMS = (
    "上证涨跌",
    "上涨/下跌家数",
    "沪深京成交额",
    "较昨日成交额",
    "涨停/跌停家数",
    "均线位置",
    "市场状态",
)


def _show_silent_message_box(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    """Show a standard modal message without the Windows alert sound."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.NoIcon)
    box.setStandardButtons(buttons)
    if default_button != QMessageBox.StandardButton.NoButton:
        box.setDefaultButton(default_button)
    return QMessageBox.StandardButton(box.exec())


def _silent_information(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    return _show_silent_message_box(parent, title, text, buttons, default_button)


def _silent_warning(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    return _show_silent_message_box(parent, title, text, buttons, default_button)


def _silent_critical(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    return _show_silent_message_box(parent, title, text, buttons, default_button)


def _silent_question(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = (
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    ),
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    return _show_silent_message_box(parent, title, text, buttons, default_button)


# QMessageBox chooses a Windows system sound from its icon. Keeping the normal
# static API preserves existing call sites; NoIcon makes every message silent.
QMessageBox.information = staticmethod(_silent_information)
QMessageBox.warning = staticmethod(_silent_warning)
QMessageBox.critical = staticmethod(_silent_critical)
QMessageBox.question = staticmethod(_silent_question)


def _is_offscreen() -> bool:
    return os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen"


def _audible_information(parent: QWidget | None, title: str, text: str):
    """Use the native information dialog and its system sound on real desktops."""
    if _is_offscreen():
        return QMessageBox.information(parent, title, text)
    return _SYSTEM_INFORMATION_MESSAGE_BOX(parent, title, text)


def _play_buy_success_sound() -> None:
    """Play the user's short Windows information sound after an accepted buy."""

    if _is_offscreen():
        return
    try:
        import winsound

        winsound.PlaySound(
            "SystemAsterisk",
            winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
    except (ImportError, OSError, RuntimeError):
        application = QApplication.instance()
        if application is not None:
            application.beep()


def _repolish_widget(widget) -> None:
    """Force a style re-apply, but skip on the headless offscreen platform.

    On the offscreen (test) platform, repeatedly unpolish/polish can trigger a
    Qt style pass that never settles and blocks the main thread. Real desktop
    users are unaffected; this simply keeps headless runs from hanging.
    """
    if _is_offscreen():
        return
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class IndexUpdateWorker(QRunnable):
    def __init__(self, history, callback):
        super().__init__()
        self.setAutoDelete(False)
        self.history = history
        self.callback = callback

    def run(self) -> None:
        try:
            bars = fetch_shanghai_index_bars(self.history)
        except Exception:
            bars = []
        try:
            self.callback(bars)
        except RuntimeError:
            pass


class MarketStatsWorker(QRunnable):
    def __init__(self, cache_path: Path, location: TdxDataLocation, previous, callback):
        super().__init__()
        self.setAutoDelete(False)
        self.cache_path = cache_path
        self.location = location
        self.previous = previous
        self.callback = callback

    def run(self) -> None:
        try:
            result = sync_local_market(self.cache_path.parent, self.location, self.previous)
            payload = (str(self.location.root), result, "")
        except Exception as exc:
            payload = (str(self.location.root), None, str(exc))
        try:
            self.callback(payload)
        except RuntimeError:
            pass


class PublicMarketStatsWorker(QRunnable):
    def __init__(self, callback):
        super().__init__()
        self.setAutoDelete(False)
        self.callback = callback

    def run(self) -> None:
        try:
            payload = (fetch_public_market_stats(), "")
        except Exception as exc:
            payload = (None, str(exc))
        try:
            self.callback(payload)
        except RuntimeError:
            pass


class GbbqLoadWorker(QRunnable):
    def __init__(self, provider, callback):
        super().__init__()
        self.setAutoDelete(False)
        self.provider = provider
        self.callback = callback

    def run(self) -> None:
        try:
            self.provider.initialize(force=False)
            payload = (self.provider.ready, self.provider.error or "")
        except Exception as exc:
            payload = (False, str(exc))
        try:
            self.callback(payload)
        except RuntimeError:
            pass


class SectorWarmupWorker(QRunnable):
    """Prepare sector catalogs and quote caches off the UI thread."""

    def __init__(self, context, cache_dir: Path, callback):
        super().__init__()
        self.setAutoDelete(False)
        self.context = context
        self.cache_dir = Path(cache_dir)
        self.callback = callback

    def run(self) -> None:
        try:
            from .sectors.service import SectorService

            if not getattr(self.context, 'root', ''):
                raise ValueError('没有可用的通达信目录')
            service = SectorService(self.context.root, cache_dir=self.cache_dir)
            service.info._load_name_cache()
            for category, level in (
                ('concept', 1),
                ('style', 1),
                ('industry', 1),
                ('industry', 2),
            ):
                service.sector_quotes(self.context, level=level, category=category)
            payload = (True, '')
        except Exception as exc:
            payload = (False, str(exc))
        try:
            self.callback(payload)
        except RuntimeError:
            pass


class SectorMemberWarmupWorker(QRunnable):
    """Warm every local stock quote once so any sector opens from cache."""

    def __init__(self, context, cache_dir: Path, callback):
        super().__init__()
        self.setAutoDelete(False)
        self.context = context
        self.cache_dir = Path(cache_dir)
        self.callback = callback

    def run(self) -> None:
        try:
            from .sectors.service import SectorService

            if not getattr(self.context, 'root', ''):
                raise ValueError('没有可用的通达信目录')
            service = SectorService(self.context.root, cache_dir=self.cache_dir)
            codes = set()
            for category, level in (
                ('concept', 1),
                ('style', 1),
                ('industry', 1),
                ('industry', 2),
            ):
                for sector in service.sectors(level=level, category=category):
                    codes.update(service.member_codes(sector.code))
            # “今日涨停 / 今日连板 / 今日跌停”需要覆盖全市场，这里把本地
            # 所有个股日K都预热一遍，避免漏掉没有归入任何板块的股票。
            try:
                codes.update(TdxDayReader(self.context.root).scan_stock_codes())
            except Exception:
                pass
            service.warm_stock_quotes(sorted(codes), self.context)
            payload = (True, '')
        except Exception as exc:
            payload = (False, str(exc))
        try:
            self.callback(payload)
        except RuntimeError:
            pass


class RandomSessionPrefetchWorker(QRunnable):
    """Prepare a random stock entirely off the UI thread."""

    def __init__(
        self,
        generation: int,
        mode: str,
        reader: TdxDayReader,
        info_reader: StockInfoReader,
        callback,
        after_date: str = "",
        exclude_code: str = "",
        min_forward_bars: int = 120,
        allowed_codes: set[str] | None = None,
    ):
        super().__init__()
        self.setAutoDelete(False)
        self.generation = generation
        self.mode = mode
        self.reader = reader
        self.info_reader = info_reader
        self.callback = callback
        self.after_date = after_date
        self.exclude_code = exclude_code
        self.min_forward_bars = max(1, int(min_forward_bars))
        self.allowed_codes = allowed_codes

    def run(self) -> None:
        try:
            if self.mode == "continuation":
                bars, start_index, code = choose_continued_session_data(
                    self.reader,
                    self.after_date,
                    self.exclude_code or None,
                    min_forward_bars=self.min_forward_bars,
                    allowed_codes=self.allowed_codes,
                )
            else:
                bars, start_index = choose_session_data(
                    self.reader,
                    None,
                    None,
                    min_forward_bars=self.min_forward_bars,
                    allowed_codes=self.allowed_codes,
                )
                code = bars[0].code
            # Random training is fixed to forward-adjusted data. Do not eagerly
            # calculate the unused raw/backward-adjusted variants here.
            variants = {"qfq": bars}
            name = self.info_reader.name_for(code) or code
            error = ""
        except Exception as exc:
            bars, start_index, code, name, variants, error = [], 0, "", "", {}, str(exc)
        payload = (
            self.generation,
            self.mode,
            os.path.normcase(os.path.abspath(str(self.reader.tdx_root))),
            self.reader.adjust_type,
            self.after_date,
            self.exclude_code,
            self.min_forward_bars,
            bars,
            start_index,
            code,
            name,
            variants,
            error,
        )
        try:
            self.callback(payload)
        except RuntimeError:
            pass


class PortableBuildWorker(QRunnable):
    def __init__(self, destination: Path, user_data_root: Path, project_root: Path, callback, market_source=None, include_market_data=True):
        super().__init__()
        self.setAutoDelete(False)
        self.destination = destination
        self.user_data_root = user_data_root
        self.project_root = project_root
        self.callback = callback
        self.market_source = market_source
        self.include_market_data = include_market_data

    def run(self) -> None:
        try:
            result = build_portable_folder(
                self.destination,
                self.user_data_root,
                project_root=self.project_root,
                market_source=self.market_source,
                include_market_data=self.include_market_data,
            )
            payload = {"result": result, "include_market_data": self.include_market_data}
        except Exception as exc:
            payload = {"error": str(exc)}
        try:
            self.callback(payload)
        except RuntimeError:
            pass


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space} and self.isEnabled():
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PlaybackAdvanceButton(QPushButton):
    """High-emphasis playback control with a lightweight gold shimmer."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("PlaybackAdvanceButton")
        self.setMinimumHeight(72)
        self.setMaximumHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("推进到下一交易阶段")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.test_mode_active = False
        self.formal_mode_badge_text = TRAINING_MODE_BADGES[TRAINING_MODE_CONTINUOUS]
        self.mode_badge_text = self.formal_mode_badge_text
        self._shimmer_progress = -0.35
        self._shimmer_timer = QTimer(self)
        self._shimmer_timer.setInterval(42)
        self._shimmer_timer.timeout.connect(self._advance_shimmer)

    def set_test_mode(self, active: bool) -> None:
        self.set_mode_badge(self.formal_mode_badge_text, test_mode_active=active)

    def set_mode_badge(self, formal_badge_text: str, test_mode_active: bool = False) -> None:
        formal_badge_text = str(formal_badge_text)
        test_mode_active = bool(test_mode_active)
        badge_text = "测试\n模式" if test_mode_active else formal_badge_text
        if (
            self.test_mode_active == test_mode_active
            and self.formal_mode_badge_text == formal_badge_text
            and self.mode_badge_text == badge_text
        ):
            return
        self.test_mode_active = test_mode_active
        self.formal_mode_badge_text = formal_badge_text
        self.mode_badge_text = badge_text
        self.setAccessibleName(
            f"{badge_text.replace(chr(10), '')}，推进到下一交易阶段"
        )
        self.update()

    def _advance_shimmer(self) -> None:
        self._shimmer_progress += 0.018
        if self._shimmer_progress > 1.35:
            self._shimmer_progress = -0.35
        self.update()

    def _sync_animation_state(self) -> None:
        should_run = self.isVisible() and self.isEnabled()
        if should_run and not self._shimmer_timer.isActive():
            self._shimmer_timer.start()
        elif not should_run and self._shimmer_timer.isActive():
            self._shimmer_timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animation_state()

    def hideEvent(self, event) -> None:
        self._shimmer_timer.stop()
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self._sync_animation_state()

    @staticmethod
    def _fit_font(text: str, target_width: float, start_size: int, minimum_size: int) -> QFont:
        font = QFont("Microsoft YaHei UI", start_size)
        font.setWeight(QFont.Weight.Bold)
        while font.pointSize() > minimum_size:
            metrics = QPainterPath()
            metrics.addText(0, 0, font, text)
            if metrics.boundingRect().width() <= target_width:
                break
            font.setPointSize(font.pointSize() - 1)
        return font

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = 10.0

        enabled = self.isEnabled()
        hovered = self.underMouse() and enabled
        pressed = self.isDown() and enabled
        if not enabled:
            left, middle, right = "#172338", "#22263e", "#30263f"
        elif pressed:
            left, middle, right = "#1858c9", "#554fc7", "#9452ca"
        elif hovered:
            left, middle, right = "#2c83ff", "#7169f2", "#c170f0"
        else:
            left, middle, right = "#216fe5", "#625de0", "#ac63e2"

        background = QLinearGradient(outer.left(), outer.top(), outer.right(), outer.bottom())
        background.setColorAt(0.0, QColor(left))
        background.setColorAt(0.48, QColor(middle))
        background.setColorAt(1.0, QColor(right))
        painter.setBrush(background)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(outer, radius, radius)

        narrow = outer.width() < 320.0
        horizontal_padding = 10.0 if narrow else 16.0
        title_rect = outer.adjusted(horizontal_padding, 5.0, -horizontal_padding, -5.0)
        arrow_size = min(38.0, max(28.0, outer.height() - 12.0))
        title_arrow_gap = 12.0 if narrow else 20.0
        badge_width = 34.0
        badge_gap = 10.0
        title_font = self._fit_font(
            self.text(),
            max(80.0, title_rect.width() - arrow_size - title_arrow_gap - badge_width - badge_gap),
            16 if narrow else 18,
            12 if narrow else 14,
        )
        title_path = QPainterPath()
        title_path.addText(0, 0, title_font, self.text())
        title_bounds = title_path.boundingRect()
        group_width = title_bounds.width() + badge_gap + badge_width + title_arrow_gap + arrow_size
        group_left = outer.center().x() - group_width / 2.0
        title_x = group_left - title_bounds.left()
        title_y = title_rect.center().y() + title_bounds.height() / 2.0 - title_bounds.bottom()
        title_path.translate(title_x, title_y)

        if enabled:
            shimmer = max(-0.2, min(1.2, self._shimmer_progress))
            text_gradient = QLinearGradient(group_left, 0, group_left + title_bounds.width(), 0)
            text_gradient.setColorAt(0.0, QColor("#ffe7a0"))
            if 0.0 < shimmer < 1.0:
                for position, color in (
                    (shimmer - 0.12, QColor("#ffd06a")),
                    (shimmer - 0.035, QColor("#fff9dc")),
                    (shimmer + 0.035, QColor("#ffffff")),
                    (shimmer + 0.12, QColor("#ffd06a")),
                ):
                    if 0.0 < position < 1.0:
                        text_gradient.setColorAt(position, color)
            text_gradient.setColorAt(1.0, QColor("#ffe7a0"))
            painter.fillPath(title_path, text_gradient)
        else:
            painter.fillPath(title_path, QColor("#707a99"))

        badge_rect = QRectF(
            group_left + title_bounds.width() + badge_gap,
            outer.center().y() - 22.0,
            badge_width,
            44.0,
        )
        badge_font = QFont("Microsoft YaHei UI", 9, QFont.Weight.Bold)
        painter.setFont(badge_font)
        painter.setPen(QColor("#fff2bd") if enabled else QColor("#707a99"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, self.mode_badge_text)

        arrow_rect = QRectF(
            group_left + title_bounds.width() + badge_gap + badge_width + title_arrow_gap,
            outer.center().y() - arrow_size / 2.0,
            arrow_size,
            arrow_size,
        )
        arrow_pixmap = QPixmap(str(PLAYBACK_ARROW_ICON_PATH)).scaled(
            arrow_rect.size().toSize(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if not enabled:
            disabled_arrow = arrow_pixmap.copy()
            icon_painter = QPainter(disabled_arrow)
            icon_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            icon_painter.fillRect(disabled_arrow.rect(), QColor("#727a96"))
            icon_painter.end()
            arrow_pixmap = disabled_arrow
        arrow_target = QRectF(
            arrow_rect.center().x() - arrow_pixmap.width() / 2.0,
            arrow_rect.center().y() - arrow_pixmap.height() / 2.0,
            arrow_pixmap.width(),
            arrow_pixmap.height(),
        )
        painter.save()
        painter.setOpacity(1.0 if enabled else 0.82)
        painter.drawPixmap(arrow_target.toRect(), arrow_pixmap)
        painter.restore()

class MainWindow(QMainWindow):
    _index_update_requested = False
    index_update_completed = Signal(object)
    market_stats_completed = Signal(object)
    public_market_stats_completed = Signal(object)
    adjust_completed = Signal(object)
    random_prefetch_completed = Signal(object)
    portable_build_completed = Signal(object)
    sector_warmup_completed = Signal(object)
    sector_deep_warmup_completed = Signal(object)
    startup_ready = Signal()

    def __init__(self):
        super().__init__()
        ensure_packaged_user_files()
        self._migration_restore_pending_restart = False
        self._startup_cache_cleanup = run_scheduled_cache_maintenance(CONFIG_PATH.parent)
        self.settings = load_settings()
        startup_location = resolve_tdx_location(self.settings.tdx_root)
        self.adjust_provider = self._make_adjust_provider(self.settings.tdx_root)
        self.adjust_provider_root = self.settings.tdx_root
        self.reader = TdxDayReader(
            startup_location or self.settings.tdx_root,
            adjust_provider=self.adjust_provider,
            adjust_type=self.settings.adjust_type,
            adjust_cache_dir=CONFIG_PATH.parent / "adjusted_bars_cache",
        )
        self.info_reader = StockInfoReader(self.settings.tdx_root)
        self.engine: DailySimulationEngine | None = None
        self.training_mode = True
        self.test_trade_active = False
        self._test_trade_browse_context: dict | None = None
        self._test_trade_start_index: int | None = None
        self._test_trade_future_slots = 0
        self.trade_started = True
        self.viewed_bar_index: int | None = None
        self.browsing_stock_name = ""
        self.shanghai_index_bars = []
        self.market_stats_by_date: dict[str, DailyMarketStats] = (
            load_market_stats_cache(CONFIG_PATH.parent / "market_stats_daily.json", startup_location.root)
            if startup_location is not None else {}
        )
        self.market_stats_root = ""
        self.market_stats_requested_root = ""
        self.market_stats_status = "" if self.market_stats_by_date else "市场统计待更新"
        self.market_stats_pending_location: TdxDataLocation | None = None
        self.index_preview_active = False
        self.index_overlay_active = False
        self.last_space_tap_time = 0.0
        self.global_stock_input_active = False
        self.global_date_input_active = False
        self.using_sample_kline = False
        self.current_node = TradeNode.OPEN
        self.chart_window_size = DEFAULT_CHART_WINDOW_SIZE
        self.pan_offset = 0
        self.reveal_current_full = False
        self._advance_button_show_close = False
        self.first_buy_price: float | None = None
        self.first_buy_index: int | None = None
        self.first_buy_node = TradeNode.OPEN
        self.active_cycle_start_cash: float | None = None
        self._frozen_position_metrics: dict[str, tuple[str, str]] | None = None
        self.completed_trade_ranges: list[tuple[int, int, float]] = []
        self.equity_curve: list[float] = []
        self.equity_points: list[EquityPoint] = []
        self.round_equity_points: list[EquityPoint] = []
        self.drawdown_overlay_active = False
        self._last_equity_record_key: tuple[int, TradeNode, bool, int, float] | None = None
        self._performance_summary_key: tuple | None = None
        self.selected_buy_ratio: float | None = self.settings.selected_buy_ratio
        self.selected_sell_ratio: float | None = self.settings.selected_sell_ratio
        self._trade_input_syncing = False
        self._buy_input_mode = "amount"
        self._sell_input_mode = "amount"
        self._random_switch_locked = False
        self._random_prefetch_generation = 0
        self._random_prefetch_queue: list[tuple[dict[str, list[DailyBar]], int, str, str]] = []
        self._random_prefetch_worker: RandomSessionPrefetchWorker | None = None
        self._random_prefetch_reader: TdxDayReader | None = None
        self._random_prefetch_info_reader: StockInfoReader | None = None
        self._random_prefetch_root = ""
        self._random_prefetch_adjust_type = ""
        self._random_switch_pending = False
        self._continuation_prefetch_generation = 0
        self._continuation_prefetch_worker: RandomSessionPrefetchWorker | None = None
        self._continuation_prefetch_reader: TdxDayReader | None = None
        self._continuation_prefetch_info_reader: StockInfoReader | None = None
        self._continuation_prefetch_candidate: tuple[tuple[str, str, str, str, int], dict[str, list[DailyBar]], int, str, str] | None = None
        self._continuation_prefetch_request: tuple[str, str, str, str, int] | None = None
        self._continuation_switch_pending = False
        self._portable_build_worker: PortableBuildWorker | None = None
        self._prefetched_stock_names: dict[str, str] = {}
        self._prefetched_bar_variants: dict[str, dict[str, list[DailyBar]]] = {}
        self._session_restore_pending = False
        self.training_mode_kind = (
            self.settings.training_mode
            if self.settings.training_mode in TRAINING_MODE_LABELS
            else TRAINING_MODE_CONTINUOUS
            if self.settings.continuous_compound_mode
            else TRAINING_MODE_SINGLE
        )
        self.continuous_compound_mode: bool = self.training_mode_kind == TRAINING_MODE_CONTINUOUS
        self._independent_switch_pending = False
        self._single_switch_pending = False
        self.account_initial_cash: float | None = None
        self.round_records: list[RoundRecord] = []
        self.round_start_cash: float | None = None
        self.round_start_date: str = ""
        self.round_start_node: TradeNode = TradeNode.OPEN
        self.ordinary_performance_records: list[RoundRecord] = load_performance_history()
        self.cumulative_holding_days_base: int = 0
        self.engine_epoch: int = 0
        self.account_baseline_locked: bool = False
        self._layout_density = "normal"
        self._compact_layout = False
        self._low_resolution_layout = False
        self._immersive_fullscreen = False
        self._fullscreen_previous_window_state = Qt.WindowState.WindowNoState
        self._fullscreen_hidden_visibility: list[tuple[QWidget, bool]] = []
        self._return_to_trading_context: dict | None = None
        self.reviewed_round_index: int | None = None
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.setWindowTitle(APP_NAME)
        self.resize(self.settings.window_width, self.settings.window_height)
        self._window_layout_restored = False
        self._build_ui()
        from .sector_integration import SectorIntegration
        self.sector_integration = SectorIntegration(self)
        self._refresh_market_source_title()
        self._build_snapshot_notice()
        self._apply_style()
        self._sync_responsive_layout()
        # Keep action-button height independent of the compact input row.
        self._dock_quick_actions_panel(True)
        self._update_status("请选择通达信目录，然后开始模拟。")
        self.index_update_worker: IndexUpdateWorker | None = None
        self.market_stats_worker: MarketStatsWorker | None = None
        self._market_sync_location = startup_location
        self._market_sync_fingerprint = None
        self._market_sync_memory_shape = None
        self._market_sync_timer = QTimer(self)
        self._market_sync_timer.setInterval(5000)
        self._market_sync_timer.timeout.connect(self._check_local_market)
        if not _is_offscreen():
            self._market_sync_timer.start()
        self.public_market_stats_worker: PublicMarketStatsWorker | None = None
        self.adjust_worker: GbbqLoadWorker | None = None
        self.sector_warmup_worker: SectorWarmupWorker | None = None
        self._sector_warmup_error = ""
        self.sector_deep_warmup_worker: SectorMemberWarmupWorker | None = None
        self._sector_deep_warmup_started = False
        self._sector_deep_warmup_scheduled = False
        self._startup_ready_emitted = False
        self.index_update_completed.connect(self._finish_shanghai_index_update)
        self.market_stats_completed.connect(self._finish_market_stats_update)
        self.public_market_stats_completed.connect(self._finish_public_market_stats_update)
        self.adjust_completed.connect(self._finish_adjust_initialize)
        self.random_prefetch_completed.connect(self._finish_random_prefetch)
        self.portable_build_completed.connect(self._finish_portable_build)
        self.sector_warmup_completed.connect(self._finish_sector_warmup)
        self.sector_deep_warmup_completed.connect(self._finish_sector_deep_warmup)
        self.index_preview_timer = QTimer(self)
        self.index_preview_timer.setSingleShot(True)
        self.index_preview_timer.setInterval(INDEX_PREVIEW_HOLD_MS)
        self.index_preview_timer.timeout.connect(self._show_held_index_preview)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(900)
        self._persist_timer.timeout.connect(self._persist_session)
        if startup_location is not None:
            self._reset_random_prefetch(startup_location)
        self._session_restore_pending = bool(
            self.settings.adjust_type != "none"
            and self.adjust_provider is not None
            and not self.adjust_provider.ready
        )
        if not self._session_restore_pending:
            self._restore_session()
        QTimer.singleShot(0, self._load_startup_market)
        self._start_adjust_initialize()
        QTimer.singleShot(0, self._start_sector_warmup)
        QTimer.singleShot(0, self._show_storage_notices)

    def _show_storage_notices(self) -> None:
        notices = consume_storage_notices(CONFIG_PATH.parent)
        if notices:
            self._update_status("；".join(notices))

    def _build_snapshot_notice(self) -> None:
        self.snapshot_flash = QFrame(self.centralWidget())
        self.snapshot_flash.setObjectName("SnapshotFlash")
        self.snapshot_flash.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.snapshot_flash.hide()
        self.snapshot_flash_timer = QTimer(self)
        self.snapshot_flash_timer.setSingleShot(True)
        self.snapshot_flash_timer.timeout.connect(self.snapshot_flash.hide)
        self.snapshot_notice = QLabel(self.centralWidget())
        self.snapshot_notice.setObjectName("SnapshotNotice")
        self.snapshot_notice.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.snapshot_notice.hide()
        self.snapshot_notice_timer = QTimer(self)
        self.snapshot_notice_timer.setSingleShot(True)
        self.snapshot_notice_timer.timeout.connect(self.snapshot_notice.hide)

    def _show_snapshot_notice(self, text: str, error: bool = False) -> None:
        self.snapshot_notice.setText(text)
        self.snapshot_notice.setProperty("error", error)
        _repolish_widget(self.snapshot_notice)
        self.snapshot_notice.adjustSize()
        parent = self.centralWidget()
        chart_origin = self.kline_widget.mapTo(parent, QPoint(0, 0))
        x = max(0, chart_origin.x() + 24)
        y = max(0, chart_origin.y() + 44)
        self.snapshot_notice.move(x, y)
        self.snapshot_notice.raise_()
        self.snapshot_notice.show()
        self.snapshot_notice_timer.start(2200)

    def _flash_snapshot_capture(self) -> None:
        self.snapshot_flash.setGeometry(self.centralWidget().rect())
        self.snapshot_flash.raise_()
        self.snapshot_flash.show()
        self.snapshot_flash_timer.start(120)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        self.root_layout = layout

        top_bar = self._build_top_bar()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_chart_panel())
        self.chart_panel_layout.insertWidget(0, top_bar)
        splitter.addWidget(self._build_side_panel())
        splitter.setSizes([960, 400])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.splitterMoved.connect(self._main_splitter_moved)
        self.main_splitter = splitter
        self.side_panel_scroll.installEventFilter(self)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

        self._build_file_menu()
        self._build_simulation_menu()
        self._build_training_mode_menu()
        self._build_trade_menu()
        self._build_view_menu()
        self._build_drawing_menu()
        self._build_adjust_menu()
        self._build_help_menu()
        self._sync_menu_actions()

    def _dispatch_menu(self, method, *args):
        integration = getattr(self, 'sector_integration', None)
        if integration and integration.active:
            return integration.handle_menu(method, *args)
        return getattr(self, method)(*args)

    def _build_file_menu(self) -> None:
        self.file_menu = self.menuBar().addMenu("文件")
        # Existing keyboard handling owns P/Ctrl+S; the tab only displays it.
        self.file_snapshot_action = QAction("保存当前快照\tP / Ctrl+S", self)
        self.file_export_performance_action = QAction("导出交易统计Excel（含图表）到桌面", self)
        self.file_export_csv_action = QAction("导出原始交易统计CSV到桌面", self)
        self.file_export_csv_action.triggered.connect(lambda _checked=False: self.export_performance_csv())
        self.file_save_config_action = QAction("保存当前配置", self)
        self.file_open_config_action = QAction("打开配置目录", self)
        self.file_data_menu = QMenu("数据备份与迁移", self)
        self.file_build_portable_action = QAction("生成免安装便携版—拷贝即用…", self)
        self.file_build_tdx_portable_action = QAction("生成免安装便携版—配合通达信使用…", self)
        self.file_export_migration_action = QAction("导出轻量数据备份（ZIP）…", self)
        self.file_import_migration_action = QAction("从轻量数据备份恢复…", self)
        self.file_storage_usage_action = QAction("查看本地数据占用", self)
        self.file_clear_cache_action = QAction("清理可重建复权缓存…", self)
        self.file_exit_action = QAction("退出", self)
        self.file_exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.file_snapshot_action.triggered.connect(lambda _checked=False: self._dispatch_menu('save_trade_snapshot'))
        self.file_export_performance_action.triggered.connect(
            lambda _checked=False: self.export_performance_excel()
        )
        self.file_save_config_action.triggered.connect(lambda _checked=False: self.save_current_config())
        self.file_open_config_action.triggered.connect(lambda _checked=False: self.open_config_directory())
        self.file_build_portable_action.triggered.connect(
            lambda _checked=False: self.build_portable_package(include_market_data=True)
        )
        self.file_build_tdx_portable_action.triggered.connect(
            lambda _checked=False: self.build_portable_package(include_market_data=False)
        )
        self.file_export_migration_action.triggered.connect(
            lambda _checked=False: self.export_user_data_package()
        )
        self.file_import_migration_action.triggered.connect(
            lambda _checked=False: self.import_user_data_package()
        )
        self.file_storage_usage_action.triggered.connect(
            lambda _checked=False: self.show_local_storage_usage()
        )
        self.file_clear_cache_action.triggered.connect(
            lambda _checked=False: self.clear_rebuildable_cache()
        )
        self.file_exit_action.triggered.connect(lambda _checked=False: self.close())
        self.file_data_menu.addAction(self.file_build_portable_action)
        self.file_data_menu.addAction(self.file_build_tdx_portable_action)
        self.file_data_menu.addSeparator()
        self.file_data_menu.addAction(self.file_export_migration_action)
        self.file_data_menu.addAction(self.file_import_migration_action)
        self.file_data_menu.addSeparator()
        self.file_data_menu.addAction(self.file_storage_usage_action)
        self.file_data_menu.addAction(self.file_clear_cache_action)
        self.file_menu.addAction(self.file_snapshot_action)
        self.file_menu.addAction(self.file_export_performance_action)
        self.file_menu.addAction(self.file_export_csv_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.file_save_config_action)
        self.file_menu.addAction(self.file_open_config_action)
        self.file_menu.addMenu(self.file_data_menu)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.file_exit_action)

    def _build_simulation_menu(self) -> None:
        self.simulation_menu = self.menuBar().addMenu("模拟")
        self.simulation_choose_dir_action = QAction("选择通达信目录…", self)
        self.simulation_bundled_action = QAction("使用内置历史数据", self)
        self.simulation_bundled_action.setEnabled((bundled_market_directory() / "vipdoc").is_dir())
        self.simulation_bundled_action.triggered.connect(lambda _checked=False: self._dispatch_menu('use_bundled_market'))
        self.simulation_sample_action = QAction("载入测试K线", self)
        self.simulation_start_action = QAction("开启模拟交易", self)
        # The real R shortcut is handled by eventFilter so typing in an input box
        # still works normally. The tab keeps the shortcut visible in the menu.
        self.simulation_random_action = QAction("开启随机换股\tR", self)
        self.simulation_training_horizon_menu = QMenu("随机训练时长", self)
        self.training_category_menu = QMenu("选股类型（随机换股范围）", self)
        self.training_category_actions: dict[str, QAction] = {}
        self.training_category_boxes: dict[str, QCheckBox] = {}
        for key, label in BOARD_CATEGORY_LABELS:
            # 用复选框做菜单项：点一下不会关菜单，可以连续勾选/取消多个。
            box = QCheckBox(label, self.training_category_menu)
            box.setChecked(True)
            check_icon = (APP_ICON_PATH.parent / 'check.svg').as_posix()
            box.setStyleSheet(
                "QCheckBox { color: #d9e2ef; spacing: 4px; padding: 3px 6px; }"
                "QCheckBox::indicator { width: 12px; height: 12px; border: 1px solid #3b4249;"
                " border-radius: 3px; background: #181c20; }"
                "QCheckBox::indicator:hover { border-color: #6b8799; }"
                f"QCheckBox::indicator:checked {{ background: #33475a; border-color: #6b8799;"
                f" image: url({check_icon}); }}"
            )
            box.toggled.connect(
                lambda checked, category=key: self._set_training_category(category, checked)
            )
            action = QWidgetAction(self.training_category_menu)
            action.setDefaultWidget(box)
            self.training_category_menu.addAction(action)
            self.training_category_actions[key] = action
            self.training_category_boxes[key] = box
        self.simulation_training_horizon_group = QActionGroup(self)
        self.simulation_training_horizon_group.setExclusive(True)
        self.simulation_training_horizon_actions: dict[str, QAction] = {}
        for key, label, bars in RANDOM_TRAINING_HORIZONS:
            action = QAction(f"{label}（至少 {bars} 个交易日）", self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, horizon=key: checked and self._set_random_training_horizon(horizon)
            )
            self.simulation_training_horizon_group.addAction(action)
            self.simulation_training_horizon_menu.addAction(action)
            self.simulation_training_horizon_actions[key] = action
        self.simulation_advance_action = QAction("行情推进（次日开盘）\t↓", self)
        self.simulation_test_trade_action = QAction("测试交易模式", self)
        self.simulation_test_trade_action.setEnabled(False)
        self.simulation_return_action = QAction("回到正在交易", self)
        self.simulation_clear_action = QAction("一键重置训练状态…", self)
        self.simulation_choose_dir_action.triggered.connect(lambda _checked=False: self._dispatch_menu('choose_tdx_dir'))
        self.simulation_sample_action.triggered.connect(lambda _checked=False: self._dispatch_menu('load_sample_kline'))
        self.simulation_start_action.triggered.connect(lambda _checked=False: self._dispatch_menu('start_simulation'))
        self.simulation_random_action.triggered.connect(lambda _checked=False: self._dispatch_menu('random_switch_stock'))
        self.simulation_advance_action.triggered.connect(lambda _checked=False: self._dispatch_menu('advance_playback'))
        self.simulation_test_trade_action.triggered.connect(
            lambda _checked=False: self._dispatch_menu('exit_test_trade_mode')
        )
        self.simulation_return_action.triggered.connect(lambda _checked=False: self._dispatch_menu('_return_to_trading'))
        self.simulation_clear_action.triggered.connect(lambda _checked=False: self._dispatch_menu('_reset_training_state'))
        self.simulation_menu.addAction(self.simulation_choose_dir_action)
        self.simulation_menu.addAction(self.simulation_bundled_action)
        self.simulation_menu.addAction(self.simulation_sample_action)
        self.simulation_menu.addSeparator()
        self.simulation_menu.addAction(self.simulation_start_action)
        self.simulation_menu.addAction(self.simulation_random_action)
        self.simulation_menu.addMenu(self.simulation_training_horizon_menu)
        self.simulation_menu.addMenu(self.training_category_menu)
        self.simulation_menu.addAction(self.simulation_advance_action)
        self.simulation_menu.addAction(self.simulation_test_trade_action)
        self.simulation_menu.addSeparator()
        self.simulation_menu.addAction(self.simulation_return_action)
        self.simulation_menu.addAction(self.simulation_clear_action)

    def _build_training_mode_menu(self) -> None:
        self.training_mode_menu = self.menuBar().addMenu("训练模式")
        self.training_mode_menu.setToolTipsVisible(True)
        self.training_mode_group = QActionGroup(self)
        self.training_mode_group.setExclusive(True)
        self.training_mode_actions: dict[str, QAction] = {}
        for mode in (TRAINING_MODE_SINGLE, TRAINING_MODE_INDEPENDENT, TRAINING_MODE_CONTINUOUS):
            action = QAction(TRAINING_MODE_LABELS[mode], self)
            action.setCheckable(True)
            action.setToolTip(TRAINING_MODE_DESCRIPTIONS[mode])
            action.setStatusTip(TRAINING_MODE_DESCRIPTIONS[mode])
            action.triggered.connect(
                lambda checked=False, selected_mode=mode: checked and self._dispatch_menu('_set_training_mode', selected_mode)
            )
            self.training_mode_group.addAction(action)
            self.training_mode_menu.addAction(action)
            self.training_mode_actions[mode] = action
        # Compatibility for older integrations that looked up this action.
        self.simulation_continuous_action = self.training_mode_actions[TRAINING_MODE_CONTINUOUS]

    def _build_trade_menu(self) -> None:
        self.trade_menu = self.menuBar().addMenu("交易")
        self.trade_buy_action = QAction("开盘买入\tB", self)
        self.trade_sell_action = QAction("开盘卖出\tS", self)
        self.trade_buy_action.triggered.connect(lambda _checked=False: self._dispatch_menu('buy_at', self.current_node))
        self.trade_sell_action.triggered.connect(lambda _checked=False: self._dispatch_menu('sell_at', self.current_node))
        self.trade_menu.addAction(self.trade_buy_action)
        self.trade_menu.addAction(self.trade_sell_action)

    def _build_view_menu(self) -> None:
        self.view_menu = self.menuBar().addMenu("视图")
        self.view_menu.setToolTipsVisible(True)
        self.view_fullscreen_action = QAction("全屏模式\tCtrl+F/Tab", self)
        self.view_fullscreen_action.setCheckable(True)
        self.view_fullscreen_action.setToolTip("Ctrl+F 或 Tab 切换全屏模式，Esc 退出全屏模式。")
        self.view_identity_action = QAction("显示股票身份", self)
        self.view_identity_action.setCheckable(True)
        self.view_return_index_action = QAction("回到上证指数\t03 / SZZS", self)
        self.view_return_index_action.setToolTip(
            "点击直接打开上证指数；也可在界面直接输入 03 或 SZZS 后按回车。"
        )
        self.view_index_preview_action = QAction("临时查看上证指数\t长按空格", self)
        self.view_index_preview_action.setToolTip(
            "在股票K线界面长按空格临时查看同一天的上证指数，松开后返回当前股票。"
        )
        self.view_index_overlay_action = QAction("上证指数叠加\t双击空格", self)
        self.view_index_overlay_action.setCheckable(True)
        self.view_performance_handle_action = QAction("显示左侧交易统计按钮", self)
        self.view_performance_handle_action.setCheckable(True)
        self.view_previous_day_action = QAction("查看前一天K线\t←", self)
        self.view_next_day_action = QAction("查看后一天K线\t→", self)
        self.view_latest_action = QAction("回到最新K线\tHome / Ctrl+→", self)
        self.view_earliest_action = QAction("跳到最早K线\tEnd / Ctrl+←", self)
        self.view_zoom_in_action = QAction("放大K线\tCtrl+↑", self)
        self.view_zoom_out_action = QAction("缩小K线\tCtrl+↓", self)
        self.view_zoom_reset_action = QAction("恢复默认缩放", self)
        self.view_fullscreen_action.triggered.connect(self._set_immersive_fullscreen)
        self.view_identity_action.triggered.connect(lambda checked: self._dispatch_menu('_set_identity_from_menu', checked))
        self.view_return_index_action.triggered.connect(
            lambda _checked=False: self._dispatch_menu('_browse_shanghai_index_from_menu')
        )
        self.view_index_preview_action.triggered.connect(
            lambda _checked=False: self._update_status(
                "请在股票K线界面长按空格临时查看上证指数，松开空格返回当前股票。"
            )
        )
        self.view_index_overlay_action.triggered.connect(lambda checked: self._dispatch_menu('_set_index_overlay_from_menu', checked))
        self.view_performance_handle_action.triggered.connect(self._set_performance_handle_visible)
        self.view_previous_day_action.triggered.connect(lambda _checked=False: self._dispatch_menu('pan_left', 1))
        self.view_next_day_action.triggered.connect(lambda _checked=False: self._dispatch_menu('pan_right', 1))
        self.view_latest_action.triggered.connect(lambda _checked=False: self._dispatch_menu('pan_to_latest'))
        self.view_earliest_action.triggered.connect(lambda _checked=False: self._dispatch_menu('pan_to_earliest'))
        self.view_zoom_in_action.triggered.connect(lambda _checked=False: self._dispatch_menu('zoom_in'))
        self.view_zoom_out_action.triggered.connect(lambda _checked=False: self._dispatch_menu('zoom_out'))
        self.view_zoom_reset_action.triggered.connect(lambda _checked=False: self._dispatch_menu('zoom_reset'))
        self.view_menu.addAction(self.view_fullscreen_action)
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.view_identity_action)
        self.view_menu.addAction(self.view_performance_handle_action)
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.view_return_index_action)
        self.view_menu.addAction(self.view_index_preview_action)
        self.view_menu.addAction(self.view_index_overlay_action)
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.view_previous_day_action)
        self.view_menu.addAction(self.view_next_day_action)
        self.view_menu.addAction(self.view_latest_action)
        self.view_menu.addAction(self.view_earliest_action)
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.view_zoom_in_action)
        self.view_menu.addAction(self.view_zoom_out_action)
        self.view_menu.addAction(self.view_zoom_reset_action)

    def _change_subpane_count(self, delta: int) -> None:
        self._set_subpane_count(len(self.kline_widget.sub_pane_indicators) + delta)

    def _set_subpane_count(self, pane_count: int) -> None:
        previous = len(self.kline_widget.sub_pane_indicators)
        self.kline_widget.set_sub_pane_count(pane_count)
        current = len(self.kline_widget.sub_pane_indicators)
        if current != previous:
            self._update_status(f"副图数量已调整为 {current} 个；拖动横向分隔线可调整主副图高度。")

    def _set_subpane_indicator_from_menu(self, pane_index: int, indicator: str) -> None:
        if not 0 <= pane_index < len(self.kline_widget.sub_pane_indicators):
            return
        self.kline_widget.set_sub_pane_indicator(pane_index, indicator)
        label = {"volume": "成交量", "kdj": "KDJ", "macd": "MACD"}[indicator]
        self._update_status(f"副图 {pane_index + 1} 已切换为 {label}。")

    def _build_drawing_menu(self) -> None:
        self.drawing_menu = self.menuBar().addMenu("画线")
        self.drawing_add_line_action = QAction("添加辅助线", self)
        self.drawing_add_rectangle_action = QAction("添加矩形标注", self)
        self.drawing_select_all_action = QAction("全选画线与标注\tCtrl+A", self)
        self.drawing_copy_action = QAction("复制选中图形\tCtrl+C", self)
        self.drawing_paste_action = QAction("粘贴图形\tCtrl+V", self)
        self.drawing_delete_action = QAction("删除选中图形\tDelete", self)
        self.drawing_clear_action = QAction("清除全部画线与标注…", self)
        self.drawing_add_line_action.triggered.connect(lambda _checked=False: self._dispatch_menu('_add_drawing_line'))
        self.drawing_add_rectangle_action.triggered.connect(
            lambda _checked=False: self._dispatch_menu('_add_drawing_rectangle')
        )
        self.drawing_select_all_action.triggered.connect(
            lambda _checked=False: self._dispatch_menu('_select_all_drawings')
        )
        self.drawing_copy_action.triggered.connect(lambda _checked=False: self._dispatch_menu('_copy_drawings'))
        self.drawing_paste_action.triggered.connect(lambda _checked=False: self._dispatch_menu('_paste_drawings'))
        self.drawing_delete_action.triggered.connect(lambda _checked=False: self._dispatch_menu('_delete_drawings'))
        self.drawing_clear_action.triggered.connect(lambda _checked=False: self._dispatch_menu('_clear_all_drawings'))
        self.drawing_menu.addAction(self.drawing_add_line_action)
        self.drawing_menu.addAction(self.drawing_add_rectangle_action)
        self.drawing_menu.addSeparator()
        self.drawing_menu.addAction(self.drawing_select_all_action)
        self.drawing_menu.addAction(self.drawing_copy_action)
        self.drawing_menu.addAction(self.drawing_paste_action)
        self.drawing_menu.addAction(self.drawing_delete_action)
        self.drawing_menu.addSeparator()
        self.drawing_menu.addAction(self.drawing_clear_action)

    def _build_help_menu(self) -> None:
        self.help_menu = self.menuBar().addMenu("帮助")
        self.shortcut_help_action = QAction("快捷键一览", self)
        self.training_modes_help_action = QAction("三种训练模式说明", self)
        self.test_trade_help_action = QAction("测试交易模式说明", self)
        self.trade_help_action = QAction("交易与仓位操作", self)
        self.performance_help_action = QAction("交易统计与CSV", self)
        self.chart_help_action = QAction("K线、复权与画图", self)
        self.continuous_help_action = self.training_modes_help_action
        self.about_action = QAction("关于与风险提示", self)
        self.shortcut_help_action.triggered.connect(lambda _checked=False: self._show_shortcut_help())
        self.training_modes_help_action.triggered.connect(lambda _checked=False: self._show_training_modes_help())
        self.test_trade_help_action.triggered.connect(lambda _checked=False: self._show_test_trade_help())
        self.trade_help_action.triggered.connect(lambda _checked=False: self._show_trade_help())
        self.performance_help_action.triggered.connect(
            lambda _checked=False: self._show_performance_help()
        )
        self.chart_help_action.triggered.connect(lambda _checked=False: self._show_chart_help())
        self.about_action.triggered.connect(lambda _checked=False: self._show_about_help())
        self.sector_help_action = QAction("板块选股：行业、概念与风格", self)
        self.sector_help_action.triggered.connect(self._show_sector_help)
        self.help_menu.addAction(self.sector_help_action)
        self.help_menu.addAction(self.shortcut_help_action)
        self.help_menu.addAction(self.training_modes_help_action)
        self.help_menu.addAction(self.test_trade_help_action)
        self.help_menu.addAction(self.trade_help_action)
        self.help_menu.addAction(self.performance_help_action)
        self.help_menu.addAction(self.chart_help_action)
        self.help_menu.addSeparator()
        self.help_menu.addAction(self.about_action)

    def _show_sector_help(self) -> None:
        QMessageBox.information(self, "板块选股使用说明",
            "【分类与定位】默认打开概念板块；一级行业、二级行业、概念、风格在同一排切换。\n"
            "选中个股后切换分类，会自动查找该股对应板块；没有对应归属时显示全部。从个股训练返回也会跟随当前股票。\n\n"
            "【搜索与排序】支持中文名称、股票/板块代码、首字母和常见多音字。搜个股可显示其所属板块；点击各列表表头切换升降序。\n"
            "涨幅列包括当日、5日、10日、20日。开盘按开盘价计算，成交额收盘后显示；缺数据以横线及状态说明表示。\n\n"
            "【今日名单】风格分类里额外提供程序自行统计的“今日涨停 / 今日连板 / 今日跌停”，按本地最新交易日计算；成分股名称后的上角标数字表示连板数。另外还有“近半月腰斩 / 近一月腰斩 / 近三月腰斩”，按区间最高收盘价到最新收盘价的跌幅计算，跌 40%~60% 的个股列入（窗口约 15 / 25 / 70 个交易日）。这些清单没有指数日线，只有成分股列表。板块表和成分股表选中一行后，可以直接按回车键向下切换。\n\n"
            "【收藏与缩放】点击板块表或成分股表最左边的“序号”即可收藏，序号变成金色角标，再点一次取消；收藏的板块或个股始终排在列表最前面，并随“保存当前配置”一起写入配置，退出重开仍保留。切换板块或个股时 K 线缩放保持不变，只把显示位置回到最新。\n\n"
            "【回到顶部】双击“一级行业 / 二级行业 / 概念 / 风格”任一标签，会把板块列表强制拉回顶部；点击表头排序后也会自动回到顶部，方便直接看到排在最前面的结果。\n\n"
            "【日期与图表】R按钮随机定位交易日；白色眼睛显示/隐藏日期，与个股训练联动，隐藏日期输入、历史范围、时间轴及日期提示。输入日期或随机定位后，板块、个股和排名共同截止所选日期，不改变原训练账户；点击最近回到本地最新行情。\n日期框输入2018、201802或20180603后回车，定位对应日期起首个交易日。Ctrl+左/End到最早，Ctrl+右/Home到最近。\n"
            "方向键平移，Ctrl+滚轮缩放，右键菜单增减副图。选中个股后，在图表或列表快速双击空格，开关当前所属板块指数的灰色叠加；切换行业、概念或风格后，叠加指数跟随当前选中的板块，并随查看日期移动。\n"
            "个股图使用前复权（资料未就绪时有提示），板块指数与列表涨幅使用原始价格。\n\n"
            "【训练与数据】单击个股预览，双击个股或点击进入个股训练。正式训练只显示已揭示日期，开盘不提前显示收盘信息。\n"
            "通达信名单是当前成分股归属，不是历史名单；概念与风格的指数日线不一定覆盖十年。日K不足时不补造数据。")

    def _show_shortcut_help(self) -> None:
        QMessageBox.information(
            self,
            "快捷键一览",
            "Ctrl+Q：退出软件（退出前自动保存配置和可续作进度）\n"
            "↓：推进行情（收盘 / 下一日开盘）\n"
            "← / →：查看前一天 / 后一天K线\n"
            "B / S：买入 / 卖出\n"
            "R：开启随机换股（输入框内仍可正常输入 R）\n"
            "03 / SZZS：回到上证指数\n"
            "P 或 Ctrl+S：保存交易快照\n"
            "Ctrl+F 或 Tab：切换全屏模式；Esc：退出全屏模式\n"
            "长按空格：临时查看同日上证指数\n"
            "快速双击空格：开关上证指数叠加（板块页选中个股后叠加当前板块指数）\n"
            "Home 或 Ctrl+→：回到最新K线\n"
            "End 或 Ctrl+←：跳到最早K线\n"
            "Ctrl+↑ / Ctrl+↓：放大 / 缩小K线\n"
            "直接输入代码、拼音首字母或日期后回车：打开或定位\n"
            "Ctrl+鼠标滚轮：缩放；右键拖动：平移\n"
            "Ctrl+A：全选画线与标注\n"
            "Ctrl+C / Ctrl+V / Delete：复制、粘贴或删除图形。",
        )

    def _show_test_trade_help(self) -> None:
        QMessageBox.information(
            self,
            "测试交易模式说明",
            "1. 先输入股票代码或拼音首字母，进入个股行情浏览模式。\n"
            "2. 在想作为起点的K线实体上快速连续右击，即可进入测试模式。\n"
            "3. 测试从该K线开盘开始，未来K线保持可见，可正常推进、买入和卖出。\n"
            "4. 交易仍遵守整手、T+1、手续费和印花税规则。\n"
            "5. 可从“模拟”菜单退出；右击已完成交易的盈亏金额条并选择“清空全部”，可重新选择起点。\n"
            "6. 测试账户和交易记录不会保存，也不会影响正式训练。",
        )

    def _show_trade_help(self) -> None:
        QMessageBox.information(
            self,
            "交易与仓位操作",
            "开始：载入行情后点黄色“开启随机换股”；也可按 R。训练会自动隐藏未来行情。\n"
            "推进：按 ↓ 在“当日收盘”和“下一交易日开盘”之间逐步推进。\n"
            "买卖：按 B/S 或点右侧按钮；菜单和按钮会随开盘/尾盘自动切换。\n"
            "仓位：可点 1/4、1/3、1/2 或满仓；也可直接修改金额、数量。\n"
            "规则：买入数量按整手处理；当日买入遵守 T+1，下一交易日才可卖。\n"
            "查看：点击K线看当日数据，右键拖动看历史，Home 回到最新位置。\n"
            "统计：首笔买入后，主图左侧出现“统计”；展开后点主图即可收起。\n"
            "模式：默认连续复利；独立训练每只股票使用相同初始本金；单吊模式只记录当前股票。"
            "切换训练模式前必须先清仓。\n"
            "复盘：独立训练和连续复利记录可双击查看，再点“回到正在交易”。\n\n"
            "输入股票、日期、金额或数量时，字母快捷键不会误触。",
        )

    def _show_performance_help(self) -> None:
        QMessageBox.information(
            self,
            "交易统计与CSV",
            "首笔买入成功后，主图最左侧会出现“统计”按钮；点击后从左侧展开双列概览。\n"
            "概览只显示名称和数值，不显示成交明细，也不需要滚动。点击浮窗内部可查看，"
            "点击主图区域会自动收起且不影响原来的看图、选中和画线操作。\n\n"
            "单吊模式：只统计当前这只股票从首笔买入到当前的区间。\n"
            "独立训练：每只股票使用相同初始本金，分别保存后汇总统计，练习日期可以重叠。\n"
            "连续复利：合并统计从第一只股票到当前股票的整个连续账户区间，"
            "包含同期上证收益率和超额收益率。\n"
            "未清仓的当前持仓会按当前价格计入资产、收益和回撤；只有完整清仓段才计入胜率、"
            "盈亏比等已完成交易指标。\n\n"
            "需要查看资金与回撤图表、每只股票、每个完整分段和每笔成交时，请点浮窗中的“导出Excel图表”，"
            "或使用“文件 → 导出交易统计Excel（含图表）到桌面”。原始CSV导出仍保留在文件菜单中；导出不会覆盖同名文件。\n"
            "若不需要左侧按钮，可在“视图 → 显示左侧交易统计按钮”中关闭。",
        )

    def _show_training_modes_help(self) -> None:
        QMessageBox.information(
            self,
            "三种训练模式说明",
            "软件首次启动默认使用连续复利模式，也可从顶部“训练模式”菜单切换。"
            "所选模式会保存为下次启动时的模式；"
            "每次成功切换后，账户都会回到设置的初始本金。当前有持仓时需先清仓。\n\n"
            "一、单吊模式\n"
            "只练习和统计当前一只股票。换股后重新使用设置的初始本金，不累计上一只股票的记录。\n\n"
            "二、独立训练模式\n"
            "每只股票都使用设置好的相同初始本金，资金互不延续，但会保存每只练习过的股票并做区间汇总。"
            "各只股票的时间互不约束：例如 9 日买入股票 A 后，可以在符合条件的任意日期开始股票 B，"
            "不必等待 A 在 10 日卖出。换股时会随机选择新股票和训练时间，不提供当前股票重新选时间的入口；"
            "双击记录可复盘。\n\n"
            "三、连续复利模式\n"
            "所有股票共用一个连续账户，上一只股票的期末资金延续给下一只。换股前必须清仓，时间也只能向后。"
            "例如 9 日买入 A、10 日卖出 A，股票 B 只能从 10 日或之后继续，不能回到更早日期。\n\n"
            "独立训练和连续复利都保留多股票记录；区别是独立训练只汇总练习结果，"
            "连续复利还会延续资金和交易时间。鼠标停留在顶部模式名称或右侧模式状态上，"
            "也可查看对应模式的简要说明。",
        )

    def _show_continuous_help(self) -> None:
        """Compatibility entry point for older callers."""
        self._show_training_modes_help()

    def _show_chart_help(self) -> None:
        QMessageBox.information(
            self,
            "K线、复权与画图",
            "点击主图 MA/BOLL/GMA 标签：切换主图指标或均线显示；再次点击已启用的 BOLL/GMA 可关闭。\n"
            "在任意副图区域点右键可增加或减少副图，最少 1 个、最多 4 个。\n"
            "拖动主图和副图之间的横向分隔线可调整高度。\n"
            "点击副图指标名也可切换指标；KDJ、MACD 右侧齿轮可修改参数。\n"
            "点击K线：查看日期、涨跌额和涨跌幅；点击空白处关闭提示。\n"
            "← / →：逐日查看前一天或后一天K线；右键拖动：左右平移；Ctrl+鼠标滚轮：缩放。\n"
            "长按空格：临时查看同日上证指数，松开后返回股票；双击空格：开关指数叠加。\n\n"
            "复权方式\n"
            "不复权：直接显示历史真实成交价，除权除息日会保留价格缺口，便于核对当时实际价格，"
            "但长周期走势容易被分红送转造成的跳空干扰。\n"
            "前复权：以当前价格为基准向前调整历史价格，消除除权缺口，近期价格接近真实行情，"
            "适合观察连续走势、均线和技术形态。\n"
            "后复权：以早期价格为基准向后调整后续价格，早期价格接近真实行情，"
            "适合观察长期累计涨幅；后期显示价可能明显不同于当时真实成交价。\n"
            "训练器会按所选复权K线进行显示和模拟。交易已经开始后不会中途替换当前股票价格，"
            "所选方式会在后续新打开或换股时生效；指数不参与复权。\n\n"
            "“画线”菜单可直接添加辅助线或矩形；添加后图形会自动选中。\n"
            "辅助线：拖线身可移动，拖两端可改角度；接近15度倍数时自动吸附。\n"
            "矩形：拖边框可移动，拖四角可缩放；悬停边框后拖旋转手柄可旋转。\n"
            "鼠标快速添加：双击空白新增辅助线；左键拖出虚线框，再按右键建立矩形。\n"
            "选择：点击选中，Ctrl+点击多选；在空白处左键框选可选择多个图形。\n"
            "编辑：Ctrl/Alt 拖动可复制；Ctrl+A/C/V、Delete 可全选、复制、粘贴、删除。\n"
            "清理：可双击单个图形删除，或用“画线→清除全部画线与标注”。\n"
            "说明：画线只显示在个股主图；临时查看指数时会隐藏，全新模拟时会清空。\n"
            "长按鼠标中键：开关银河背景；按住中键滑动：产生流星。",
        )

    def _add_drawing_line(self) -> None:
        if self.kline_widget.add_user_line_at_center():
            self._update_status("已添加辅助线；拖动线身移动，拖动端点调整角度。")
        else:
            self._update_status("请先载入个股K线，再添加辅助线。")
        self._sync_menu_actions()

    def _add_drawing_rectangle(self) -> None:
        if self.kline_widget.add_user_rectangle_at_center():
            self._update_status("已添加矩形；拖边框移动，拖四角缩放，拖旋转手柄旋转。")
        else:
            self._update_status("请先载入个股K线，再添加矩形标注。")
        self._sync_menu_actions()

    def _select_all_drawings(self) -> None:
        count = self.kline_widget.select_all_user_annotations()
        self._update_status(f"已选中 {count} 个画线/标注。" if count else "当前没有可选择的画线或标注。")

    def _copy_drawings(self) -> None:
        count = self.kline_widget.copy_selected_user_annotations()
        self._update_status(f"已复制 {count} 个画线/标注。" if count else "请先点击或框选需要复制的图形。")

    def _paste_drawings(self) -> None:
        count = self.kline_widget.paste_user_annotations()
        self._update_status(f"已粘贴 {count} 个画线/标注。" if count else "当前没有已复制的图形。")

    def _delete_drawings(self) -> None:
        count = self.kline_widget.delete_selected_user_annotations()
        self._update_status(f"已删除 {count} 个画线/标注。" if count else "请先点击或框选需要删除的图形。")

    def _clear_all_drawings(self) -> None:
        count = self.kline_widget.user_annotation_count()
        if not count:
            self._update_status("当前没有可清除的画线或标注。")
            return
        answer = QMessageBox.question(
            self,
            "清除全部画线与标注",
            f"确定清除当前图表中的 {count} 个画线/标注吗？此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.kline_widget.clear_user_annotations()
        self._update_status(f"已清除 {count} 个画线/标注。")
        self._sync_menu_actions()

    def _show_about_help(self) -> None:
        QMessageBox.information(
            self,
            "关于与风险提示",
            f"{APP_NAME}\n\n"
            "本软件用于训练日K观察、分仓、T+1和交易节奏，不提供股票推荐、买卖建议、"
            "收益承诺或投资指导。模拟结果仅供学习参考，真实投资风险需自行承担。",
        )

    def _set_identity_from_menu(self, checked: bool) -> None:
        if self.engine and self.engine.current_bar.code == SHANGHAI_INDEX_CODE:
            self._sync_menu_actions()
            return
        self.identity_toggle.setChecked(checked)
        self.save_display_preferences()

    def _browse_shanghai_index_from_menu(self) -> None:
        self.code_input.setText("szzs")
        self.browse_stock_from_input()

    def _set_index_overlay_from_menu(self, checked: bool) -> None:
        if checked:
            self._enable_index_overlay()
        else:
            self._disable_index_overlay()
        self._sync_menu_actions()

    def _set_performance_handle_visible(self, checked: bool) -> None:
        self.settings.performance_handle_visible = bool(checked)
        self.performance_overlay.set_handle_enabled(bool(checked))
        self._save_settings()
        state = "显示" if checked else "隐藏"
        self._update_status(f"左侧交易统计按钮已{state}。")
        self._sync_menu_actions()

    def _set_immersive_fullscreen(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._immersive_fullscreen:
            self.view_fullscreen_action.setChecked(enabled)
            return
        if enabled:
            self._fullscreen_previous_window_state = self.windowState()
            self._dock_quick_actions_panel(True)
            self._fullscreen_hidden_visibility = [
                (self.menuBar(), self.menuBar().isVisible()),
                (self.simulation_settings_panel, self.simulation_settings_panel.isVisible()),
                (self.chart_header_panel, self.chart_header_panel.isVisible()),
                (self.top_bar_fields, self.top_bar_fields.isVisible()),
            ]
            for widget, _was_visible in self._fullscreen_hidden_visibility:
                widget.hide()
            self._immersive_fullscreen = True
            self.view_fullscreen_action.setChecked(True)
            self.showFullScreen()
            return

        self._immersive_fullscreen = False
        previous_state = self._fullscreen_previous_window_state
        if previous_state & Qt.WindowState.WindowMaximized:
            self.showMaximized()
        else:
            self.showNormal()
        for widget, was_visible in self._fullscreen_hidden_visibility:
            widget.setVisible(was_visible)
        self._fullscreen_hidden_visibility = []
        self._dock_quick_actions_panel(True)
        self.view_fullscreen_action.setChecked(False)

    def _dock_quick_actions_panel(self, docked: bool) -> None:
        """Move the same controls between the top bar and side column."""
        if not hasattr(self, "quick_actions_panel"):
            return
        docked = bool(docked)
        if bool(self.quick_actions_panel.property("sideDocked")) == docked:
            self._sync_quick_actions_panel_layout()
            return
        if docked:
            for widget in (self.dir_btn, self.sample_kline_btn, self.action_row_holder):
                self.top_bar_layout.removeWidget(widget)
            self.quick_actions_layout.addWidget(self.dir_btn, 0, 0)
            self.quick_actions_layout.addWidget(self.sample_kline_btn, 0, 1)
            self.quick_actions_layout.addWidget(self.action_row_holder, 1, 0, 1, 2)
            self.quick_actions_panel.setParent(self.side_panel_scroll.widget())
            self.side_panel_layout.insertWidget(0, self.quick_actions_panel)
        else:
            self.side_panel_layout.removeWidget(self.quick_actions_panel)
            for widget in (self.dir_btn, self.sample_kline_btn, self.action_row_holder):
                self.quick_actions_layout.removeWidget(widget)
            self.quick_actions_panel.setParent(self.simulation_settings_panel)
            self.top_bar_layout.addWidget(self.dir_btn, 0, 4)
            self.top_bar_layout.addWidget(self.sample_kline_btn, 0, 5)
            self.top_bar_layout.addWidget(self.action_row_holder, 1, 4, 1, 2)
            self.quick_actions_panel.hide()
        self.quick_actions_panel.setProperty("sideDocked", docked)
        self._sync_quick_actions_panel_layout()
        self.quick_actions_panel.setVisible(docked)

    def _sync_quick_actions_panel_layout(self) -> None:
        if not hasattr(self, "quick_actions_panel"):
            return
        docked = bool(self.quick_actions_panel.property("sideDocked"))
        density = self._layout_density
        compact = density != "normal"
        low_resolution = density == "low"

        def density_value(normal_value, compact_value, low_value):
            if low_resolution:
                return low_value
            if compact:
                return compact_value
            return normal_value

        if docked:
            margin = density_value(8, 7, 6)
            self.quick_actions_layout.setContentsMargins(margin, margin, margin, margin)
            self.quick_actions_layout.setHorizontalSpacing(density_value(8, 7, 6))
            self.quick_actions_layout.setVerticalSpacing(density_value(13, 11, 9))
            for button in (self.dir_btn, self.sample_kline_btn):
                self._set_control_height(button, density_value(32, 28, 24))
                button.setMaximumWidth(16_777_215)
                button.setMinimumWidth(0)
            for button in (self.random_btn, self.start_btn):
                self._set_control_height(button, density_value(38, 32, 28))
                button.setMaximumWidth(16_777_215)
                button.setMinimumWidth(0)
            self.start_btn.setObjectName("DockedStartButton")
            self.random_btn.setObjectName("DockedRandomButton")
            self.quick_actions_panel.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
        else:
            self.quick_actions_layout.setContentsMargins(0, 0, 0, 0)
            self.quick_actions_layout.setHorizontalSpacing(density_value(6, 4, 3))
            self.quick_actions_layout.setVerticalSpacing(density_value(4, 2, 1))
            for button in (self.dir_btn, self.sample_kline_btn, self.random_btn, self.start_btn):
                self._set_control_height(button, density_value(None, 24, 22))
            self.start_btn.setObjectName("StartButton")
            self.random_btn.setObjectName("RandomButton")
            self.start_btn.setMinimumWidth(0)
            self.random_btn.setMinimumWidth(0)
            self.quick_actions_panel.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Preferred,
            )
        _repolish_widget(self.quick_actions_panel)
        _repolish_widget(self.start_btn)
        _repolish_widget(self.random_btn)
        if not docked:
            QTimer.singleShot(0, self._align_top_actions_with_side_panel)

    def _align_top_actions_with_side_panel(self, *_args) -> None:
        """Align both top action rows to the unchanged playback button bounds."""
        if (
            not hasattr(self, "side_panel_scroll")
            or not hasattr(self, "quick_actions_panel")
            or not hasattr(self, "advance_phase_btn")
            or bool(self.quick_actions_panel.property("sideDocked"))
            or not self.simulation_settings_panel.isVisible()
        ):
            return
        playback_visible = self.playback_nav_box.isVisible()
        playback_width = self.advance_phase_btn.width()
        if playback_visible and 180 <= playback_width <= self.side_panel_scroll.width():
            target_origin = self.advance_phase_btn.mapToGlobal(QPoint(0, 0))
            total_width = playback_width
        else:
            target_origin = self.side_panel_scroll.mapToGlobal(QPoint(0, 0))
            total_width = self.side_panel_scroll.width()
        playback_left = self.simulation_settings_panel.mapFromGlobal(target_origin).x()
        playback_right = playback_left + total_width
        margins = self.top_bar_layout.contentsMargins()
        right_margin = max(0, self.simulation_settings_panel.width() - playback_right)
        if margins.right() != right_margin:
            self.top_bar_layout.setContentsMargins(
                margins.left(), margins.top(), right_margin, margins.bottom()
            )
        spacing = self.top_bar_layout.horizontalSpacing()
        upper_width = max(0, total_width - spacing)
        base_width, remainder = divmod(upper_width, 2)
        widths = [base_width + (1 if index < remainder else 0) for index in range(2)]
        for button, width in zip(
            (self.dir_btn, self.sample_kline_btn),
            widths,
        ):
            button.setFixedWidth(width)
        self.start_btn.setFixedWidth(total_width)
        self.random_btn.setFixedWidth(total_width)

    def _main_splitter_moved(self, *_args) -> None:
        self._align_top_actions_with_side_panel()
        QTimer.singleShot(0, self._align_top_actions_with_side_panel)

    def _sync_menu_actions(self) -> None:
        if not hasattr(self, "file_menu"):
            return
        self._sync_training_category_actions()
        has_engine = self.engine is not None
        training = bool(has_engine and self.training_mode)
        is_index = bool(has_engine and self.engine.current_bar.code == SHANGHAI_INDEX_CODE)
        self.file_snapshot_action.setEnabled(training)
        self.file_export_performance_action.setEnabled(training and self.trade_started)
        self.simulation_sample_action.setEnabled(self.sample_kline_btn.isEnabled())
        self.simulation_start_action.setText(self.start_btn.text())
        self.simulation_start_action.setEnabled(self.start_btn.isEnabled())
        self.simulation_start_action.setVisible(is_index)
        self.simulation_random_action.setEnabled(self.random_btn.isEnabled())
        self.simulation_random_action.setVisible(not is_index)
        self.simulation_advance_action.setText(f"{self.advance_phase_btn.text()}\t↓")
        self.simulation_advance_action.setEnabled(self.advance_phase_btn.isEnabled())
        test_menu_text, test_menu_enabled = menu_presentation(self.test_trade_active)
        self.simulation_test_trade_action.setText(test_menu_text)
        self.simulation_test_trade_action.setEnabled(test_menu_enabled)
        self.advance_phase_btn.set_mode_badge(
            TRAINING_MODE_BADGES.get(
                self.training_mode_kind,
                TRAINING_MODE_BADGES[TRAINING_MODE_CONTINUOUS],
            ),
            test_mode_active=self.test_trade_active,
        )
        has_return_context = self._return_to_trading_context is not None
        self.simulation_return_action.setEnabled(has_return_context)
        for mode, action in self.training_mode_actions.items():
            action.setChecked(mode == self.training_mode_kind)
            action.setEnabled(not self.test_trade_active)
        self.simulation_clear_action.setVisible(self._uses_round_records())
        self.simulation_clear_action.setEnabled(
            self._uses_round_records() and training and not self.test_trade_active
        )
        for key, action in self.simulation_training_horizon_actions.items():
            action.setChecked(key == self.settings.random_training_horizon)
        self.trade_buy_action.setText(f"{self.trade_buy_btn.text()}\tB")
        self.trade_buy_action.setEnabled(self.trade_buy_btn.isEnabled())
        self.trade_sell_action.setText(f"{self.trade_sell_btn.text()}\tS")
        self.trade_sell_action.setEnabled(self.trade_sell_btn.isEnabled())
        self.view_identity_action.setChecked(self.identity_toggle.isChecked())
        self.view_identity_action.setEnabled(not is_index)
        self.view_index_preview_action.setEnabled(self._can_use_index_shortcut())
        self.view_index_overlay_action.setChecked(self.index_overlay_active)
        self.view_index_overlay_action.setEnabled(self._can_use_index_shortcut())
        self.view_performance_handle_action.setChecked(self.settings.performance_handle_visible)
        self.view_fullscreen_action.setChecked(self._immersive_fullscreen)
        for action in (
            self.view_latest_action,
            self.view_earliest_action,
            self.view_previous_day_action,
            self.view_next_day_action,
            self.view_zoom_in_action,
            self.view_zoom_out_action,
            self.view_zoom_reset_action,
        ):
            action.setEnabled(has_engine)
        drawings_available = has_engine and not self.kline_widget.suppress_user_annotations
        for action in (
            self.drawing_add_line_action,
            self.drawing_add_rectangle_action,
            self.drawing_select_all_action,
            self.drawing_copy_action,
            self.drawing_paste_action,
            self.drawing_delete_action,
            self.drawing_clear_action,
        ):
            action.setEnabled(drawings_available)

        integration = getattr(self, 'sector_integration', None)
        if integration:
            integration.sync_menu_actions()

    def _build_top_bar(self) -> QWidget:
        box = QFrame()
        box.setObjectName("SimulationSettingsPanel")
        self.simulation_settings_panel = box
        layout = QGridLayout(box)
        layout.setContentsMargins(8, 1, 8, 1)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(2)
        self.top_bar_layout = layout
        self.tdx_path = QLineEdit(self.settings.tdx_root)
        self.tdx_path.setReadOnly(True)
        self.tdx_path.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tdx_path.setAcceptDrops(False)
        self.tdx_path.setProperty("locked", True)
        self.tdx_path.setToolTip(
            "通达信目录只能通过右侧“选择目录”按钮修改。\n"
            "选择后请在通达信“选项”菜单中找到“K线盘后数据下载”，"
            "下载尽可能多年份的沪深京日K数据。"
        )
        # 提示文字要能完整显示，这里用短提示；完整说明放在上面的悬停提示里。
        self.tdx_path.setPlaceholderText("请选择通达信目录，例如 D:\\TDX")
        self.code_input = QLineEdit()
        self.code_input.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.code_input.setPlaceholderText("输入代码或首字母后回车查看，例如 YMSP、szzs、03")
        self.code_input.returnPressed.connect(self._browse_or_accept_stock_candidate)
        self.code_input.textChanged.connect(self._update_stock_candidates)
        self.stock_candidate_list = QListWidget(self)
        self.stock_candidate_list.setObjectName("StockCandidateList")
        self.stock_candidate_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stock_candidate_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stock_candidate_list.itemClicked.connect(self._accept_stock_candidate)
        self.stock_candidate_list.hide()
        self.date_input = QLineEdit()
        self.date_input.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.date_input.setPlaceholderText("留空随机；支持 2018、201612、20180506")
        self.date_input.returnPressed.connect(self._navigate_from_date_input)
        self.start_date_label = QLabel("开始日期")
        self.start_date_label.setObjectName("StartDateLabel")
        self.start_btn = QPushButton("开启模拟交易")
        self.start_btn.setObjectName("StartButton")
        self.start_btn.clicked.connect(self.start_simulation)
        self.start_btn.hide()
        self.random_btn = QPushButton("开启随机换股")
        self.random_btn.setObjectName("RandomButton")
        self.random_btn.clicked.connect(self.random_switch_stock)
        self.dir_btn = QPushButton("选择目录")
        self.dir_btn.clicked.connect(self.choose_tdx_dir)
        self.sample_kline_btn = QPushButton("载入测试K线")
        self.sample_kline_btn.setObjectName("SampleKLineButton")
        self.sample_kline_btn.clicked.connect(self.load_sample_kline)
        # 第二行只有一个按钮位（“开启模拟交易”和“开启随机换股”二选一显示）。
        # 两个按钮放在同一网格单元时，Qt 会把这一行的行间距算没，导致第一行和
        # 第二行贴在一起；用一个容器承载它们，外层就只剩一个控件，间距恢复正常。
        self.action_row_holder = QWidget(box)
        self.action_row_holder.setObjectName("ActionRowHolder")
        self.action_row_holder.setStyleSheet(
            "QWidget#ActionRowHolder { background: transparent; }"
        )
        self.action_row_holder.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        action_row_layout = QGridLayout(self.action_row_holder)
        action_row_layout.setContentsMargins(0, 0, 0, 0)
        action_row_layout.setSpacing(0)
        action_row_layout.addWidget(self.random_btn, 0, 0)
        action_row_layout.addWidget(self.start_btn, 0, 0)
        self.quick_actions_panel = QWidget(box)
        self.quick_actions_panel.setObjectName("QuickActionsPanel")
        self.quick_actions_panel.setProperty("sideDocked", False)
        self.quick_actions_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        quick_layout = QGridLayout(self.quick_actions_panel)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setHorizontalSpacing(6)
        quick_layout.setVerticalSpacing(4)
        self.quick_actions_layout = quick_layout
        self.quick_actions_panel.hide()
        self.top_bar_controls = (
            self.tdx_path,
            self.code_input,
            self.date_input,
            self.start_btn,
            self.random_btn,
            self.dir_btn,
            self.sample_kline_btn,
        )

        fields = QWidget(box)
        fields.setObjectName("MarketInputRow")
        fields.setStyleSheet("QWidget#MarketInputRow, QWidget#MarketInputRow QLabel { background: transparent; }")
        # 个股页会把这一行并入标签栏，让“标签 + 三个输入”同处最上面一行。
        self.top_bar_fields = fields
        fields_layout = QHBoxLayout(fields)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(6)
        fields_layout.addWidget(QLabel("股票"))
        self.code_input.setFixedWidth(TOP_CODE_FIELD_WIDTH)
        fields_layout.addWidget(self.code_input)
        fields_layout.addWidget(self.start_date_label)
        self.date_input.setFixedWidth(TOP_CODE_FIELD_WIDTH)
        fields_layout.addWidget(self.date_input)
        fields_layout.addWidget(QLabel("通达信目录"))
        self.tdx_path.setFixedWidth(TOP_TDX_FIELD_WIDTH)
        fields_layout.addWidget(self.tdx_path)
        layout.addWidget(fields, 0, 0, 2, 4)
        layout.addWidget(self.dir_btn, 0, 4)
        layout.addWidget(self.sample_kline_btn, 0, 5)
        layout.addWidget(self.action_row_holder, 1, 4, 1, 2)
        self._sync_random_btn_tooltip()
        self._refresh_sample_kline_button_state()
        return box

    def _build_chart_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.chart_panel_layout = layout
        header_panel = QWidget(panel)
        header_layout = QVBoxLayout(header_panel)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_header_panel = header_panel
        self.chart_header_layout = header_layout
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self.chart_title_layout = title_row
        self.title_label = QLabel("未开始")
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        self.title_label.setMinimumWidth(0)
        self.identity_toggle = QPushButton("")
        self.identity_toggle.setObjectName("IdentityToggle")
        self.identity_toggle.setCheckable(True)
        self.identity_toggle.setChecked(self.settings.show_stock_identity)
        self.identity_toggle.setFlat(False)
        self.identity_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.identity_toggle.setAccessibleName("显示或隐藏股票信息")
        self.identity_toggle.setIconSize(QSize(20, 20))
        self.identity_toggle.setFixedSize(30, 28)
        self.identity_toggle.setStyleSheet(
            "QPushButton#IdentityToggle {"
            " background: #20252a; border: 1px solid #373e44;"
            " border-radius: 6px; padding: 0px;"
            "}"
            "QPushButton#IdentityToggle:hover { background: #2b3238; }"
            "QPushButton#IdentityToggle:pressed { background: #1b2024; }"
        )
        self._sync_identity_toggle_appearance()
        self.identity_toggle.clicked.connect(self.save_display_preferences)
        title_row.addWidget(self.title_label)
        title_row.addWidget(self.identity_toggle)
        title_row.addStretch(1)
        self.market_strip = QGridLayout()
        self.market_strip.setHorizontalSpacing(6)
        self.market_labels: dict[str, QLabel] = {}
        self.index_market_labels: dict[str, QLabel] = {}
        for index, name in enumerate(STOCK_MARKET_ITEMS):
            label = QLabel(f"{name}\n--")
            label.setObjectName("MetricLabel")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(0)
            label.setMinimumHeight(50)
            if name in {"持仓均价", "第一笔买入价", "最大振幅"}:
                label.setProperty("metricRole", "priceReference")
            self.market_labels[name] = label
            self.index_market_labels[INDEX_MARKET_ITEMS[index]] = label
            self.market_strip.addWidget(label, 0, index)
            self.market_strip.setColumnStretch(index, 1)
        self.kline_widget = KLineWidget(self)
        self.kline_widget.show_time_marks = self.settings.show_stock_identity
        self.kline_widget.hidden_ma_periods = set(self.settings.hidden_ma_periods)
        self.kline_widget.set_sub_pane_indicators(self.settings.sub_pane_indicators)
        self.kline_widget.set_pane_height_ratios(self.settings.pane_height_ratios)
        self.kline_widget.hidden_volume_ma_periods = set(self.settings.hidden_volume_ma_periods)
        self.kline_widget.set_macd_parameters(self.settings.macd_fast, self.settings.macd_slow, self.settings.macd_signal)
        self.kline_widget.set_kdj_parameters(self.settings.kdj_n, self.settings.kdj_k, self.settings.kdj_d)
        self.kline_widget.main_overlay_mode = self.settings.main_overlay_mode
        self.kline_widget.set_boll_parameters(self.settings.boll_n, self.settings.boll_k)
        pane_macd = self.settings.pane_macd_params
        if pane_macd[:MAX_SUB_PANE_COUNT] == [[12, 26, 9] for _ in range(MAX_SUB_PANE_COUNT)] and (self.settings.macd_fast, self.settings.macd_slow, self.settings.macd_signal) != (12, 26, 9):
            pane_macd = [[self.settings.macd_fast, self.settings.macd_slow, self.settings.macd_signal] for _ in range(MAX_SUB_PANE_COUNT)]
        for index, params in enumerate(pane_macd[:MAX_SUB_PANE_COUNT]):
            self.kline_widget.set_pane_macd_parameters(index, *params)
        pane_kdj = self.settings.pane_kdj_params
        if pane_kdj[:MAX_SUB_PANE_COUNT] == [[9, 3, 3] for _ in range(MAX_SUB_PANE_COUNT)] and (self.settings.kdj_n, self.settings.kdj_k, self.settings.kdj_d) != (9, 3, 3):
            pane_kdj = [[self.settings.kdj_n, self.settings.kdj_k, self.settings.kdj_d] for _ in range(MAX_SUB_PANE_COUNT)]
        for index, params in enumerate(pane_kdj[:MAX_SUB_PANE_COUNT]):
            self.kline_widget.set_pane_kdj_parameters(index, *params)
        self.performance_overlay = PerformanceOverlay(self.kline_widget)
        self.performance_overlay.export_requested.connect(self.export_performance_excel)
        self.performance_overlay.summary_refresh_requested.connect(
            self._refresh_performance_overlay_current
        )
        self.performance_overlay.set_handle_enabled(self.settings.performance_handle_visible)
        self.day_info = QLabel("--")
        self.day_info.setObjectName("DayInfo")
        header_layout.addLayout(title_row)
        header_layout.addLayout(self.market_strip)
        layout.addWidget(header_panel)
        layout.addWidget(self.kline_widget, 1)
        layout.addWidget(self.day_info)
        return panel

    def _build_side_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("SidePanelScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(520)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.side_panel_scroll = scroll

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.side_panel_layout = layout
        nav_box = QGroupBox()
        self.playback_nav_box = nav_box
        nav_layout = QGridLayout(nav_box)
        nav_layout.setContentsMargins(8, 8, 8, 8)
        nav_layout.setVerticalSpacing(6)
        self.playback_nav_layout = nav_layout
        self.advance_phase_btn = PlaybackAdvanceButton("行情推进（次日开盘）")
        self.advance_phase_btn.clicked.connect(self.advance_playback)
        # Keep these aliases for existing integrations while the interface uses one button.
        self.next_day_btn = self.advance_phase_btn
        self.close_phase_btn = self.advance_phase_btn
        nav_layout.addWidget(self.advance_phase_btn, 0, 0, 2, 1)
        # Keep the playback box from absorbing extra vertical space in the side panel.
        nav_box.setMaximumHeight(124)

        account = QGroupBox("账户")
        account.setObjectName("AccountBox")
        account.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.account_box = account
        form = QGridLayout(account)
        form.setContentsMargins(6, 6, 6, 6)
        form.setVerticalSpacing(4)
        form.setHorizontalSpacing(8)
        self.account_layout = form
        self.account_value_widgets: dict[str, QWidget] = {}
        self.account_key_labels: dict[str, QLabel] = {}
        self.cash_input = QLineEdit(f"{self.settings.initial_cash:.0f}")
        self.cash_input.setMinimumHeight(30)
        self.cash_input.textEdited.connect(self._initial_cash_text_edited)
        self.cash_label = QLabel("--")
        self.position_label = QLabel("--")
        self.position_profit_label = QLabel("--")
        self.asset_label = QLabel("--")
        self.cumulative_holding_days_label = QLabel("--")
        self.profit_label = QLabel("--")
        self.max_drawdown_label = ClickableLabel("--")
        self.max_drawdown_label.setProperty("drawdownToggle", True)
        self.max_drawdown_label.setProperty("drawdownActive", False)
        self.max_drawdown_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.max_drawdown_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.max_drawdown_label.setAccessibleName("最大回撤区间开关")
        self.max_drawdown_label.setToolTip("点击显示或隐藏最大回撤区间")
        self.max_drawdown_label.clicked.connect(self._toggle_max_drawdown_overlay)
        self._add_account_row(form, 0, "初始本金", self.cash_input)
        self._add_account_row(form, 1, "现金", self.cash_label)
        self._add_account_row(form, 2, "持仓市值", self.position_label)
        self._add_account_row(form, 3, "持仓盈亏", self.position_profit_label)
        self._add_account_row(form, 4, "总资产", self.asset_label)
        self._add_account_row(form, 5, "累计持有", self.cumulative_holding_days_label)
        self._add_account_row(form, 6, "总盈亏", self.profit_label, emphasized=True)
        self._add_account_row(form, 7, "最大回撤", self.max_drawdown_label)

        trade_box = QGroupBox("交易")
        trade_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        trade_layout = QGridLayout(trade_box)
        trade_layout.setContentsMargins(6, 6, 6, 6)
        trade_layout.setVerticalSpacing(4)
        trade_layout.setHorizontalSpacing(8)
        self.trade_layout = trade_layout
        trade_layout.setColumnMinimumWidth(0, ACCOUNT_KEY_LABEL_WIDTH)
        self.trade_key_labels: dict[str, QLabel] = {}
        self.buy_budget_input = QLineEdit(self._format_budget_text(self.settings.buy_budget))
        self.budget_input = self.buy_budget_input
        self.sell_budget_input = QLineEdit(self._format_budget_text(self.settings.sell_budget))
        self.buy_quantity_input = self._build_quantity_input()
        self.sell_quantity_input = self._build_quantity_input()
        self.buy_budget_input.textEdited.connect(self._buy_budget_text_edited)
        self.sell_budget_input.textEdited.connect(self._sell_budget_text_edited)
        self.buy_quantity_input.editingFinished.connect(self._buy_quantity_editing_finished)
        self.sell_quantity_input.editingFinished.connect(self._sell_quantity_editing_finished)
        self.buy_ratio_buttons: list[tuple[QPushButton, float]] = []
        self.sell_ratio_buttons: list[tuple[QPushButton, float]] = []
        buy_ratio_row = self._build_ratio_row(self.apply_buy_budget_ratio, "满仓", self.buy_ratio_buttons)
        sell_ratio_row = self._build_ratio_row(self.apply_sell_budget_ratio, "清仓", self.sell_ratio_buttons)
        self.buy_timing_label = self._build_trade_key_label("买入时机")
        self.trade_buy_btn = QPushButton("开盘买入")
        self.trade_buy_btn.setObjectName("BuyButton")
        self.sell_timing_label = self._build_trade_key_label("卖出时机")
        self.trade_sell_btn = QPushButton("开盘卖出")
        self.trade_sell_btn.setObjectName("SellButton")
        # Compatibility aliases keep existing shortcut and integration references working.
        self.open_buy_btn = self.trade_buy_btn
        self.close_buy_btn = self.trade_buy_btn
        self.open_sell_btn = self.trade_sell_btn
        self.close_sell_btn = self.trade_sell_btn
        self.trade_buy_btn.clicked.connect(lambda: self.buy_at(self.current_node))
        self.trade_sell_btn.clicked.connect(lambda: self.sell_at(self.current_node))
        trade_divider = QFrame()
        trade_divider.setObjectName("TradeSectionDivider")
        trade_divider.setFrameShape(QFrame.Shape.HLine)
        trade_divider.setFixedHeight(7)
        self.trade_divider = trade_divider
        trade_layout.addWidget(self._build_trade_key_label("买入金额"), 0, 0)
        trade_layout.addWidget(self.buy_budget_input, 0, 1, 1, 2)
        trade_layout.addWidget(self._build_trade_key_label("买入数量"), 1, 0)
        trade_layout.addWidget(self.buy_quantity_input, 1, 1, 1, 2)
        trade_layout.addWidget(self._build_trade_key_label("买入仓位"), 2, 0)
        trade_layout.addLayout(buy_ratio_row, 2, 1, 1, 2)
        trade_layout.addWidget(self.buy_timing_label, 3, 0)
        trade_layout.addWidget(self.trade_buy_btn, 3, 1, 1, 2)
        trade_layout.addWidget(trade_divider, 4, 0, 1, 3)
        trade_layout.addWidget(self._build_trade_key_label("卖出金额"), 5, 0)
        trade_layout.addWidget(self.sell_budget_input, 5, 1, 1, 2)
        trade_layout.addWidget(self._build_trade_key_label("卖出数量"), 6, 0)
        trade_layout.addWidget(self.sell_quantity_input, 6, 1, 1, 2)
        trade_layout.addWidget(self._build_trade_key_label("卖出仓位"), 7, 0)
        trade_layout.addLayout(sell_ratio_row, 7, 1, 1, 2)
        trade_layout.addWidget(self.sell_timing_label, 8, 0)
        trade_layout.addWidget(self.trade_sell_btn, 8, 1, 1, 2)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._status_label_minimum_height = 68
        self.status_label.setFixedHeight(self._status_label_minimum_height)
        self.status_label.setMinimumWidth(220)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        trade_layout.addWidget(self._build_trade_key_label("状态"), 9, 0)
        trade_layout.addWidget(self.status_label, 9, 1, 1, 2)
        self.allocation_box = QGroupBox("我的仓位")
        self.allocation_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        allocation_layout = QVBoxLayout(self.allocation_box)
        allocation_layout.setContentsMargins(8, 8, 8, 8)
        self.allocation_layout = allocation_layout
        self.position_ratio_bar = QProgressBar()
        self.position_ratio_bar.setObjectName("PositionRatioBar")
        self.position_ratio_bar.setRange(0, 100)
        self.position_ratio_bar.setValue(0)
        self.position_ratio_bar.setFormat("持仓 0% / 现金 100%")
        allocation_layout.addWidget(self.position_ratio_bar)
        layout.addWidget(nav_box)
        layout.addWidget(account)
        layout.addWidget(trade_box)
        layout.addWidget(self.allocation_box)
        self.round_log_box = QGroupBox("连续复利记录")
        round_layout = QVBoxLayout(self.round_log_box)
        round_layout.setContentsMargins(8, 8, 8, 8)
        round_layout.setSpacing(6)
        self.round_layout = round_layout
        self.continuous_btn = QPushButton(TRAINING_MODE_LABELS[self.training_mode_kind])
        self.continuous_btn.setObjectName("ContinuousModeButton")
        self.continuous_btn.setCheckable(False)
        self.continuous_btn.setEnabled(False)
        self.continuous_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.continuous_btn.setFixedHeight(34)
        self.continuous_btn.setToolTip("当前训练模式仅供查看；请从顶部“训练模式”菜单切换。")
        round_layout.addWidget(self.continuous_btn)
        self.round_content = QWidget()
        round_content_layout = QVBoxLayout(self.round_content)
        round_content_layout.setContentsMargins(0, 0, 0, 0)
        round_content_layout.setSpacing(6)
        self.round_content_layout = round_content_layout
        self.round_log = QListWidget()
        self.round_log.setObjectName("RoundLog")
        self.round_log.setAlternatingRowColors(False)
        self.round_log.setWordWrap(True)
        self.round_log.setMinimumHeight(40)
        self.round_log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.round_log.setToolTip("连续复利模式下已完成股票的轮次盈亏记录；最多可见 30 条，超出可滚动查看。")
        self.round_log.itemDoubleClicked.connect(self._open_round_review)
        self.round_log.viewport().installEventFilter(self)
        round_content_layout.addWidget(self.round_log)
        round_clear_row = QHBoxLayout()
        round_clear_row.addStretch(1)
        self.return_trade_btn = QPushButton("回到正在交易")
        self.return_trade_btn.setObjectName("ReturnTradeButton")
        self.return_trade_btn.setFixedHeight(28)
        self.return_trade_btn.setToolTip("切回正在交易的股票，恢复它的买卖点与持仓数据。")
        self.return_trade_btn.clicked.connect(self._return_to_trading)
        self.return_trade_btn.hide()
        round_clear_row.addWidget(self.return_trade_btn)
        self.clear_round_btn = QPushButton("一键重置")
        self.clear_round_btn.setObjectName("ClearRoundButton")
        self.clear_round_btn.setFixedHeight(28)
        self.clear_round_btn.setToolTip(
            "保留当前训练模式，清除轮次、买卖、持仓和盈亏数据，账户回到初始本金的未交易状态。"
        )
        self.clear_round_btn.clicked.connect(self._reset_training_state)
        round_clear_row.addWidget(self.clear_round_btn)
        round_content_layout.addLayout(round_clear_row)
        round_layout.addWidget(self.round_content)
        self._sync_return_button_state()
        layout.addWidget(self.round_log_box)
        layout.addStretch(1)
        layout.setStretchFactor(self.round_log_box, 3)
        self._update_trade_button_states()
        self._set_ratio_buttons_checked(self.buy_ratio_buttons, self.selected_buy_ratio)
        self._set_ratio_buttons_checked(self.sell_ratio_buttons, self.selected_sell_ratio)
        self._sync_continuous_mode_widget()
        self._sync_round_log_visibility()
        scroll.setWidget(panel)
        return scroll

    @staticmethod
    def _build_quantity_input() -> QSpinBox:
        quantity_input = QSpinBox()
        quantity_input.setObjectName("TradeQuantityInput")
        quantity_input.setRange(0, 2_000_000_000)
        quantity_input.setSingleStep(100)
        quantity_input.setSuffix("")
        quantity_input.setKeyboardTracking(False)
        quantity_input.setAlignment(Qt.AlignmentFlag.AlignLeft)
        return quantity_input

    def _build_ratio_row(self, handler, full_label: str, button_store: list[tuple[QPushButton, float]]) -> QHBoxLayout:
        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(6)
        for label, ratio in (("1/4", 0.25), ("1/3", 1 / 3), ("1/2", 0.5), (full_label, 1.0)):
            ratio_btn = QPushButton(label)
            ratio_btn.setObjectName("RatioButton")
            ratio_btn.setCheckable(True)
            ratio_btn.clicked.connect(lambda checked=False, value=ratio: handler(value, checked))
            button_store.append((ratio_btn, ratio))
            ratio_row.addWidget(ratio_btn)
        return ratio_row

    @staticmethod
    def _set_ratio_buttons_checked(buttons: list[tuple[QPushButton, float]], selected_ratio: float | None) -> None:
        for button, ratio in buttons:
            button.setChecked(selected_ratio is not None and abs(ratio - selected_ratio) < 0.000001)

    def _uses_round_records(self) -> bool:
        return self.continuous_compound_mode or self.training_mode_kind == TRAINING_MODE_INDEPENDENT

    def _set_training_mode(self, mode: str) -> None:
        if mode not in TRAINING_MODE_LABELS or mode == self.training_mode_kind:
            self._sync_continuous_mode_widget()
            return
        if self._has_position():
            QMessageBox.information(
                self,
                "请先清仓",
                "当前训练模式还有未清仓的股票。\n"
                "建议先完成卖出并清仓，再切换训练模式，以免混用不同的资金统计方式。\n\n"
                "本次未切换。",
            )
            self._sync_continuous_mode_widget()
            self._sync_round_log_visibility()
            self._sync_random_btn_tooltip()
            self._update_status("训练模式未切换：请先清仓当前持仓。")
            return
        if self.round_records and not self._confirm_reset_if_records():
            self._sync_continuous_mode_widget()
            self._sync_round_log_visibility()
            self._sync_random_btn_tooltip()
            self._update_status("已取消切换训练模式，原有训练记录已保留。")
            return
        self.training_mode_kind = mode
        self.continuous_compound_mode = mode == TRAINING_MODE_CONTINUOUS
        self.settings.training_mode = mode
        self.settings.continuous_compound_mode = self.continuous_compound_mode
        self._independent_switch_pending = False
        self._single_switch_pending = False
        self._reset_account_after_training_mode_switch()
        self._save_settings()
        self._sync_continuous_mode_widget()
        self._sync_round_log_visibility()
        self._sync_random_btn_tooltip()
        self._update_status(
            f"已切换为{TRAINING_MODE_LABELS[mode]}，账户已重置为初始本金："
            f"{TRAINING_MODE_DESCRIPTIONS[mode]}"
        )

    def _reset_account_after_training_mode_switch(self) -> None:
        """Reset account statistics without moving the current market date."""
        self.round_records = []
        self.reviewed_round_index = None
        self.equity_curve = []
        self.equity_points = []
        self.round_equity_points = []
        self.completed_trade_ranges = []
        self.cumulative_holding_days_base = 0
        self._last_equity_record_key = None
        self._performance_summary_key = None
        self._frozen_position_metrics = None
        self._reset_drawdown_overlay()
        self._reset_first_buy_cycle()
        self._clear_return_context()
        delete_document()
        if not self.engine:
            return
        initial_cash = float(self.settings.initial_cash)
        self.engine.initial_cash = initial_cash
        self.engine.cash = initial_cash
        self.engine.slots = [PositionSlot(index=index) for index in range(self.settings.slot_count)]
        self.engine.trades = []
        self.trade_started = False
        self.account_initial_cash = initial_cash
        self.round_start_cash = initial_cash
        self.round_start_date = self.engine.current_bar.date
        self.round_start_node = self.current_node
        self.account_baseline_locked = False
        self.engine_epoch += 1
        if self.selected_buy_ratio is not None:
            self._sync_buy_budget_from_selected_ratio()
        if self.selected_sell_ratio is not None:
            self._sync_sell_budget_from_selected_ratio()
        self._refresh()

    def _toggle_continuous_mode(self, checked: bool) -> None:
        self._set_training_mode(TRAINING_MODE_CONTINUOUS if checked else TRAINING_MODE_SINGLE)

    def _sync_continuous_mode_widget(self) -> None:
        if not hasattr(self, "continuous_btn"):
            return
        self.continuous_btn.setText(TRAINING_MODE_LABELS[self.training_mode_kind])
        description = TRAINING_MODE_DESCRIPTIONS[self.training_mode_kind]
        self.continuous_btn.setToolTip(
            f"{description}\n训练模式仅从顶部“训练模式”菜单切换。"
        )
        self.round_log_box.setToolTip(description)
        if hasattr(self, "performance_overlay"):
            self.performance_overlay.set_training_mode_layout(self.training_mode_kind)
        self._sync_menu_actions()

    def _sync_round_log_visibility(self) -> None:
        if not hasattr(self, "round_content"):
            return
        on = self._uses_round_records()
        has_return_context = self._return_to_trading_context is not None
        has_browse_records = bool(self.round_records) or has_return_context
        is_formal_training = self.training_mode and not self.test_trade_active
        show_mode_status = is_formal_training
        show_round_content = on and (is_formal_training or has_browse_records)
        self.continuous_btn.setVisible(show_mode_status)
        self.round_content.setVisible(show_round_content)
        self.round_log_box.setVisible(show_mode_status or show_round_content)
        if self.training_mode_kind == TRAINING_MODE_INDEPENDENT:
            self.round_log_box.setTitle("独立训练记录")
            self.round_log.setToolTip("独立训练模式下每只练习股票的盈亏记录；各轮资金和日期互不延续。")
        elif self.training_mode_kind == TRAINING_MODE_CONTINUOUS:
            self.round_log_box.setTitle("连续复利记录")
            self.round_log.setToolTip("连续复利模式下已完成股票的轮次盈亏记录；资金和时间连续延续。")
        else:
            self.round_log_box.setTitle("训练模式")
            self.round_log.setToolTip("")
        # Clearing records is an account action; hide it while reviewing a past
        # round so it can't be confused with the ongoing trading session.
        self.clear_round_btn.setVisible(on and is_formal_training)
        if show_round_content:
            self.round_log_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        else:
            self.round_log_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._sync_return_button_state()

    def _confirm_reset_if_records(self) -> bool:
        """Ask for confirmation before an action that would wipe the round records."""
        if not self.round_records:
            return True
        answer = QMessageBox.question(
            self,
            "确认清空训练记录",
            f"此操作会清空当前已记录的 {len(self.round_records)} 轮训练记录，是否继续？\n"
            "账户将回到设置的初始本金。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_reset_account(self) -> bool:
        """Confirm a fresh-start reset that clears records and/or an open position."""
        if not self.round_records and not self._has_position():
            return True
        parts = []
        if self.round_records:
            parts.append(f"清空 {len(self.round_records)} 轮训练记录")
        if self._has_position():
            parts.append("重置当前未平仓的交易")
        answer = QMessageBox.question(
            self,
            "确认重置",
            f"此操作会{'、'.join(parts)}，并将账户回到初始本金，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _sync_random_btn_tooltip(self) -> None:
        if not hasattr(self, "random_btn"):
            return
        if self.continuous_compound_mode:
            self.random_btn.setToolTip(
                "换股续作：仅在空仓时可用，账户资金与总盈亏延续，轮次记录累计；时间只往前。"
            )
        elif self.training_mode_kind == TRAINING_MODE_INDEPENDENT:
            self.random_btn.setToolTip(
                "独立换股：保存当前股票练习记录；下一只股票重新使用设置的初始本金，日期可独立选择。"
            )
        else:
            self.random_btn.setToolTip("开启随机换股：换股会重置账户到初始本金。")

    def _random_training_forward_bars(self) -> int:
        selected = self.settings.random_training_horizon
        return next(
            (bars for key, _label, bars in RANDOM_TRAINING_HORIZONS if key == selected),
            120,
        )

    def _set_random_training_horizon(self, horizon: str) -> None:
        option = next(
            ((label, bars) for key, label, bars in RANDOM_TRAINING_HORIZONS if key == horizon),
            None,
        )
        if option is None:
            return
        label, bars = option
        changed = self.settings.random_training_horizon != horizon
        self.settings.random_training_horizon = horizon
        if changed:
            self._save_settings()
            location = resolve_tdx_location(self.tdx_path.text().strip())
            if location is not None:
                self._reset_random_prefetch(location)
        for key, action in self.simulation_training_horizon_actions.items():
            action.setChecked(key == horizon)
        self._update_status(
            f"随机训练时长已设为{label}：起点前保留半年历史，后方至少保留 {bars} 个交易日。"
        )

    @staticmethod
    def _format_budget_text(value: float) -> str:
        numeric = float(value)
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.2f}"

    @staticmethod
    def _parse_money_text(text: str) -> float | None:
        normalized = text.strip().replace(",", "")
        if not normalized:
            return None
        try:
            value = float(normalized)
        except ValueError:
            return None
        return value if math.isfinite(value) else None

    def _initial_cash_text_edited(self, text: str) -> None:
        if self._initial_cash_input_locked():
            if self.engine:
                self.cash_input.setText(self._format_budget_text(self.engine.initial_cash))
            self._update_status("初始本金已锁定，不能修改。")
            return
        value = self._parse_money_text(text)
        if value is None or value <= 0:
            return
        self.settings.initial_cash = value
        if self.engine and not self.engine.trades and all(slot.is_empty for slot in self.engine.slots):
            self.engine.initial_cash = value
            self.engine.cash = value
            self.account_initial_cash = value
            self.round_start_cash = value
        if self.selected_buy_ratio is not None and self.engine is None:
            amount = budget_from_ratio(value, self.selected_buy_ratio)
            self.buy_budget_input.setText(str(amount))
            self._set_ratio_buttons_checked(self.buy_ratio_buttons, self.selected_buy_ratio)
            self.settings.buy_budget = amount
        elif self.selected_buy_ratio is not None and self.engine:
            self.settings.buy_budget = self._sync_buy_budget_from_selected_ratio()
        self._save_settings()
        if self.engine:
            self._refresh()

    def _initial_cash_input_locked(self) -> bool:
        if (
            self.engine
            and not self.training_mode
            and self.engine.current_bar.code == SHANGHAI_INDEX_CODE
        ):
            return False
        engine_locked = bool(self.engine and any(trade.accepted and trade.side == "buy" for trade in self.engine.trades))
        return self.account_baseline_locked or engine_locked

    def _update_initial_cash_input_state(self) -> None:
        locked = self._initial_cash_input_locked()
        self.cash_input.setReadOnly(locked)
        property_changed = self.cash_input.property("locked") != locked
        if property_changed:
            self.cash_input.setProperty("locked", locked)
        self.cash_input.setToolTip("初始本金已锁定，不能修改。" if locked else "开始买入前可以修改初始本金。")
        if property_changed:
            _repolish_widget(self.cash_input)

    def _buy_budget_text_edited(self, text: str) -> None:
        if self._trade_input_syncing:
            return
        self._buy_input_mode = "amount"
        self.selected_buy_ratio = None
        self._set_ratio_buttons_checked(self.buy_ratio_buttons, None)
        value = self._parse_money_text(text)
        if value is not None:
            self.settings.buy_budget = value
            self._sync_buy_quantity_from_budget(value)
        self.settings.selected_buy_ratio = None
        self._save_settings()

    def _sell_budget_text_edited(self, text: str) -> None:
        if self._trade_input_syncing:
            return
        self._sell_input_mode = "amount"
        self.selected_sell_ratio = None
        self._set_ratio_buttons_checked(self.sell_ratio_buttons, None)
        value = self._parse_money_text(text)
        if value is not None:
            self.settings.sell_budget = value
            self._sync_sell_quantity_from_budget(value)
        self.settings.selected_sell_ratio = None
        self._save_settings()

    @staticmethod
    def _whole_lot_quantity(value: int | float) -> int:
        return max(0, int(value) // 100 * 100)

    def _set_quantity_value(self, quantity_input: QSpinBox, value: int) -> None:
        quantity = self._whole_lot_quantity(value)
        was_syncing = self._trade_input_syncing
        self._trade_input_syncing = True
        try:
            quantity_input.setValue(quantity)
            quantity_input.setSuffix(" 股" if quantity >= 100 else "")
        finally:
            self._trade_input_syncing = was_syncing

    def _set_budget_text(self, budget_input: QLineEdit, value: float) -> None:
        was_syncing = self._trade_input_syncing
        self._trade_input_syncing = True
        try:
            budget_input.setText(self._format_budget_text(value))
        finally:
            self._trade_input_syncing = was_syncing

    def _sync_buy_quantity_from_budget(self, budget: float) -> int:
        quantity = self.engine.buy_quantity_for_budget(self.current_node, budget) if self.engine else 0
        self._set_quantity_value(self.buy_quantity_input, quantity)
        return quantity

    def _sync_sell_quantity_from_budget(self, budget: float) -> int:
        if not self.engine:
            quantity = 0
        else:
            price = self.engine.current_bar.price_at(self.current_node)
            sellable = sum(
                slot.sellable_quantity if self.engine.t_plus_one else slot.quantity for slot in self.engine.slots
            )
            quantity = min(sellable, self._whole_lot_quantity(float(budget) / price)) if price > 0 else 0
        self._set_quantity_value(self.sell_quantity_input, quantity)
        return quantity

    @staticmethod
    def _quantity_editor_value(quantity_input: QSpinBox) -> int:
        text = quantity_input.lineEdit().text().replace("股", "").replace(",", "").strip()
        try:
            return max(0, int(text))
        except ValueError:
            return 0

    def _buy_quantity_editing_finished(self) -> None:
        value = self._quantity_editor_value(self.buy_quantity_input)
        QTimer.singleShot(0, lambda: self._buy_quantity_changed(value))

    def _sell_quantity_editing_finished(self) -> None:
        value = self._quantity_editor_value(self.sell_quantity_input)
        QTimer.singleShot(0, lambda: self._sell_quantity_changed(value))

    def _buy_quantity_changed(self, value: int) -> None:
        if self._trade_input_syncing:
            return
        below_one_lot = 0 < value < 100
        quantity = self._whole_lot_quantity(value)
        if self.engine:
            quantity = min(quantity, self.engine.buy_quantity_for_budget(self.current_node, self.engine.cash))
        self._set_quantity_value(self.buy_quantity_input, quantity)
        self._buy_input_mode = "quantity"
        self.selected_buy_ratio = None
        self._set_ratio_buttons_checked(self.buy_ratio_buttons, None)
        self.settings.selected_buy_ratio = None
        amount = round(self.engine.current_bar.price_at(self.current_node) * quantity, 2) if self.engine else 0.0
        self._set_budget_text(self.buy_budget_input, amount)
        self.settings.buy_budget = amount
        self._save_settings()
        if below_one_lot:
            self._update_status("买入数量不足 100 股；A股买入必须是 100 股的整数倍。")

    def _sell_quantity_changed(self, value: int) -> None:
        if self._trade_input_syncing:
            return
        below_one_lot = 0 < value < 100
        quantity = self._whole_lot_quantity(value)
        if self.engine:
            sellable = sum(
                slot.sellable_quantity if self.engine.t_plus_one else slot.quantity for slot in self.engine.slots
            )
            quantity = min(quantity, sellable)
        self._set_quantity_value(self.sell_quantity_input, quantity)
        self._sell_input_mode = "quantity"
        self.selected_sell_ratio = None
        self._set_ratio_buttons_checked(self.sell_ratio_buttons, None)
        self.settings.selected_sell_ratio = None
        amount = round(self.engine.current_bar.price_at(self.current_node) * quantity, 2) if self.engine else 0.0
        self._set_budget_text(self.sell_budget_input, amount)
        self.settings.sell_budget = amount
        self._save_settings()
        if below_one_lot:
            self._update_status("卖出数量不足 100 股；请输入至少 100 股。")

    def _sync_trade_quantity_inputs(self) -> None:
        if not self.engine:
            self._set_quantity_value(self.buy_quantity_input, 0)
            self._set_quantity_value(self.sell_quantity_input, 0)
            return
        price = self.engine.current_bar.price_at(self.current_node)
        if self._buy_input_mode == "quantity":
            maximum = self.engine.buy_quantity_for_budget(self.current_node, self.engine.cash)
            quantity = min(self._whole_lot_quantity(self.buy_quantity_input.value()), maximum)
            self._set_quantity_value(self.buy_quantity_input, quantity)
            self._set_budget_text(self.buy_budget_input, round(price * quantity, 2))
        else:
            budget = self._parse_money_text(self.buy_budget_input.text()) or 0.0
            self._sync_buy_quantity_from_budget(budget)
        if self._sell_input_mode == "quantity":
            sellable = sum(
                slot.sellable_quantity if self.engine.t_plus_one else slot.quantity for slot in self.engine.slots
            )
            quantity = min(self._whole_lot_quantity(self.sell_quantity_input.value()), sellable)
            self._set_quantity_value(self.sell_quantity_input, quantity)
            self._set_budget_text(self.sell_budget_input, round(price * quantity, 2))
        else:
            budget = self._parse_money_text(self.sell_budget_input.text()) or 0.0
            self._sync_sell_quantity_from_budget(budget)

    def _add_account_row(self, layout: QGridLayout, row: int, name: str, value_widget: QWidget, emphasized: bool = False) -> None:
        name_label = QLabel(self._account_key_text(name))
        name_label.setObjectName("TotalProfitKey" if emphasized else "AccountKey")
        name_label.setFixedWidth(ACCOUNT_KEY_LABEL_WIDTH)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setMinimumHeight(34 if emphasized else 28)
        if emphasized:
            font = name_label.font()
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 8)
            name_label.setFont(font)
        self.account_key_labels[name] = name_label
        self.account_value_widgets[name] = value_widget
        value_widget.setObjectName("TotalProfitValue" if emphasized else "AccountValue")
        value_widget.setMinimumHeight(34 if emphasized else 28)
        layout.addWidget(name_label, row, 0)
        layout.addWidget(value_widget, row, 1)

    def _build_trade_key_label(self, name: str, minimum_height: int = 28) -> QLabel:
        label = QLabel(name)
        label.setObjectName("AccountKey")
        label.setFixedWidth(ACCOUNT_KEY_LABEL_WIDTH)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumHeight(minimum_height)
        self.trade_key_labels[name] = label
        return label

    @staticmethod
    def _account_key_text(name: str) -> str:
        return name

    def _responsive_density(self) -> str:
        pixel_ratio = max(1.0, float(self.devicePixelRatioF()))
        physical_width = round(self.width() * pixel_ratio)
        physical_height = round(self.height() * pixel_ratio)
        if (
            self.isVisible()
            and physical_width <= LOW_RES_MAX_PHYSICAL_WIDTH
            and physical_height <= LOW_RES_MAX_PHYSICAL_HEIGHT
        ):
            return "low"
        if (
            COMPACT_MIN_PHYSICAL_WIDTH <= physical_width <= COMPACT_MAX_PHYSICAL_WIDTH
            and physical_height <= COMPACT_MAX_PHYSICAL_HEIGHT
        ):
            return "compact"
        return "normal"

    def _uses_compact_layout(self) -> bool:
        return self._responsive_density() != "normal"

    @staticmethod
    def _set_control_height(widget: QWidget, height: int | None) -> None:
        widget.setMaximumHeight(16_777_215)
        widget.setMinimumHeight(0)
        if height is not None:
            widget.setFixedHeight(height)

    def _sync_windowed_market_strip_height(self) -> None:
        if not hasattr(self, "market_labels"):
            return
        minimum_height = {
            "normal": 50,
            "compact": COMPACT_METRIC_HEIGHT,
            "low": LOW_RES_METRIC_HEIGHT,
        }[self._layout_density]
        fixed_height = None
        if not self.isMaximized() and not self.isFullScreen():
            vertical_padding = {"normal": 12, "compact": 6, "low": 4}[self._layout_density]
            fixed_height = max(
                minimum_height,
                max(label.fontMetrics().lineSpacing() for label in self.market_labels.values()) * 3
                + vertical_padding,
            )
        for label in self.market_labels.values():
            self._set_control_height(label, fixed_height)
            if fixed_height is None:
                label.setMinimumHeight(minimum_height)

    def _sync_responsive_layout(self) -> None:
        if not hasattr(self, "main_splitter"):
            return
        density = self._responsive_density()
        if density == self._layout_density:
            return
        self._layout_density = density
        low_resolution = density == "low"
        compact = density != "normal"
        self._compact_layout = compact
        self._low_resolution_layout = low_resolution

        def density_value(normal_value, compact_value, low_value):
            if low_resolution:
                return low_value
            if compact:
                return compact_value
            return normal_value

        self.root_layout.setContentsMargins(*density_value((10, 8, 10, 8), (6, 4, 6, 4), (4, 3, 4, 3)))
        self.root_layout.setSpacing(density_value(6, 4, 3))
        self.top_bar_layout.setContentsMargins(*density_value((8, 1, 8, 1), (6, 1, 6, 1), (4, 1, 4, 1)))
        self.top_bar_layout.setHorizontalSpacing(density_value(6, 4, 3))
        self.top_bar_layout.setVerticalSpacing(density_value(2, 1, 1))
        for control in self.top_bar_controls:
            self._set_control_height(control, density_value(26, 24, 22))
        self._sync_quick_actions_panel_layout()

        self.chart_panel_layout.setSpacing(density_value(6, 3, 2))
        self.chart_header_layout.setSpacing(density_value(6, 3, 2))
        self.chart_title_layout.setSpacing(density_value(8, 6, 4))
        self.market_strip.setHorizontalSpacing(density_value(6, 4, 3))
        for label in self.market_labels.values():
            label.setMinimumHeight(density_value(50, COMPACT_METRIC_HEIGHT, LOW_RES_METRIC_HEIGHT))
        self.title_label.setStyleSheet(density_value("", "font-size: 18px;", "font-size: 16px;"))
        self.identity_toggle.setFixedSize(30, 28)

        label_width = density_value(ACCOUNT_KEY_LABEL_WIDTH, COMPACT_ACCOUNT_KEY_LABEL_WIDTH, LOW_RES_ACCOUNT_KEY_LABEL_WIDTH)
        side_minimum = density_value(360, COMPACT_SIDE_PANEL_MIN_WIDTH, LOW_RES_SIDE_PANEL_MIN_WIDTH)
        side_maximum = density_value(520, COMPACT_SIDE_PANEL_MAX_WIDTH, LOW_RES_SIDE_PANEL_MAX_WIDTH)
        self.side_panel_scroll.setMinimumWidth(side_minimum)
        self.side_panel_scroll.setMaximumWidth(side_maximum)
        self.side_panel_layout.setSpacing(density_value(8, 4, 2))
        self.playback_nav_layout.setContentsMargins(*density_value((8, 8, 8, 8), (5, 5, 5, 5), (3, 3, 3, 3)))
        self.playback_nav_layout.setVerticalSpacing(density_value(6, 3, 1))
        self.advance_phase_btn.setFixedHeight(density_value(72, 54, 44))
        self.playback_nav_box.setMaximumHeight(density_value(124, 92, 68))
        self.account_layout.setContentsMargins(*density_value((6, 6, 6, 6), (4, 4, 4, 4), (3, 3, 3, 3)))
        self.account_layout.setVerticalSpacing(density_value(4, 2, 1))
        self.account_layout.setHorizontalSpacing(density_value(8, 5, 4))
        self.account_layout.setColumnMinimumWidth(0, label_width)
        self.trade_layout.setContentsMargins(*density_value((6, 6, 6, 6), (4, 4, 4, 4), (3, 3, 3, 3)))
        self.trade_layout.setVerticalSpacing(density_value(4, 2, 1))
        self.trade_layout.setHorizontalSpacing(density_value(8, 5, 4))
        self.trade_layout.setColumnMinimumWidth(0, label_width)
        self.trade_divider.setFixedHeight(density_value(7, 7, 4))

        for name, label in self.account_key_labels.items():
            emphasized = name == "总盈亏"
            label.setFixedWidth(label_width)
            label.setMinimumHeight(
                density_value(34 if emphasized else 28, 30 if emphasized else 24, 26 if emphasized else 20)
            )
        for name, widget in self.account_value_widgets.items():
            emphasized = name == "总盈亏"
            self._set_control_height(
                widget,
                density_value(None, 30 if emphasized else 24, 26 if emphasized else 20),
            )
            if not compact:
                widget.setMinimumHeight(34 if emphasized else 28)
        for label in self.trade_key_labels.values():
            label.setFixedWidth(label_width)
            label.setMinimumHeight(density_value(28, 24, 20))
        trade_controls = (
            self.buy_budget_input,
            self.sell_budget_input,
            self.buy_quantity_input,
            self.sell_quantity_input,
            self.trade_buy_btn,
            self.trade_sell_btn,
            *(button for button, _ratio in self.buy_ratio_buttons),
            *(button for button, _ratio in self.sell_ratio_buttons),
        )
        for control in trade_controls:
            self._set_control_height(control, density_value(None, 24, 20))
        self.status_label.setMinimumWidth(density_value(220, 188, 154))
        self._status_label_minimum_height = density_value(68, 60, 54)
        self._sync_status_label_height()

        self.allocation_layout.setContentsMargins(*density_value((8, 8, 8, 8), (5, 5, 5, 5), (4, 4, 4, 4)))
        self.round_layout.setContentsMargins(*density_value((8, 8, 8, 8), (5, 5, 5, 5), (4, 4, 4, 4)))
        self.round_layout.setSpacing(density_value(6, 4, 2))
        self.round_content_layout.setSpacing(density_value(6, 4, 2))
        self.continuous_btn.setFixedHeight(density_value(34, 28, 24))
        self.return_trade_btn.setFixedHeight(density_value(28, 24, 22))
        self.clear_round_btn.setFixedHeight(density_value(28, 24, 22))
        self.round_log.setMinimumHeight(density_value(40, 40, 32))

        current_sizes = self.main_splitter.sizes()
        total_width = max(self.main_splitter.width(), sum(current_sizes))
        target_width = density_value(400, COMPACT_SIDE_PANEL_TARGET_WIDTH, LOW_RES_SIDE_PANEL_TARGET_WIDTH)
        self.main_splitter.setSizes([max(1, total_width - target_width), target_width])
        QTimer.singleShot(0, self._align_top_actions_with_side_panel)
        self._apply_style()
        self._sync_windowed_market_strip_height()
        QTimer.singleShot(0, self._sync_status_label_height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_responsive_layout()
        self._sync_windowed_market_strip_height()
        QTimer.singleShot(0, self._align_top_actions_with_side_panel)
        QTimer.singleShot(0, self._sync_status_label_height)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_responsive_layout()
        if not self._window_layout_restored and not _is_offscreen():
            self._window_layout_restored = True
            if hasattr(self, "main_splitter"):
                self.main_splitter.setSizes(self.settings.main_splitter_sizes)
        self._sync_windowed_market_strip_height()
        QTimer.singleShot(0, self._align_top_actions_with_side_panel)
        QTimer.singleShot(0, self._sync_status_label_height)

    def closeEvent(self, event) -> None:
        if self.sector_integration.page:
            self.sector_integration.page.cancel_pending()
        self._market_sync_timer.stop()
        if self._migration_restore_pending_restart:
            super().closeEvent(event)
            return
        if self.test_trade_active:
            self.exit_test_trade_mode(update_status=False)
            if self._return_to_trading_context is not None:
                self._return_to_trading(update_status=False)
        if self.training_mode_kind == TRAINING_MODE_SINGLE and not self.continuous_compound_mode:
            self._archive_ordinary_performance()
        self._persist_session()
        self._save_all_manual_settings()
        super().closeEvent(event)

    @staticmethod
    def _tinted_icon(path: Path, color: str, active_color: str) -> QIcon:
        source_icon = QIcon(str(path))
        render_size = QSize(54, 54)

        def tinted_pixmap(tint: str) -> QPixmap:
            source = source_icon.pixmap(render_size)
            pixmap = source.copy()
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            painter.fillRect(pixmap.rect(), QColor(tint))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            painter.drawPixmap(0, 0, source)
            painter.end()
            return pixmap

        icon = QIcon()
        for state in (QIcon.State.Off, QIcon.State.On):
            icon.addPixmap(tinted_pixmap(color), QIcon.Mode.Normal, state)
            icon.addPixmap(tinted_pixmap(active_color), QIcon.Mode.Active, state)
        return icon

    def _sync_identity_toggle_appearance(self) -> None:
        self.identity_toggle.setText("")
        if self.identity_toggle.isChecked():
            self.identity_toggle.setIcon(QIcon(str(EYE_ICON_PATH)))
            self.identity_toggle.setToolTip("点击隐藏股票、日期、标题和时间轴")
        else:
            self.identity_toggle.setIcon(QIcon(str(EYE_OFF_ICON_PATH)))
            self.identity_toggle.setToolTip("点击显示股票、日期、标题和时间轴")
        self._sync_identity_input_privacy()
        self._sync_menu_actions()

    def _sync_identity_input_privacy(self, is_shanghai_index: bool | None = None) -> None:
        if is_shanghai_index is None:
            is_shanghai_index = bool(self.engine and self.engine.current_bar.code == SHANGHAI_INDEX_CODE)
        hide_identity = not self.identity_toggle.isChecked() and not is_shanghai_index
        echo_mode = QLineEdit.EchoMode.Password if hide_identity else QLineEdit.EchoMode.Normal
        self.code_input.setEchoMode(echo_mode)
        self.date_input.setEchoMode(echo_mode)

    def _save_all_manual_settings(self) -> None:
        self.settings.tdx_root = self.tdx_path.text()
        initial_cash = self._parse_money_text(self.cash_input.text())
        if initial_cash is not None and initial_cash > 0:
            self.settings.initial_cash = initial_cash
        buy_budget = self._parse_money_text(self.buy_budget_input.text())
        if buy_budget is not None:
            self.settings.buy_budget = buy_budget
        sell_budget = self._parse_money_text(self.sell_budget_input.text())
        if sell_budget is not None:
            self.settings.sell_budget = sell_budget
        self.settings.selected_buy_ratio = self.selected_buy_ratio
        self.settings.selected_sell_ratio = self.selected_sell_ratio
        self.settings.show_stock_identity = self.identity_toggle.isChecked()
        self.settings.hidden_ma_periods = sorted(self.kline_widget.hidden_ma_periods)
        self.settings.sub_pane_indicators = list(self.kline_widget.sub_pane_indicators)
        self.settings.pane_height_ratios = list(self.kline_widget.pane_height_ratios)
        self.settings.hidden_volume_ma_periods = sorted(self.kline_widget.hidden_volume_ma_periods)
        self.settings.macd_fast = self.kline_widget.macd_fast
        self.settings.macd_slow = self.kline_widget.macd_slow
        self.settings.macd_signal = self.kline_widget.macd_signal
        self.settings.kdj_n = self.kline_widget.kdj_n
        self.settings.kdj_k = self.kline_widget.kdj_k
        self.settings.kdj_d = self.kline_widget.kdj_d
        self.settings.pane_macd_params = [list(params) for params in self.kline_widget.pane_macd_params]
        self.settings.pane_kdj_params = [list(params) for params in self.kline_widget.pane_kdj_params]
        self.settings.main_overlay_mode = self.kline_widget.main_overlay_mode
        self.settings.boll_n = self.kline_widget.boll_n
        self.settings.boll_k = self.kline_widget.boll_k
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        self.settings.window_maximized = self.isMaximized()
        if hasattr(self, "main_splitter"):
            self.settings.main_splitter_sizes = list(self.main_splitter.sizes())
        integration = getattr(self, "sector_integration", None)
        page = getattr(integration, "page", None) if integration is not None else None
        if page is not None:
            self.settings.sector_splitter_sizes = list(page.sector_splitter.sizes())
            self.settings.sector_chart_splitter_sizes = list(page.sector_chart_splitter.sizes())
            self.settings.sector_sub_pane_indicators = list(page.chart.sub_pane_indicators)
            self.settings.sector_pane_height_ratios = list(page.chart.pane_height_ratios)
            self.settings.sector_chart_window_size = int(page._window)
            (
                self.settings.favorite_sectors,
                self.settings.favorite_stocks,
            ) = page.favorite_codes()
            self.settings.board_filters = page.board_filter_keys()
            self.settings.sector_table_widths = [
                page.sector_table.columnWidth(column)
                for column in range(page.sector_table.columnCount())
            ]
            self.settings.stock_table_widths = [
                page.stock_table.columnWidth(column)
                for column in range(page.stock_table.columnCount())
            ]
        self._save_settings()

    def save_current_config(self) -> None:
        self._save_all_manual_settings()
        message = f"当前配置已保存：{CONFIG_PATH}"
        integration = getattr(self, "sector_integration", None)
        page = getattr(integration, "page", None) if integration is not None else None
        if integration is not None and integration.active and page is not None:
            page.status.setText(message)
        else:
            self._update_status(message)

    def open_config_directory(self) -> None:
        self._save_all_manual_settings()
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_PATH.parent)))
        self._update_status(f"配置已保存：{CONFIG_PATH}")

    def export_user_data_package(self) -> Path | None:
        self._save_all_manual_settings()
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        suggested = self._desktop_directory() / f"大A日K训练器-用户数据-{timestamp}.zip"
        filename, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "打包迁移全部用户数据",
            str(suggested),
            "用户数据迁移包 (*.zip)",
        )
        if not filename:
            return None
        self._persist_timer.stop()
        self._persist_session(include_ordinary=True)
        try:
            package = export_migration_package(Path(filename), CONFIG_PATH.parent)
        except (OSError, MigrationPackageError) as exc:
            QMessageBox.warning(self, "打包失败", f"用户数据打包失败：\n{exc}")
            return None
        usage = calculate_storage_usage(CONFIG_PATH.parent)
        QMessageBox.information(
            self,
            "打包完成",
            f"用户数据已打包到：\n{package}\n\n"
            f"已包含：设置、可续作训练会话、历史成绩（{self._format_storage_size(usage.user_data_bytes)}）。\n"
            "未包含：通达信原始行情、可重建缓存、桌面截图和 CSV。\n"
            "换电脑后安装/打开新版软件，再从“文件 → 数据备份与迁移”恢复即可。",
        )
        self._update_status(f"用户数据迁移包已保存：{package}")
        return package

    def build_portable_package(self, *, include_market_data: bool = True) -> bool:
        if self._portable_build_worker is not None:
            QMessageBox.information(self, "正在打包", "免安装便携版正在生成，请稍候。")
            return False
        self._save_all_manual_settings()
        self._persist_session()
        destination = QFileDialog.getExistingDirectory(
            self,
            "选择拷贝即用版的保存位置" if include_market_data else "选择配合通达信版的保存位置",
            str(self._desktop_directory()),
        )
        if not destination:
            return False
        self._persist_timer.stop()
        self._persist_session(include_ordinary=True)
        self.file_build_portable_action.setEnabled(False)
        self.file_build_tdx_portable_action.setEnabled(False)
        self._update_status("正在生成免安装便携版，请稍候；源码/BAT 模式首次打包可能需要几分钟……")
        project_root = Path(__file__).resolve().parent.parent
        worker = PortableBuildWorker(
            Path(destination),
            CONFIG_PATH.parent,
            project_root,
            self.portable_build_completed.emit,
            market_source=self.tdx_path.text().strip(),
            include_market_data=include_market_data,
        )
        self._portable_build_worker = worker
        QThreadPool.globalInstance().start(worker)
        return True

    def _finish_portable_build(self, payload: dict) -> None:
        self._portable_build_worker = None
        self.file_build_portable_action.setEnabled(True)
        self.file_build_tdx_portable_action.setEnabled(True)
        error = payload.get("error") if isinstance(payload, dict) else "未知错误"
        if error:
            QMessageBox.warning(self, "便携版生成失败", str(error))
            self._update_status("免安装便携版生成失败。")
            return
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, PortableBuildResult):
            QMessageBox.warning(self, "便携版生成失败", "打包结果异常，请重试。")
            self._update_status("免安装便携版生成失败。")
            return
        usage = (
            "包含当前数据源的日K、复权和股票资料。首次打开自动使用内置历史数据；"
            "以后可在模拟菜单切换外部通达信目录。"
            if payload.get("include_market_data", True)
            else "本版不包含个股行情。首次使用请通过“模拟 → 选择通达信目录”连接本机通达信行情。"
        )
        QMessageBox.information(
            self,
            "便携版生成完成",
            f"免安装便携版已生成：\n{result.directory}\n\n"
            "把整个文件夹复制到另一台 Windows 电脑，双击“运行.bat”即可使用，"
            "不需要安装 Python、PySide6 或其他依赖。\n"
            "便携包使用干净默认状态：连续复利模式、关闭全部均线、显示两个副图；"
            "不包含续作会话或历史成绩。\n" + usage,
        )
        self._update_status(f"免安装便携版已生成：{result.directory}")

    def import_user_data_package(self) -> bool:
        filename, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择用户数据迁移包",
            str(self._desktop_directory()),
            "用户数据迁移包 (*.zip)",
        )
        if not filename:
            return False
        answer = QMessageBox.question(
            self,
            "恢复用户数据",
            "恢复后将用迁移包中的设置、续作会话和历史成绩替换当前数据。\n"
            "当前数据会先自动备份，恢复完成后软件将关闭，请重新打开。\n\n"
            "是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        timer_was_active = self._persist_timer.isActive()
        self._persist_timer.stop()
        self._migration_restore_pending_restart = True
        try:
            result = import_migration_package(Path(filename), CONFIG_PATH.parent)
        except (OSError, MigrationPackageError) as exc:
            self._migration_restore_pending_restart = False
            if timer_was_active:
                self._schedule_persist()
            QMessageBox.warning(self, "恢复失败", f"迁移包恢复失败，请检查数据及迁移备份：\n{exc}")
            return False
        self._migration_restore_pending_restart = True
        backup_text = str(result.backup_directory) if result.backup_directory else "当前没有旧数据，无需备份"
        QMessageBox.information(
            self,
            "恢复完成",
            "用户数据已恢复，软件现在将关闭，请重新打开。\n\n"
            f"旧数据备份：{backup_text}\n"
            "如果换了电脑或通达信位置，请重新选择一次通达信目录。",
        )
        self.close()
        return True

    def show_local_storage_usage(self) -> None:
        usage = calculate_storage_usage(CONFIG_PATH.parent)
        QMessageBox.information(
            self,
            "本地数据占用",
            f"数据目录：\n{CONFIG_PATH.parent}\n\n"
            f"必须迁移的用户数据：{self._format_storage_size(usage.user_data_bytes)}"
            f"（{usage.user_file_count} 个文件）\n"
            f"可重建行情缓存：{self._format_storage_size(usage.cache_bytes)}"
            f"（{usage.cache_file_count} 个文件）\n"
            f"导入前自动备份：{self._format_storage_size(usage.migration_backup_bytes)}\n"
            f"其他文件：{self._format_storage_size(usage.other_bytes)}\n"
            f"合计：{self._format_storage_size(usage.total_bytes)}\n\n"
            f"复权 K 线缓存每周自动检查，最多保留约 "
            f"{self._format_storage_size(DEFAULT_ADJUSTED_CACHE_LIMIT_BYTES)}；训练记录不会被自动删除。",
        )

    def clear_rebuildable_cache(self) -> bool:
        usage = calculate_storage_usage(CONFIG_PATH.parent)
        answer = QMessageBox.question(
            self,
            "清理可重建复权缓存",
            f"当前可重建缓存共 {self._format_storage_size(usage.cache_bytes)}。\n"
            "清理只删除前复权 K 线缓存，不会删除设置、训练会话和历史成绩。\n"
            "之后首次打开某只股票时会重新生成缓存，短时间内可能稍慢。\n\n"
            "是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        result = clear_adjusted_bars_cache(CONFIG_PATH.parent)
        QMessageBox.information(
            self,
            "清理完成",
            f"已删除 {result.removed_files} 个复权缓存文件，释放 "
            f"{self._format_storage_size(result.removed_bytes)}。",
        )
        self._update_status("可重建复权缓存已清理，用户数据未受影响。")
        return True

    @staticmethod
    def _format_storage_size(value: int) -> str:
        size = float(max(0, value))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} GB"

    def _load_startup_market(self) -> None:
        if _is_offscreen():
            return
        location = resolve_tdx_location(self.tdx_path.text().strip())
        if location is not None:
            previous_root = self.settings.tdx_root
            self._apply_tdx_location(location)
            if previous_root != str(location.root):
                self._save_settings()
        if self.engine is not None and self.training_mode:
            self._request_shanghai_index_update()
            return
        bars = []
        if location is not None:
            # Read a fresh local snapshot before showing the initial chart;
            # whole-market statistics can finish separately in the background.
            try:
                bars = TdxDayReader(location, adjust_type="none").read_daily_bars(SHANGHAI_INDEX_CODE)
            except Exception:
                try:
                    bars = [replace(bar, code=SHANGHAI_INDEX_CODE) for bar in
                            TdxDayReader(location, adjust_type="none").read_daily_bars("sh000001")]
                except Exception:
                    bars = []
        cached = load_index_cache(CONFIG_PATH.parent / "shanghai_index_daily.json")
        bars = (merge_index_bars(bars, cached) if cached and bars and cached[-1].date > bars[-1].date
                else merge_index_bars(cached, bars))
        if bars:
            self._activate_browse_engine(
                bars,
                SHANGHAI_INDEX_NAME,
                f"当前上证行情：{bars[-1].date}，正在尝试获取最新行情；统计单独补齐。{INDEX_BROWSE_GUIDANCE}",
            )
            self._request_public_market_stats_update(bars[-1].date)
        else:
            self._update_status("正在联网获取上证指数行情；也可以先设置通达信目录。")
        self._request_shanghai_index_update()

    def eventFilter(self, watched, event) -> bool:
        if getattr(self, "sector_integration", None) and self.sector_integration.active:
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                if event.key() == Qt.Key.Key_Escape and self._immersive_fullscreen:
                    self._set_immersive_fullscreen(False)
                    return True
                if event.key() == Qt.Key.Key_Tab and event.modifiers() == Qt.KeyboardModifier.NoModifier:
                    self._set_immersive_fullscreen(not self._immersive_fullscreen)
                    return True
                if (
                    event.key() == Qt.Key.Key_F
                    and event.modifiers() == Qt.KeyboardModifier.ControlModifier
                ):
                    self._set_immersive_fullscreen(not self._immersive_fullscreen)
                    return True
            return super().eventFilter(watched, event)
        if (
            hasattr(self, "side_panel_scroll")
            and watched is self.side_panel_scroll
            and event.type() in (QEvent.Type.Move, QEvent.Type.Resize)
        ):
            self._align_top_actions_with_side_panel()
            QTimer.singleShot(0, self._align_top_actions_with_side_panel)
        if event.type() == QEvent.Type.MouseButtonPress:
            if watched is self.round_log.viewport() and event.button() == Qt.MouseButton.LeftButton:
                position = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if self.round_log.itemAt(position) is None:
                    self.round_log.clearSelection()
                    self.round_log.setCurrentItem(None)
                    self.reviewed_round_index = None
            if (
                (self.global_stock_input_active or self.global_date_input_active)
                and isinstance(watched, QWidget)
                and not (self.global_stock_input_active and watched is self.code_input)
                and not (self.global_date_input_active and watched is self.date_input)
                and watched is not self.stock_candidate_list
                and not self.stock_candidate_list.isAncestorOf(watched)
            ):
                self._cancel_global_keyboard_input("已取消未确认的输入，请重新输入后按回车确认。")
            return super().eventFilter(watched, event)
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return super().eventFilter(watched, event)
        if not isinstance(event, QKeyEvent):
            return super().eventFilter(watched, event)
        if not isinstance(watched, QWidget) or (watched is not self and not self.isAncestorOf(watched)):
            return super().eventFilter(watched, event)
        if (
            event.key() == Qt.Key.Key_Tab
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self._set_immersive_fullscreen(not self._immersive_fullscreen)
            return True
        if (
            event.key() == Qt.Key.Key_F
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        ):
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self._set_immersive_fullscreen(not self._immersive_fullscreen)
            return True
        if self._immersive_fullscreen and event.key() == Qt.Key.Key_Escape:
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self._set_immersive_fullscreen(False)
            return True
        if watched is self.code_input and self.stock_candidate_list.isVisible():
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                    self._move_stock_candidate_selection(-1 if event.key() == Qt.Key.Key_Up else 1)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                    self._accept_stock_candidate()
                return True
            if event.key() == Qt.Key.Key_Escape:
                if event.type() == QEvent.Type.KeyPress:
                    self.stock_candidate_list.hide()
                return True
        spinbox_editor = isinstance(watched, QWidget) and isinstance(watched.parentWidget(), QAbstractSpinBox)
        text_entry_active = isinstance(watched, (QLineEdit, QAbstractSpinBox)) or spinbox_editor
        if self._handle_trade_snapshot_shortcut(event, allow_plain_p=not text_entry_active):
            return True
        if text_entry_active:
            return super().eventFilter(watched, event)
        if self._handle_random_switch_shortcut(event):
            return True
        if self._handle_training_keyboard_shortcut(event):
            return True
        if self._is_history_boundary_shortcut(event):
            return True
        if event.key() == Qt.Key.Key_Space:
            if event.isAutoRepeat():
                return True
            if event.type() == QEvent.Type.KeyPress:
                self._begin_index_preview_hold()
            else:
                was_preview_active = self._end_index_preview_hold()
                if was_preview_active:
                    self.last_space_tap_time = 0.0
                else:
                    self._register_space_tap()
            return True
        return self._handle_global_stock_key(event)

    def _handle_random_switch_shortcut(self, event: QKeyEvent) -> bool:
        if self.global_stock_input_active or self.global_date_input_active:
            return False
        blocked = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        if event.modifiers() & blocked or event.key() != Qt.Key.Key_R:
            return False
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat() and self.random_btn.isEnabled():
            self.random_switch_stock()
        return True

    def _handle_trade_snapshot_shortcut(self, event: QKeyEvent, allow_plain_p: bool = True) -> bool:
        if not self.engine or not self.training_mode:
            return False
        modifiers = event.modifiers()
        plain_p = allow_plain_p and event.key() == Qt.Key.Key_P and modifiers == Qt.KeyboardModifier.NoModifier
        ctrl_s = (
            event.key() == Qt.Key.Key_S
            and bool(modifiers & Qt.KeyboardModifier.ControlModifier)
            and not bool(modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier))
        )
        if not (plain_p or ctrl_s):
            return False
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
            self.save_trade_snapshot()
        return True

    def _handle_training_keyboard_shortcut(self, event: QKeyEvent) -> bool:
        if not self.training_mode or not self.engine:
            return False
        if self.global_stock_input_active or self.global_date_input_active:
            return False
        blocked = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        if event.modifiers() & blocked:
            return False
        if event.key() == Qt.Key.Key_Down:
            if event.type() == QEvent.Type.KeyPress:
                self._advance_training_phase()
            return True
        if event.key() not in (Qt.Key.Key_B, Qt.Key.Key_S):
            return False
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
            if not self.test_trade_active and (
                self.pan_offset != 0 or self.viewed_bar_index != self.engine.current_index
            ):
                QMessageBox.information(
                    self,
                    "请返回训练当前K线",
                    "当前正在查看过往行情。\n"
                    "请按 Ctrl+右方向键或 Home 返回训练当前K线后，再使用 B/S 交易。",
                )
            elif event.key() == Qt.Key.Key_B:
                self.buy_at(self.current_node)
            else:
                self.sell_at(self.current_node)
        return True

    def _advance_training_phase(self) -> None:
        if not self.engine or not self.training_mode:
            return
        if self.pan_offset != 0 or self.viewed_bar_index != self.engine.current_index:
            self.pan_to_latest(update_status=False)
        self.advance_playback()

    def _handle_global_stock_key(self, event: QKeyEvent) -> bool:
        blocked_modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        if event.modifiers() & blocked_modifiers:
            return False
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.global_date_input_active:
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self._commit_global_date_input()
            return True
        if self.global_stock_input_active and self.stock_candidate_list.isVisible() and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self._move_stock_candidate_selection(-1 if event.key() == Qt.Key.Key_Up else 1)
            return True
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.global_stock_input_active:
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                if self.stock_candidate_list.isVisible():
                    self._accept_stock_candidate()
                else:
                    self._commit_global_stock_input()
            return True
        if event.key() == Qt.Key.Key_Escape and (self.global_stock_input_active or self.global_date_input_active):
            if event.type() == QEvent.Type.KeyPress:
                self._cancel_global_keyboard_input()
            return True
        if event.key() == Qt.Key.Key_Backspace and self.global_date_input_active:
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self.date_input.setText(self.date_input.text()[:-1])
            return True
        if event.key() == Qt.Key.Key_Backspace and self.global_stock_input_active:
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self.code_input.setText(self.code_input.text()[:-1])
            return True
        text = event.text()
        if not text or not text.isascii() or not text.isalnum():
            return False
        if event.type() == QEvent.Type.KeyRelease or event.isAutoRepeat():
            return True
        if self.global_date_input_active:
            if text.isdigit():
                self.date_input.setText(self.date_input.text() + text)
            return True
        if not self.global_stock_input_active:
            self.global_stock_input_active = True
            self.code_input.clear()
        next_text = self.code_input.text() + text
        if next_text in ("19", "20"):
            self.global_stock_input_active = False
            self.global_date_input_active = True
            if self.engine:
                self.code_input.setText(self.engine.current_bar.code)
            else:
                self.code_input.clear()
            self.date_input.setText(next_text)
        else:
            self.code_input.setText(next_text)
        return True

    def _commit_global_stock_input(self) -> None:
        if not self.global_stock_input_active or not self.code_input.text().strip():
            return
        query = self.code_input.text().strip()
        if self._looks_like_date_query(query):
            self._navigate_to_date_query(query)
            if self.engine:
                self.code_input.setText(self.engine.current_bar.code)
            self._reset_global_stock_input()
            return
        if self.browse_stock_from_input(silent=False):
            self._reset_global_stock_input()
        else:
            self._cancel_global_stock_input()

    def _reset_global_stock_input(self) -> None:
        self.global_stock_input_active = False
        self.stock_candidate_list.hide()

    def _reset_global_date_input(self) -> None:
        self.global_date_input_active = False

    def _cancel_global_keyboard_input(self, message: str = "") -> None:
        if self.global_date_input_active:
            self.date_input.clear()
            self._reset_global_date_input()
        if self.global_stock_input_active:
            self._cancel_global_stock_input()
        if message:
            self._update_status(message)

    def _cancel_global_stock_input(self, message: str = "") -> None:
        if self.engine:
            self.code_input.setText(self.engine.current_bar.code)
        else:
            self.code_input.clear()
        self._reset_global_stock_input()
        if message:
            self._update_status(message)

    def _update_stock_candidates(self, text: str) -> None:
        query = text.strip()
        if not query.isascii() or not query.isalpha():
            self.stock_candidate_list.hide()
            return
        try:
            matches = self.info_reader.find_code_matches(query, self.reader.scan_stock_codes())
        except Exception:
            matches = []
        self.stock_candidate_list.clear()
        for match in matches:
            item = QListWidgetItem(f"{match.name}    {match.code.upper()}")
            item.setData(Qt.ItemDataRole.UserRole, match.code)
            self.stock_candidate_list.addItem(item)
        if not matches:
            self.stock_candidate_list.hide()
            return
        self.stock_candidate_list.setCurrentRow(0)
        point = self.code_input.mapTo(self, QPoint(0, self.code_input.height() + 2))
        row_height = max(28, self.stock_candidate_list.sizeHintForRow(0))
        visible_rows = min(len(matches), 6)
        self.stock_candidate_list.setGeometry(
            point.x(),
            point.y(),
            max(self.code_input.width(), 300),
            visible_rows * row_height + 6,
        )
        self.stock_candidate_list.show()
        self.stock_candidate_list.raise_()

    def _move_stock_candidate_selection(self, offset: int) -> None:
        count = self.stock_candidate_list.count()
        if count == 0:
            return
        current = max(0, self.stock_candidate_list.currentRow())
        self.stock_candidate_list.setCurrentRow((current + offset) % count)
        self.stock_candidate_list.scrollToItem(self.stock_candidate_list.currentItem())

    def _accept_stock_candidate(self, item: QListWidgetItem | None = None) -> None:
        chosen = item or self.stock_candidate_list.currentItem()
        if chosen is None:
            return
        code = chosen.data(Qt.ItemDataRole.UserRole)
        self.stock_candidate_list.hide()
        self.code_input.setText(str(code))
        was_global_input = self.global_stock_input_active
        if self.browse_stock_from_input(silent=False):
            self._reset_global_stock_input()
        elif was_global_input:
            self._cancel_global_stock_input()

    def _browse_or_accept_stock_candidate(self) -> None:
        if self.stock_candidate_list.isVisible():
            self._accept_stock_candidate()
        else:
            self.browse_stock_from_input()

    @staticmethod
    def _looks_like_date_query(query: str) -> bool:
        return query.isdigit() and len(query) in (4, 6, 8) and query[:2] in ("19", "20")

    def _commit_global_date_input(self) -> None:
        query = self.date_input.text().strip()
        self._navigate_to_date_query(query)
        self._reset_global_date_input()

    def _navigate_from_date_input(self) -> None:
        query = self.date_input.text().strip()
        if query:
            self._navigate_to_date_query(query)
            self.kline_widget.setFocus()

    def _navigate_to_date_query(self, query: str) -> bool:
        try:
            if not self.engine:
                raise ValueError("请先打开一只股票，再使用日期定位。")
            normalized = normalize_start_date(query)
            if self.training_mode and not self.test_trade_active and normalized > self.engine.current_bar.date:
                self.pan_to_latest(update_status=False)
                QMessageBox.information(
                    self,
                    "训练模式禁止查看未来行情",
                    f"训练模式不能查看 {query} 对应的未来行情。\n"
                    f"已停留在当前训练K线 {self.engine.current_bar.date}。",
                )
                self._update_status(f"未来行情已隐藏，当前训练截止日期为 {self.engine.current_bar.date}。")
                return False
            available_bars = (
                self.engine.bars
                if self.test_trade_active
                else self.engine.bars[: self.engine.current_index + 1]
            )
            target_index = next(
                (index for index, bar in enumerate(available_bars) if bar.date >= normalized),
                len(available_bars) - 1,
            )
            target_bar = available_bars[target_index]
            self.pan_offset = self.engine.current_index - target_index
            self.viewed_bar_index = target_index
            self._sync_date_input_to_viewed_bar()
            self.kline_widget.selected_bar_date = target_bar.date
            self._refresh()
            self._update_status(f"已定位到 {target_bar.date}（输入 {query}）。模拟交易日没有改变。")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "无法定位日期", str(exc))
            return False

    def _is_history_boundary_shortcut(self, event: QKeyEvent) -> bool:
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        go_latest = event.key() == Qt.Key.Key_Home or (ctrl and event.key() == Qt.Key.Key_Right)
        go_earliest = event.key() == Qt.Key.Key_End or (ctrl and event.key() == Qt.Key.Key_Left)
        if not go_latest and not go_earliest:
            return False
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
            if go_latest:
                self.pan_to_latest()
            else:
                self.pan_to_earliest()
        return True

    def _begin_index_preview_hold(self) -> None:
        if not self._can_use_index_shortcut() or self.index_preview_active:
            return
        if not self.index_preview_timer.isActive():
            self.index_preview_timer.start()

    def _end_index_preview_hold(self) -> bool:
        self.index_preview_timer.stop()
        if not self.index_preview_active:
            return False
        self.index_preview_active = False
        self.kline_widget.suppress_user_annotations = False
        self._refresh()
        return True

    def _register_space_tap(self) -> None:
        if not self._can_use_index_shortcut():
            self.last_space_tap_time = 0.0
            return
        now = time.monotonic()
        if self.last_space_tap_time and now - self.last_space_tap_time <= DOUBLE_SPACE_INTERVAL_SECONDS:
            self.last_space_tap_time = 0.0
            if self.index_overlay_active:
                self._disable_index_overlay()
            else:
                self._enable_index_overlay()
            return
        self.last_space_tap_time = now

    def _enable_index_overlay(self) -> None:
        if not self._can_use_index_shortcut():
            return
        self.index_overlay_active = True
        if not self._sync_index_overlay():
            self.index_overlay_active = False
            self._sync_menu_actions()
            return
        self.day_info.setText(self.day_info.text() + "  |  上证指数灰色叠加中（再次双击空格关闭）")
        self._sync_menu_actions()

    def _sync_index_overlay(self) -> bool:
        if not self.index_overlay_active or not self._can_use_index_shortcut():
            return False
        bars = self._index_bars_for_preview()
        if not bars:
            return False
        displayed_index = self._displayed_bar_index()
        simulation_date = self.engine.bars[displayed_index].date
        reveal_current_full = (
            True
            if self.test_trade_active
            else displayed_index < self.engine.current_index or self.reveal_current_full
        )
        overlay_bars = [bar for bar in bars if bar.date <= simulation_date]
        if not overlay_bars:
            return False
        self.kline_widget.set_index_overlay(overlay_bars, simulation_date, reveal_current_full)
        return True

    def _disable_index_overlay(self) -> None:
        if not self.index_overlay_active:
            self._sync_menu_actions()
            return
        self.index_overlay_active = False
        self.kline_widget.clear_index_overlay()
        self._refresh()
        self._sync_menu_actions()

    def _show_held_index_preview(self) -> None:
        if not self._can_use_index_shortcut():
            return
        bars = self._index_bars_for_preview()
        if not bars:
            return
        displayed_index = self._displayed_bar_index()
        preview_date = self.engine.bars[displayed_index].date
        preview_reveal_full = (
            True
            if self.test_trade_active
            else displayed_index < self.engine.current_index or self.reveal_current_full
        )
        matching_indices = [index for index, bar in enumerate(bars) if bar.date <= preview_date]
        if not matching_indices:
            return
        if self.index_overlay_active:
            self.kline_widget.clear_index_overlay()
        current_index = matching_indices[-1]
        bar = bars[current_index]
        display_bars = bars
        if not preview_reveal_full:
            display_bars = list(bars)
            display_bars[current_index] = replace(
                bar,
                high=bar.open,
                low=bar.open,
                close=bar.open,
                amount=0.0,
                volume=0,
            )
        self.index_preview_active = True
        self.kline_widget.suppress_user_annotations = True
        index_by_date = {bar.date: bar for bar in display_bars}
        preview_bars = [
            index_by_date[stock_bar.date]
            for stock_bar in self.kline_widget.bars
            if stock_bar.date in index_by_date
        ]
        self.kline_widget.set_data(
            all_bars=display_bars,
            visible_bars=preview_bars,
            trades=[],
            current_index=current_index,
            pan_offset=0,
            window_size=self.chart_window_size,
            reveal_current_full=preview_reveal_full,
            average_cost_price=None,
            completed_trade_ranges=[],
        )
        self.title_label.setText(
            self._format_index_title_html(
                bar,
                bars,
                current_index,
                preview_reveal_full,
                "松开空格返回训练股票",
            )
        )
        self._refresh_index_market_metrics(display_bars, current_index, preview_reveal_full)
        if preview_reveal_full:
            self.day_info.setText(f"上证指数：开 {bar.open:.2f}  高 {bar.high:.2f}  低 {bar.low:.2f}  收 {bar.close:.2f}")
        else:
            self.day_info.setText(f"上证指数：开 {bar.open:.2f}  当前训练处于开盘阶段，收盘K线未揭示")

    def _index_bars_for_preview(self):
        if self.shanghai_index_bars:
            return self.shanghai_index_bars
        try:
            bars = self.reader.read_daily_bars(SHANGHAI_INDEX_CODE)
        except Exception:
            bars = load_index_cache(CONFIG_PATH.parent / "shanghai_index_daily.json")
        self.shanghai_index_bars = bars
        return bars

    def _can_use_index_shortcut(self) -> bool:
        return bool(self.engine and self.engine.current_bar.code != SHANGHAI_INDEX_CODE)

    def browse_stock_from_input(self, silent: bool = False) -> bool:
        try:
            query = self.code_input.text().strip()
            if not query:
                raise ValueError("请输入股票代码、拼音首字母，或上证指数别名。")
            if is_shanghai_index_query(query):
                tdx_location = resolve_tdx_location(self.tdx_path.text().strip())
                bars = self.shanghai_index_bars or load_index_cache(
                    CONFIG_PATH.parent / "shanghai_index_daily.json"
                )
                if not bars and tdx_location is not None:
                    self._apply_tdx_location(tdx_location)
                    try:
                        bars = TdxDayReader(tdx_location, adjust_type="none").read_daily_bars(SHANGHAI_INDEX_CODE)
                    except TdxDataError:
                        bars = []
                if not bars:
                    self._request_shanghai_index_update()
                    self._update_status("正在获取最新上证行情，统计将在有数据后单独补齐。")
                    return True
                self._activate_browse_engine(
                    bars,
                    SHANGHAI_INDEX_NAME,
                    f"已打开上证指数完整历史行情。{INDEX_BROWSE_GUIDANCE}",
                )
                self.using_sample_kline = tdx_location is None
                self._request_shanghai_index_update()
                return True
            location = self._resolve_tdx_location_or_raise(self.tdx_path.text().strip())
            self._apply_tdx_location(location)
            code = self._resolve_market_code_query(query)
            bars = self.reader.read_daily_bars(code)
            if not bars:
                raise ValueError("这只股票没有可用的日K数据。")
            stock_name = self.info_reader.name_for(code)
            self._activate_browse_engine(
                bars,
                stock_name,
                "行情浏览模式：当前显示全部历史数据；点击黄色“开启随机换股”后进入随机训练并隐藏未来K线。",
            )
            return True
        except Exception as exc:
            if silent:
                self._update_status(f"暂未识别“{self.code_input.text().strip()}”，可以继续输入或按退格修改。")
            else:
                QMessageBox.warning(self, "无法打开行情", str(exc))
            return False

    def _resolve_market_code_query(self, query: str) -> str:
        if is_shanghai_index_query(query):
            return SHANGHAI_INDEX_CODE
        return self.info_reader.resolve_code_query(query, self.reader.scan_stock_codes())

    def _sync_start_button_label(self) -> None:
        is_index = bool(self.engine and self.engine.current_bar.code == SHANGHAI_INDEX_CODE)
        self.start_btn.setText("开启模拟交易")
        self.start_btn.setVisible(is_index)
        self.start_btn.setEnabled(is_index)
        self.start_btn.setToolTip("从上证指数浏览界面进入随机股票模拟训练。")
        self.random_btn.setVisible(not is_index)
        self.random_btn.setEnabled(not is_index and not self._random_switch_locked)
        if hasattr(self, "simulation_start_action"):
            self.simulation_start_action.setText(self.start_btn.text())
            self.simulation_start_action.setEnabled(is_index)
            self.simulation_start_action.setVisible(is_index)
            self.simulation_random_action.setEnabled(self.random_btn.isEnabled())
            self.simulation_random_action.setVisible(not is_index)
        if not bool(self.quick_actions_panel.property("sideDocked")):
            QTimer.singleShot(0, self._align_top_actions_with_side_panel)

    def _activate_browse_engine(self, bars, stock_name: str, status: str, view_index: int | None = None) -> None:
        if not bars:
            return
        if self.test_trade_active:
            self.exit_test_trade_mode(update_status=False)
        self._capture_return_context_if_trading()
        initial_cash = self._parse_money_text(self.cash_input.text()) or self.settings.initial_cash
        start_index = len(bars) - 1 if view_index is None else max(0, min(view_index, len(bars) - 1))
        self.engine = DailySimulationEngine(
            bars=bars,
            initial_cash=initial_cash,
            slot_count=self.settings.slot_count,
            commission_rate=self.settings.commission_rate,
            stamp_tax_rate=self.settings.stamp_tax_rate,
            min_commission=self.settings.min_commission,
            start_index=start_index,
        )
        self.engine.start()
        if self.engine.current_bar.code == SHANGHAI_INDEX_CODE:
            self.shanghai_index_bars = list(bars)
        self.training_mode = False
        self.trade_started = False
        self.reviewed_round_index = None
        self.last_space_tap_time = 0.0
        if self.engine.current_bar.code == SHANGHAI_INDEX_CODE:
            self.index_overlay_active = False
            self.kline_widget.clear_index_overlay()
        self.index_preview_timer.stop()
        self.index_preview_active = False
        self.kline_widget.suppress_user_annotations = False
        self.using_sample_kline = False
        self.browsing_stock_name = stock_name
        self.code_input.setText(self.engine.current_bar.code)
        self.pan_offset = 0
        self.viewed_bar_index = self.engine.current_index
        self._sync_date_input_to_viewed_bar()
        self.current_node = TradeNode.CLOSE
        self.reveal_current_full = True
        self._advance_button_show_close = False
        self._reset_first_buy_cycle()
        self._frozen_position_metrics = None
        self.completed_trade_ranges = []
        self.equity_curve = []
        self.equity_points = []
        self.round_equity_points = []
        self._last_equity_record_key = None
        self._reset_drawdown_overlay()
        self.kline_widget.clear_user_annotations()
        self._refresh()
        self._update_status(status)
        self.kline_widget.setFocus()
        self._sync_start_button_label()
        self._sync_round_log_visibility()
        self._schedule_random_prefetch()

    def start_test_trade_from_bar(self, date: str) -> bool:
        """Start a disposable trade session from a browsed stock candle."""
        if (
            not self.engine
            or (self.training_mode and not self.test_trade_active)
            or self.engine.current_bar.code == SHANGHAI_INDEX_CODE
        ):
            return False
        if self.test_trade_active and (
            self.trade_started
            or any(trade.accepted and trade.side == "buy" for trade in self.engine.trades)
            or any(not slot.is_empty for slot in self.engine.slots)
            or self.completed_trade_ranges
        ):
            self._update_status("已经买入过，不能通过右键双击切换测试起点。")
            return False
        selected_index = self._index_for_date(self.engine.bars, date)
        if selected_index is None:
            return False
        initial_cash = self._parse_money_text(self.cash_input.text())
        if initial_cash is None or initial_cash <= 0:
            self._update_status("测试交易未启动：初始本金必须是大于 0 的数字。")
            return False

        browse_context = self._test_trade_browse_context if self.test_trade_active else None
        if browse_context is None:
            browse_context = self._capture_trading_context()
            browse_context.update(
                {
                    "formal_return_context": self._return_to_trading_context,
                    "reviewed_round_index": self.reviewed_round_index,
                    "selected_bar_date": self.kline_widget.selected_bar_date,
                }
            )
        previous_anchor = self._displayed_bar_index()
        anchor, future_slots = test_window_anchor(
            selected_index,
            previous_anchor,
            len(self.engine.bars),
            self.chart_window_size,
        )
        test_engine = DailySimulationEngine(
            bars=list(self.engine.bars),
            initial_cash=initial_cash,
            slot_count=self.settings.slot_count,
            commission_rate=self.settings.commission_rate,
            stamp_tax_rate=self.settings.stamp_tax_rate,
            min_commission=self.settings.min_commission,
            start_index=selected_index,
        )
        test_engine.start()

        self._test_trade_browse_context = browse_context
        self._test_trade_start_index = selected_index
        self._test_trade_future_slots = future_slots
        self.test_trade_active = True
        self.engine = test_engine
        self.training_mode = True
        self.trade_started = False
        self.current_node = TradeNode.OPEN
        self.reveal_current_full = False
        self._advance_button_show_close = True
        self.pan_offset = 0
        self.viewed_bar_index = anchor
        self.reviewed_round_index = None
        self.account_initial_cash = initial_cash
        self.account_baseline_locked = True
        self.round_start_cash = initial_cash
        self.round_start_date = self.engine.current_bar.date
        self.round_start_node = TradeNode.OPEN
        self.round_records = []
        self.completed_trade_ranges = []
        self.equity_curve = []
        self.equity_points = []
        self.round_equity_points = []
        self.cumulative_holding_days_base = 0
        self._last_equity_record_key = None
        self._performance_summary_key = None
        self._frozen_position_metrics = None
        self.engine_epoch += 1
        self._reset_first_buy_cycle()
        self._reset_drawdown_overlay()
        if self.browsing_stock_name:
            self._prefetched_stock_names[self.engine.current_bar.code] = self.browsing_stock_name
        self.code_input.setText(self.engine.current_bar.code)
        self._sync_date_input_to_viewed_bar()
        self.kline_widget.selected_bar_date = self.engine.current_bar.date
        self._refresh()
        self._sync_round_log_visibility()
        self._update_status(
            f"测试交易模式：从 {self.engine.current_bar.date} 开盘开始；后续行情保持可见，测试账户不会保存。"
        )
        self.kline_widget.setFocus()
        return True

    def exit_test_trade_mode(self, update_status: bool = True) -> bool:
        """Discard the transient account and restore the exact browse context."""
        context = self._test_trade_browse_context
        if not self.test_trade_active or not context:
            return False

        self.engine = context["engine"]
        self.training_mode = context["training_mode"]
        self.trade_started = context["trade_started"]
        self.current_node = context["current_node"]
        self.reveal_current_full = context["reveal_current_full"]
        self._advance_button_show_close = context["advance_button_show_close"]
        self.first_buy_price = context["first_buy_price"]
        self.first_buy_index = context["first_buy_index"]
        self.first_buy_node = context["first_buy_node"]
        self.active_cycle_start_cash = context["active_cycle_start_cash"]
        self._frozen_position_metrics = dict(context.get("frozen_position_metrics") or {}) or None
        self.completed_trade_ranges = list(context["completed_trade_ranges"])
        self.equity_curve = list(context["equity_curve"])
        self.equity_points = list(context.get("equity_points", []))
        self.round_equity_points = list(context.get("round_equity_points", []))
        self.cumulative_holding_days_base = context["cumulative_holding_days_base"]
        self.round_records = list(context["round_records"])
        self.round_start_cash = context["round_start_cash"]
        self.round_start_date = context["round_start_date"]
        self.round_start_node = context.get("round_start_node", TradeNode.OPEN)
        self.account_initial_cash = context["account_initial_cash"]
        self.account_baseline_locked = context["account_baseline_locked"]
        self.engine_epoch = context["engine_epoch"]
        self.using_sample_kline = context["using_sample_kline"]
        self.pan_offset = context["pan_offset"]
        self.viewed_bar_index = context["viewed_bar_index"]
        self.browsing_stock_name = context["browsing_stock_name"]
        self.reviewed_round_index = context.get("reviewed_round_index")
        self._return_to_trading_context = context.get("formal_return_context")
        self.kline_widget.selected_bar_date = context.get("selected_bar_date", "")
        self.test_trade_active = False
        self._test_trade_browse_context = None
        self._test_trade_start_index = None
        self._test_trade_future_slots = 0
        self._last_equity_record_key = None
        self._performance_summary_key = None
        self.code_input.setText(self.engine.current_bar.code)
        self._sync_date_input_to_viewed_bar()
        self._refresh()
        self._sync_round_log_visibility()
        self._sync_return_button_state()
        if update_status:
            self._update_status("已退出测试交易模式，恢复进入测试前的行情浏览位置。")
        self.kline_widget.setFocus()
        return True

    def _request_shanghai_index_update(self) -> None:
        if self._migration_restore_pending_restart:
            return
        if self._market_sync_location is not None:
            self._check_local_market()
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            return
        if self.index_update_worker is not None:
            return
        MainWindow._index_update_requested = True
        history = list(self.shanghai_index_bars)
        self.index_update_worker = IndexUpdateWorker(history, self.index_update_completed.emit)
        QThreadPool.globalInstance().start(self.index_update_worker)

    def _finish_shanghai_index_update(self, bars) -> None:
        try:
            if self._migration_restore_pending_restart:
                return
            if not bars:
                self._update_status("暂未取得更新行情，保留当前可用数据；可检查网络或更新通达信后重试。")
                return
            if self.shanghai_index_bars and bars[-1].date < self.shanghai_index_bars[-1].date:
                return
            bars = merge_index_bars(self.shanghai_index_bars, bars)
            changed = bars != self.shanghai_index_bars
            self.shanghai_index_bars = bars
            save_index_cache(CONFIG_PATH.parent / "shanghai_index_daily.json", bars)
            if changed and not self.index_preview_active and (self.engine is None or (
                not self.training_mode and self.engine.current_bar.code == SHANGHAI_INDEX_CODE
            )):
                self._activate_browse_engine(
                    bars,
                    SHANGHAI_INDEX_NAME,
                    f"上证指数已自动更新至 {bars[-1].date}。{INDEX_BROWSE_GUIDANCE}",
                )
            self._request_public_market_stats_update(bars[-1].date)
            self._refresh_synced_market_view()
        except (OSError, ValueError):
            return
        finally:
            self.index_update_worker = None
            MainWindow._index_update_requested = False

    def _check_local_market(self) -> None:
        if self._migration_restore_pending_restart:
            return
        location = self._market_sync_location
        if location is not None:
            self._request_market_stats_update(location)

    def _request_market_stats_update(self, location: TdxDataLocation) -> None:
        if self._migration_restore_pending_restart:
            return
        self._market_sync_location = location
        root_text = str(location.root)
        cache_path = CONFIG_PATH.parent / "market_stats_daily.json"
        root_changed = root_text != self.market_stats_root
        previous_status = self.market_stats_status
        if root_changed:
            self.market_stats_root = root_text
            self._market_sync_fingerprint = None
            self.market_stats_by_date = load_market_stats_cache(cache_path, location.root)
        if self.market_stats_worker is not None:
            if self.market_stats_requested_root != root_text:
                self.market_stats_pending_location = location
            return
        self.market_stats_requested_root = root_text
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            self.market_stats_status = "统计中…" if not self.market_stats_by_date else ""
            return
        if not self.market_stats_by_date and self._market_sync_fingerprint is None:
            self.market_stats_status = "正在读取通达信统计…"
        if root_changed or previous_status != self.market_stats_status:
            self._refresh_synced_market_view()
        previous = self._market_sync_fingerprint
        if self._market_sync_memory_shape != (len(self.market_stats_by_date), len(self.shanghai_index_bars)):
            previous = None
        self.market_stats_worker = MarketStatsWorker(cache_path, location, previous, self.market_stats_completed.emit)
        QThreadPool.globalInstance().start(self.market_stats_worker)

    def _finish_market_stats_update(self, payload) -> None:
        try:
            root_text, result, error = payload
            if root_text != self.market_stats_root or self._migration_restore_pending_restart:
                return
            if isinstance(result, LocalMarketUpdate):
                self._market_sync_fingerprint = result.fingerprint
                self.market_stats_by_date = result.stats.stats
                self.market_stats_status = "" if result.stats.file_count else "通达信目录没有股票日K数据"
                if result.bars:
                    bars = (merge_index_bars(result.bars, self.shanghai_index_bars)
                            if self.shanghai_index_bars and self.shanghai_index_bars[-1].date > result.bars[-1].date
                            else merge_index_bars(self.shanghai_index_bars, result.bars))
                    changed = self.shanghai_index_bars != bars
                    self.shanghai_index_bars = bars
                    if bars != result.bars:
                        save_index_cache(CONFIG_PATH.parent / "shanghai_index_daily.json", bars)
                    if changed and (
                        self.engine is None or (not self.training_mode
                        and self.engine.current_bar.code == SHANGHAI_INDEX_CODE)
                    ) and not self.index_preview_active:
                        self._activate_browse_engine(bars, SHANGHAI_INDEX_NAME,
                            f"当前上证行情已更新至 {bars[-1].date}。{INDEX_BROWSE_GUIDANCE}")
                self._market_sync_memory_shape = (len(self.market_stats_by_date), len(self.shanghai_index_bars))
                if result.stats.stats:
                    self._update_status(f"通达信统计已更新至 {max(result.stats.stats)}，共处理 {result.stats.file_count} 个股票文件。")
                else:
                    self._update_status(self.market_stats_status)
            elif error:
                self.market_stats_status = f"通达信统计待重试：{error}"
                self._update_status(f"通达信统计失败，将自动重试：{error}")
            else:
                return
            self._refresh_synced_market_view()
        finally:
            self.market_stats_worker = None
            pending = self.market_stats_pending_location
            self.market_stats_pending_location = None
            if pending is not None:
                self._request_market_stats_update(pending)

    def _refresh_synced_market_view(self) -> None:
        """Publish market results without depending on navigation or account refresh."""
        if not self.engine:
            return
        if self.index_preview_active:
            self._show_held_index_preview()
        elif self.engine.current_bar.code == SHANGHAI_INDEX_CODE:
            index = self._displayed_bar_index()
            reveal = (self.test_trade_active or index < self.engine.current_index
                      or self.reveal_current_full)
            self._refresh_index_market_metrics(self.engine.bars, index, reveal)
        elif self.index_overlay_active:
            self._sync_index_overlay()
        else:
            return
        # Request painting once when new results arrive, including when the
        # mouse and chart remain stationary. Unchanged checks never get here.
        for label in self.index_market_labels.values():
            label.update()
        self.kline_widget.update()

    def _request_public_market_stats_update(self, target_date: str) -> None:
        # Statistics are produced only from a directory selected by this user.
        # Retain this entry point for callers; online index updates stay independent.
        return

    def _finish_public_market_stats_update(self, payload) -> None:
        # Ignore any obsolete online-statistics result after changing this policy.
        self.public_market_stats_worker = None

    def _refresh_market_source_title(self) -> None:
        root = Path(self.settings.tdx_root) if self.settings.tdx_root else None
        if root is not None and root.resolve() == bundled_market_directory().resolve():
            latest = "未知"
            try:
                manifest = json.loads((root / "snapshot.json").read_text(encoding="utf-8"))
                latest = str(manifest.get("latest_date", "未知"))
            except (OSError, ValueError, AttributeError):
                pass  # The data remains usable if its descriptive manifest is absent.
            self.setWindowTitle(f"{APP_NAME} — 内置历史数据（最晚 {latest}，各股日期可能不同）")
        else:
            self.setWindowTitle(APP_NAME)

    def use_bundled_market(self) -> None:
        location = resolve_tdx_location(bundled_market_directory())
        if location is None:
            QMessageBox.warning(self, "内置数据不可用", "未找到内置日K数据，请恢复完整便携文件夹。")
            return
        self._apply_tdx_location(location)
        self._save_settings()
        self._update_status("已切回内置历史数据，个股行情不会自动更新。")
        self._request_shanghai_index_update()

    def choose_tdx_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择通达信安装目录", self.tdx_path.text())
        if path:
            location = resolve_tdx_location(path)
            self.using_sample_kline = False
            if location is None:
                self.tdx_path.setText(path)
                self.settings.tdx_root = path
                self._save_settings()
                self.adjust_provider = None
                self.reader = TdxDayReader(
                    path,
                    adjust_provider=None,
                    adjust_type=self.settings.adjust_type,
                    adjust_cache_dir=CONFIG_PATH.parent / "adjusted_bars_cache",
                )
                self.info_reader = StockInfoReader(path)
                self._reset_random_prefetch()
                self.market_stats_by_date = {}
                self.market_stats_root = ""
                self._market_sync_location = None
                self._market_sync_fingerprint = None
                self.market_stats_requested_root = ""
                self.market_stats_status = "" if self.market_stats_by_date else "市场统计待更新"
                self._refresh_sample_kline_button_state()
                self._update_status("已记录目录，但没有检测到日K数据。请确认已下载日线数据，或选择包含 .day 文件的目录。")
                self._request_shanghai_index_update()
                return
            self._apply_tdx_location(location)
            self._save_settings()
            note = "已自动纠正到通达信根目录" if str(location.root) != path else "已设置通达信目录"
            self._update_status(f"{note}：{location.root}")
            self._request_shanghai_index_update()

    def _current_stock_name(self, code: str) -> str:
        if self.using_sample_kline:
            return SAMPLE_KLINE_NAME
        cached = self._prefetched_stock_names.get(code)
        if cached:
            return cached
        return self.info_reader.name_for(code) or code

    def _load_stock_bars(self, code: str, source: str | None = None) -> tuple[list, str]:
        """Load a stock's daily bars and display name by code and data source."""
        prefer_sample = self.using_sample_kline if source is None else (source == "sample")
        if prefer_sample:
            try:
                return load_sample_bars(code), SAMPLE_KLINE_NAME
            except ValueError:
                pass
        bars = self.reader.read_daily_bars(code)
        name = self._prefetched_stock_names.get(code) or self.info_reader.name_for(code) or code
        return bars, name

    @staticmethod
    def _index_for_date(bars, date: str, fallback_index: int | None = None) -> int | None:
        if not bars:
            return None
        if date:
            for index, bar in enumerate(bars):
                if bar.date >= date:
                    return index
        if fallback_index is not None:
            return max(0, min(fallback_index, len(bars) - 1))
        return None

    def _archive_round(self, mode: str | None = None) -> None:
        if self.test_trade_active or not self.engine or not self.engine.trades:
            return
        index = len(self.round_records) + 1
        record_mode = mode or ("continuous" if self.continuous_compound_mode else "independent")
        self.round_records.append(
            replace(self._current_performance_record(index, record_mode), status="completed")
        )

    def _archive_ordinary_performance(self) -> None:
        if (
            not self.engine
            or self.test_trade_active
            or not self.training_mode
            or not self.trade_started
            or not self.engine.trades
        ):
            return
        record = self._current_performance_record(
            len(self.ordinary_performance_records) + 1,
            "ordinary",
        )
        self.ordinary_performance_records.append(record)
        save_performance_history(self.ordinary_performance_records)

    def _current_performance_record(self, index: int, mode: str) -> RoundRecord:
        if not self.engine:
            raise RuntimeError("performance record requires an active engine")
        code = self.engine.current_bar.code
        name = self._current_stock_name(code)
        start_cash = float(self.round_start_cash or self.engine.initial_cash)
        snapshot = self.engine.snapshot(self.current_node)
        accepted = [trade for trade in self.engine.trades if trade.accepted and trade.side in {"buy", "sell"}]
        first_trade = accepted[0] if accepted else None
        start_date = first_trade.date if first_trade else self.round_start_date
        start_node = first_trade.node if first_trade else self.round_start_node
        segments = build_trade_segments(list(self.engine.trades), list(self.engine.bars), start_cash)
        return RoundRecord(
            index=index,
            code=code,
            name=name,
            profit=round(snapshot.total_asset - start_cash, 2),
            start_date=start_date,
            end_date=self.engine.current_bar.date,
            source="sample" if self.using_sample_kline else "tdx",
            trades=list(self.engine.trades),
            ranges=[tuple(item) for item in self.completed_trade_ranges],
            start_cash=round(start_cash, 2),
            end_asset=round(snapshot.total_asset, 2),
            start_node=start_node,
            end_node=self.current_node,
            equity_points=list(self.round_equity_points),
            segments=segments,
            mode=mode,
            status="active" if self._has_position() else "completed",
        )

    def _build_continuation_engine(self, after_date: str) -> tuple[DailySimulationEngine, str]:
        exclude_code = self.engine.current_bar.code if self.engine else None
        if self.using_sample_kline:
            return create_continued_sample_engine(
                after_date=after_date,
                account_initial_cash=self.account_initial_cash,
                slot_count=self.settings.slot_count,
                commission_rate=self.settings.commission_rate,
                stamp_tax_rate=self.settings.stamp_tax_rate,
                min_commission=self.settings.min_commission,
                exclude_code=exclude_code,
            )
        return create_continued_engine(
            reader=self.reader,
            after_date=after_date,
            account_initial_cash=self.account_initial_cash,
            slot_count=self.settings.slot_count,
            commission_rate=self.settings.commission_rate,
            stamp_tax_rate=self.settings.stamp_tax_rate,
            min_commission=self.settings.min_commission,
            exclude_code=exclude_code,
            min_forward_bars=self._random_training_forward_bars(),
            allowed_codes=self.training_allowed_codes(),
        )

    def _switch_to_continued_stock(self) -> None:
        if not self.engine or not self.training_mode or not self.trade_started:
            return
        if self._has_position():
            self._update_status("连续复利模式下换股需先清仓，资金会保留到下一只股票。")
            QMessageBox.information(
                self,
                "请先清仓",
                "当前还有持仓。请先卖出清仓，再点击“开启随机换股”进入下一只股票。\n"
                "账户资金和轮次记录会延续，不会回到初始本金。",
            )
            return
        after_date = self.engine.current_bar.date
        key = self._current_continuation_prefetch_key()
        if key is not None:
            if self._consume_continuation_prefetch(key):
                return
            if not _is_offscreen():
                self._continuation_switch_pending = True
                self._schedule_continuation_prefetch()
                self._update_status(f"正在后台准备 {after_date} 之后的下一只股票…")
                return
        # Headless tests and environments without a valid prefetch source keep
        # the original synchronous fallback.
        carried_cash = self.engine.cash
        try:
            new_engine, code = self._build_continuation_engine(after_date)
        except Exception as exc:
            self._update_status(f"无法换股续作：{exc}")
            return
        self._activate_continuation_engine(new_engine, code, self._current_stock_name(code), carried_cash)

    def random_switch_stock(self) -> None:
        if self._random_switch_locked or (
            self.engine and self.engine.current_bar.code == SHANGHAI_INDEX_CODE
        ):
            return
        self._lock_random_switch()
        try:
            exited_test_trade = self.test_trade_active
            if exited_test_trade:
                self.exit_test_trade_mode(update_status=False)
            if self._return_to_trading_context is not None:
                return_engine = self._return_to_trading_context.get("engine")
                return_has_position = bool(
                    return_engine
                    and any(not slot.is_empty for slot in return_engine.slots)
                )
                if return_engine is None or return_has_position:
                    if exited_test_trade and return_engine is not None:
                        self._return_to_trading(update_status=False)
                        self._update_status(
                            "已退出测试交易模式并回到正在交易；正式账户仍有持仓，不能随机换股。"
                        )
                        return
                    self._update_status("当前交易仍有持仓，请先回到正在交易并清仓，再换股。")
                    QMessageBox.information(
                        self,
                        "请先回到正在交易",
                        "当前交易仍有持仓。请先点击“回到正在交易”并清仓，再进行换股。",
                    )
                    return
                # A preparation session or an already-flat session needs no
                # extra round trip through the UI. Restore its bookkeeping in
                # memory, then continue this same click as a normal switch.
                self._return_to_trading()
            if not self.using_sample_kline and self.settings.adjust_type != "qfq":
                self._set_adjust_type("qfq")
            if (
                self.continuous_compound_mode
                and self.engine
                and self.training_mode
                and self.trade_started
            ):
                self._switch_to_continued_stock()
                return
            if (
                self.training_mode_kind == TRAINING_MODE_INDEPENDENT
                and self.engine
                and self.training_mode
            ):
                if self._block_resetting_mode_switch_if_holding("独立训练模式"):
                    return
                # Archive only when the next engine is successfully activated.
                # This avoids losing or duplicating the current practice when a
                # random-stock load fails and the user retries.
                self._independent_switch_pending = True
            if (
                self.training_mode_kind == TRAINING_MODE_SINGLE
                and self.engine
                and self.training_mode
            ):
                if self._block_resetting_mode_switch_if_holding("单吊模式"):
                    return
                self._single_switch_pending = True
            if self.using_sample_kline:
                self.date_input.clear()
                self._start_sample_kline(training=True, confirm_reset=False)
                return
            self.code_input.clear()
            self.date_input.clear()
            if not _is_offscreen() and self._random_prefetch_root:
                if self._consume_random_prefetch():
                    return
                self._random_switch_pending = True
                self._schedule_random_prefetch()
                self._update_status("正在后台准备下一只随机股票…")
                return
            self.start_simulation(force_random_stock=True, confirm_reset=False)
        finally:
            self.kline_widget.setFocus()
            QTimer.singleShot(RANDOM_SWITCH_COOLDOWN_MS, self._release_random_switch_lock)

    def _block_resetting_mode_switch_if_holding(self, mode_name: str) -> bool:
        if not self._has_position():
            return False
        self._independent_switch_pending = False
        self._single_switch_pending = False
        self._update_status(f"{mode_name}下换股需先清仓。")
        QMessageBox.information(
            self,
            "请先清仓",
            "当前还有持仓。请先卖出全部持仓，再点击“开启随机换股”。\n"
            "清仓后，本轮买卖记录和盈亏区间会被完整保存。",
        )
        return True

    def _lock_random_switch(self) -> None:
        self._random_switch_locked = True
        self.random_btn.setEnabled(False)
        if hasattr(self, "simulation_random_action"):
            self.simulation_random_action.setEnabled(False)

    def _release_random_switch_lock(self) -> None:
        self._random_switch_locked = False
        is_index = bool(self.engine and self.engine.current_bar.code == SHANGHAI_INDEX_CODE)
        self.random_btn.setEnabled(not is_index)
        if hasattr(self, "simulation_random_action"):
            self.simulation_random_action.setEnabled(not is_index)

    def _build_prepared_engine(
        self,
        bars: list[DailyBar],
        start_index: int,
        initial_cash: float,
    ) -> DailySimulationEngine:
        return DailySimulationEngine(
            bars=bars,
            initial_cash=initial_cash,
            slot_count=self.settings.slot_count,
            commission_rate=self.settings.commission_rate,
            stamp_tax_rate=self.settings.stamp_tax_rate,
            min_commission=self.settings.min_commission,
            start_index=start_index,
        )

    def _consume_random_prefetch(self) -> bool:
        while self._random_prefetch_queue:
            variants, start_index, code, name = self._random_prefetch_queue.pop(0)
            if self.engine and code == self.engine.current_bar.code and self._random_prefetch_queue:
                continue
            initial_cash = self._parse_money_text(self.cash_input.text())
            if initial_cash is None or initial_cash <= 0:
                self._update_status("初始本金必须是大于 0 的数字。")
                return True
            self.settings.initial_cash = initial_cash
            self.settings.show_stock_identity = self.identity_toggle.isChecked()
            self._prefetched_stock_names[code] = name
            self._prefetched_bar_variants[code] = variants
            self._random_switch_pending = False
            bars = variants.get("qfq") or variants.get("none")
            if not bars:
                continue
            self._activate_engine(
                self._build_prepared_engine(bars, start_index, initial_cash),
                "训练准备：行情按开盘、收盘顺序推进；第一笔可在开盘或尾盘买入。",
                awaiting_first_buy=True,
            )
            self._schedule_random_prefetch()
            return True
        return False

    def _activate_continuation_engine(
        self,
        new_engine: DailySimulationEngine,
        code: str,
        name: str,
        carried_cash: float,
    ) -> None:
        # Archive only after the next stock is ready. Otherwise a failed load
        # followed by a retry would duplicate the just-finished round.
        self._archive_round()
        self._prefetched_stock_names[code] = name
        self.cumulative_holding_days_base = self._cumulative_holding_days()
        self._continuation_switch_pending = False
        self._activate_engine(
            new_engine,
            f"已保留资金 {carried_cash:,.2f} 元，从 {new_engine.current_bar.date} 续作 {code}{name}。",
            awaiting_first_buy=False,
            continuation=True,
            carried_cash=carried_cash,
        )

    def _current_continuation_prefetch_key(self) -> tuple[str, str, str, str, int] | None:
        if (
            not self.engine
            or not self.continuous_compound_mode
            or not self.training_mode
            or not self.trade_started
            or self.using_sample_kline
            or self._has_position()
            or not self._random_prefetch_root
        ):
            return None
        return (
            self._random_prefetch_root,
            "qfq",
            self.engine.current_bar.date,
            self.engine.current_bar.code,
            self._random_training_forward_bars(),
        )

    def _consume_continuation_prefetch(self, key: tuple[str, str, str, str, int]) -> bool:
        candidate = self._continuation_prefetch_candidate
        if candidate is None or candidate[0] != key or not self.engine:
            return False
        _candidate_key, variants, start_index, code, name = candidate
        self._continuation_prefetch_candidate = None
        carried_cash = self.engine.cash
        initial_cash = float(self.account_initial_cash or self.engine.initial_cash)
        self._prefetched_bar_variants[code] = variants
        bars = variants.get("qfq") or variants.get("none")
        if not bars:
            return False
        new_engine = self._build_prepared_engine(bars, start_index, initial_cash)
        self._activate_continuation_engine(new_engine, code, name, carried_cash)
        return True

    def _reset_random_prefetch(self, location: TdxDataLocation | None = None) -> None:
        self._random_prefetch_generation += 1
        self._continuation_prefetch_generation += 1
        self._random_prefetch_queue.clear()
        self._continuation_prefetch_candidate = None
        self._continuation_prefetch_request = None
        if location is None:
            self._random_prefetch_reader = None
            self._random_prefetch_info_reader = None
            self._continuation_prefetch_reader = None
            self._continuation_prefetch_info_reader = None
            self._random_prefetch_root = ""
            self._random_prefetch_adjust_type = ""
            return
        root_key = os.path.normcase(os.path.abspath(str(location.root)))
        self._random_prefetch_root = root_key
        self._random_prefetch_adjust_type = "qfq"
        self._random_prefetch_reader = TdxDayReader(
            location,
            adjust_provider=self.adjust_provider,
            adjust_type="qfq",
            adjust_cache_dir=CONFIG_PATH.parent / "adjusted_bars_cache",
        )
        self._random_prefetch_info_reader = StockInfoReader(location.root)
        self._continuation_prefetch_reader = TdxDayReader(
            location,
            adjust_provider=self.adjust_provider,
            adjust_type="qfq",
            adjust_cache_dir=CONFIG_PATH.parent / "adjusted_bars_cache",
        )
        self._continuation_prefetch_info_reader = StockInfoReader(location.root)
        self._schedule_random_prefetch()
        self._schedule_continuation_prefetch()

    def _prefetch_adjustment_ready(self) -> bool:
        return bool(self.adjust_provider is not None and self.adjust_provider.ready)

    def _schedule_random_prefetch(self) -> None:
        if (
            _is_offscreen()
            or not self._prefetch_adjustment_ready()
            or self._random_prefetch_worker is not None
            or self._random_prefetch_reader is None
            or self._random_prefetch_info_reader is None
            or len(self._random_prefetch_queue) >= RANDOM_PREFETCH_TARGET
        ):
            return
        worker = RandomSessionPrefetchWorker(
            self._random_prefetch_generation,
            "ordinary",
            self._random_prefetch_reader,
            self._random_prefetch_info_reader,
            self.random_prefetch_completed.emit,
            min_forward_bars=self._random_training_forward_bars(),
            allowed_codes=self.training_allowed_codes(),
        )
        self._random_prefetch_worker = worker
        QThreadPool.globalInstance().start(worker, 1)

    def training_allowed_codes(self) -> set[str] | None:
        """按板块筛选勾选，返回随机换股可选的股票代码。

        五个类别（主板/创业板/科创板/北交所/ST）全部勾选（默认）时返回 None，
        表示不筛选；否则只保留勾选类别里的股票，随机换股和连续换股都遵守。
        """
        integration = getattr(self, 'sector_integration', None)
        page = getattr(integration, 'page', None) if integration is not None else None
        keys = page.board_filter_keys() if page is not None else None
        if keys is None:
            keys = list(self.settings.board_filters)
        selected = {str(key) for key in (keys or [])}
        if selected >= BOARD_CATEGORIES:
            return None
        allowed: set[str] = set()
        if not selected:
            return allowed
        for code in self.reader.scan_stock_codes():
            if stock_category(code, self.info_reader.name_for(code) or '') in selected:
                allowed.add(code)
        return allowed

    def _set_training_category(self, key: str, checked: bool) -> None:
        """菜单里勾选“选股类型”，与板块页的筛选项保持同步。"""
        integration = getattr(self, 'sector_integration', None)
        page = getattr(integration, 'page', None) if integration is not None else None
        if page is not None:
            box = page.board_filters.get(key)
            if box is not None:
                box.setChecked(bool(checked))
                return
        keys = {str(value) for value in self.settings.board_filters}
        keys.add(key) if checked else keys.discard(key)
        order = [item[0] for item in BOARD_CATEGORY_LABELS]
        self.settings.board_filters = [item for item in order if item in keys]

    def _sync_training_category_actions(self) -> None:
        integration = getattr(self, 'sector_integration', None)
        page = getattr(integration, 'page', None) if integration is not None else None
        keys = page.board_filter_keys() if page is not None else list(self.settings.board_filters)
        selected = {str(value) for value in (keys or [])}
        for key, box in self.training_category_boxes.items():
            box.blockSignals(True)
            box.setChecked(key in selected)
            box.blockSignals(False)

    def _schedule_continuation_prefetch(self) -> None:
        if _is_offscreen() or not self._prefetch_adjustment_ready():
            return
        key = self._current_continuation_prefetch_key()
        if key is None or self._continuation_prefetch_reader is None or self._continuation_prefetch_info_reader is None:
            return
        if self._continuation_prefetch_candidate is not None and self._continuation_prefetch_candidate[0] == key:
            return
        if self._continuation_prefetch_worker is not None:
            if self._continuation_prefetch_request != key:
                self._continuation_prefetch_generation += 1
                self._continuation_prefetch_request = key
            return
        self._continuation_prefetch_generation += 1
        worker = RandomSessionPrefetchWorker(
            self._continuation_prefetch_generation,
            "continuation",
            self._continuation_prefetch_reader,
            self._continuation_prefetch_info_reader,
            self.random_prefetch_completed.emit,
            after_date=key[2],
            exclude_code=key[3],
            min_forward_bars=key[4],
            allowed_codes=self.training_allowed_codes(),
        )
        self._continuation_prefetch_request = key
        self._continuation_prefetch_worker = worker
        QThreadPool.globalInstance().start(worker, 1)

    def _finish_random_prefetch(self, payload) -> None:
        if not payload or len(payload) < 13:
            return
        generation, mode, root, adjust_type, after_date, exclude_code, min_forward_bars, bars, start_index, code, name, variants, error = payload
        if mode == "ordinary":
            if generation != self._random_prefetch_generation:
                if self._random_prefetch_worker is not None and self._random_prefetch_worker.generation == generation:
                    self._random_prefetch_worker = None
                    self._schedule_random_prefetch()
                return
            self._random_prefetch_worker = None
            if (
                root != self._random_prefetch_root
                or adjust_type != "qfq"
                or min_forward_bars != self._random_training_forward_bars()
            ):
                self._schedule_random_prefetch()
                return
            if not error and bars and code and variants:
                self._prefetched_stock_names[code] = name
                self._prefetched_bar_variants[code] = variants
                self._random_prefetch_queue.append((variants, start_index, code, name))
            if self._random_switch_pending and self._consume_random_prefetch():
                return
            if not error:
                self._schedule_random_prefetch()
            elif self._random_switch_pending:
                self._random_switch_pending = False
                self._update_status(f"无法准备随机股票：{error}")
            return

        if mode != "continuation":
            return
        if generation != self._continuation_prefetch_generation:
            if self._continuation_prefetch_worker is not None and self._continuation_prefetch_worker.generation == generation:
                self._continuation_prefetch_worker = None
                self._schedule_continuation_prefetch()
            return
        self._continuation_prefetch_worker = None
        key = (root, "qfq", after_date, exclude_code, min_forward_bars)
        if key != self._continuation_prefetch_request:
            return
        if not error and bars and code and variants:
            self._prefetched_stock_names[code] = name
            self._prefetched_bar_variants[code] = variants
            self._continuation_prefetch_candidate = (key, variants, start_index, code, name)
        current_key = self._current_continuation_prefetch_key()
        if self._continuation_switch_pending and current_key is not None:
            if self._consume_continuation_prefetch(current_key):
                return
            if error:
                self._continuation_switch_pending = False
                self._update_status(f"无法换股续作：{error}")
            else:
                self._schedule_continuation_prefetch()

    def load_sample_kline(self) -> None:
        self._refresh_sample_kline_button_state()
        if not self.sample_kline_btn.isEnabled():
            self._update_status("已设置有效通达信目录，请使用真实日K数据模拟。")
            return
        self._start_sample_kline(training=False)

    def _start_sample_kline(self, code: str | None = None, training: bool = True, confirm_reset: bool = True) -> None:
        try:
            if training and confirm_reset and not self._confirm_reset_if_records():
                return
            initial_cash = self._parse_money_text(self.cash_input.text())
            if initial_cash is None or initial_cash <= 0:
                raise ValueError("初始本金必须是大于 0 的数字。")
            self.settings.initial_cash = initial_cash
            self.settings.show_stock_identity = self.identity_toggle.isChecked()
            self._save_settings()
            self.using_sample_kline = True
            engine = create_sample_engine(
                start_date=None,
                initial_cash=self.settings.initial_cash,
                slot_count=self.settings.slot_count,
                commission_rate=self.settings.commission_rate,
                stamp_tax_rate=self.settings.stamp_tax_rate,
                min_commission=self.settings.min_commission,
                code=code,
            )
            self.code_input.setText(engine.bars[0].code)
            if training:
                self._activate_engine(
                    engine,
                    "训练准备：行情按开盘、收盘顺序推进；第一笔可在开盘或尾盘买入。",
                    awaiting_first_buy=True,
                )
            else:
                self._activate_browse_engine(
                    engine.bars,
                    SAMPLE_KLINE_NAME,
                    "已载入测试K线完整历史；点击黄色“开启随机换股”后进入随机训练。",
                )
                self.using_sample_kline = True
        except Exception as exc:
            QMessageBox.warning(self, "无法载入测试K线", str(exc))

    def start_simulation(self, force_random_stock: bool = False, confirm_reset: bool = True) -> None:
        try:
            if confirm_reset and not self._confirm_reset_account():
                return
            if force_random_stock and not self.using_sample_kline and self.settings.adjust_type != "qfq":
                self._set_adjust_type("qfq")
            if self.using_sample_kline:
                sample_code = None if force_random_stock else (self.code_input.text().strip() or None)
                self._start_sample_kline(sample_code, training=True, confirm_reset=False)
                return
            location = self._resolve_tdx_location(self.tdx_path.text().strip())
            if location is None:
                QMessageBox.warning(self, "未设置通达信目录", "您未设置通达信目录，请先点击 载入测试K线 进行体验。")
                return
            self.using_sample_kline = False
            self._apply_tdx_location(location)
            initial_cash = self._parse_money_text(self.cash_input.text())
            if initial_cash is None or initial_cash <= 0:
                raise ValueError("初始本金必须是大于 0 的数字。")
            self.settings.initial_cash = initial_cash
            self.settings.show_stock_identity = self.identity_toggle.isChecked()
            self._save_all_manual_settings()
            raw_code = self.code_input.text().strip()
            if force_random_stock or not raw_code or is_shanghai_index_query(raw_code):
                resolved_code = None
            else:
                resolved_code = self._resolve_market_code_query(raw_code)
            self.date_input.clear()
            engine = create_engine(
                reader=self.reader,
                code=resolved_code,
                start_date=None,
                initial_cash=self.settings.initial_cash,
                slot_count=self.settings.slot_count,
                commission_rate=self.settings.commission_rate,
                stamp_tax_rate=self.settings.stamp_tax_rate,
                min_commission=self.settings.min_commission,
                random_min_forward_bars=self._random_training_forward_bars(),
                allowed_codes=self.training_allowed_codes(),
            )
            self._activate_engine(
                engine,
                "训练准备：行情按开盘、收盘顺序推进；第一笔可在开盘或尾盘买入。",
                awaiting_first_buy=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "无法开始模拟", str(exc))

    def _activate_engine(
        self,
        engine: DailySimulationEngine,
        status: str,
        awaiting_first_buy: bool = False,
        continuation: bool = False,
        carried_cash: float | None = None,
    ) -> None:
        preserve_independent_records = (
            not continuation
            and self.training_mode_kind == TRAINING_MODE_INDEPENDENT
            and self._independent_switch_pending
        )
        preserve_single_records = (
            not continuation
            and self.training_mode_kind == TRAINING_MODE_SINGLE
            and self._single_switch_pending
        )
        if preserve_independent_records and self._block_resetting_mode_switch_if_holding(
            "独立训练模式"
        ):
            return
        if preserve_single_records and self._block_resetting_mode_switch_if_holding("单吊模式"):
            return
        if preserve_independent_records:
            self._archive_round("independent")
            self._independent_switch_pending = False
        elif not continuation and self.training_mode_kind == TRAINING_MODE_SINGLE:
            self._archive_ordinary_performance()
            self._single_switch_pending = False
        self.engine = engine
        self.engine.start()
        self.training_mode = True
        if continuation:
            self.trade_started = True
            self.engine.cash = round(float(carried_cash), 2)
            self.round_start_cash = self.engine.cash
            self.round_start_date = self.engine.current_bar.date
            self.round_start_node = TradeNode.OPEN
            self.account_baseline_locked = True
            self.round_equity_points = []
        else:
            self.trade_started = not awaiting_first_buy
            self.account_initial_cash = self.engine.initial_cash
            self.round_start_cash = self.engine.cash
            self.round_start_date = self.engine.current_bar.date
            self.round_start_node = TradeNode.OPEN
            if not preserve_independent_records:
                self.round_records = []
            self.equity_curve = []
            self.equity_points = []
            self.round_equity_points = []
            self.cumulative_holding_days_base = 0
            self.account_baseline_locked = False
            self._clear_return_context()
            delete_document()
        self.engine_epoch += 1
        self._performance_summary_key = None
        self._reset_drawdown_overlay()
        self.last_space_tap_time = 0.0
        if self.engine.current_bar.code == SHANGHAI_INDEX_CODE:
            self.index_overlay_active = False
            self.kline_widget.clear_index_overlay()
        self.index_preview_timer.stop()
        self.index_preview_active = False
        self.kline_widget.suppress_user_annotations = False
        self.browsing_stock_name = ""
        self.code_input.setText(self.engine.current_bar.code)
        self.pan_offset = 0
        self.viewed_bar_index = self.engine.current_index
        self._sync_date_input_to_viewed_bar()
        self.current_node = TradeNode.OPEN
        self.reveal_current_full = False
        self._advance_button_show_close = True
        self.first_buy_price = None
        self.first_buy_index = None
        self.first_buy_node = TradeNode.OPEN
        self.active_cycle_start_cash = None
        self._frozen_position_metrics = None
        self.completed_trade_ranges = []
        self._last_equity_record_key = None
        self.kline_widget.clear_user_annotations()
        if self.selected_buy_ratio is not None:
            self._sync_buy_budget_from_selected_ratio()
        if self.selected_sell_ratio is not None:
            self._sync_sell_budget_from_selected_ratio()
        self._refresh()
        self._update_status(status)
        self.kline_widget.setFocus()
        self._sync_start_button_label()
        self._sync_round_log_visibility()
        if preserve_independent_records:
            self._persist_session()
        self._schedule_random_prefetch()
        if continuation:
            self._schedule_continuation_prefetch()

    def _resolve_tdx_location(self, raw_path: str) -> TdxDataLocation | None:
        return resolve_tdx_location(raw_path)

    def _resolve_tdx_location_or_raise(self, raw_path: str) -> TdxDataLocation:
        location = self._resolve_tdx_location(raw_path)
        if location is None:
            raise TdxDataError(
                "未找到通达信日K数据。请点击“选择目录”，可选择通达信安装目录、vipdoc 目录、lday 子目录，"
                "或包含 sh/sz .day 文件的数据目录；同时确认已在通达信下载日线数据。"
            )
        return location

    def _apply_tdx_location(self, location: TdxDataLocation) -> None:
        root_text = str(location.root)
        self.tdx_path.setText(root_text)
        self.settings.tdx_root = root_text
        self._refresh_market_source_title()
        # 只有在根目录变化时才重建复权提供者，避免每次换股都把已解码的复权数据丢失。
        if self.adjust_provider is None or self.adjust_provider_root != root_text:
            self.adjust_provider = self._make_adjust_provider(location.root)
            self.adjust_provider_root = root_text
        same_reader = os.path.normcase(os.path.abspath(str(self.reader.tdx_root))) == os.path.normcase(
            os.path.abspath(root_text)
        )
        if same_reader:
            # Random switching uses the same TDX tree. Keep the scanned stock
            # list, decoded daily bars, and stock-name tables across clicks.
            self.reader.adjust_provider = self.adjust_provider
            self.reader.adjust_type = self.settings.adjust_type
        else:
            self.reader = TdxDayReader(
                location,
                adjust_provider=self.adjust_provider,
                adjust_type=self.settings.adjust_type,
                adjust_cache_dir=CONFIG_PATH.parent / "adjusted_bars_cache",
            )
            self.info_reader = StockInfoReader(location.root)
        self.using_sample_kline = False
        root_key = os.path.normcase(os.path.abspath(root_text))
        if (
            self._random_prefetch_root != root_key
            or self._random_prefetch_reader is None
            or self._random_prefetch_reader.adjust_provider is not self.adjust_provider
        ):
            self._reset_random_prefetch(location)
        else:
            self._random_prefetch_adjust_type = "qfq"
            self._random_prefetch_reader.adjust_type = "qfq"
            if self._continuation_prefetch_reader is not None:
                self._continuation_prefetch_reader.adjust_type = "qfq"
            self._schedule_random_prefetch()
            self._schedule_continuation_prefetch()
        self._refresh_sample_kline_button_state(has_valid_tdx=True)
        self._request_market_stats_update(location)
        self._start_adjust_initialize()

    def _make_adjust_provider(self, tdx_root: str) -> GbbqProvider | None:
        if not str(tdx_root or "").strip():
            return None
        gbbq_path = locate_gbbq_path(tdx_root)
        if not gbbq_path.exists():
            return None
        return GbbqProvider(gbbq_path, cache_path=CONFIG_PATH.parent / "gbbq_events.json")

    def _start_adjust_initialize(self) -> None:
        if self.adjust_provider is None:
            return
        if self.adjust_provider.ready:
            return
        if self.adjust_worker is not None:
            return
        self._update_status("正在后台初始化复权数据…")
        worker = GbbqLoadWorker(self.adjust_provider, self.adjust_completed.emit)
        self.adjust_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _finish_adjust_initialize(self, payload) -> None:
        ready, error = payload if payload and len(payload) >= 2 else (False, "")
        completed_worker = self.adjust_worker
        self.adjust_worker = None
        if completed_worker is not None and completed_worker.provider is not self.adjust_provider:
            self._start_adjust_initialize()
            return
        if ready:
            self._update_status("复权数据已初始化，个股K线按前复权显示。")
            if self._session_restore_pending:
                self._session_restore_pending = False
                self._restore_session()
            else:
                self._reload_current_stock_adjusted()
            location = resolve_tdx_location(self.tdx_path.text().strip())
            if location is not None:
                # Any candidates prepared while the provider was still loading
                # contain raw prices and must be rebuilt as forward-adjusted data.
                self._reset_random_prefetch(location)
        elif error:
            if self._session_restore_pending:
                self._session_restore_pending = False
                self._restore_session()
            self._update_status(f"复权数据加载失败，已回退不复权：{error}")
        else:
            if self._session_restore_pending:
                self._session_restore_pending = False
                self._restore_session()
            self._update_status("复权数据加载失败，已回退不复权。")

    def _start_sector_warmup(self) -> None:
        if self.sector_warmup_worker is not None:
            return
        try:
            context = self.sector_integration.market_context()
        except Exception:
            context = None
        worker = SectorWarmupWorker(
            context,
            CONFIG_PATH.parent / "sector_cache",
            self.sector_warmup_completed.emit,
        )
        self.sector_warmup_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _finish_sector_warmup(self, payload) -> None:
        self.sector_warmup_worker = None
        self._sector_warmup_error = ""
        if isinstance(payload, (tuple, list)) and payload and not payload[0]:
            self._sector_warmup_error = str(payload[1]) if len(payload) > 1 else "预热失败"
            self._emit_startup_ready()
            return
        try:
            self.sector_integration.prepare()
        except Exception as exc:
            self._sector_warmup_error = str(exc)
            self._emit_startup_ready()
            return
        page = self.sector_integration.page
        if page is None or page.sector_table.rowCount() > 0:
            self._begin_startup_deep_warmup()
            return
        page.readiness_changed.connect(self._begin_startup_deep_warmup)
        QTimer.singleShot(1500, self._begin_startup_deep_warmup)

    def _emit_startup_ready(self) -> None:
        if self._startup_ready_emitted:
            return
        self._startup_ready_emitted = True
        self.startup_ready.emit()

    def _begin_startup_deep_warmup(self) -> None:
        try:
            self.sector_integration.prime_page()
        except Exception:
            pass
        if (
            self._sector_deep_warmup_started
            or self._sector_deep_warmup_scheduled
            or self.sector_deep_warmup_worker is not None
        ):
            return
        cache_file = CONFIG_PATH.parent / "sector_cache" / "stock_quotes.json"
        if cache_file.is_file():
            # The full-market cache already exists. Keep startup snappy and
            # validate/refresh it shortly after the window is visible.
            self._sector_deep_warmup_scheduled = True
            QTimer.singleShot(3000, self._launch_sector_deep_warmup)
            self._emit_startup_ready()
            return
        self._launch_sector_deep_warmup()

    def _launch_sector_deep_warmup(self) -> None:
        self._sector_deep_warmup_scheduled = False
        if self._sector_deep_warmup_started or self.sector_deep_warmup_worker is not None:
            return
        self._sector_deep_warmup_started = True
        try:
            context = self.sector_integration.market_context()
        except Exception:
            context = None
        worker = SectorMemberWarmupWorker(
            context,
            CONFIG_PATH.parent / "sector_cache",
            self.sector_deep_warmup_completed.emit,
        )
        self.sector_deep_warmup_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _start_sector_deep_warmup(self) -> None:
        if self.sector_deep_warmup_worker is None and not self._sector_deep_warmup_started:
            self._launch_sector_deep_warmup()

    def _finish_sector_deep_warmup(self, payload) -> None:
        self.sector_deep_warmup_worker = None
        if isinstance(payload, (tuple, list)) and payload and not payload[0]:
            self._sector_deep_warmup_started = False
            self._sector_deep_warmup_scheduled = False
        self._emit_startup_ready()

    def _reload_current_stock_adjusted(self) -> bool:
        """复权就绪/切换后，把当前浏览或“训练准备（未交易）”的K线刷新为复权数据。

        - 浏览态：重新激活（跳到最新一根，保持“看全量历史”的语义）。
        - 训练准备态（还没第一笔交易）：原地替换 bars，保留当前进度。
        - 已开单训练：不触碰，避免影响进行中的模拟。
        """
        if self.engine is None:
            return False
        code = self.engine.current_bar.code
        if code == SHANGHAI_INDEX_CODE or self.using_sample_kline:
            return False
        cached_variants = self._prefetched_bar_variants.get(code, {})
        cached_bars = cached_variants.get(self.reader.adjust_type)
        if (
            cached_bars is None
            and self.reader.adjust_type != "none"
            and (self.reader.adjust_provider is None or not self.reader.adjust_provider.ready)
        ):
            # 复权数据还没就绪，先不刷新，等后台解码完成后再加载。
            return False
        try:
            bars = cached_bars or self.reader.read_daily_bars(code)
        except Exception:
            return False
        if not bars:
            return False
        if not self.training_mode:
            stock_name = self.info_reader.name_for(code) or code
            # 浏览态定位日期时改的是 pan_offset / viewed_bar_index，current_index 仍在最新。
            # 因此要传「当前真正查看的那根K线」的索引，切换复权后才能停留在原日期。
            view_index = max(
                0,
                min(self.engine.current_index - self.pan_offset, len(bars) - 1),
            )
            self._activate_browse_engine(
                bars,
                stock_name,
                f"{stock_name}：复权数据已加载。点击黄色“开启随机换股”进入随机训练。",
                view_index=view_index,
            )
            return True
        if not self.trade_started:
            # 训练准备态：长度/日期不变，仅替换为复权价格，进度不受影响。
            self.engine.bars = bars
            self._refresh()
            return True
        return False

    def _build_adjust_menu(self) -> None:
        self.adjust_menu = self.menuBar().addMenu("复权")
        self.adjust_none_action = QAction("不复权", self)
        self.adjust_qfq_action = QAction("前复权", self)
        self.adjust_hfq_action = QAction("后复权", self)
        for action, key in (
            (self.adjust_none_action, "none"),
            (self.adjust_qfq_action, "qfq"),
            (self.adjust_hfq_action, "hfq"),
        ):
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, _key=key: self._dispatch_menu('_set_adjust_type', _key))
            self.adjust_menu.addAction(action)
        self._refresh_adjust_actions()

    def _refresh_adjust_actions(self) -> None:
        current = self.settings.adjust_type
        self.adjust_none_action.setChecked(current == "none")
        self.adjust_qfq_action.setChecked(current == "qfq")
        self.adjust_hfq_action.setChecked(current == "hfq")

    def _set_adjust_type(self, adjust_type: str) -> None:
        if adjust_type not in ("none", "qfq", "hfq"):
            return
        if self.settings.adjust_type != adjust_type:
            self.settings.adjust_type = adjust_type
            self.reader.adjust_type = adjust_type
            self._save_settings()
            self._random_prefetch_adjust_type = "qfq"
            if self._random_prefetch_reader is not None:
                self._random_prefetch_reader.adjust_type = "qfq"
            if self._continuation_prefetch_reader is not None:
                self._continuation_prefetch_reader.adjust_type = "qfq"
            if adjust_type != "none":
                self._start_adjust_initialize()
        self._refresh_adjust_actions()
        label = {"none": "不复权", "qfq": "前复权", "hfq": "后复权"}.get(adjust_type, adjust_type)
        reloaded = self._reload_current_stock_adjusted()
        self._update_status(
            f"K线复权已切换为：{label}。"
            if reloaded
            else f"K线复权已保存为：{label}；新打开/换股的个股生效。"
        )
        self._refresh()

    def _refresh_sample_kline_button_state(self, has_valid_tdx: bool | None = None) -> None:
        if not hasattr(self, "sample_kline_btn"):
            return
        if has_valid_tdx is None:
            has_valid_tdx = resolve_tdx_location(self.tdx_path.text().strip()) is not None
        self.sample_kline_btn.setEnabled(not has_valid_tdx)
        if hasattr(self, "simulation_sample_action"):
            self.simulation_sample_action.setEnabled(not has_valid_tdx)
        self.sample_kline_btn.setToolTip("未设置通达信目录时可载入测试K线体验。" if not has_valid_tdx else "已设置有效通达信目录，请使用真实日K数据。")

    def save_display_preferences(self) -> None:
        self.settings.show_stock_identity = self.identity_toggle.isChecked()
        self._sync_identity_toggle_appearance()
        self.kline_widget.show_time_marks = self.identity_toggle.isChecked()
        self._save_settings()
        self._refresh()

    def save_chart_preferences(self) -> None:
        self.settings.hidden_ma_periods = sorted(self.kline_widget.hidden_ma_periods)
        self.settings.sub_pane_indicators = list(self.kline_widget.sub_pane_indicators)
        self.settings.pane_height_ratios = list(self.kline_widget.pane_height_ratios)
        self.settings.hidden_volume_ma_periods = sorted(self.kline_widget.hidden_volume_ma_periods)
        self.settings.kdj_n = self.kline_widget.kdj_n
        self.settings.kdj_k = self.kline_widget.kdj_k
        self.settings.kdj_d = self.kline_widget.kdj_d
        self.settings.pane_macd_params = [list(params) for params in self.kline_widget.pane_macd_params]
        self.settings.pane_kdj_params = [list(params) for params in self.kline_widget.pane_kdj_params]
        self.settings.main_overlay_mode = self.kline_widget.main_overlay_mode
        self.settings.boll_n = self.kline_widget.boll_n
        self.settings.boll_k = self.kline_widget.boll_k
        self._save_settings()

    def edit_macd_parameters(self, pane_index: int = 0) -> None:
        fast, slow, signal = self.kline_widget.pane_macd_params[pane_index]
        current = f"{fast},{slow},{signal}"
        text, accepted = QInputDialog.getText(self, "修改 MACD 参数", "输入格式：快线,慢线,信号", text=current)
        if not accepted:
            return
        try:
            fast, slow, signal = self._parse_macd_parameters(text)
        except ValueError as exc:
            self._update_status(str(exc))
            return
        self.save_macd_parameters(fast, slow, signal, pane_index)

    def save_macd_parameters(self, fast: int, slow: int, signal: int, pane_index: int = 0) -> bool:
        if slow <= fast:
            self._update_status("MACD 慢线周期必须大于快线周期。")
            return False
        pane_list = list(self.settings.pane_macd_params)
        while len(pane_list) <= pane_index:
            pane_list.append([12, 26, 9])
        pane_list[pane_index] = [fast, slow, signal]
        self.settings.pane_macd_params = pane_list
        self.settings.macd_fast = fast
        self.settings.macd_slow = slow
        self.settings.macd_signal = signal
        self.kline_widget.set_pane_macd_parameters(pane_index, fast, slow, signal)
        self._save_settings()
        self._update_status(f"MACD 参数已保存（副图{pane_index + 1}）：{fast},{slow},{signal}")
        return True

    @staticmethod
    def _parse_macd_parameters(text: str) -> tuple[int, int, int]:
        parts = [part.strip() for part in text.replace("，", ",").replace("、", ",").split(",")]
        if len(parts) != 3 or any(not part for part in parts):
            raise ValueError("MACD 参数格式应为：快线,慢线,信号，例如 12,26,9。")
        try:
            fast, slow, signal = (int(part) for part in parts)
        except ValueError as exc:
            raise ValueError("MACD 参数只能输入整数，例如 12,26,9。") from exc
        if min(fast, slow, signal) < 1:
            raise ValueError("MACD 参数必须大于 0。")
        if slow <= fast:
            raise ValueError("MACD 慢线周期必须大于快线周期。")
        return fast, slow, signal

    def edit_kdj_parameters(self, pane_index: int = 0) -> None:
        n, k, d = self.kline_widget.pane_kdj_params[pane_index]
        current = f"{n},{k},{d}"
        text, accepted = QInputDialog.getText(self, "修改 KDJ 参数", "输入格式：N,快线平滑,慢线平滑", text=current)
        if not accepted:
            return
        try:
            n, k, d = self._parse_kdj_parameters(text)
        except ValueError as exc:
            self._update_status(str(exc))
            return
        self.save_kdj_parameters(n, k, d, pane_index)

    def save_kdj_parameters(self, n: int, k: int, d: int, pane_index: int = 0) -> bool:
        if k < 1 or d < 1 or n < 1:
            self._update_status("KDJ 参数必须大于 0。")
            return False
        pane_list = list(self.settings.pane_kdj_params)
        while len(pane_list) <= pane_index:
            pane_list.append([9, 3, 3])
        pane_list[pane_index] = [n, k, d]
        self.settings.pane_kdj_params = pane_list
        self.settings.kdj_n = n
        self.settings.kdj_k = k
        self.settings.kdj_d = d
        self.kline_widget.set_pane_kdj_parameters(pane_index, n, k, d)
        self._save_settings()
        self._update_status(f"KDJ 参数已保存（副图{pane_index + 1}）：{n},{k},{d}")
        return True

    @staticmethod
    def _parse_kdj_parameters(text: str) -> tuple[int, int, int]:
        parts = [part.strip() for part in text.replace("，", ",").replace("、", ",").split(",")]
        if len(parts) != 3 or any(not part for part in parts):
            raise ValueError("KDJ 参数格式应为：N,快线平滑,慢线平滑，例如 9,3,3。")
        try:
            n, k, d = (int(part) for part in parts)
        except ValueError as exc:
            raise ValueError("KDJ 参数只能输入整数，例如 9,3,3。") from exc
        if min(n, k, d) < 1:
            raise ValueError("KDJ 参数必须大于 0。")
        return n, k, d

    def _save_settings(self) -> None:
        save_settings(self.settings)

    def buy_at(self, node: TradeNode) -> None:
        if not self.engine or not self.training_mode:
            return
        if not self.trade_started:
            if not self.test_trade_active and (
                self.pan_offset != 0 or self.viewed_bar_index != self.engine.current_index
            ):
                QMessageBox.information(
                    self,
                    "请返回训练当前K线",
                    "当前正在查看过往行情。\n"
                    "请按 Ctrl+右方向键或 Home 返回训练当前K线后，再执行第一笔买入。",
                )
                return
        if node == TradeNode.CLOSE and not self.reveal_current_full:
            self._update_status("请点击“行情推进（当日收盘）”完整揭示收盘，再按尾盘价交易。")
            return
        if node == TradeNode.OPEN and self.reveal_current_full:
            self._update_status("当前已经到收盘阶段，不能再按开盘价成交。")
            return
        try:
            if self.selected_buy_ratio is not None:
                self._buy_input_mode = "amount"
                self.settings.buy_budget = self._sync_buy_budget_from_selected_ratio()
            budget = self._parse_money_text(self.buy_budget_input.text())
            if budget is None:
                self._update_status("买入金额必须是数字。")
                return
            if budget <= 0:
                self._update_status("买入金额必须大于 0。")
                return
            self.current_node = node
            quantity_requested = self._buy_input_mode == "quantity" and self.selected_buy_ratio is None
            requested_quantity = self._whole_lot_quantity(self.buy_quantity_input.value())
            if quantity_requested:
                if requested_quantity <= 0:
                    self._update_status("买入数量至少需要 100 股。")
                    return
                requested_amount = round(self.engine.current_bar.price_at(node) * requested_quantity, 2)
                requested_total = round(requested_amount + self.engine._commission(requested_amount), 2)
                if requested_total > self.engine.cash:
                    message = f"可用现金不足，买入 {requested_quantity} 股需要 {requested_total:.2f} 元（含手续费）。"
                    self._update_status(message)
                    QMessageBox.warning(self, "可用现金不足", message)
                    return
            else:
                minimum_lot_cost = self._minimum_buy_lot_cost(node)
                if min(budget, self.engine.cash) < minimum_lot_cost:
                    if self.engine.cash < minimum_lot_cost:
                        message = f"可用现金不足，至少需要 {minimum_lot_cost:.2f} 元才能买入 100 股。"
                        self._update_status(message)
                        QMessageBox.warning(self, "可用现金不足", message)
                    else:
                        self._update_status(f"买入金额不足，至少需要 {minimum_lot_cost:.2f} 元才能买入 100 股。")
                    self._refresh()
                    return
            had_position = self._has_position()
            was_first_round_trade = not self.engine.trades
            cycle_start_cash = self.engine.cash if not had_position else None
            if quantity_requested:
                result = self.engine.buy_quantity(self._auto_buy_slot(), node, requested_quantity)
            else:
                result = self.engine.buy(self._auto_buy_slot(), node, budget)
            if result.accepted and not self.trade_started:
                self.trade_started = True
                self.engine.start_index = self.engine.current_index
            if result.accepted and was_first_round_trade:
                self.round_start_cash = cycle_start_cash if cycle_start_cash is not None else self.engine.initial_cash
                self.round_start_date = result.date
                self.round_start_node = result.node
            if result.accepted and not had_position:
                self._frozen_position_metrics = None
                self.first_buy_price = result.price
                self.first_buy_index = self.engine.current_index
                self.first_buy_node = node
                self.active_cycle_start_cash = cycle_start_cash
                self.account_baseline_locked = True
            if result.accepted:
                if node == TradeNode.OPEN and not self.reveal_current_full:
                    # Before the first buy, preparation skips hidden closes. Once an
                    # open buy succeeds, always complete that day's open/close flow.
                    self._advance_button_show_close = True
                _play_buy_success_sound()
                self._update_status(
                    f"买入成功：共买入 {result.quantity} 股，成交金额 {result.amount:.2f}，手续费 {result.fee:.2f}"
                )
            else:
                self._update_status(result.message)
            if not result.accepted and "现金不足" in result.message:
                QMessageBox.warning(self, "可用现金不足", result.message)
            self._refresh()
            if result.accepted:
                self._refresh_performance_after_trade()
        except Exception as exc:
            self._update_status(str(exc))

    def apply_budget_ratio(self, ratio: float) -> None:
        self.apply_buy_budget_ratio(ratio)

    def apply_buy_budget_ratio(self, ratio: float, checked: bool | None = None) -> None:
        if checked is False and self.selected_buy_ratio is not None and abs(self.selected_buy_ratio - ratio) < 0.000001:
            amount = self._parse_money_text(self.buy_budget_input.text()) or 0
            self.selected_buy_ratio = None
            self._set_ratio_buttons_checked(self.buy_ratio_buttons, None)
            self.settings.selected_buy_ratio = None
            self.settings.buy_budget = amount
            self._save_settings()
            self._update_status(f"已切换为固定买入金额：{self._format_budget_text(amount)}")
            return
        self._buy_input_mode = "amount"
        self.selected_buy_ratio = ratio
        amount = self._sync_buy_budget_from_selected_ratio()
        self.settings.selected_buy_ratio = ratio
        self.settings.buy_budget = amount
        self._save_settings()
        self._update_status(f"买入金额已设置为可用现金的 {ratio:.0%}：{amount}")

    def apply_sell_budget_ratio(self, ratio: float, checked: bool | None = None) -> None:
        if checked is False and self.selected_sell_ratio is not None and abs(self.selected_sell_ratio - ratio) < 0.000001:
            amount = self._parse_money_text(self.sell_budget_input.text()) or 0
            self.selected_sell_ratio = None
            self._set_ratio_buttons_checked(self.sell_ratio_buttons, None)
            self.settings.selected_sell_ratio = None
            self.settings.sell_budget = amount
            self._save_settings()
            self._update_status(f"已切换为固定卖出金额：{self._format_budget_text(amount)}")
            return
        self._sell_input_mode = "amount"
        self.selected_sell_ratio = ratio
        amount = self._sync_sell_budget_from_selected_ratio()
        self.settings.selected_sell_ratio = ratio
        self.settings.sell_budget = amount
        self._save_settings()
        self._update_status(f"卖出金额已设置为可卖市值的 {ratio:.0%}：{amount}")

    def sell_at(self, node: TradeNode) -> None:
        if not self.engine or not self.training_mode or not self.trade_started:
            return
        if node == TradeNode.CLOSE and not self.reveal_current_full:
            self._update_status("请点击“行情推进（当日收盘）”完整揭示收盘，再按尾盘价交易。")
            return
        if node == TradeNode.OPEN and self.reveal_current_full:
            self._update_status("当前已经到收盘阶段，不能再按开盘价成交。")
            return
        try:
            clear_position_requested = self.selected_sell_ratio == 1.0
            if self.selected_sell_ratio is not None:
                self._sell_input_mode = "amount"
                self.settings.sell_budget = self._sync_sell_budget_from_selected_ratio()
            self.current_node = node
            position_metrics_before_sell = self._current_position_metric_values()
            if clear_position_requested:
                results = self._sell_all_sellable(node)
            elif self._sell_input_mode == "quantity":
                quantity = self._whole_lot_quantity(self.sell_quantity_input.value())
                if quantity <= 0:
                    self._update_status("卖出数量至少需要 100 股。")
                    return
                results = self._sell_by_quantity(node, quantity)
            else:
                budget = self._parse_money_text(self.sell_budget_input.text())
                if budget is None:
                    self._update_status("卖出金额必须是数字。")
                    return
                if budget <= 0:
                    self._update_status("卖出金额必须大于 0。")
                    return
                results = self._sell_by_budget(node, budget)
            accepted = [result for result in results if result.accepted]
            cleared_position = False
            if accepted:
                quantity = sum(result.quantity for result in accepted)
                amount = sum(result.amount for result in accepted)
                if not self._has_position():
                    self._archive_current_trade_cycle()
                    self._frozen_position_metrics = position_metrics_before_sell
                    self._reset_first_buy_cycle()
                    cleared_position = True
                self._update_status(f"卖出成功：共卖出 {quantity} 股，成交金额 {amount:.2f}")
            elif results:
                self._update_status(results[-1].message)
            else:
                self._update_status("没有可卖持仓。")
            self._refresh()
            if accepted:
                self._refresh_performance_after_trade()
            if cleared_position:
                self._schedule_continuation_prefetch()
                _audible_information(self, "本轮交易结束", "您已清仓，本轮交易结束，您可以继续交易。")
        except Exception as exc:
            self._update_status(str(exc))

    def prev_day(self) -> None:
        if not self.engine or not self.trade_started or self.engine.current_index <= 0:
            return
        self.engine.current_index -= 1
        self.pan_offset = 0
        self.viewed_bar_index = self.engine.current_index
        self._sync_date_input_to_viewed_bar()
        self.current_node = TradeNode.OPEN
        self.reveal_current_full = False
        self._advance_button_show_close = True
        self._refresh()
        self._refresh_performance_after_market_step()

    def advance_playback(self) -> None:
        if not self.engine or not self.training_mode:
            return
        if self._advance_button_show_close:
            self.show_close_phase()
        else:
            self.next_day()

    def next_day(self) -> None:
        if not self.engine or not self.training_mode:
            return
        if not self.engine.next_day():
            self._update_status("已经到最后一天。")
            self._refresh()
            return
        self.pan_offset = 0
        self.viewed_bar_index = (
            min(
                len(self.engine.bars) - 1,
                self.engine.current_index + self._test_trade_future_slots,
            )
            if self.test_trade_active
            else self.engine.current_index
        )
        self._sync_date_input_to_viewed_bar()
        self.current_node = TradeNode.OPEN
        self.reveal_current_full = False
        self._advance_button_show_close = True
        self._refresh()
        self._refresh_performance_after_market_step()
        if self.trade_started:
            self._update_status("已进入下一日开盘阶段：可以按开盘价买入或卖出可卖底仓。")
        else:
            self._update_status("训练准备：已进入下一日开盘，可继续观察或按 B 完成第一笔买入。")

    def show_close_phase(self) -> None:
        if not self.engine or not self.training_mode:
            return
        if self.reveal_current_full:
            self._update_status("当前已经显示收盘K线。")
            return
        self.current_node = TradeNode.CLOSE
        self.reveal_current_full = True
        self._advance_button_show_close = False
        self._refresh()
        self._refresh_performance_after_market_step()
        if self.trade_started:
            self._update_status("已显示完整K线：现在可以按尾盘价买入或卖出可卖底仓。")
        else:
            self._update_status("训练准备：已显示当日收盘；可按尾盘价完成第一笔买入，或进入下一日。")

    def _auto_buy_slot(self) -> int:
        if not self.engine:
            return 0
        for slot in self.engine.slots:
            if slot.is_empty:
                return slot.index
        return min(self.engine.slots, key=lambda item: item.quantity).index

    def _auto_sell_slot(self) -> int:
        if not self.engine:
            return 0
        for slot in self.engine.slots:
            if slot.sellable_quantity > 0:
                return slot.index
        for slot in self.engine.slots:
            if not slot.is_empty:
                return slot.index
        return 0

    def _sellable_market_value(self, node: TradeNode) -> float:
        if not self.engine:
            return 0.0
        price = self.engine.current_bar.price_at(node)
        quantity = sum(slot.sellable_quantity if self.engine.t_plus_one else slot.quantity for slot in self.engine.slots)
        return round(quantity * price, 2)

    def _locked_today_market_value(self, node: TradeNode) -> float:
        if not self.engine:
            return 0.0
        price = self.engine.current_bar.price_at(node)
        quantity = sum(min(slot.today_quantity, slot.quantity) for slot in self.engine.slots) if self.engine.t_plus_one else 0
        return round(quantity * price, 2)

    def _sync_buy_budget_from_selected_ratio(self) -> int:
        ratio = self.selected_buy_ratio
        if ratio is None:
            self._set_ratio_buttons_checked(self.buy_ratio_buttons, None)
            current = self._parse_money_text(self.buy_budget_input.text())
            return int(current or 0)
        available_cash = self.engine.cash if self.engine else (self._parse_money_text(self.cash_input.text()) or self.settings.initial_cash)
        amount = budget_from_ratio(available_cash, ratio)
        self.buy_budget_input.setText(str(amount))
        self._buy_input_mode = "amount"
        self._sync_buy_quantity_from_budget(amount)
        self._set_ratio_buttons_checked(self.buy_ratio_buttons, ratio)
        return amount

    def _sync_sell_budget_from_selected_ratio(self) -> int:
        ratio = self.selected_sell_ratio
        if ratio is None:
            self._set_ratio_buttons_checked(self.sell_ratio_buttons, None)
            current = self._parse_money_text(self.sell_budget_input.text())
            return int(current or 0)
        amount = budget_from_ratio(self._sellable_market_value(self.current_node), ratio) if self.engine else int(self.settings.sell_budget)
        self.sell_budget_input.setText(str(amount))
        self._sell_input_mode = "amount"
        self._sync_sell_quantity_from_budget(amount)
        self._set_ratio_buttons_checked(self.sell_ratio_buttons, ratio)
        return amount

    def _sync_sell_budget_default(self) -> int:
        return self._sync_sell_budget_from_selected_ratio()

    def _has_position(self) -> bool:
        return bool(self.engine and any(not slot.is_empty for slot in self.engine.slots))

    def _cumulative_holding_days(self) -> int:
        completed_days = sum(
            abs(end_index - start_index) + 1
            for start_index, end_index, _profit in self.completed_trade_ranges
        )
        if not self.engine or self.first_buy_index is None or not self._has_position():
            return self.cumulative_holding_days_base + completed_days
        return self.cumulative_holding_days_base + completed_days + abs(self.engine.current_index - self.first_buy_index) + 1

    def _reset_first_buy_cycle(self) -> None:
        self.first_buy_price = None
        self.first_buy_index = None
        self.first_buy_node = TradeNode.OPEN
        self.active_cycle_start_cash = None

    def _archive_current_trade_cycle(self) -> None:
        if not self.engine or self.first_buy_index is None:
            return
        start_index = max(0, min(self.first_buy_index, len(self.engine.bars) - 1))
        end_index = max(0, min(self.engine.current_index, len(self.engine.bars) - 1))
        cycle_start_cash = self.active_cycle_start_cash
        cycle_profit = 0.0 if cycle_start_cash is None else round(self.engine.cash - cycle_start_cash, 2)
        completed_range = (min(start_index, end_index), max(start_index, end_index), cycle_profit)
        if not self.completed_trade_ranges or self.completed_trade_ranges[-1] != completed_range:
            self.completed_trade_ranges.append(completed_range)

    @staticmethod
    def _desktop_directory() -> Path:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        return Path(desktop) if desktop else Path.home() / "Desktop"

    @staticmethod
    def _safe_snapshot_name(value: str, fallback: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().rstrip(".")
        return cleaned or fallback

    @staticmethod
    def _available_snapshot_path(directory: Path, stock_name: str, filename_tail: str) -> Path:
        candidate = directory / f"{stock_name}-{filename_tail}.png"
        suffix = 2
        while candidate.exists():
            candidate = directory / f"{stock_name}-{suffix}-{filename_tail}.png"
            suffix += 1
        return candidate

    @staticmethod
    def _snapshot_profit_filename_text(rate: float) -> str:
        magnitude = f"{abs(rate):.2f}".rstrip("0").rstrip(".")
        if rate > 0:
            return f"总盈利+{magnitude}%"
        if rate < 0:
            return f"总亏损-{magnitude}%"
        return "总盈亏0%"

    def save_trade_snapshot(self) -> Path | None:
        if not self.engine or not self.training_mode:
            self._update_status("请先进入模拟训练，再保存交易快照。")
            return None
        try:
            bar = self.engine.bars[self._displayed_bar_index()]
            if self.using_sample_kline:
                stock_name = SAMPLE_KLINE_NAME
            else:
                stock_name = self.info_reader.name_for(bar.code) or bar.code
            snapshot = self.engine.snapshot(self.current_node)
            safe_name = self._safe_snapshot_name(stock_name, "未知股票")
            safe_code = self._safe_snapshot_name(bar.code, "未知代码")
            date_text = bar.date.replace("-", "")
            profit_text = self._snapshot_profit_filename_text(snapshot.profit_rate)
            directory = self._desktop_directory() / "K线交易记录"
            directory.mkdir(parents=True, exist_ok=True)
            filename_tail = f"{safe_code}-{date_text}-{profit_text}"
            path = self._available_snapshot_path(directory, safe_name, filename_tail)
            self.repaint()
            pixmap = self.centralWidget().grab()
            if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
                raise OSError("截图图片保存失败。")
            self._update_status(f"交易快照已保存：{path}")
            self._flash_snapshot_capture()
            self._show_snapshot_notice("交易快照已保存到桌面")
            return path
        except Exception as exc:
            self._update_status(f"交易快照保存失败：{exc}")
            self._show_snapshot_notice("交易快照保存失败", error=True)
            return None

    @staticmethod
    def _available_performance_csv_path(directory: Path, filename: str) -> Path:
        candidate = directory / f"{filename}.csv"
        suffix = 2
        while candidate.exists():
            candidate = directory / f"{filename}-{suffix}.csv"
            suffix += 1
        return candidate

    @staticmethod
    def _metrics_csv_fields(metrics: PerformanceMetrics) -> dict[str, object]:
        def csv_value(value):
            if value is None:
                return ""
            if isinstance(value, float) and math.isinf(value):
                return "∞"
            return value

        return {
            "期初资产": csv_value(metrics.initial_asset),
            "期末资产": csv_value(metrics.ending_asset),
            "净盈亏": csv_value(metrics.net_profit),
            "总收益率%": csv_value(metrics.total_return),
            "同期上证收益率%": csv_value(metrics.benchmark_return),
            "超额收益率%": csv_value(metrics.excess_return),
            "年化收益率%": csv_value(metrics.annual_return),
            "最大回撤%": csv_value(metrics.max_drawdown),
            "年化波动率%": csv_value(metrics.annual_volatility),
            "夏普比率": csv_value(metrics.sharpe_ratio),
            "Sortino比率": csv_value(metrics.sortino_ratio),
            "收益回撤比": csv_value(metrics.return_drawdown_ratio),
            "Calmar比率": csv_value(metrics.calmar_ratio),
            "信息比率": csv_value(metrics.information_ratio),
            "完整交易段数": csv_value(metrics.segment_count),
            "胜率%": csv_value(metrics.win_rate),
            "盈亏比": csv_value(metrics.profit_loss_ratio),
            "利润因子": csv_value(metrics.profit_factor),
            "单段期望收益%": csv_value(metrics.expectancy),
            "平均盈利%": csv_value(metrics.average_win),
            "平均亏损%": csv_value(metrics.average_loss),
            "最大单段盈利%": csv_value(metrics.best_segment),
            "最大单段亏损%": csv_value(metrics.worst_segment),
            "成交次数": csv_value(metrics.trade_count),
            "累计持有交易日": csv_value(metrics.holding_days),
            "手续费及税费": csv_value(metrics.fee_and_tax),
            "股票数量": csv_value(metrics.stock_count),
            "轮次数量": csv_value(metrics.round_count),
            "风险指标样本日": csv_value(metrics.sample_days),
        }

    def _metrics_for_one_record(self, record: RoundRecord, index_bars) -> PerformanceMetrics:
        initial_asset = float(record.start_cash or max(1.0, record.end_asset - record.profit))
        ending_asset = float(record.end_asset or initial_asset + record.profit)
        return calculate_performance_metrics(
            initial_asset=initial_asset,
            ending_asset=ending_asset,
            segments=self._segments_for_record(record),
            trades=list(record.trades),
            equity_points=list(record.equity_points),
            index_bars=index_bars,
            start_date=record.start_date,
            start_node=record.start_node,
            end_date=record.end_date,
            end_node=record.end_node,
            stock_count=1,
            round_count=1,
        )

    def export_performance_csv(self) -> Path | None:
        return self._export_performance_report("CSV")

    def export_performance_excel(self) -> Path | None:
        return self._export_performance_report("Excel")

    def _export_performance_report(self, output_format: str) -> Path | None:
        records = self._performance_records_for_overlay()
        scope = self._calculate_performance_scope(records)
        if not records or scope is None:
            self._update_status("请先完成第一笔买入，再导出交易统计。")
            return None
        try:
            metrics, index_bars, start_date, start_node, end_date, end_node = scope
            mode_text = TRAINING_MODE_LABELS.get(self.training_mode_kind, "单吊模式")
            multi_stock_mode = self._uses_round_records()
            rows: list[dict[str, object]] = []
            summary_row: dict[str, object] = {
                "记录层级": "区间汇总",
                "交易模式": mode_text,
                "轮次": "全部" if multi_stock_mode else records[0].index,
                "股票代码": "多股票" if multi_stock_mode else records[0].code.upper(),
                "股票名称": (
                    "连续账户"
                    if self.continuous_compound_mode
                    else "独立训练汇总"
                    if self.training_mode_kind == TRAINING_MODE_INDEPENDENT
                    else records[0].name
                ),
                "状态": "进行中" if self._has_position() else "已清仓",
                "开始日期": start_date,
                "结束日期": end_date,
                "开始阶段": "开盘" if start_node == TradeNode.OPEN else "收盘",
                "结束阶段": "开盘" if end_node == TradeNode.OPEN else "收盘",
            }
            summary_row.update(self._metrics_csv_fields(metrics))
            rows.append(summary_row)

            for record in records:
                record_metrics = self._metrics_for_one_record(record, index_bars)
                round_row: dict[str, object] = {
                    "记录层级": "股票轮次",
                    "交易模式": mode_text,
                    "轮次": record.index,
                    "股票代码": record.code.upper(),
                    "股票名称": record.name,
                    "状态": "进行中" if record.status == "active" else "已完成",
                    "开始日期": record.start_date,
                    "结束日期": record.end_date,
                    "开始阶段": "开盘" if record.start_node == TradeNode.OPEN else "收盘",
                    "结束阶段": "开盘" if record.end_node == TradeNode.OPEN else "收盘",
                }
                round_row.update(self._metrics_csv_fields(record_metrics))
                rows.append(round_row)

                for segment in self._segments_for_record(record):
                    segment_benchmark = benchmark_interval_return(
                        index_bars,
                        segment.start_date,
                        segment.start_node,
                        segment.end_date,
                        segment.end_node,
                    )
                    rows.append(
                        {
                            "记录层级": "交易分段",
                            "交易模式": mode_text,
                            "轮次": record.index,
                            "股票代码": record.code.upper(),
                            "股票名称": record.name,
                            "状态": "已完成",
                            "开始日期": segment.start_date,
                            "结束日期": segment.end_date,
                            "开始阶段": "开盘" if segment.start_node == TradeNode.OPEN else "收盘",
                            "结束阶段": "开盘" if segment.end_node == TradeNode.OPEN else "收盘",
                            "期初资产": segment.start_asset,
                            "期末资产": segment.end_asset,
                            "净盈亏": segment.profit,
                            "总收益率%": segment.return_rate,
                            "同期上证收益率%": segment_benchmark,
                            "超额收益率%": (
                                round(segment.return_rate - segment_benchmark, 6)
                                if segment_benchmark is not None
                                else None
                            ),
                            "累计持有交易日": segment.holding_days,
                            "手续费及税费": round(segment.fee + segment.tax, 2),
                            "分段序号": segment.index,
                            "买入次数": segment.buy_count,
                            "卖出次数": segment.sell_count,
                        }
                    )

                for trade_index, trade in enumerate(record.trades, start=1):
                    if not trade.accepted or trade.side not in {"buy", "sell"}:
                        continue
                    rows.append(
                        {
                            "记录层级": "成交明细",
                            "交易模式": mode_text,
                            "轮次": record.index,
                            "股票代码": record.code.upper(),
                            "股票名称": record.name,
                            "状态": "已成交",
                            "成交序号": trade_index,
                            "买卖方向": "买入" if trade.side == "buy" else "卖出",
                            "成交日期": trade.date,
                            "成交阶段": "开盘" if trade.node == TradeNode.OPEN else "收盘",
                            "成交价": trade.price,
                            "成交数量": trade.quantity,
                            "成交金额": trade.amount,
                            "手续费": trade.fee,
                            "印花税": trade.tax,
                            "分仓编号": trade.slot_index + 1,
                        }
                    )

            fieldnames = [
                "记录层级", "交易模式", "轮次", "股票代码", "股票名称", "状态",
                "开始日期", "结束日期", "开始阶段", "结束阶段",
                "期初资产", "期末资产", "净盈亏", "总收益率%",
                "同期上证收益率%", "超额收益率%", "年化收益率%", "最大回撤%",
                "年化波动率%", "夏普比率", "Sortino比率", "收益回撤比", "Calmar比率", "信息比率",
                "完整交易段数", "胜率%", "盈亏比", "利润因子", "单段期望收益%",
                "平均盈利%", "平均亏损%", "最大单段盈利%", "最大单段亏损%",
                "成交次数", "累计持有交易日", "手续费及税费", "股票数量", "轮次数量",
                "风险指标样本日", "分段序号", "买入次数", "卖出次数", "成交序号",
                "买卖方向", "成交日期", "成交阶段", "成交价", "成交数量", "成交金额",
                "手续费", "印花税", "分仓编号",
            ]
            directory = self._desktop_directory()
            directory.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            filename = f"交易统计-{mode_text}-{start_date.replace('-', '')}-{timestamp}"
            if output_format == "Excel":
                from .excel_export import write_performance_workbook
                path = directory / f"{filename}.xlsx"
                suffix = 2
                while path.exists():
                    path = directory / f"{filename}-{suffix}.xlsx"
                    suffix += 1
                write_performance_workbook(path, rows, fieldnames, records)
                self._update_status(f"交易统计Excel已保存：{path}")
                self._show_snapshot_notice("含资金与回撤图表的Excel已保存到桌面")
                return path
            path = self._available_performance_csv_path(directory, filename)
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(
                    {
                        key: (
                            ""
                            if value is None
                            else "∞"
                            if isinstance(value, float) and math.isinf(value)
                            else value
                        )
                        for key, value in row.items()
                    }
                    for row in rows
                )
            self._update_status(f"交易统计CSV已保存：{path}")
            self._show_snapshot_notice("交易统计CSV已保存到桌面")
            return path
        except Exception as exc:
            self._update_status(f"交易统计{output_format}导出失败：{exc}")
            self._show_snapshot_notice(f"交易统计{output_format}导出失败", error=True)
            return None

    def _minimum_buy_lot_cost(self, node: TradeNode) -> float:
        if not self.engine:
            return 0.0
        price = self.engine.current_bar.price_at(node)
        amount = round(price * 100, 2)
        fee = self.engine._commission(amount)
        return round(amount + fee, 2)

    def _sell_by_budget(self, node: TradeNode, budget: float):
        if not self.engine:
            return []
        price = self.engine.current_bar.price_at(node)
        minimum_lot_value = round(price * 100, 2)
        remaining = float(budget)
        results = []
        for slot in self.engine.slots:
            sellable_quantity = slot.sellable_quantity if self.engine.t_plus_one else slot.quantity
            if sellable_quantity <= 0:
                continue
            if round(remaining, 2) + 0.000001 < minimum_lot_value:
                break
            slot_value = round(sellable_quantity * price, 2)
            result = self.engine.sell(slot.index, node, min(remaining, slot_value))
            results.append(result)
            if not result.accepted:
                continue
            remaining = round(remaining - result.amount, 2)
        return results

    def _sell_by_quantity(self, node: TradeNode, quantity: int):
        if not self.engine:
            return []
        remaining = self._whole_lot_quantity(quantity)
        results = []
        for slot in self.engine.slots:
            sellable_quantity = slot.sellable_quantity if self.engine.t_plus_one else slot.quantity
            if sellable_quantity <= 0 or remaining <= 0:
                continue
            slot_quantity = min(remaining, sellable_quantity)
            result = self.engine.sell(slot.index, node, quantity=slot_quantity)
            results.append(result)
            if result.accepted:
                remaining -= result.quantity
        return results

    def _sell_all_sellable(self, node: TradeNode):
        if not self.engine:
            return []
        results = []
        for slot in self.engine.slots:
            sellable_quantity = slot.sellable_quantity if self.engine.t_plus_one else slot.quantity
            if sellable_quantity <= 0:
                continue
            results.append(self.engine.sell(slot.index, node))
        return results

    def pan_left(self, steps: int = 10) -> None:
        if not self.engine:
            return
        if self.test_trade_active:
            self.viewed_bar_index = max(0, self._displayed_bar_index() - steps)
            self.pan_offset = 0
            self._sync_date_input_to_viewed_bar()
            self._refresh(persist=False)
            return
        self.pan_offset = min(self.engine.current_index, self.pan_offset + steps)
        self.viewed_bar_index = self.engine.current_index - self.pan_offset
        self._sync_date_input_to_viewed_bar()
        self._refresh(persist=False)

    def pan_right(self, steps: int = 10) -> None:
        if not self.engine:
            return
        if self.test_trade_active:
            self.viewed_bar_index = min(
                len(self.engine.bars) - 1,
                self._displayed_bar_index() + steps,
            )
            self.pan_offset = 0
            self._sync_date_input_to_viewed_bar()
            self._refresh(persist=False)
            return
        self.pan_offset = max(0, self.pan_offset - steps)
        self.viewed_bar_index = self.engine.current_index - self.pan_offset
        self._sync_date_input_to_viewed_bar()
        self._refresh(persist=False)

    def pan_reset(self) -> None:
        self.pan_offset = 0
        if self.engine:
            self.viewed_bar_index = (
                min(
                    len(self.engine.bars) - 1,
                    self.engine.current_index + self._test_trade_future_slots,
                )
                if self.test_trade_active
                else self.engine.current_index
            )
            self._sync_date_input_to_viewed_bar()
        self._refresh(persist=False)

    def pan_to_latest(self, update_status: bool = True) -> None:
        if not self.engine:
            return
        self.pan_offset = 0
        self.viewed_bar_index = (
            min(
                len(self.engine.bars) - 1,
                self.engine.current_index + self._test_trade_future_slots,
            )
            if self.test_trade_active
            else self.engine.current_index
        )
        self._sync_date_input_to_viewed_bar()
        self.kline_widget.selected_bar_date = self.engine.current_bar.date
        self._refresh(persist=False)
        if update_status:
            if self.test_trade_active:
                self._update_status(f"已回到测试交易日 {self.engine.current_bar.date}。")
            else:
                label = "当前训练截止时间" if self.training_mode else "最新可用时间"
                self._update_status(f"已定位到{label} {self.engine.current_bar.date}。")

    def pan_to_earliest(self) -> None:
        if not self.engine:
            return
        earliest_window_end = min(self.engine.current_index, max(0, self.chart_window_size - 1))
        self.pan_offset = self.engine.current_index - earliest_window_end
        self.viewed_bar_index = 0
        self._sync_date_input_to_viewed_bar()
        self.kline_widget.selected_bar_date = self.engine.bars[0].date
        self._refresh(persist=False)
        self._update_status(f"已定位到最早可用时间 {self.engine.bars[0].date}。")

    def zoom_in(self) -> None:
        self.chart_window_size = max(MIN_CHART_WINDOW_SIZE, int(self.chart_window_size * ZOOM_IN_FACTOR))
        self._refresh(persist=False)

    def zoom_out(self) -> None:
        self.chart_window_size = min(MAX_CHART_WINDOW_SIZE, int(self.chart_window_size * ZOOM_OUT_FACTOR))
        self._refresh(persist=False)

    def zoom_in_fully(self) -> None:
        """放大到极致（屏幕显示最少K线），等效于 Ctrl+滚轮向上滚到极限。"""
        self.chart_window_size = MIN_CHART_WINDOW_SIZE
        self._refresh(persist=False)

    def zoom_out_fully(self) -> None:
        """缩小到极致（屏幕显示最多K线），等效于 Ctrl+滚轮向下滚到极限。"""
        self.chart_window_size = MAX_CHART_WINDOW_SIZE
        self._refresh(persist=False)

    def zoom_reset(self) -> None:
        self.chart_window_size = DEFAULT_CHART_WINDOW_SIZE
        self.reveal_current_full = self.current_node == TradeNode.CLOSE
        self._refresh(persist=False)

    def _refresh(self, *, persist: bool = True) -> None:
        if getattr(self, "sector_integration", None):
            self.sector_integration.sync()
        if not self.engine:
            return
        self._refresh_round_log()
        self._sync_start_button_label()
        if persist and self.training_mode and self.trade_started and not self.test_trade_active:
            self._schedule_persist()
        display_index = self._displayed_bar_index()
        bar = self.engine.bars[display_index]
        display_reveal_full = (
            True
            if self.test_trade_active
            else display_index < self.engine.current_index or self.reveal_current_full
        )
        snapshot = self.engine.snapshot(self.current_node)
        self._update_initial_cash_input_state()
        if self.training_mode and self.selected_buy_ratio is not None:
            self._sync_buy_budget_from_selected_ratio()
        if self.training_mode and self.selected_sell_ratio is not None:
            self._sync_sell_budget_from_selected_ratio()
        elif self.training_mode and self._sellable_market_value(self.current_node) <= 0:
            self.sell_budget_input.setText("0")
        self._sync_trade_quantity_inputs()
        if self.training_mode and self.trade_started:
            self._record_equity_point(snapshot.total_asset)
        has_performance_data = bool(
            self.engine.trades or (self._uses_round_records() and self.round_records)
        )
        completed_multi_stock_rounds = bool(self._uses_round_records() and self.round_records)
        self.performance_overlay.set_available(
            bool(
                self.training_mode
                and has_performance_data
                and (self.trade_started or completed_multi_stock_rounds)
            )
        )
        self._update_trade_button_states()
        self._sync_menu_actions()
        self._set_account_inactive(
            not (self.training_mode and (self.trade_started or self.test_trade_active))
        )
        if not self.training_mode:
            stock_name = self.browsing_stock_name
        elif bar.code == SHANGHAI_INDEX_CODE:
            stock_name = SHANGHAI_INDEX_NAME
        else:
            stock_name = (
                SAMPLE_KLINE_NAME
                if self.using_sample_kline
                else self._prefetched_stock_names.get(bar.code) or self.info_reader.name_for(bar.code)
            )
        is_shanghai_index = bar.code == SHANGHAI_INDEX_CODE
        self.identity_toggle.setVisible(not is_shanghai_index)
        self._sync_identity_input_privacy(is_shanghai_index)
        self.kline_widget.show_time_marks = True if is_shanghai_index else self.identity_toggle.isChecked()
        title_html = self._format_title_html(bar, stock_name, display_index, display_reveal_full)
        full_title_html = self._format_title_html(bar, stock_name, display_index, True)
        self._set_stable_title_text(title_html, full_title_html)
        self._refresh_market_metrics(display_index, display_reveal_full)
        pan_note = f"  历史左移 {self.pan_offset} 日" if self.pan_offset else ""
        if display_reveal_full:
            self.day_info.setText(f"开 {bar.open:.2f}  高 {bar.high:.2f}  低 {bar.low:.2f}  收 {bar.close:.2f}{pan_note}")
        else:
            self.day_info.setText(f"开 {bar.open:.2f}  当前处于开盘阶段，收盘K线未揭示{pan_note}")
        if not self.training_mode:
            for label in (
                self.cash_label,
                self.position_label,
                self.position_profit_label,
                self.asset_label,
                self.cumulative_holding_days_label,
                self.profit_label,
                self.max_drawdown_label,
            ):
                label.setText("--")
                if label.property("profit") is not None:
                    label.setProperty("profit", None)
                    _repolish_widget(label)
            self.position_ratio_bar.setValue(0)
            self.position_ratio_bar.setFormat("行情浏览模式")
            self._draw_chart()
            return
        self.cash_label.setText(f"{snapshot.cash:,.2f}")
        position_quantity = sum(slot.quantity for slot in snapshot.slots)
        self.position_label.setText(f"{snapshot.position_value:,.2f}（共{position_quantity}股）")
        position_profit_text = f"{snapshot.position_profit:,.2f} ({snapshot.position_profit_rate:.2f}%)"
        position_profit_trend = "up" if snapshot.position_profit >= 0 else "down"
        position_profit_changed = self.position_profit_label.property("profit") != position_profit_trend
        self.position_profit_label.setText(position_profit_text)
        if position_profit_changed:
            self.position_profit_label.setProperty("profit", position_profit_trend)
            _repolish_widget(self.position_profit_label)
        self.asset_label.setText(f"{snapshot.total_asset:,.2f}")
        self.cumulative_holding_days_label.setText(f"{self._cumulative_holding_days()} 天")
        profit_text = f"{snapshot.total_profit:,.2f} ({snapshot.profit_rate:.2f}%)"
        profit_trend = "up" if snapshot.total_profit >= 0 else "down"
        profit_changed = self.profit_label.property("profit") != profit_trend
        self.profit_label.setText(profit_text)
        if profit_changed:
            self.profit_label.setProperty("profit", profit_trend)
            _repolish_widget(self.profit_label)
        max_drawdown = maximum_drawdown(self.equity_curve, self._minimum_valid_equity()) if self.trade_started else 0.0
        self.max_drawdown_label.setText(f"{max_drawdown:.2f}%")
        drawdown_trend = "down" if max_drawdown < 0 else "up"
        if self.max_drawdown_label.property("profit") != drawdown_trend:
            self.max_drawdown_label.setProperty("profit", drawdown_trend)
            _repolish_widget(self.max_drawdown_label)
        if self.trade_started:
            self._refresh_allocation_bar(snapshot.position_value, snapshot.total_asset)
        else:
            self.position_ratio_bar.setValue(0)
            self.position_ratio_bar.setFormat("训练准备：可在开盘或尾盘完成第一笔买入")
        self._draw_chart()

    @staticmethod
    def _round_record_first_buy_timestamp(record: RoundRecord) -> str:
        first_buy_date = next(
            (
                trade.date
                for trade in record.trades
                if trade.accepted and trade.side == "buy" and trade.date
            ),
            record.start_date,
        )
        return str(first_buy_date or "").replace("-", "")

    def _refresh_round_log(self) -> None:
        if not hasattr(self, "round_log"):
            return
        signature = (
            self.identity_toggle.isChecked(), self.training_mode_kind, self.reviewed_round_index,
            tuple((record.index, record.code, record.name, record.profit,
                   self._round_record_first_buy_timestamp(record)) for record in self.round_records),
        )
        if getattr(self, "_round_log_signature", None) == signature:
            return
        self._round_log_signature = signature
        self.round_log.clear()
        reviewed_item = None
        show_identity = self.identity_toggle.isChecked()
        if not self.round_records:
            placeholder_text = (
                "尚无练习记录；换股后记录"
                if self.training_mode_kind == TRAINING_MODE_INDEPENDENT
                else "尚无完成轮次；换股续作后记录"
            )
            placeholder = QListWidgetItem(placeholder_text)
            placeholder.setForeground(QColor("#5c6b80"))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.round_log.addItem(placeholder)
            return
        for record in self.round_records:
            if show_identity:
                identity = f"{record.code.upper()}{record.name}" if record.name else record.code.upper()
            else:
                identity = "股票***"
            amount = abs(record.profit)
            amount_text = f"{amount:.0f}"
            if record.profit > 0:
                amount_text = "+" + amount_text
            elif record.profit < 0:
                amount_text = "-" + amount_text
            text = f"{record.index:02d}-{identity} {amount_text}"
            timestamp = self._round_record_first_buy_timestamp(record)
            item = QListWidgetItem(f"{text} {timestamp}".rstrip())
            if record.profit > 0:
                profit_color = "#ff5555"
            elif record.profit < 0:
                profit_color = "#4ade80"
            else:
                profit_color = "#8ea3bb"
            # The custom row widget below owns all visible text. Keep the
            # QListWidgetItem text for lookup/accessibility without painting a
            # second copy underneath it.
            item.setForeground(QColor(0, 0, 0, 0))
            item.setSizeHint(QSize(0, 28))
            self.round_log.addItem(item)
            row_widget = QWidget(self.round_log)
            row_widget.setObjectName("RoundLogRow")
            row_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            row_widget.setStyleSheet("background: transparent;")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(8, 0, 8, 0)
            row_layout.setSpacing(8)
            record_label = QLabel(text)
            record_label.setStyleSheet(f"background: transparent; color: {profit_color};")
            row_layout.addWidget(record_label, 1)
            timestamp_label = QLabel(timestamp)
            timestamp_label.setObjectName("RoundTimestamp")
            timestamp_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            timestamp_label.setMinimumWidth(76)
            timestamp_label.setStyleSheet("background: transparent; color: #ffffff;")
            row_layout.addWidget(timestamp_label)
            self.round_log.setItemWidget(item, row_widget)
            if record.index == self.reviewed_round_index:
                reviewed_item = item
        if reviewed_item is not None:
            self.round_log.setCurrentItem(reviewed_item)

    def _open_round_review(self, item) -> None:
        if item is None:
            return
        row = self.round_log.row(item)
        if row is None or row < 0 or row >= len(self.round_records):
            return
        record = self.round_records[row]
        try:
            bars, name = self._load_stock_bars(record.code, record.source)
        except Exception as exc:
            self._update_status(f"无法载入 {record.code} 历史K线：{exc}")
            return
        view_index = self._index_for_date(bars, record.end_date or record.start_date)
        if view_index is None:
            view_index = 0
        self._persist_session()
        self._open_review_browse(bars, name, record, view_index)

    def _open_review_browse(self, bars, name: str, record: RoundRecord, view_index: int) -> None:
        identity = name.rsplit(" ", 1)[-1] if self.identity_toggle.isChecked() else "当前股票"
        label = f"{record.index:02d} 轮 {identity} 历史K线（{record.start_date} 起）"
        self._activate_browse_engine(
            bars, name, f"已进入 {label}，可左右平移查看；点“回到正在交易”返回当前训练。", view_index=view_index,
        )
        self.reviewed_round_index = record.index
        # Review mode must retain the record's source. Otherwise a sample-K-line
        # review incorrectly tries to start from a TDX directory on fresh start.
        self.using_sample_kline = record.source == "sample"
        # Keep the traded stock's buy/sell markers while reviewing it.
        self.engine.trades = list(record.trades)
        # Restore the completed trade-cycle ranges so the chart draws the held
        # intervals, profit strips and the hover "本轮持有 X 天".
        self.completed_trade_ranges = [tuple(item) for item in record.ranges]
        self._refresh()

    def _capture_return_context_if_trading(self) -> None:
        # A training session remains returnable during the preparation phase
        # before its first buy.  Independent mode enters that phase after each
        # stock switch, so requiring ``trade_started`` loses the return target
        # when the user temporarily opens the Shanghai index with 03/SZZS.
        if not (self.training_mode and self.engine):
            return
        self._return_to_trading_context = self._capture_trading_context()
        self._sync_return_button_state()

    def _capture_trading_context(self) -> dict:
        return {
            "engine": self.engine,
            "training_mode": self.training_mode,
            "trade_started": self.trade_started,
            "current_node": self.current_node,
            "reveal_current_full": self.reveal_current_full,
            "advance_button_show_close": self._advance_button_show_close,
            "first_buy_price": self.first_buy_price,
            "first_buy_index": self.first_buy_index,
            "first_buy_node": self.first_buy_node,
            "active_cycle_start_cash": self.active_cycle_start_cash,
            "frozen_position_metrics": dict(self._frozen_position_metrics or {}),
            "completed_trade_ranges": list(self.completed_trade_ranges),
            "equity_curve": list(self.equity_curve),
            "equity_points": list(self.equity_points),
            "round_equity_points": list(self.round_equity_points),
            "cumulative_holding_days_base": self.cumulative_holding_days_base,
            "round_records": list(self.round_records),
            "round_start_cash": self.round_start_cash,
            "round_start_date": self.round_start_date,
            "round_start_node": self.round_start_node,
            "account_initial_cash": self.account_initial_cash,
            "account_baseline_locked": self.account_baseline_locked,
            "engine_epoch": self.engine_epoch,
            "using_sample_kline": self.using_sample_kline,
            "pan_offset": self.pan_offset,
            "viewed_bar_index": self.viewed_bar_index,
            "browsing_stock_name": self.browsing_stock_name,
        }

    def _return_to_trading(
        self,
        _checked: bool = False,
        *,
        update_status: bool = True,
    ) -> None:
        if self.test_trade_active:
            self.exit_test_trade_mode(update_status=False)
        context = self._return_to_trading_context
        if not context:
            self._update_status("当前没有可返回的正在交易股票。")
            return
        self.engine = context["engine"]
        self.training_mode = context["training_mode"]
        self.trade_started = context["trade_started"]
        self.current_node = context["current_node"]
        self.reveal_current_full = context["reveal_current_full"]
        self._advance_button_show_close = not self.reveal_current_full
        self.first_buy_price = context["first_buy_price"]
        self.first_buy_index = context["first_buy_index"]
        self.first_buy_node = context["first_buy_node"]
        self.active_cycle_start_cash = context["active_cycle_start_cash"]
        self._frozen_position_metrics = dict(context.get("frozen_position_metrics") or {}) or None
        self.completed_trade_ranges = list(context["completed_trade_ranges"])
        self.equity_curve = list(context["equity_curve"])
        self.equity_points = list(context.get("equity_points", []))
        self.round_equity_points = list(context.get("round_equity_points", []))
        self.cumulative_holding_days_base = context["cumulative_holding_days_base"]
        self.round_records = list(context["round_records"])
        self.round_start_cash = context["round_start_cash"]
        self.round_start_date = context["round_start_date"]
        self.round_start_node = context.get("round_start_node", TradeNode.OPEN)
        self.account_initial_cash = context["account_initial_cash"]
        self.account_baseline_locked = context["account_baseline_locked"]
        self.engine_epoch = context["engine_epoch"]
        self.using_sample_kline = context["using_sample_kline"]
        self.pan_offset = context["pan_offset"]
        self.viewed_bar_index = context["viewed_bar_index"]
        self.browsing_stock_name = context["browsing_stock_name"]
        self.index_overlay_active = False
        self.kline_widget.suppress_user_annotations = False
        self.last_space_tap_time = 0.0
        self.code_input.setText(self.engine.current_bar.code)
        self._sync_date_input_to_viewed_bar()
        self._last_equity_record_key = None
        self._sync_continuous_mode_widget()
        self._sync_random_btn_tooltip()
        self._clear_return_context()
        # Browsing the index hides account actions.  Restore the complete
        # record/action area after putting the training context back, rather
        # than waiting for a stock switch to trigger this synchronization.
        self._sync_round_log_visibility()
        self._refresh()
        identity = "当前股票"
        if self.identity_toggle.isChecked():
            code = self.engine.current_bar.code
            identity = f"{code}{self._current_stock_name(code)}"
        if update_status:
            self._update_status(
                f"已回到正在交易：{identity}。"
            )

    def _clear_return_context(self) -> None:
        self._return_to_trading_context = None
        self.reviewed_round_index = None
        self._sync_return_button_state()

    def _sync_return_button_state(self) -> None:
        if not hasattr(self, "return_trade_btn"):
            return
        has_context = self._return_to_trading_context is not None
        self.return_trade_btn.setVisible(self._uses_round_records() and has_context)
        self.return_trade_btn.setEnabled(has_context)
        if hasattr(self, "simulation_return_action"):
            self.simulation_return_action.setEnabled(has_context)

    def _reset_training_state(self) -> None:
        if not self._uses_round_records():
            self._update_status("单吊模式不提供一键重置训练状态。")
            return
        if not self.engine or not self.training_mode:
            self._update_status("当前没有可重置的训练状态。")
            return
        has_training_state = bool(
            self.trade_started
            or self.round_records
            or self.engine.trades
            or self.completed_trade_ranges
            or self._has_position()
        )
        if not has_training_state:
            self._update_status("当前已是未交易的初始状态。")
            return
        mode_name = TRAINING_MODE_LABELS[self.training_mode_kind]
        answer = QMessageBox.question(
            self,
            "一键重置",
            f"确定将{mode_name}重置到未交易状态吗？\n"
            "所有轮次记录、买卖记录、持仓和累计盈亏都会清除，账户回到初始本金；当前训练模式保留。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._reset_account_after_training_mode_switch()
        self._sync_round_log_visibility()
        self._update_status(f"已将{mode_name}重置为未交易状态，账户已回到初始本金。")

    def _build_session_payload(self) -> dict:
        code = self.engine.current_bar.code
        name = self._current_stock_name(code)
        return {
            "version": 1,
            "training_mode": self.training_mode_kind,
            "continuous_compound_mode": self.continuous_compound_mode,
            "using_sample_kline": self.using_sample_kline,
            "account_initial_cash": self.account_initial_cash,
            "cumulative_holding_days_base": self.cumulative_holding_days_base,
            "equity_curve": self.equity_curve,
            "equity_points": [equity_point_to_dict(point) for point in self.equity_points],
            "round_equity_points": [equity_point_to_dict(point) for point in self.round_equity_points],
            "round_records": [round_to_dict(record) for record in self.round_records],
            "active": {
                "code": code,
                "name": name,
                "current_index": self.engine.current_index,
                "current_date": self.engine.current_bar.date,
                "cash": self.engine.cash,
                "slots": [slot_to_dict(slot) for slot in self.engine.slots],
                "trades": [trade_to_dict(trade) for trade in self.engine.trades],
                "first_buy_price": self.first_buy_price,
                "first_buy_index": self.first_buy_index,
                "first_buy_node": self.first_buy_node.value if self.first_buy_node else None,
                "active_cycle_start_cash": self.active_cycle_start_cash,
                "frozen_position_metrics": self._frozen_position_metrics,
                "completed_trade_ranges": [list(item) for item in self.completed_trade_ranges],
                "trade_started": self.trade_started,
                "current_node": self.current_node.value,
                "reveal_current_full": self.reveal_current_full,
                "advance_button_show_close": self._advance_button_show_close,
                "round_start_cash": self.round_start_cash,
                "round_start_date": self.round_start_date,
                "round_start_node": self.round_start_node.value,
                "engine_epoch": self.engine_epoch,
            },
        }

    def _persist_session(self, include_ordinary: bool = False) -> None:
        if self._migration_restore_pending_restart or self.test_trade_active:
            return
        if not self._uses_round_records() and not include_ordinary:
            delete_document()
            return
        if not self.engine or not self.training_mode:
            return
        if not (self.trade_started or self.round_records or self.engine.trades):
            return
        save_document(self._build_session_payload())

    def _schedule_persist(self) -> None:
        if self._migration_restore_pending_restart or not hasattr(self, "_persist_timer"):
            return
        self._persist_timer.start()

    def _restore_session(self) -> bool:
        document = load_document()
        if document is None:
            return False
        try:
            validate_session_document(document)
        except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
            preserve_invalid_file(session_path())
            self._show_storage_notices()
            return False
        active = document["active"]
        code = active.get("code", "")
        if not code:
            return False
        source = "sample" if document.get("using_sample_kline") else "tdx"
        try:
            bars, _name = self._load_stock_bars(code, source)
        except Exception:
            return False
        target_index = self._index_for_date(
            bars,
            active.get("current_date", ""),
            active.get("current_index"),
        )
        if target_index is None:
            return False
        account_initial_cash = float(document.get("account_initial_cash") or self.settings.initial_cash)
        if account_initial_cash <= 0:
            account_initial_cash = self.settings.initial_cash
        engine = DailySimulationEngine(
            bars=bars,
            initial_cash=account_initial_cash,
            slot_count=self.settings.slot_count,
            commission_rate=self.settings.commission_rate,
            stamp_tax_rate=self.settings.stamp_tax_rate,
            min_commission=self.settings.min_commission,
            start_index=target_index,
        )
        engine.start()
        engine.current_index = target_index
        engine.cash = round(float(active.get("cash", account_initial_cash)), 2)
        engine.slots = [slot_from_dict(data, index) for index, data in enumerate(active.get("slots", []))]
        if len(engine.slots) < self.settings.slot_count:
            engine.slots = engine.slots + [PositionSlot(index=i) for i in range(len(engine.slots), self.settings.slot_count)]
        engine.trades = [trade_from_dict(data) for data in active.get("trades", [])]

        self.engine = engine
        self.training_mode = True
        self.trade_started = bool(active.get("trade_started", False))
        self.using_sample_kline = bool(document.get("using_sample_kline", False))
        restored_mode = document.get("training_mode")
        if restored_mode not in TRAINING_MODE_LABELS:
            restored_mode = (
                TRAINING_MODE_CONTINUOUS
                if bool(document.get("continuous_compound_mode", True))
                else TRAINING_MODE_SINGLE
            )
        self.training_mode_kind = restored_mode
        self.continuous_compound_mode = restored_mode == TRAINING_MODE_CONTINUOUS
        self.settings.training_mode = restored_mode
        self.settings.continuous_compound_mode = self.continuous_compound_mode
        self.account_initial_cash = account_initial_cash
        self.round_start_cash = active.get("round_start_cash")
        self.round_start_date = active.get("round_start_date", "")
        self.round_start_node = TradeNode(active.get("round_start_node", "open"))
        self.cumulative_holding_days_base = int(document.get("cumulative_holding_days_base", 0))
        self.equity_curve = list(document.get("equity_curve", []))
        self.equity_points = [equity_point_from_dict(item) for item in document.get("equity_points", [])]
        self.round_equity_points = [
            equity_point_from_dict(item) for item in document.get("round_equity_points", [])
        ]
        self.round_records = [round_from_dict(item) for item in document.get("round_records", [])]
        self.completed_trade_ranges = [tuple(item) for item in active.get("completed_trade_ranges", [])]
        self.first_buy_price = active.get("first_buy_price")
        self.first_buy_index = active.get("first_buy_index")
        self.first_buy_node = TradeNode(active["first_buy_node"]) if active.get("first_buy_node") else TradeNode.OPEN
        self.active_cycle_start_cash = active.get("active_cycle_start_cash")
        frozen_position_metrics = active.get("frozen_position_metrics") or {}
        self._frozen_position_metrics = {
            str(name): (str(value[0]), str(value[1]))
            for name, value in frozen_position_metrics.items()
            if name in POSITION_MARKET_ITEMS and isinstance(value, (list, tuple)) and len(value) == 2
        } or None
        self.current_node = TradeNode(active.get("current_node", "open"))
        self.reveal_current_full = bool(active.get("reveal_current_full", False))
        self._advance_button_show_close = not self.reveal_current_full
        self.engine_epoch = int(active.get("engine_epoch", 0))
        self.account_baseline_locked = self.trade_started or bool(self.round_records)
        self.last_space_tap_time = 0.0
        self.index_overlay_active = False
        self.kline_widget.suppress_user_annotations = False
        self._reset_drawdown_overlay()
        self.browsing_stock_name = ""
        self.pan_offset = 0
        self.viewed_bar_index = self.engine.current_index
        self.code_input.setText(self.engine.current_bar.code)
        self._sync_date_input_to_viewed_bar()
        self._last_equity_record_key = None
        self.kline_widget.clear_user_annotations()
        self._sync_continuous_mode_widget()
        self._sync_round_log_visibility()
        self._sync_random_btn_tooltip()
        self._refresh()
        self._update_status(
            f"已恢复上次训练：{code}{active.get('name', '')}，现金 {self.engine.cash:,.2f}。"
        )
        return True

    def _displayed_bar_index(self) -> int:
        if not self.engine:
            return 0
        fallback = self.engine.current_index - self.pan_offset
        selected = fallback if self.viewed_bar_index is None else self.viewed_bar_index
        maximum = len(self.engine.bars) - 1 if self.test_trade_active else self.engine.current_index
        return max(0, min(selected, maximum))

    def _sync_date_input_to_viewed_bar(self) -> None:
        if not self.engine:
            return
        index = self._displayed_bar_index()
        self.date_input.setText(self.engine.bars[index].date.replace("-", ""))

    def _set_account_inactive(self, inactive: bool) -> None:
        widgets: list[QWidget] = [
            self.cash_input,
            self.cash_label,
            self.position_label,
            self.position_profit_label,
            self.asset_label,
            self.cumulative_holding_days_label,
            self.profit_label,
            self.max_drawdown_label,
            *self.account_key_labels.values(),
        ]
        for widget in widgets:
            if widget.property("accountInactive") != inactive:
                widget.setProperty("accountInactive", inactive)
                _repolish_widget(widget)

    def _performance_records_for_overlay(self) -> list[RoundRecord]:
        if not self.engine:
            return []
        current = None
        if self.engine.trades:
            mode = (
                "continuous"
                if self.continuous_compound_mode
                else "independent"
                if self.training_mode_kind == TRAINING_MODE_INDEPENDENT
                else "ordinary"
            )
            current_index = len(self.round_records) + 1 if self._uses_round_records() else 1
            current = self._current_performance_record(current_index, mode)
        if self._uses_round_records():
            records = list(self.round_records)
            if current is not None:
                records.append(current)
            return records
        return [current] if current is not None else []

    @staticmethod
    def _segments_for_record(record: RoundRecord) -> list[TradeSegment]:
        if record.segments:
            return list(record.segments)
        running_asset = float(record.start_cash or max(1.0, record.end_asset - record.profit))
        segments: list[TradeSegment] = []
        for index, item in enumerate(record.ranges, start=1):
            if len(item) < 3:
                continue
            start_index, end_index, profit = item[:3]
            profit = float(profit)
            end_asset = round(running_asset + profit, 2)
            rate = round(profit / running_asset * 100, 6) if running_asset > 0 else 0.0
            segments.append(
                TradeSegment(
                    index=index,
                    start_date=record.start_date,
                    end_date=record.end_date,
                    start_node=record.start_node,
                    end_node=record.end_node,
                    start_asset=round(running_asset, 2),
                    end_asset=end_asset,
                    profit=round(profit, 2),
                    return_rate=rate,
                    holding_days=abs(int(end_index) - int(start_index)) + 1,
                    buy_count=0,
                    sell_count=0,
                    fee=0.0,
                    tax=0.0,
                )
            )
            running_asset = end_asset
        return segments

    def _calculate_performance_scope(
        self, records: list[RoundRecord]
    ) -> tuple[PerformanceMetrics, list, str, TradeNode, str, TradeNode] | None:
        if not records:
            return None
        segments = [segment for record in records for segment in self._segments_for_record(record)]
        trades = [trade for record in records for trade in record.trades]
        first = records[0]
        last = records[-1]
        independent = self.training_mode_kind == TRAINING_MODE_INDEPENDENT
        if independent:
            initial_asset = sum(
                float(record.start_cash or max(1.0, record.end_asset - record.profit))
                for record in records
            )
            ending_asset = sum(
                float(record.end_asset or record.start_cash + record.profit)
                for record in records
            )
            start_record = min(records, key=lambda record: record.start_date or "9999-99-99")
            end_record = max(records, key=lambda record: record.end_date or "")
            start_date = start_record.start_date
            start_node = start_record.start_node
            end_date = end_record.end_date
            end_node = end_record.end_node
        else:
            initial_asset = float(
                (self.account_initial_cash if self.continuous_compound_mode else first.start_cash)
                or first.start_cash
                or max(1.0, first.end_asset - first.profit)
            )
        if not independent and self.engine and records[-1].status == "active":
            ending_asset = self.engine.snapshot(self.current_node).total_asset
            end_date = self.engine.current_bar.date
            end_node = self.current_node
        elif not independent:
            ending_asset = last.end_asset or (last.start_cash + last.profit)
            end_date = last.end_date
            end_node = last.end_node
        if self.continuous_compound_mode:
            equity_points = list(self.equity_points)
        elif independent:
            equity_points = []
        else:
            equity_points = list(first.equity_points)
        if not equity_points and not independent:
            equity_points = [point for record in records for point in record.equity_points]
        try:
            index_bars = self._index_bars_for_preview()
        except Exception:
            index_bars = []
        metrics = calculate_performance_metrics(
            initial_asset=initial_asset,
            ending_asset=ending_asset,
            segments=segments,
            trades=trades,
            equity_points=equity_points,
            index_bars=index_bars,
            start_date=start_date if independent else first.start_date,
            start_node=start_node if independent else first.start_node,
            end_date=end_date,
            end_node=end_node,
            stock_count=len({record.code for record in records if record.code}),
            round_count=len(records),
        )
        return (
            metrics,
            index_bars,
            start_date if independent else first.start_date,
            start_node if independent else first.start_node,
            end_date,
            end_node,
        )

    @staticmethod
    def _performance_tone(value: float | None, positive_threshold: float = 0.0) -> str:
        if value is None:
            return "muted"
        if value > positive_threshold:
            return "up"
        if value < positive_threshold:
            return "down"
        return ""

    @staticmethod
    def _performance_money(value: float | None, signed: bool = False) -> str:
        if value is None:
            return "--"
        prefix = "+" if signed and value > 0 else ""
        return f"{prefix}{value:,.2f}"

    @staticmethod
    def _performance_percent(value: float | None, signed: bool = False) -> str:
        if value is None:
            return "--"
        prefix = "+" if signed and value > 0 else ""
        return f"{prefix}{value:.2f}%"

    @staticmethod
    def _performance_ratio(value: float | None) -> str:
        if value is None:
            return "--"
        return "无亏损" if math.isinf(value) else f"{value:.2f}"

    def _refresh_performance_overlay_current(self) -> None:
        if not self.engine or not self.training_mode:
            return
        has_completed_rounds = bool(self._uses_round_records() and self.round_records)
        if not (self.engine.trades or has_completed_rounds):
            return
        if not self.trade_started and not has_completed_rounds:
            return
        self._refresh_performance_overlay(self.engine.snapshot(self.current_node))

    def _refresh_performance_after_trade(self) -> None:
        """Invalidate statistics only after a successful fill, then refresh if visible."""
        self._performance_summary_key = None
        self._refresh_performance_after_market_step()

    def _refresh_performance_after_market_step(self) -> None:
        """Refresh visible statistics after a date or open/close phase change."""
        if self.performance_overlay.expanded:
            self._refresh_performance_overlay_current()

    def _refresh_performance_overlay(self, snapshot) -> None:
        records = self._performance_records_for_overlay()
        summary_key = (
            self.engine_epoch,
            self.training_mode_kind,
            self.current_node,
            self.reveal_current_full,
            round(snapshot.total_asset, 2),
            self.identity_toggle.isChecked(),
            len(self.equity_points),
            tuple(
                (
                    record.index,
                    record.status,
                    record.end_date,
                    round(record.end_asset, 2),
                    round(record.profit, 2),
                    len(record.trades),
                    len(record.segments),
                    len(record.equity_points),
                )
                for record in records
            ),
        )
        if summary_key == self._performance_summary_key:
            return
        scope = self._calculate_performance_scope(records)
        if scope is None:
            return
        metrics, _index_bars, start_date, _start_node, end_date, _end_node = scope
        if self.continuous_compound_mode:
            title = "连续复利 · 全区间统计"
            subtitle = (
                f"{start_date} → {end_date}   "
                f"{metrics.stock_count}只股票 / {metrics.round_count}轮"
            )
        elif self.training_mode_kind == TRAINING_MODE_INDEPENDENT:
            title = "独立训练 · 区间汇总"
            subtitle = (
                f"{start_date} → {end_date}   "
                f"{metrics.stock_count}只股票 / {metrics.round_count}轮（资金独立）"
            )
        else:
            record = records[0]
            identity = (
                f"{record.code.upper()} {record.name}" if self.identity_toggle.isChecked() else "当前股票"
            )
            title = f"单吊模式 · {identity}"
            status = "进行中" if self._has_position() else "已清仓"
            subtitle = f"{start_date} → {end_date}   {status}"
        values = {
            "initial_asset": (self._performance_money(metrics.initial_asset), ""),
            "ending_asset": (
                self._performance_money(metrics.ending_asset),
                self._performance_tone(metrics.net_profit),
            ),
            "net_profit": (
                self._performance_money(metrics.net_profit, signed=True),
                self._performance_tone(metrics.net_profit),
            ),
            "total_return": (
                self._performance_percent(metrics.total_return, signed=True),
                self._performance_tone(metrics.total_return),
            ),
            "annual_return": (
                self._performance_percent(metrics.annual_return, signed=True),
                self._performance_tone(metrics.annual_return),
            ),
            "segment_count": (f"{metrics.segment_count} 段", ""),
            "win_rate": (
                self._performance_percent(metrics.win_rate),
                self._performance_tone(metrics.win_rate, 50.0),
            ),
            "profit_loss_ratio": (
                self._performance_ratio(metrics.profit_loss_ratio),
                self._performance_tone(metrics.profit_loss_ratio, 1.0),
            ),
            "profit_factor": (
                self._performance_ratio(metrics.profit_factor),
                self._performance_tone(metrics.profit_factor, 1.0),
            ),
            "expectancy": (
                self._performance_percent(metrics.expectancy, signed=True),
                self._performance_tone(metrics.expectancy),
            ),
            "benchmark_return": (
                self._performance_percent(metrics.benchmark_return, signed=True),
                self._performance_tone(metrics.benchmark_return),
            ),
            "excess_return": (
                self._performance_percent(metrics.excess_return, signed=True),
                self._performance_tone(metrics.excess_return),
            ),
            "max_drawdown": (
                self._performance_percent(metrics.max_drawdown),
                "down" if metrics.max_drawdown < 0 else "",
            ),
            "annual_volatility": (self._performance_percent(metrics.annual_volatility), ""),
            "sharpe_ratio": (
                self._performance_ratio(metrics.sharpe_ratio),
                self._performance_tone(metrics.sharpe_ratio),
            ),
            "sortino_ratio": (
                self._performance_ratio(metrics.sortino_ratio),
                self._performance_tone(metrics.sortino_ratio),
            ),
            "return_drawdown_ratio": (
                "无回撤" if math.isinf(metrics.return_drawdown_ratio or 0.0)
                else self._performance_ratio(metrics.return_drawdown_ratio),
                self._performance_tone(metrics.return_drawdown_ratio),
            ),
            "average_win": (
                self._performance_percent(metrics.average_win, signed=True),
                "up" if metrics.average_win is not None else "muted",
            ),
            "average_loss": (
                self._performance_percent(metrics.average_loss),
                "down" if metrics.average_loss is not None else "muted",
            ),
            "fee_and_tax": (self._performance_money(metrics.fee_and_tax), ""),
        }
        if self.training_mode_kind == TRAINING_MODE_INDEPENDENT:
            hint = f"样本 {metrics.segment_count} 段 · 建议至少 30 段后再判断稳定性"
        else:
            hint = ""
        if self.training_mode_kind == TRAINING_MODE_CONTINUOUS and metrics.sample_days < 20:
            hint = f"日样本 {metrics.sample_days} · 风险指标仅供参考"
        self.performance_overlay.set_summary(
            title,
            subtitle,
            values,
            hint,
            sample_days=metrics.sample_days,
        )
        self._performance_summary_key = summary_key

    def _record_equity_point(self, total_asset: float) -> None:
        if not self.engine:
            return
        if total_asset <= self._minimum_valid_equity():
            return
        key = (
            self.engine_epoch,
            self.engine.current_index,
            self.current_node,
            self.reveal_current_full,
            len(self.engine.trades),
            round(total_asset, 2),
        )
        if key == self._last_equity_record_key:
            return
        self._last_equity_record_key = key
        self.equity_curve.append(round(total_asset, 2))
        point = EquityPoint(
            date=self.engine.current_bar.date,
            node=self.current_node,
            total_asset=round(total_asset, 2),
            code=self.engine.current_bar.code,
        )
        self.equity_points.append(point)
        self.round_equity_points.append(point)

    def _minimum_valid_equity(self) -> float:
        if not self.engine:
            return 0.0
        return max(1.0, self.engine.initial_cash * 0.01)

    def _format_title_html(
        self,
        bar,
        stock_name: str,
        bar_index: int | None = None,
        reveal_full: bool | None = None,
    ) -> str:
        effective_reveal = self.reveal_current_full if reveal_full is None else reveal_full
        effective_index = self.engine.current_index if bar_index is None and self.engine else (bar_index or 0)
        if bar.code == SHANGHAI_INDEX_CODE and self.engine:
            return self._format_index_title_html(
                bar,
                self.engine.bars,
                effective_index,
                effective_reveal,
            )
        node = TradeNode.CLOSE if effective_reveal else TradeNode.OPEN
        price = bar.price_at(node)
        color = self._title_price_color(price, bar_index)
        price_text = f"{price:.2f}"
        if color:
            price_text = f'<span style="color:{color};">{price_text}</span>'
        open_color = self._title_price_color(bar.open, bar_index)
        open_price_text = f"{bar.open:.2f}"
        if open_color:
            open_price_text = f'<span style="color:{open_color};">{open_price_text}</span>'
        close_price_text = price_text if effective_reveal else "--"
        revealed_price_part = f"开盘价 {open_price_text}&nbsp;&nbsp;收盘价 {close_price_text}"
        if not self.identity_toggle.isChecked():
            return f"********&nbsp;&nbsp;{revealed_price_part}"
        identity_items = [bar.code.upper()]
        if stock_name:
            identity_items.append(stock_name)
        identity_part = escape("  ".join(identity_items))
        return f"{identity_part}&nbsp;&nbsp;{escape(bar.date)}&nbsp;&nbsp;{revealed_price_part}"

    def _set_stable_title_text(self, title_html: str, full_title_html: str) -> None:
        self.title_label.setMinimumWidth(0)
        self.title_label.setText(title_html)
        visible_width = self.title_label.sizeHint().width()
        self.title_label.setText(full_title_html)
        full_width = self.title_label.sizeHint().width()
        self.title_label.setText(title_html)
        self.title_label.setMinimumWidth(max(visible_width, full_width))

    def _format_index_title_html(
        self,
        bar,
        bars,
        bar_index: int,
        reveal_full: bool,
        suffix: str = "",
    ) -> str:
        identity_part = escape(f"{SHANGHAI_INDEX_CODE.upper()}  {SHANGHAI_INDEX_NAME}")
        previous_close = bars[bar_index - 1].close if 0 < bar_index < len(bars) else None

        def colored_price(price: float) -> str:
            text = f"{price:.2f}"
            if previous_close is None or previous_close <= 0:
                return text
            color = "#ff5555" if price > previous_close else ("#4ade80" if price < previous_close else "")
            return f'<span style="color:{color};">{text}</span>' if color else text

        close_text = colored_price(bar.close) if reveal_full else "--"
        result = (
            f"{identity_part}&nbsp;&nbsp;{escape(bar.date)}"
            f"&nbsp;&nbsp;开盘价 {colored_price(bar.open)}"
            f"&nbsp;&nbsp;收盘价 {close_text}"
        )
        if suffix:
            result += f"&nbsp;&nbsp;<span style='color:#8ea3bb;'>{escape(suffix)}</span>"
        return result

    def _title_price_color(self, price: float, bar_index: int | None = None) -> str:
        if not self.engine:
            return ""
        index = self.engine.current_index if bar_index is None else bar_index
        if index <= 0:
            return ""
        prev_close = self.engine.bars[index - 1].close
        if prev_close <= 0:
            return ""
        if price > prev_close:
            return "#ff5555"
        if price < prev_close:
            return "#4ade80"
        return ""

    def _update_trade_button_states(self) -> None:
        has_engine = self.engine is not None and self.training_mode
        index_browse_mode = bool(
            self.engine
            and not self.training_mode
            and self.engine.current_bar.code == SHANGHAI_INDEX_CODE
        )
        for widget in (
            self.buy_budget_input,
            self.buy_quantity_input,
            self.sell_budget_input,
            self.sell_quantity_input,
            *(button for button, _ratio in self.buy_ratio_buttons),
            *(button for button, _ratio in self.sell_ratio_buttons),
        ):
            widget.setEnabled(not index_browse_mode)
        if index_browse_mode:
            self.buy_budget_input.clear()
            self.sell_budget_input.clear()
            for quantity_input in (self.buy_quantity_input, self.sell_quantity_input):
                quantity_input.setSpecialValueText(" ")
                quantity_input.setValue(0)
            self._set_ratio_buttons_checked(self.buy_ratio_buttons, None)
            self._set_ratio_buttons_checked(self.sell_ratio_buttons, None)
        else:
            for quantity_input in (self.buy_quantity_input, self.sell_quantity_input):
                quantity_input.setSpecialValueText("")
            if self.training_mode:
                self._set_ratio_buttons_checked(self.buy_ratio_buttons, self.selected_buy_ratio)
                self._set_ratio_buttons_checked(self.sell_ratio_buttons, self.selected_sell_ratio)
        self.playback_nav_box.setVisible(has_engine)
        advance_text = "行情推进（当日收盘）" if self._advance_button_show_close else "行情推进（次日开盘）"
        self.advance_phase_btn.setText(advance_text)
        has_next_day = bool(self.engine and self.engine.current_index < len(self.engine.bars) - 1)
        advance_enabled = has_engine and (
            (self._advance_button_show_close and not self.reveal_current_full)
            or (not self._advance_button_show_close and has_next_day)
        )
        self.advance_phase_btn.setEnabled(advance_enabled)
        close_phase = self.reveal_current_full
        self.trade_buy_btn.setText("尾盘买入" if close_phase else "开盘买入")
        self.trade_sell_btn.setText("尾盘卖出" if close_phase else "开盘卖出")
        if has_engine and not self.trade_started:
            self.trade_buy_btn.setEnabled(True)
            self.trade_sell_btn.setEnabled(False)
            return
        has_sellable_position = has_engine and self._sellable_market_value(self.current_node) > 0
        self.trade_buy_btn.setEnabled(has_engine)
        self.trade_sell_btn.setEnabled(has_engine and has_sellable_position)

    def _refresh_allocation_bar(self, position_value: float, total_asset: float) -> None:
        position_ratio = 0 if total_asset <= 0 else round(position_value / total_asset * 100)
        position_ratio = max(0, min(100, position_ratio))
        sellable_value = self._sellable_market_value(self.current_node)
        locked_value = max(0.0, self._locked_today_market_value(self.current_node))
        sellable_ratio = 0 if total_asset <= 0 else round(sellable_value / total_asset * 100)
        locked_ratio = 0 if total_asset <= 0 else round(locked_value / total_asset * 100)
        sellable_ratio = max(0, min(100, sellable_ratio))
        locked_ratio = max(0, min(100, locked_ratio))
        cash_ratio = 100 - position_ratio
        self.position_ratio_bar.setValue(position_ratio)
        if locked_value > 0:
            self.position_ratio_bar.setFormat(f"可卖 {sellable_ratio}% / 今买不可卖 {locked_ratio}% / 现金 {cash_ratio}%")
        else:
            self.position_ratio_bar.setFormat(f"持仓 {position_ratio}% / 现金 {cash_ratio}%")

    def _current_position_metric_values(self) -> dict[str, tuple[str, str]]:
        if not self.engine:
            return {name: ("--", "neutral") for name in POSITION_MARKET_ITEMS}
        current_bar = self.engine.current_bar
        reference_price = current_bar.close if self.reveal_current_full else current_bar.open
        avg_price = holding_avg_price(self.engine.slots)
        active_first_buy_price = self.first_buy_price if avg_price is not None else None
        active_first_buy_index = self.first_buy_index if avg_price is not None else None
        max_amplitude = open_close_range_amplitude(
            self.engine.bars,
            active_first_buy_index,
            self.engine.current_index,
            self.current_node,
            self.first_buy_node,
        )
        post_buy_change = percent_change_from_base(active_first_buy_price, reference_price)
        post_buy_trend = "neutral" if post_buy_change is None else ("up" if post_buy_change >= 0 else "down")
        post_buy_highest_change = post_buy_highest_change_from_base(
            active_first_buy_price,
            self.engine.bars,
            active_first_buy_index,
            self.engine.current_index,
            self.current_node,
            self.first_buy_node,
        )
        post_buy_highest_trend = (
            "neutral"
            if post_buy_highest_change is None
            else ("up" if post_buy_highest_change >= 0 else "down")
        )
        return {
            "持仓均价": ("--" if avg_price is None else f"{avg_price:.2f}", "neutral"),
            "第一笔买入价": (
                "--" if active_first_buy_price is None else f"{active_first_buy_price:.2f}",
                "neutral",
            ),
            "最大振幅": ("--" if max_amplitude is None else f"{max_amplitude:.2f}%", "neutral"),
            "买入后到目前涨跌幅": (
                "--" if post_buy_change is None else f"{post_buy_change:+.2f}%",
                post_buy_trend,
            ),
            "买入后最高涨幅": (
                "--" if post_buy_highest_change is None else f"{post_buy_highest_change:+.2f}%",
                post_buy_highest_trend,
            ),
        }

    def _set_position_metrics_frozen(self, frozen: bool) -> None:
        for name, label in self.market_labels.items():
            value = bool(frozen and name in POSITION_MARKET_ITEMS)
            if bool(label.property("metricFrozen")) != value:
                label.setProperty("metricFrozen", value)
                _repolish_widget(label)

    def _refresh_market_metrics(
        self,
        display_index: int | None = None,
        display_reveal_full: bool | None = None,
    ) -> None:
        if not self.engine:
            return
        index = self.engine.current_index if display_index is None else display_index
        bar = self.engine.bars[index]
        reveal_display = self.reveal_current_full if display_reveal_full is None else display_reveal_full
        if bar.code == SHANGHAI_INDEX_CODE:
            self._refresh_index_market_metrics(self.engine.bars, index, reveal_display)
            return
        for name, label in self.market_labels.items():
            label.setProperty(
                "metricRole",
                "priceReference" if name in {"持仓均价", "第一笔买入价", "最大振幅"} else None,
            )
        if reveal_display:
            change, change_pct = change_metrics(self.engine.bars, index)
        else:
            prev_close = self.engine.bars[index - 1].close if index > 0 else bar.open
            change = round(bar.open - prev_close, 2)
            change_pct = round(change / prev_close * 100, 2) if prev_close else 0.0
        frozen = bool(not self._has_position() and self._frozen_position_metrics)
        position_values = (
            dict(self._frozen_position_metrics)
            if frozen and self._frozen_position_metrics is not None
            else self._current_position_metric_values()
        )
        values = {
            "当日涨跌额": (f"{change:+.2f}", "up" if change >= 0 else "down"),
            "当日涨跌幅": (f"{change_pct:+.2f}%", "up" if change >= 0 else "down"),
            **position_values,
        }
        self._set_position_metrics_frozen(frozen)
        self._apply_metric_values(self.market_labels, values)

    def _refresh_index_market_metrics(self, bars, index: int, reveal_display: bool) -> None:
        if not bars:
            return
        self._set_position_metrics_frozen(False)
        index = max(0, min(index, len(bars) - 1))
        bar = bars[index]
        previous_close = bars[index - 1].close if index > 0 else bar.open
        reference_price = bar.close if reveal_display else bar.open
        change = round(reference_price - previous_close, 2)
        change_pct = round(change / previous_close * 100, 2) if previous_close else 0.0
        amplitude = round((bar.high - bar.low) / previous_close * 100, 2) if reveal_display and previous_close else None
        change_value = f"{change:+.2f}  {change_pct:+.2f}%"
        change_value += f"  振{amplitude:.2f}%" if amplitude is not None else "  振待收盘"
        change_trend = "up" if change >= 0 else "down"

        ma_index = index if reveal_display else index - 1
        raw_ma_value = index_ma_state(bars, ma_index) if ma_index >= 0 else "数据不足"
        ma_trend = "down" if raw_ma_value.startswith("位于全部") else "neutral"
        if raw_ma_value == "站上5、10、20、60日线":
            ma_trend = "up"
        ma_value = raw_ma_value
        if not reveal_display and raw_ma_value not in {"--", "数据不足"}:
            ma_value = f"昨收｜{raw_ma_value}"

        values = {
            "上证涨跌": (change_value, change_trend),
            "上涨/下跌家数": ("待收盘", "neutral"),
            "沪深京成交额": ("待收盘", "neutral"),
            "较昨日成交额": ("待收盘", "neutral"),
            "涨停/跌停家数": ("待收盘", "neutral"),
            "均线位置": (ma_value, ma_trend),
            "市场状态": ("待收盘", "neutral"),
        }
        if reveal_display:
            daily = self.market_stats_by_date.get(bar.date)
            if daily is None:
                if self._market_sync_location is None:
                    unavailable = "请选择通达信目录"
                elif self.market_stats_status.startswith(("正在", "统计中")):
                    unavailable = "正在统计…"
                elif "待重试" in self.market_stats_status:
                    unavailable = "统计失败，将重试"
                elif self.market_stats_by_date:
                    unavailable = f"本地统计截至 {max(self.market_stats_by_date)}"
                else:
                    unavailable = self.market_stats_status or "目录暂无可用股票统计"
                for name in (
                    "上涨/下跌家数",
                    "沪深京成交额",
                    "较昨日成交额",
                    "涨停/跌停家数",
                    "市场状态",
                ):
                    values[name] = (unavailable, "neutral")
            else:
                previous = previous_market_stats(self.market_stats_by_date, bar.date)
                amount_change = market_amount_change_pct(daily, previous)
                breadth_trend = "up" if daily.up_count >= daily.down_count else "down"
                amount_change_text = "无上日数据"
                amount_change_trend = "neutral"
                if amount_change is not None:
                    amount_change_text = f"放量 +{amount_change:.2f}%" if amount_change >= 0 else f"缩量 {amount_change:.2f}%"
                    amount_change_trend = "up" if amount_change >= 0 else "down"
                state_text, state_trend = market_state_text(change_pct, daily, amount_change)
                values.update(
                    {
                        "上涨/下跌家数": (f"{daily.up_count} / {daily.down_count}", breadth_trend),
                        "沪深京成交额": (format_market_amount(daily.amount), "neutral"),
                        "较昨日成交额": (amount_change_text, amount_change_trend),
                        "涨停/跌停家数": (
                            f"{daily.limit_up_count} / {daily.limit_down_count}",
                            "up" if daily.limit_up_count >= daily.limit_down_count else "down",
                        ),
                        "市场状态": (state_text, state_trend),
                    }
                )
        for label in self.index_market_labels.values():
            label.setProperty("metricRole", None)
        self._apply_metric_values(self.index_market_labels, values)

    @staticmethod
    def _apply_metric_values(labels: dict[str, QLabel], values: dict[str, tuple[str, str]]) -> None:
        for name, (value, trend) in values.items():
            label = labels[name]
            text = f"{name}\n{value}"
            trend_changed = label.property("trend") != trend
            if label.text() != text:
                label.setText(text)
            if trend_changed:
                label.setProperty("trend", trend)
                _repolish_widget(label)

    def _draw_chart(self) -> None:
        if not self.engine:
            return
        chart_anchor = self._displayed_bar_index() if self.test_trade_active else self.engine.current_index
        chart_pan_offset = 0 if self.test_trade_active else self.pan_offset
        bars = visible_bars(self.engine.bars, chart_anchor, self.chart_window_size, chart_pan_offset)
        average_cost = holding_avg_price(self.engine.slots)
        self.kline_widget.set_data(
            all_bars=self.engine.bars,
            visible_bars=bars,
            trades=self.engine.trades,
            current_index=self.engine.current_index,
            pan_offset=self.pan_offset,
            window_size=self.chart_window_size,
            reveal_current_full=True if self.test_trade_active else self.reveal_current_full,
            average_cost_price=average_cost,
            completed_trade_ranges=self.completed_trade_ranges,
            active_trade_range=(self.first_buy_index, self.engine.current_index)
            if self.first_buy_index is not None and self._has_position()
            else None,
            max_drawdown_range=self._max_drawdown_overlay_spec()
            if self.drawdown_overlay_active
            else None,
            history_unmask_start_index=self._test_trade_start_index
            if self.test_trade_active
            else None,
            current_node=self.current_node if self.training_mode else None,
        )
        if self.index_overlay_active:
            self._sync_index_overlay()

    def _toggle_max_drawdown_overlay(self) -> None:
        if not self.training_mode or not self.trade_started:
            return
        if not self.drawdown_overlay_active and self._max_drawdown_overlay_spec() is None:
            self._update_status("当前还没有可显示的最大回撤区间。")
            return
        self.drawdown_overlay_active = not self.drawdown_overlay_active
        self.max_drawdown_label.setProperty("drawdownActive", self.drawdown_overlay_active)
        _repolish_widget(self.max_drawdown_label)
        self._draw_chart()

    def _reset_drawdown_overlay(self) -> None:
        self.drawdown_overlay_active = False
        if hasattr(self, "max_drawdown_label"):
            self.max_drawdown_label.setProperty("drawdownActive", False)
            _repolish_widget(self.max_drawdown_label)
        if hasattr(self, "kline_widget"):
            self.kline_widget.max_drawdown_range = None
            self.kline_widget.update()

    def _max_drawdown_overlay_spec(self) -> tuple[int, int, float, int] | None:
        if not self.engine:
            return None
        span = maximum_drawdown_span(self.equity_curve, self._minimum_valid_equity())
        if span is None:
            return None
        drawdown_pct, peak_point_index, trough_point_index = span
        if trough_point_index >= len(self.equity_points):
            return None
        peak_point = self.equity_points[peak_point_index]
        trough_point = self.equity_points[trough_point_index]
        current_code = self.engine.current_bar.code.lower()
        for point in (peak_point, trough_point):
            if point.code and point.code.lower() != current_code:
                return None
        date_to_index = {bar.date: index for index, bar in enumerate(self.engine.bars)}
        if peak_point.date not in date_to_index or trough_point.date not in date_to_index:
            return None
        peak_bar_index = date_to_index[peak_point.date]
        trough_bar_index = date_to_index[trough_point.date]
        start_index = min(peak_bar_index, trough_bar_index)
        end_index = max(peak_bar_index, trough_bar_index)
        return start_index, end_index, drawdown_pct, end_index - start_index + 1

    def _update_status(self, text: str) -> None:
        self.status_label.setText(text)
        self._sync_status_label_height()
        QTimer.singleShot(0, self._sync_status_label_height)

    def _sync_status_label_height(self) -> None:
        if not hasattr(self, "status_label"):
            return
        available_width = max(self.status_label.width(), self.status_label.minimumWidth(), 1)
        wrapped_height = self.status_label.heightForWidth(available_width)
        if wrapped_height < 0:
            wrapped_height = self.status_label.sizeHint().height()
        target_height = max(self._status_label_minimum_height, wrapped_height)
        if self.status_label.height() != target_height:
            self.status_label.setFixedHeight(target_height)
            self.trade_layout.invalidate()

    def _apply_style(self) -> None:
        base_style = """
            QMainWindow, QWidget { background: #0b1017; color: #d9e2ef; font-size: 13px; }
            QMenuBar { background: #0b1017; color: #d9e2ef; }
            QMenuBar::item { background: transparent; color: #c9d4e0; }
            QMenuBar::item:selected { background: #1d2a3a; color: #ffffff; }
            QMenuBar::item:pressed { background: #1f6feb; color: #ffffff; }
            QMenu { background: #0f1620; color: #d9e2ef; border: 1px solid #2b3a4f; }
            QMenu::item { background: transparent; color: #d9e2ef; padding: 6px 26px 6px 18px; }
            QMenu::item:selected { background: #1d4ed8; color: #ffffff; }
            QMenu::item:disabled { color: #5b6672; background: transparent; }
            QMenu::item:disabled:selected { color: #5b6672; background: transparent; }
            QMenu::separator { height: 1px; background: #253244; margin: 4px 8px; }
            QGroupBox { border: 1px solid #1d2937; border-radius: 6px; margin-top: 8px; padding: 8px; background: #121a24; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #8ea3bb; }
            QFrame#SimulationSettingsPanel { border: 1px solid #1d2937; border-radius: 6px; background: #121a24; }
            QLabel#StartDateLabel { background: #121a24; color: #d9e2ef; }
            QWidget#QuickActionsPanel[sideDocked="true"] { background: #121a24; border: 1px solid #1d2937; border-radius: 6px; }
            QWidget#QuickActionsPanel[sideDocked="true"] QPushButton { min-width: 0; }
            QWidget#QuickActionsPanel[sideDocked="true"] QPushButton#DockedStartButton,
            QWidget#QuickActionsPanel[sideDocked="true"] QPushButton#DockedRandomButton { min-width: 0; }
            QPushButton { background: #1f6feb; color: white; border: 0; border-radius: 5px; padding: 7px 10px; font-weight: 600; }
            QPushButton:hover { background: #388bfd; }
            QPushButton#RandomButton { min-width: 320px; }
            QPushButton#RandomButton:pressed, QPushButton#DockedRandomButton:pressed { background: #b85600; padding: 9px 13px 7px 15px; }
            QPushButton:disabled { background: #223044; color: #6f7d8f; }
            QPushButton#BuyButton { background: #d63d3d; color: #ffffff; }
            QPushButton#BuyButton:hover { background: #ef5350; }
            QPushButton#BuyButton:disabled { background: #4c2227; color: #7d8794; }
            QPushButton#SellButton { background: #009688; color: #ffffff; }
            QPushButton#SellButton:hover { background: #00bfa5; }
            QPushButton#SellButton:disabled { background: #124541; color: #7d8794; }
            QPushButton#RatioButton { background: #172231; color: #d9e2ef; border: 1px solid #30425a; padding: 5px 8px; }
            QPushButton#RatioButton:hover { background: #223249; }
            QPushButton#RatioButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2c4a74, stop:0.45 #234066, stop:1 #1d3456); border-color: #5782ae; color: #ffffff; }
            QFrame#TradeSectionDivider { color: #24364b; background: #24364b; margin: 5px 0; }
            QLabel#StatusLabel { color: #9fb2c8; background: #0f1620; border: 1px solid #223044; border-radius: 4px; padding: 5px; }
            QLabel#AccountKey { color: #d9e2ef; background: #0b121b; padding: 4px 6px; border-radius: 3px; }
            QLabel#AccountValue { color: #e6edf3; background: #0f1620; border: 1px solid #223044; border-radius: 4px; padding: 4px 8px; }
            QLabel#AccountValue[drawdownToggle="true"] {
                border: 1px solid rgba(74, 222, 128, 82);
                background: rgba(34, 197, 94, 10);
                color: #4ade80;
            }
            QLabel#AccountValue[drawdownToggle="true"]:hover {
                border-color: rgba(134, 239, 172, 175);
                background: rgba(34, 197, 94, 28);
            }
            QLabel#AccountValue[drawdownToggle="true"]:focus {
                border-color: #bbf7d0;
                background: rgba(34, 197, 94, 42);
            }
            QLabel#AccountValue[drawdownToggle="true"][drawdownActive="true"] {
                border: 2px solid #4ade80;
                background: rgba(34, 197, 94, 58);
                color: #86efac;
            }
            QLineEdit#AccountValue { background: #0f1620; border: 1px solid #223044; border-radius: 4px; }
            QLabel#TotalProfitKey { color: #ffffff; background: #0b121b; padding: 6px 8px; border-radius: 3px; font-size: 15px; font-weight: 800; }
            QLabel#TotalProfitValue { color: #e6edf3; background: #0f1620; border: 1px solid #223044; border-radius: 4px; padding: 6px 8px; font-size: 17px; font-weight: 900; }
            QLabel[accountInactive="true"], QLineEdit[accountInactive="true"] { color: #667586; background: #0a1119; }
            QLineEdit, QComboBox, QSpinBox { background: #0f1620; color: #e6edf3; border: 1px solid #223044; border-radius: 4px; padding: 5px; }
            QSpinBox#TradeQuantityInput::up-button, QSpinBox#TradeQuantityInput::down-button { width: 0; border: none; }
            QListWidget#StockCandidateList { background: #0f1620; color: #e6edf3; border: 1px solid #3b82f6; border-radius: 4px; outline: none; padding: 2px; }
            QListWidget#StockCandidateList::item { min-height: 28px; padding: 2px 8px; }
            QListWidget#StockCandidateList::item:selected { background: #1d4ed8; color: white; }
            QListWidget#RoundLog { background: #0f1620; color: #e6edf3; border: 1px solid #223044; border-radius: 4px; outline: none; padding: 2px; }
            QListWidget#RoundLog::item { min-height: 24px; padding: 2px 8px; }
            QListWidget#RoundLog::item:hover { background: #172231; }
            QListWidget#RoundLog::item:selected { background: #1d4ed8; color: transparent; }
            QProgressBar#PositionRatioBar { background: #0f1620; color: #e6edf3; border: 1px solid #223044; border-radius: 4px; min-height: 22px; text-align: center; font-weight: 800; }
            QProgressBar#PositionRatioBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6b5310, stop:0.55 #9a7a1c, stop:1 #7d6314); border-radius: 3px; }
            QTableWidget { background: #0f1620; color: #d9e2ef; border: 1px solid #1d2937; gridline-color: #1c2735; selection-background-color: #203858; }
            QHeaderView::section { background: #172231; color: #9fb2c8; padding: 6px; border: 0; }
            QSplitter::handle { background: #172231; }
            QLabel#TitleLabel { font-size: 22px; font-weight: 800; color: #f5f8fc; }
            QPushButton#IdentityToggle { background: transparent; border: none; padding: 0; outline: none; }
            QPushButton#IdentityToggle:hover { background: transparent; border: none; }
            QPushButton#IdentityToggle:pressed { background: transparent; border: none; padding: 2px 0 0 2px; }
            QPushButton#ContinuousModeButton:disabled {
                background: #17212c; color: #b7c5d4;
                border: 1px solid #344252; font-weight: 800;
            }
            QPushButton#StartButton, QPushButton#DockedStartButton,
            QPushButton#RandomButton, QPushButton#DockedRandomButton { background: #d66a00; color: #ffffff; padding: 8px 14px; }
            QPushButton#StartButton, QPushButton#RandomButton { min-width: 320px; }
            QPushButton#StartButton:hover, QPushButton#DockedStartButton:hover,
            QPushButton#RandomButton:hover, QPushButton#DockedRandomButton:hover { background: #f08a1f; }
            QPushButton#PlaybackAdvanceButton { background: transparent; border: none; padding: 0; }
            QLabel#SnapshotNotice {
                background: rgba(28, 36, 47, 205);
                color: #b9c7d6;
                border: 1px solid rgba(105, 125, 148, 120);
                border-radius: 5px;
                padding: 5px 9px;
            }
            QLabel#SnapshotNotice[error="true"] {
                color: #e4b7b7;
                border-color: rgba(170, 95, 95, 130);
            }
            QFrame#SnapshotFlash {
                background: rgba(255, 255, 255, 72);
                border: none;
            }
            QLabel#MetricLabel, QLabel[objectName="MetricLabel"] { background: #0b121b; border: 1px solid #1b2633; border-radius: 3px; color: #a9b7c6; padding: 6px 8px; min-width: 0; }
            QLabel#MetricLabel[metricRole="priceReference"] { font-weight: 800; }
            QLabel#MetricLabel[trend="up"] { color: #ff5555; font-weight: 800; }
            QLabel#MetricLabel[trend="down"] { color: #00e5e5; font-weight: 800; }
            QLabel#MetricLabel[metricFrozen="true"] {
                color: #718094; background: #0d141d; border-color: #1a2532; font-weight: 500;
            }
            QLabel#DayInfo { color: #9fb2c8; padding: 4px 0; }
            QLabel#AccountValue[profit="up"] { color: #ff5555; font-weight: 800; }
            QLabel#AccountValue[profit="down"] { color: #4ade80; font-weight: 800; }
            QLabel#TotalProfitValue[profit="up"] { color: #ff5555; font-weight: 900; }
            QLabel#TotalProfitValue[profit="down"] { color: #4ade80; font-weight: 900; }
            QLabel[profit="up"] { color: #ff5555; font-weight: 800; }
            QLabel[profit="down"] { color: #4ade80; font-weight: 800; }
            QLineEdit[locked="true"] { color: #8ea3bb; background: #071019; border-color: #1d2a3a; }
            QLabel[accountInactive="true"], QLineEdit[accountInactive="true"] { color: #667586; background: #0a1119; font-weight: 500; }
            QLabel#AccountValue[drawdownToggle="true"][accountInactive="true"] {
                color: #667586;
                background: #0a1119;
                border: 1px solid #223044;
            }
            """
        compact_style = """
            QFrame#SimulationSettingsPanel QLabel,
            QFrame#SimulationSettingsPanel QLineEdit,
            QFrame#SimulationSettingsPanel QPushButton { font-size: 12px; }
            QFrame#SimulationSettingsPanel QLineEdit { padding: 2px 4px; }
            QFrame#SimulationSettingsPanel QPushButton { padding: 2px 7px; }
            QLabel#TitleLabel { font-size: 18px; }
            QLabel#MetricLabel, QLabel[objectName="MetricLabel"] { padding: 3px 5px; font-size: 12px; }
            QScrollArea#SidePanelScroll QGroupBox { margin-top: 6px; padding: 5px; }
            QScrollArea#SidePanelScroll QGroupBox::title { left: 8px; padding: 0 3px; }
            QScrollArea#SidePanelScroll QPushButton { padding: 3px 5px; font-size: 12px; }
            QScrollArea#SidePanelScroll QLineEdit,
            QScrollArea#SidePanelScroll QSpinBox { padding: 3px; font-size: 12px; }
            QScrollArea#SidePanelScroll QLabel#AccountKey,
            QScrollArea#SidePanelScroll QLabel#AccountValue { padding: 2px 4px; font-size: 12px; }
            QScrollArea#SidePanelScroll QLabel#TotalProfitKey { padding: 3px 5px; font-size: 14px; }
            QScrollArea#SidePanelScroll QLabel#TotalProfitValue { padding: 3px 4px; font-size: 15px; }
            QScrollArea#SidePanelScroll QLabel#StatusLabel { padding: 3px; font-size: 12px; }
            """ if self._compact_layout else ""
        low_resolution_style = """
            QFrame#SimulationSettingsPanel QLabel,
            QFrame#SimulationSettingsPanel QLineEdit,
            QFrame#SimulationSettingsPanel QPushButton { font-size: 11px; }
            QFrame#SimulationSettingsPanel QLineEdit { padding: 1px 3px; }
            QFrame#SimulationSettingsPanel QPushButton { padding: 1px 5px; }
            QLabel#TitleLabel { font-size: 16px; }
            QLabel#MetricLabel, QLabel[objectName="MetricLabel"] { padding: 2px 4px; font-size: 11px; }
            QScrollArea#SidePanelScroll QGroupBox { margin-top: 5px; padding: 3px; }
            QScrollArea#SidePanelScroll QGroupBox::title { left: 6px; padding: 0 2px; font-size: 11px; }
            QScrollArea#SidePanelScroll QPushButton { padding: 1px 3px; font-size: 11px; }
            QScrollArea#SidePanelScroll QLineEdit,
            QScrollArea#SidePanelScroll QSpinBox { padding: 1px 2px; font-size: 11px; }
            QScrollArea#SidePanelScroll QLabel#AccountKey,
            QScrollArea#SidePanelScroll QLabel#AccountValue { padding: 1px 2px; font-size: 11px; }
            QScrollArea#SidePanelScroll QLabel#TotalProfitKey { padding: 2px 3px; font-size: 12px; }
            QScrollArea#SidePanelScroll QLabel#TotalProfitValue { padding: 2px; font-size: 13px; }
            QScrollArea#SidePanelScroll QLabel#StatusLabel { padding: 2px; font-size: 11px; }
            QProgressBar#PositionRatioBar { min-height: 18px; max-height: 18px; font-size: 11px; }
            QListWidget#RoundLog::item { min-height: 18px; padding: 1px 4px; }
            """ if self._low_resolution_layout else ""
        self.setStyleSheet(base_style + compact_style + low_resolution_style)


class StartupGradientBar(QWidget):
    """Small moving gradient used while the first window is prepared."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self) -> None:
        self._phase = (self._phase + 4.0) % 240.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0d1823"))
        painter.drawRoundedRect(rect, 7, 7)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 7, 7)
        painter.setClipPath(clip)
        span = max(90.0, rect.width() * 0.36)
        x = -span + (rect.width() + span * 2) * (self._phase / 240.0)
        gradient = QLinearGradient(x, 0, x + span, 0)
        gradient.setColorAt(0.0, QColor(56, 189, 248, 0))
        gradient.setColorAt(0.35, QColor(56, 189, 248, 205))
        gradient.setColorAt(0.55, QColor(245, 158, 11, 235))
        gradient.setColorAt(0.75, QColor(56, 189, 248, 205))
        gradient.setColorAt(1.0, QColor(56, 189, 248, 0))
        painter.setBrush(gradient)
        painter.drawRect(rect)
        painter.setClipping(False)
        painter.setPen(QColor("#24364a"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 7, 7)


def _random_investment_quote() -> dict:
    try:
        data = json.loads(INVESTMENT_QUOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = []
    if isinstance(data, list):
        quotes = [
            item for item in data
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ]
        if quotes:
            return random.choice(quotes)
    return {
        "text": "投资最重要的不是预测，而是准备。",
        "author": "市场流传",
        "category": "投资哲学",
    }


class StartupSplash(QWidget):
    """Dark first-paint surface shown before the main window is ready."""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen,
        )
        self.setObjectName("StartupSplash")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(560, 250)
        self.setWindowOpacity(0.98)
        self.setStyleSheet(
            """
            QWidget#StartupSplash { background: #0b1118; border: 1px solid #24364a; }
            QLabel#StartupTitle { color: #f3f7fb; font-size: 18px; font-weight: 700; }
            QLabel#StartupStatus { color: #c9d8e8; font-size: 13px; }
            QLabel#StartupQuote {
                color: #dbe7f5; font-size: 13px; background: #101b27;
                border-left: 3px solid #f59e0b; border-radius: 5px;
                padding: 8px 10px;
            }
            QLabel#StartupTip { color: #7f93a8; font-size: 11px; }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(8)
        title = QLabel(APP_NAME)
        title.setObjectName("StartupTitle")
        self.status_label = QLabel("正在加载界面与行情数据")
        self.status_label.setObjectName("StartupStatus")
        quote = _random_investment_quote()
        quote_text = (
            f'“{quote.get("text", "")}”\n'
            f'—— {quote.get("author", "市场流传")}'
        )
        self.quote_label = QLabel(quote_text)
        self.quote_label.setObjectName("StartupQuote")
        self.quote_label.setWordWrap(True)
        self.quote_label.setMinimumHeight(58)
        self.bar = StartupGradientBar()
        tip = QLabel("首次启动会准备板块缓存，之后打开板块会更快")
        tip.setObjectName("StartupTip")
        tip.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(self.status_label)
        layout.addWidget(self.quote_label)
        layout.addSpacing(2)
        layout.addWidget(self.bar)
        layout.addWidget(tip)
        self._dots = 0
        self._text_timer = QTimer(self)
        self._text_timer.setInterval(360)
        self._text_timer.timeout.connect(self._tick)
        self._text_timer.start()

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        self.status_label.setText("正在加载界面与行情数据" + "·" * self._dots)

    def showEvent(self, event) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            center = screen.availableGeometry().center()
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        super().showEvent(event)

    def finish(self) -> None:
        self._text_timer.stop()
        self.bar._timer.stop()
        self.close()


def _enable_per_monitor_dpi() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        except (AttributeError, OSError):
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE fallback
    except (ImportError, AttributeError, OSError):
        pass


def main() -> int:
    _enable_per_monitor_dpi()
    app = QApplication(sys.argv)
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    splash = StartupSplash()
    splash.show()
    app.processEvents()
    try:
        window = MainWindow()
    except Exception:
        splash.finish()
        raise
    splash_started_at = time.monotonic()
    shown = False

    def show_now() -> None:
        if window.settings.window_maximized:
            window.showMaximized()
        else:
            window.show()
        splash.finish()

    def show_main_window(_payload=None) -> None:
        nonlocal shown
        if shown:
            return
        shown = True
        remaining_ms = max(0, int((1.6 - (time.monotonic() - splash_started_at)) * 1000))
        if remaining_ms:
            QTimer.singleShot(remaining_ms, show_now)
        else:
            show_now()

    window.startup_ready.connect(show_main_window)
    QTimer.singleShot(20000, show_main_window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
