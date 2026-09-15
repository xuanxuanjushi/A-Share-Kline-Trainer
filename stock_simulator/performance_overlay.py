from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


LEFT_METRICS = (
    ("initial_asset", "期初资产"),
    ("ending_asset", "当前/期末资产"),
    ("net_profit", "净盈亏"),
    ("total_return", "总收益率"),
    ("annual_return", "年化收益率"),
    ("segment_count", "完整交易段"),
    ("win_rate", "胜率"),
    ("profit_loss_ratio", "盈亏比"),
    ("profit_factor", "利润因子"),
    ("expectancy", "单段期望收益"),
)

RIGHT_METRICS = (
    ("benchmark_return", "同期上证收益率"),
    ("excess_return", "超额收益率"),
    ("max_drawdown", "最大回撤"),
    ("annual_volatility", "年化波动率"),
    ("sharpe_ratio", "夏普比率"),
    ("sortino_ratio", "Sortino比率"),
    ("return_drawdown_ratio", "收益回撤比"),
    ("average_win", "平均盈利"),
    ("average_loss", "平均亏损"),
    ("fee_and_tax", "手续费及税费"),
)

SINGLE_MODE_LEFT_METRICS = (
    "initial_asset",
    "ending_asset",
    "net_profit",
    "total_return",
    "segment_count",
)

SINGLE_MODE_RIGHT_METRICS = (
    "benchmark_return",
    "excess_return",
    "max_drawdown",
    "return_drawdown_ratio",
    "fee_and_tax",
)

INDEPENDENT_MODE_LEFT_METRICS = (
    "total_return",
    "net_profit",
    "segment_count",
    "win_rate",
    "expectancy",
)

INDEPENDENT_MODE_RIGHT_METRICS = (
    "average_win",
    "average_loss",
    "profit_loss_ratio",
    "profit_factor",
    "fee_and_tax",
)

METRIC_EXPLANATIONS = {
    "initial_asset": "统计区间开始时的账户总资产，是后续收益计算的基准。",
    "ending_asset": "当前或统计区间结束时的账户总资产。",
    "net_profit": "期末资产减去期初资产后的实际盈亏金额。",
    "total_return": "净盈亏占期初资产的比例，反映整个区间的总体成绩。",
    "annual_return": "把当前区间收益折算成一年的理论收益，短区间容易失真。",
    "segment_count": "从首次买入到完全清仓算一个完整交易段。",
    "win_rate": "盈利交易段占全部完整交易段的比例，需结合盈亏比一起看。",
    "profit_loss_ratio": "平均盈利幅度除以平均亏损幅度，越高越有利。",
    "profit_factor": "所有盈利金额之和除以所有亏损金额之和，越高越好。",
    "expectancy": "平均每个完整交易段带来的收益率。",
    "benchmark_return": "同一时间区间内上证指数的涨跌幅。",
    "excess_return": "总收益率减去同期上证收益率，反映是否跑赢大盘。",
    "max_drawdown": "资产从阶段高点回落到随后低点的最大跌幅，绝对值越小越稳。",
    "annual_volatility": "收益波动折算到一年的幅度，越高表示净值起伏越大。",
    "sharpe_ratio": "每承担一份综合波动风险获得的收益，越高越好。",
    "sortino_ratio": "只把下跌波动视为风险，衡量每承担一份下跌风险获得的收益。",
    "return_drawdown_ratio": "总收益率除以最大回撤绝对值，衡量用多大回撤换来多少收益。",
    "average_win": "所有盈利交易段的平均收益率。",
    "average_loss": "所有亏损交易段的平均收益率。",
    "fee_and_tax": "区间内已成交订单产生的手续费和印花税合计。",
}


class PerformanceOverlay(QWidget):
    """A non-scrolling chart overlay that slides in from the main chart's left edge."""

    export_requested = Signal()
    summary_refresh_requested = Signal()

    def __init__(self, chart_widget: QWidget):
        super().__init__(chart_widget)
        self.chart_widget = chart_widget
        self.available = False
        self.handle_enabled = True
        self.expanded = False
        self._animation = QPropertyAnimation(self, b"geometry", self)
        self._animation.setDuration(190)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._finish_animation)
        self._target_geometry = QRect()
        self._value_labels: dict[str, QLabel] = {}
        self._metric_cells: dict[str, QFrame] = {}
        self._metric_name_labels: dict[str, QLabel] = {}
        self._metric_titles: dict[str, str] = {}
        self._metric_explanations = dict(METRIC_EXPLANATIONS)
        self._single_mode_layout = False
        self._layout_mode = "continuous"
        self._build_ui()
        self.chart_widget.installEventFilter(self)
        self.hide()

        self.handle = QPushButton("统计", chart_widget)
        self.handle.setObjectName("PerformanceHandle")
        self.handle.setToolTip("展开本轮交易统计")
        self.handle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.handle.clicked.connect(self.expand)
        self.handle.hide()
        self._apply_style()

    def _build_ui(self) -> None:
        self.setObjectName("PerformanceOverlay")
        self.setToolTip("将鼠标停留在某项指标上，可查看具体解释和当前水平。")
        # The application-wide QWidget rule paints every child with its own dark
        # background.  Force this overlay and its cells through the styled
        # background path so Windows never treats transparent children as holes.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        self.title_label = QLabel("交易绩效")
        self.title_label.setObjectName("PerformanceTitle")
        self.subtitle_label = QLabel("--")
        self.subtitle_label.setObjectName("PerformanceSubtitle")
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        header.addLayout(title_box, 1)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("PerformanceClose")
        self.close_button.setFixedSize(26, 26)
        self.close_button.setToolTip("收起交易统计")
        self.close_button.clicked.connect(self.collapse)
        header.addWidget(self.close_button)
        root.addLayout(header)

        groups = QGridLayout()
        self._metric_grid = groups
        groups.setContentsMargins(0, 0, 0, 0)
        groups.setHorizontalSpacing(12)
        groups.setVerticalSpacing(2)
        self._left_header = QLabel("收益与交易")
        self._right_header = QLabel("风险与基准")
        self._left_header.setObjectName("PerformanceGroupTitle")
        self._right_header.setObjectName("PerformanceGroupTitle")
        groups.addWidget(self._left_header, 0, 0)
        groups.addWidget(self._right_header, 0, 1)
        for row, ((left_key, left_text), (right_key, right_text)) in enumerate(
            zip(LEFT_METRICS, RIGHT_METRICS), start=1
        ):
            groups.addWidget(self._metric_cell(left_key, left_text), row, 0)
            groups.addWidget(self._metric_cell(right_key, right_text), row, 1)
            groups.setRowStretch(row, 1)
        groups.setColumnStretch(0, 1)
        groups.setColumnStretch(1, 1)
        root.addLayout(groups, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.sample_hint = QLabel("")
        self.sample_hint.setObjectName("PerformanceSampleHint")
        self.sample_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.sample_hint, 1)
        self.export_button = QPushButton("导出Excel图表")
        self.export_button.setObjectName("PerformanceExport")
        self.export_button.setFixedHeight(28)
        self.export_button.clicked.connect(self.export_requested)
        footer.addWidget(self.export_button)
        root.addLayout(footer)

    def set_single_mode_layout(self, single_mode: bool) -> None:
        """Show the compact 10-metric layout only for single-stock training."""
        self.set_training_mode_layout("single" if single_mode else "continuous")

    def set_training_mode_layout(self, mode: str) -> None:
        """Choose mode-specific metrics without changing their calculations."""
        if mode not in {"single", "independent", "continuous"}:
            mode = "continuous"
        self._layout_mode = mode
        self._single_mode_layout = mode == "single"
        if mode == "single":
            left_keys = SINGLE_MODE_LEFT_METRICS
            right_keys = SINGLE_MODE_RIGHT_METRICS
            left_header = "收益与交易"
            right_header = "风险与基准"
        elif mode == "independent":
            left_keys = INDEPENDENT_MODE_LEFT_METRICS
            right_keys = INDEPENDENT_MODE_RIGHT_METRICS
            left_header = "总体结果"
            right_header = "交易质量"
        else:
            left_keys = tuple(key for key, _title in LEFT_METRICS)
            right_keys = tuple(key for key, _title in RIGHT_METRICS)
            left_header = "收益与交易"
            right_header = "风险与基准"

        self._left_header.setText(left_header)
        self._right_header.setText(right_header)
        default_titles = dict((*LEFT_METRICS, *RIGHT_METRICS))
        for key, default_title in default_titles.items():
            title = default_title
            explanation = METRIC_EXPLANATIONS[key]
            if mode == "independent" and key == "total_return":
                title = "平均每轮收益率"
                explanation = (
                    "各独立轮次净盈亏合计除以各轮期初资金合计；"
                    "各轮本金相同时等同于平均每轮收益率。"
                )
            elif mode == "independent" and key == "net_profit":
                title = "累计净盈亏"
                explanation = "所有独立训练轮次净盈亏金额的合计。"
            self._metric_titles[key] = title
            self._metric_explanations[key] = explanation
            self._metric_name_labels[key].setText(title)

        visible_keys = set(left_keys) | set(right_keys)
        for row in range(1, max(len(LEFT_METRICS), len(RIGHT_METRICS)) + 1):
            self._metric_grid.setRowStretch(row, 0)
        for key, cell in self._metric_cells.items():
            self._metric_grid.removeWidget(cell)
            cell.setVisible(key in visible_keys)
        for row, key in enumerate(left_keys, start=1):
            self._metric_grid.addWidget(self._metric_cells[key], row, 0)
            self._metric_grid.setRowStretch(row, 1)
        for row, key in enumerate(right_keys, start=1):
            self._metric_grid.addWidget(self._metric_cells[key], row, 1)
            self._metric_grid.setRowStretch(row, 1)
        self._layout_overlay()

    def _metric_cell(self, key: str, title: str) -> QWidget:
        cell = QFrame()
        cell.setObjectName("PerformanceMetricCell")
        cell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(7, 1, 7, 1)
        layout.setSpacing(8)
        name_label = QLabel(title)
        name_label.setObjectName("PerformanceMetricName")
        value_label = QLabel("--")
        value_label.setObjectName("PerformanceMetricValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_label.setFont(QFont("Consolas", 10, QFont.Weight.DemiBold))
        value_label.setMinimumWidth(88)
        layout.addWidget(name_label)
        layout.addStretch(1)
        layout.addWidget(value_label)
        self._value_labels[key] = value_label
        self._metric_cells[key] = cell
        self._metric_name_labels[key] = name_label
        self._metric_titles[key] = title
        return cell

    @staticmethod
    def _numeric_value(text: str) -> float | None:
        cleaned = text.strip().replace(",", "").replace("%", "")
        cleaned = cleaned.removesuffix("段").strip()
        if cleaned in {"", "--", "无亏损", "无回撤"}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def _metric_evaluation(
        cls,
        key: str,
        text: str,
        tone: str,
        sample_days: int,
    ) -> str:
        value = cls._numeric_value(text)
        if text == "无亏损":
            return "当前没有亏损样本，结果很好，但样本增加后可能变化。"
        if text == "无回撤":
            return "当前收益为正且尚未出现回撤，样本增加后再判断稳定性。"
        if value is None:
            return "当前样本不足，暂时无法形成有效评价。"
        if key == "initial_asset":
            return "基准数值，本身没有好坏之分。"
        if key == "ending_asset":
            return "高于期初说明盈利，低于期初说明亏损。" if not tone else (
                "当前高于期初资产，处于盈利状态。" if tone == "up" else "当前低于期初资产，处于亏损状态。"
            )
        if key in {"net_profit", "total_return", "expectancy", "excess_return"}:
            return "当前为正，表现积极。" if value > 0 else (
                "当前为负，需要改善。" if value < 0 else "当前基本持平。"
            )
        if key == "annual_return":
            if sample_days < 60:
                return f"仅有 {sample_days} 个日收益样本，年化结果容易被放大，参考性较低。"
            return "当前年化结果为正。" if value > 0 else "当前年化结果为负。"
        if key == "segment_count":
            return "少于10段，样本很少。" if value < 10 else (
                "10–29段，样本仍偏少。" if value < 30 else "达到30段以上，初步具备统计参考性。"
            )
        if key == "win_rate":
            return "60%以上，当前胜率较高。" if value >= 60 else (
                "50%–60%，当前胜率中等。" if value >= 50 else "低于50%，需依靠较高盈亏比弥补。"
            )
        if key in {"profit_loss_ratio", "profit_factor"}:
            return "达到2以上，当前表现较好。" if value >= 2 else (
                "1–2之间，当前有正向优势。" if value >= 1 else "低于1，当前盈利不足以覆盖亏损。"
            )
        if key == "benchmark_return":
            return "同期大盘上涨。" if value > 0 else ("同期大盘下跌。" if value < 0 else "同期大盘基本持平。")
        if key == "max_drawdown":
            drawdown = abs(value)
            return "5%以内，回撤控制优秀。" if drawdown <= 5 else (
                "5%–10%，回撤控制良好。" if drawdown <= 10 else (
                    "10%–20%，回撤中等。" if drawdown <= 20 else "超过20%，回撤风险较高。"
                )
            )
        if key == "annual_volatility":
            level = "波动较低。" if value < 15 else ("波动中等。" if value < 30 else "波动较高。")
            return level + (" 当前样本较少，评级不稳定。" if sample_days < 20 else "")
        if key in {"sharpe_ratio", "sortino_ratio"}:
            level = "2以上，当前表现优秀。" if value >= 2 else (
                "1–2之间，当前表现良好。" if value >= 1 else (
                    "0–1之间，风险收益效率一般。" if value >= 0 else "低于0，当前收益未覆盖风险。"
                )
            )
            return level + (" 但样本少于20日，数值可能失真。" if sample_days < 20 else "")
        if key == "return_drawdown_ratio":
            return "3以上，当前收益与回撤的配合优秀。" if value >= 3 else (
                "2–3之间，当前表现良好。" if value >= 2 else (
                    "1–2之间，当前尚可。" if value >= 1 else "低于1，收益不足以覆盖同等幅度的回撤。"
                )
            )
        if key == "average_win":
            return "当前平均盈利为正，需结合平均亏损和胜率判断。"
        if key == "average_loss":
            return "亏损幅度越接近0越好，需结合平均盈利判断。"
        if key == "fee_and_tax":
            return "成本没有固定好坏标准，应结合成交频率和净盈利判断。"
        return "请结合交易样本数量和其他指标综合判断。"

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#PerformanceOverlay {
                background: #111820;
                border: 1px solid #36434f;
                border-left: none;
                border-top-right-radius: 10px;
                border-bottom-right-radius: 10px;
            }
            QLabel#PerformanceTitle {
                color: #eef2f5; background: #111820;
                font-size: 15px; font-weight: 800;
            }
            QLabel#PerformanceSubtitle {
                color: #929da8; background: #111820; font-size: 10px;
            }
            QLabel#PerformanceGroupTitle {
                color: #9aafc2; background: #1a222b;
                font-size: 10px; font-weight: 800;
                padding: 4px 7px;
                border: 1px solid #303c47;
                border-radius: 4px;
            }
            QFrame#PerformanceMetricCell {
                background: #171f28;
                border: 1px solid #2a3540;
                border-radius: 4px;
            }
            QFrame#PerformanceMetricCell QLabel { background: #171f28; }
            QLabel#PerformanceMetricName { color: #a6afb8; font-size: 10px; }
            QLabel#PerformanceMetricValue { color: #edf4fb; font-size: 10px; }
            QLabel#PerformanceMetricValue[tone="up"] { color: #ff5b5b; }
            QLabel#PerformanceMetricValue[tone="down"] { color: #42d887; }
            QLabel#PerformanceMetricValue[tone="muted"] { color: #687b91; }
            QLabel#PerformanceSampleHint {
                color: #b7a277; background: #111820; font-size: 9px;
            }
            QPushButton#PerformanceClose {
                color: #a8b0b8; background: #111820; border: none;
                font-size: 19px; font-weight: 700;
            }
            QPushButton#PerformanceClose:hover { color: white; background: #24354a; border-radius: 6px; }
            QPushButton#PerformanceExport {
                color: #eaf2ff; background: #1f6feb; border: 1px solid #438cf2;
                border-radius: 5px; padding: 3px 10px; font-weight: 700;
            }
            QPushButton#PerformanceExport:hover { background: #2d7ff0; }
            """
        )
        self.handle.setStyleSheet(
            """
            QPushButton#PerformanceHandle {
                color: #e5eaee; background: #26333f;
                border: 1px solid #526474;
                border-radius: 6px;
                font-size: 11px; font-weight: 800; padding: 0 12px;
            }
            QPushButton#PerformanceHandle:hover {
                background: #34495c; border-color: #71879a; color: white;
            }
            """
        )

    def set_available(self, available: bool) -> None:
        self.available = bool(available)
        if not self.available:
            self._animation.stop()
            self.expanded = False
            self.hide()
            self.handle.hide()
            return
        self._layout_overlay()
        if not self.expanded and self.handle_enabled:
            self.handle.show()
            self.handle.raise_()

    def set_handle_enabled(self, enabled: bool) -> None:
        self.handle_enabled = bool(enabled)
        if not self.handle_enabled:
            self._animation.stop()
            self.expanded = False
            self.hide()
            self.handle.hide()
        elif self.available:
            self._layout_overlay()
            self.handle.show()
            self.handle.raise_()

    def set_summary(
        self,
        title: str,
        subtitle: str,
        values: dict[str, tuple[str, str]],
        sample_hint: str = "",
        sample_days: int = 0,
    ) -> None:
        if self.title_label.text() != title:
            self.title_label.setText(title)
        if self.subtitle_label.text() != subtitle:
            self.subtitle_label.setText(subtitle)
        if self.sample_hint.text() != sample_hint:
            self.sample_hint.setText(sample_hint)
        for key, label in self._value_labels.items():
            text, tone = values.get(key, ("--", "muted"))
            if label.text() != text:
                label.setText(text)
            if label.property("tone") != tone:
                label.setProperty("tone", tone)
                label.style().unpolish(label)
                label.style().polish(label)
            metric_title = self._metric_titles[key]
            explanation = self._metric_explanations[key]
            evaluation = self._metric_evaluation(key, text, tone, sample_days)
            self._metric_cells[key].setToolTip(
                f"{metric_title}\n当前值：{text}\n含义：{explanation}\n当前评价：{evaluation}"
            )

    def expand(self) -> None:
        if not self.available or not self.handle_enabled or self.expanded:
            return
        self.expanded = True
        self.handle.hide()
        self.summary_refresh_requested.emit()
        start, end = self._panel_geometries()
        self.setGeometry(start)
        self.show()
        self.raise_()
        self._animate_to(end)

    def collapse(self) -> None:
        if not self.expanded:
            return
        self.expanded = False
        start, end = self._panel_geometries()
        self._animate_to(start)

    def _animate_to(self, geometry: QRect) -> None:
        self._target_geometry = geometry
        self._animation.stop()
        self._animation.setStartValue(self.geometry())
        self._animation.setEndValue(geometry)
        self._animation.start()

    def _finish_animation(self) -> None:
        if not self.expanded:
            self.hide()
            if self.available and self.handle_enabled:
                self.handle.show()
                self.handle.raise_()

    def _chart_rect(self) -> QRect:
        try:
            main_rect, _pane_rects = self.chart_widget._layout_areas()
            return main_rect.toRect()
        except (AttributeError, TypeError):
            return self.chart_widget.rect()

    def _panel_geometries(self) -> tuple[QRect, QRect]:
        chart_rect = self._chart_rect()
        # Two metric columns need more than half the chart at common 720p/125%
        # layouts; the old 50% width clipped the right-hand values.
        width = max(560, min(760, int(chart_rect.width() * 0.72)))
        width = min(width, max(260, chart_rect.width() - 8))
        top = chart_rect.top() + 2
        # Keep the two-column rows comfortably readable on very tall/4K
        # windows instead of stretching each separator dozens of pixels apart.
        target_height = 330 if self._layout_mode in {"single", "independent"} else 520
        height = max(1, min(target_height, chart_rect.height() - 4))
        open_geometry = QRect(chart_rect.left(), top, width, height)
        closed_geometry = QRect(chart_rect.left() - width - 2, top, width, height)
        return closed_geometry, open_geometry

    def _layout_overlay(self) -> None:
        closed_geometry, open_geometry = self._panel_geometries()
        self.setGeometry(open_geometry if self.expanded else closed_geometry)
        chart_rect = self._chart_rect()
        # Keep the compact horizontal entry directly below the MA legend while
        # leaving breathing room from the chart's left dashed boundary.
        handle_left = chart_rect.left() + 8
        handle_top = chart_rect.top() + min(34, max(4, chart_rect.height() - 32))
        self.handle.setGeometry(
            handle_left,
            handle_top,
            min(92, max(56, chart_rect.right() - handle_left)),
            min(28, max(24, chart_rect.bottom() - handle_top)),
        )
        if self.expanded:
            self.raise_()
        elif self.available and self.handle_enabled:
            self.handle.raise_()

    def mousePressEvent(self, event) -> None:
        # Labels and empty cell areas do not handle mouse presses themselves.
        # Accept the propagated event here so an inside click never reaches the
        # chart and gets mistaken for an outside-click collapse request.
        event.accept()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.chart_widget:
            if event.type() == QEvent.Type.Resize:
                self._layout_overlay()
            elif event.type() == QEvent.Type.MouseButtonPress and self.expanded:
                if hasattr(event, "position") and self.geometry().contains(
                    event.position().toPoint()
                ):
                    return False
                # Return False so the same click still performs the chart's normal action.
                self.collapse()
                return False
        return super().eventFilter(watched, event)
