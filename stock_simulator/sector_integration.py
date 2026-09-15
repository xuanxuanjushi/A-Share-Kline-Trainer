"""Local API adapter: the only sector component allowed to know the legacy host.

The sector UI consumes TrainingAPI via immutable requests/signals. This adapter
keeps account, persistence, and mode transition policy in the existing host.
"""
from datetime import date
from pathlib import Path
import re

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QButtonGroup, QMessageBox

from .sectors.contracts import MarketContext, TrainingRequest
from .sectors.page import SectorPage
from .sectors.style import NAV_STYLE
from .tdx_reader import resolve_tdx_location
from .app import TRAINING_MODE_INDEPENDENT, TRAINING_MODE_SINGLE
from . import config


class SectorIntegration(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.active = False
        self.page = None
        self._busy = False
        self._primed = False
        self._last_host_context = None
        self._source_setting = None
        self._source_root = ''
        self.nav = QWidget()
        self.nav.setObjectName('SectorNavigation')
        self.nav.setFixedHeight(30)
        self.nav.setStyleSheet(NAV_STYLE)
        row = QHBoxLayout(self.nav)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.sector_tab = QPushButton('板块选股训练')
        self.stock_tab = QPushButton('个股训练')
        self.group = QButtonGroup(self.nav)
        for button in (self.sector_tab, self.stock_tab):
            button.setCheckable(True)
            button.setFixedHeight(28)
            self.group.addButton(button)
            row.addWidget(button)
        row.addStretch(1)
        self.stock_tab.setChecked(True)
        self.clock = QLabel('模拟日期 —')
        self.clock.setObjectName('SectorClock')
        self.phase_label = QLabel()
        self.phase_label.setObjectName('SectorPhase')
        row.addWidget(self.clock)
        row.addWidget(self.phase_label)
        self.clock.hide()
        self.phase_label.hide()
        # 个股页顶部：标签栏横跨整行，三个输入框（股票 / 开始日期 / 通达信目录）
        # 并入同一行的标签右侧，五个控件同处最上面一行。
        self._nav_row = row
        self.top_bar_fields = host.top_bar_fields
        host.simulation_settings_panel.hide()
        # 放在这一行最后：标签栏自带的伸缩量会把三个输入框推到靠右的位置。
        row.addWidget(self.top_bar_fields)
        host.chart_panel_layout.insertWidget(0, self.nav)
        self.sector_tab.clicked.connect(self.show_sectors)
        self.stock_tab.clicked.connect(self.show_stock)
        # Keep the QMenu/QAction wrappers alive until the window is destroyed.
        # Letting temporary wrappers be collected can invalidate the native
        # menus on PySide6 and make later menu access fail.
        self._menu_actions = list(host.menuBar().actions())
        self._menu_refs = []
        for action in self._menu_actions:
            menu = action.menu()
            if menu:
                self._menu_refs.append(menu)
                menu.aboutToShow.connect(host._sync_menu_actions)

    def market_context(self):
        h = self.host
        engine = h.engine
        raw_root = h.tdx_path.text().strip()
        if raw_root != self._source_setting:
            location = resolve_tdx_location(raw_root)
            self._source_root = str(location.root) if location else raw_root
            self._source_setting = raw_root
        root = self._source_root
        return MarketContext(root, engine.current_bar.date if engine else date.today().isoformat(),
                             bool(h.reveal_current_full) if engine else True,
                             bool(engine and h.training_mode))

    def _ensure_page(self):
        if self.page:
            return self.page
        self.page = SectorPage(cache_dir=config.CONFIG_PATH.parent / 'sector_cache')
        self.page.visibility_requested.connect(self.set_date_visibility)
        self.page.training_requested.connect(self.open_training)
        self.page.advance_requested.connect(self.advance_market)
        self.page.context_changed.connect(self._show_date)
        self.page.readiness_changed.connect(self.host._sync_menu_actions)
        self.host.root_layout.addWidget(self.page, 1)
        self.page.hide()
        settings = self.host.settings
        self.page.apply_configured_favorites(
            settings.favorite_sectors, settings.favorite_stocks
        )
        self.page.apply_board_filters(settings.board_filters)
        self.page.apply_layout_sizes(
            settings.sector_splitter_sizes,
            settings.sector_chart_splitter_sizes,
            settings.sector_table_widths,
            settings.stock_table_widths,
        )
        self.page.apply_chart_preferences(
            settings.sector_sub_pane_indicators,
            settings.sector_pane_height_ratios,
            settings.sector_chart_window_size,
        )
        return self.page

    def prepare(self):
        """Build the hidden page and prefill its first snapshot at startup."""
        page = self._ensure_page()
        context = self.market_context()
        self._last_host_context = context
        self._set_page_training_context()
        if page.sector_table.rowCount() == 0:
            page._auto_select_first = True
        page.set_context(context, reload=True)

    def prime_page(self):
        """Lay out and render the hidden sector page before it is first shown."""
        if self._primed or not self.page:
            return
        page = self.page
        if page.sector_table.rowCount() <= 0:
            return
        self._primed = True
        page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        try:
            central = self.host.centralWidget()
            if central is not None:
                page.resize(central.size())
            page.show()
            page.grab()
            page.hide()
        finally:
            page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)

    def show_sectors(self):
        entering = not self.active
        self.host._start_sector_deep_warmup()
        if self.host._immersive_fullscreen:
            self.host._set_immersive_fullscreen(False)
        engine = self.host.engine
        stock = engine.current_bar.code if engine else ''
        follow_stock = entering and bool(re.fullmatch(r'(sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})', stock))
        self._cancel_pending_switches()
        self._ensure_page()
        self._set_page_training_context()
        current = self.market_context()
        self._last_host_context = current
        if not follow_stock and self.page.context and not current.locked and not self.page.context.locked and self.page.context.root == current.root:
            current = self.page.context
        self.active = True
        # 板块页只显示标签，输入框先收起，切回个股页再显示。
        self.top_bar_fields.hide()
        self.host.root_layout.removeWidget(self.nav)
        self.host.root_layout.insertWidget(0, self.nav)
        self.nav.show()
        self.host.stock_candidate_list.hide()
        self.host.simulation_settings_panel.hide()
        self.host.main_splitter.hide()
        self.page.set_dates_visible(self.host.identity_toggle.isChecked())
        self.page.show()
        self.page.set_adjust_provider(self.host.adjust_provider)
        self.page.set_context(current, reload=not follow_stock)
        if follow_stock:
            # 进入板块页优先显示个股K线：只有当前图已经是某只个股的图时保持原样，
            # 否则（在看板块指数、或还没加载）按训练个股重新定位。
            page = self.page
            showing_member_chart = bool(
                page._chart_code and page._chart_code not in (page._sector_code, '')
            )
            if page._chart_code != stock and not showing_member_chart:
                self.page.focus_stock(stock)
        self._show_date(current)
        self.sector_tab.setChecked(True)
        self.host._sync_menu_actions()

    def show_stock(self):
        self.active = False
        self.host.root_layout.removeWidget(self.nav)
        self.host.chart_panel_layout.insertWidget(0, self.nav)
        self.nav.show()
        self.top_bar_fields.show()
        if self.page:
            self.page.hide()
        # 输入框已经并入标签栏，原来的输入框外框保持隐藏，避免留下空条。
        self.host.simulation_settings_panel.hide()
        self.host.main_splitter.show()
        self.stock_tab.setChecked(True)
        self.sync()
        self.host._refresh_adjust_actions()
        self.host._sync_menu_actions()

    def _cancel_pending_switches(self):
        # Cached candidates remain reusable, but a previous click must not
        # activate an unrelated engine after an explicit sector selection.
        self.host._random_switch_pending = False
        self.host._continuation_switch_pending = False
        self.host._independent_switch_pending = False
        self.host._single_switch_pending = False

    def _show_date(self, context):
        self.clock.hide()
        self.phase_label.hide()
        self.clock.setText(context.date.replace('-', ' / '))
        self.phase_label.setText('收盘' if context.closed else '开盘')

    def _training_date_limit(self):
        h = self.host
        if h.engine and not h.test_trade_active:
            current_bar = getattr(h.engine, 'current_bar', None)
            return getattr(current_bar, 'date', None)
        return None

    def _training_stock_code(self):
        h = self.host
        if h.engine and h.training_mode and not h.test_trade_active:
            current_bar = getattr(h.engine, 'current_bar', None)
            return getattr(current_bar, 'code', '') or ''
        return ''

    def _set_page_training_context(self):
        if not self.page:
            return
        try:
            horizon = self.host._random_training_forward_bars()
        except Exception:
            horizon = 0
        self.page.set_training_context(
            self._training_date_limit(),
            self._training_stock_code(),
            horizon,
        )

    def sync(self):
        context = self.market_context()
        if self.active and self.page:
            self._set_page_training_context()
            self.page.set_dates_visible(self.host.identity_toggle.isChecked())
            self.page.set_adjust_provider(self.host.adjust_provider)
            if context != self._last_host_context or self.page.context is None or context.root != self.page.context.root:
                self.page.set_context(context)
            self._show_date(self.page.context)
        else:
            self._show_date(context)
        self._last_host_context = context

    def set_date_visibility(self, visible):
        self.host.identity_toggle.setChecked(visible)
        self.host.save_display_preferences()

    def advance_market(self):
        if self.active and self.page.context == self.market_context():
            self.host._advance_training_phase()
            self.sync()

    def open_training(self, request: TrainingRequest):
        if self._busy:
            return False
        self._busy = True
        h = self.host
        try:
            if not self.active or request.context != self.page.context:
                raise ValueError('选股页面已改变，请重新选择股票。')
            current = self.market_context()
            if request.context.root != current.root:
                raise ValueError('数据源已改变，请刷新后重新选择。')
            if h.test_trade_active or h._return_to_trading_context is not None:
                raise ValueError('请先退出临时测试并返回原训练。')
            if not re.fullmatch(r'(sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})', request.code):
                raise ValueError('请选择有效的股票代码。')
            if h.engine and h.training_mode and h.engine.current_bar.code == request.code:
                self.show_stock()
                return True
            if h._has_position():
                raise ValueError('当前仍有持仓，请先在个股训练中卖出，再换股。切换页面不会影响持仓。')
            bars = h.reader.read_daily_bars(request.code)
            start = next((i for i, b in enumerate(bars) if b.date == request.context.date), None)
            if start is None:
                raise ValueError('该股票在模拟日期没有日K，不能跳到未来日期开始训练。')
            cash = h._parse_money_text(h.cash_input.text())
            if cash is None or cash <= 0:
                raise ValueError('初始本金必须大于 0。')
            continuation = bool(h.engine and h.training_mode and h.trade_started and h.continuous_compound_mode)
            initial = float(h.account_initial_cash or h.engine.initial_cash) if continuation else cash
            engine = h._build_prepared_engine(bars, start, initial)
            name = h.info_reader.name_for(request.code)
            self._cancel_pending_switches()
            h._prefetched_stock_names[request.code] = name
            if continuation:
                h._activate_continuation_engine(engine, request.code, name, h.engine.cash)
            else:
                if h.engine and h.training_mode:
                    h._independent_switch_pending = h.training_mode_kind == TRAINING_MODE_INDEPENDENT
                    h._single_switch_pending = h.training_mode_kind == TRAINING_MODE_SINGLE
                h._activate_engine(engine, '已从板块选股进入训练，未来日K继续隐藏。', awaiting_first_buy=True)
            h.using_sample_kline = False
            if request.context.closed:
                h.show_close_phase()
            self.show_stock()
            return True
        except Exception as exc:
            QMessageBox.warning(h, '无法进入个股训练', str(exc))
            return False
        finally:
            self._busy = False

    def handle_menu(self, method, *args):
        p, h = self.page, self.host
        chart_actions = {
            'pan_left': p.pan_left, 'pan_right': p.pan_right,
            'pan_to_latest': p.latest, 'pan_to_earliest': lambda: p._navigate_date('first'),
            'zoom_in': p.zoom_in, 'zoom_out': p.zoom_out, 'zoom_reset': p.reset_zoom,
            'advance_playback': p._advance,
            '_set_identity_from_menu': p._request_visibility,
            '_set_index_overlay_from_menu': lambda checked: p._toggle_index_overlay(),
            '_add_drawing_line': p.chart.add_user_line_at_center,
            '_add_drawing_rectangle': p.chart.add_user_rectangle_at_center,
            '_select_all_drawings': p.chart.select_all_user_annotations,
            '_copy_drawings': p.chart.copy_selected_user_annotations,
            '_paste_drawings': p.chart.paste_user_annotations,
            '_delete_drawings': p.chart.delete_selected_user_annotations,
        }
        if method == '_set_adjust_type' and args:
            adjust_type = args[0]
            p.set_adjust_type(adjust_type)
            if adjust_type in ('none', 'qfq', 'hfq') and h.settings.adjust_type != adjust_type:
                h.settings.adjust_type = adjust_type
                h.reader.adjust_type = adjust_type
                h._save_settings()
            h._refresh_adjust_actions()
            self.sync_menu_actions()
            return
        if method in chart_actions:
            result = chart_actions[method](*args)
            self.sync_menu_actions()
            return result
        if method == '_clear_all_drawings':
            if p.chart.user_annotation_count() and QMessageBox.question(h, '清除标注', '清除当前板块图表中的全部画线和标注？') == QMessageBox.StandardButton.Yes:
                p.chart.clear_user_annotations()
            return
        if method == 'save_trade_snapshot':
            directory = h._desktop_directory() / '板块截图'
            directory.mkdir(parents=True, exist_ok=True)
            path = h._available_snapshot_path(directory, '板块选股', '截图')
            if not p.grab().save(str(path), 'PNG'):
                QMessageBox.warning(h, '保存失败', '无法保存板块截图。')
            else:
                p.status.setText(f'截图已保存：{path}')
            return
        if method in ('choose_tdx_dir', 'use_bundled_market'):
            result = getattr(h, method)()
            if self.active:
                self.sync()
            return result
        # Account actions become visible before using the existing account rules.
        self.show_stock()
        return getattr(h, method)(*args)

    def sync_menu_actions(self):
        h, p = self.host, self.page
        h.view_index_overlay_action.setText('板块指数叠加\t双击空格' if self.active else '上证指数叠加\t双击空格')
        h.view_identity_action.setText('显示日期' if self.active else '显示股票身份')
        if not self.active or p is None:
            return
        ready = bool(p._history)
        snapshot_ready = bool(ready or (p.service is not None and p.sector_table.rowCount()))
        for name in ('file_snapshot', 'view_latest', 'view_earliest', 'view_previous_day', 'view_next_day',
                     'view_zoom_in', 'view_zoom_out', 'view_zoom_reset', 'drawing_add_line',
                     'drawing_add_rectangle', 'drawing_select_all', 'drawing_copy', 'drawing_paste',
                     'drawing_delete', 'drawing_clear'):
            getattr(h, name + '_action').setEnabled(ready)
        h.file_snapshot_action.setEnabled(snapshot_ready)
        h.view_identity_action.setEnabled(True)
        h.view_identity_action.setChecked(p._dates_visible)
        h.view_index_overlay_action.setEnabled(ready and not p._chart_code.startswith('sh880'))
        h.view_index_overlay_action.setChecked(p._index_enabled)
        h.view_performance_handle_action.setEnabled(False)
        h.view_index_preview_action.setEnabled(False)
        h.trade_buy_action.setEnabled(False)
        h.trade_sell_action.setEnabled(False)
        h.simulation_sample_action.setEnabled(False)
        h.simulation_start_action.setEnabled(False)
        h.simulation_random_action.setEnabled(False)
        h.simulation_test_trade_action.setEnabled(False)
        h.simulation_return_action.setEnabled(False)
        h.simulation_clear_action.setEnabled(False)
        for action in h.training_mode_actions.values():
            action.setEnabled(False)
        h.simulation_advance_action.setEnabled(p.context is not None)
        h.simulation_advance_action.setText(p.advance.text())
        for key in ('none', 'qfq', 'hfq'):
            getattr(h, 'adjust_' + key + '_action').setChecked(p.adjust_type == key)
