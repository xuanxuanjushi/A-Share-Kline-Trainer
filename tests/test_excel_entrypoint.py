import csv
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from openpyxl import load_workbook
from stock_simulator.app import MainWindow
from stock_simulator.models import EquityPoint, RoundRecord, TradeNode, TradeResult
from stock_simulator.performance import calculate_performance_metrics


def report_window(directory, points=None):
    points = points or [EquityPoint('2020-01-02', TradeNode.CLOSE, 99990),
                        EquityPoint('2020-01-03', TradeNode.CLOSE, 105000)]
    trade = TradeResult(True, '', 'buy', 0, points[0].date, price=10, quantity=100, amount=1000, fee=5)
    record = RoundRecord(1, 'sz000061', '测试股票', points[-1].total_asset - 100000,
                         start_date=points[0].date, end_date=points[-1].date,
                         start_cash=100000, end_asset=points[-1].total_asset,
                         equity_points=points, trades=[trade])
    metrics = calculate_performance_metrics(initial_asset=100000, ending_asset=record.end_asset,
        segments=[], trades=record.trades, equity_points=points, index_bars=[],
        start_date=record.start_date, end_date=record.end_date, start_node=TradeNode.OPEN, end_node=TradeNode.CLOSE)
    return SimpleNamespace(
        _performance_records_for_overlay=lambda: [record],
        _calculate_performance_scope=lambda records: (metrics, [], record.start_date, TradeNode.OPEN, record.end_date, TradeNode.CLOSE),
        training_mode_kind='continuous', continuous_compound_mode=True,
        _uses_round_records=lambda: True, _has_position=lambda: False,
        _metrics_csv_fields=MainWindow._metrics_csv_fields,
        _metrics_for_one_record=lambda r, bars: metrics, _segments_for_record=lambda r: [],
        _desktop_directory=lambda: directory, _available_performance_csv_path=MainWindow._available_performance_csv_path,
        _update_status=Mock(), _show_snapshot_notice=Mock())


class ExcelEntrypointTests(unittest.TestCase):
    def test_excel_and_csv_keep_identical_statistics_and_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = report_window(Path(tmp))
            csv_path = MainWindow._export_performance_report(window, 'CSV')
            excel_path = MainWindow._export_performance_report(window, 'Excel')
            self.assertIsNotNone(excel_path, window._update_status.call_args)
            repeated = MainWindow._export_performance_report(window, 'Excel')
            self.assertNotEqual(excel_path, repeated)
            with csv_path.open(encoding='utf-8-sig', newline='') as handle:
                source = list(csv.reader(handle))
            workbook = load_workbook(excel_path)
            actual = list(workbook['原始统计'].values)
            self.assertEqual(len(source), len(actual))
            for left, right in zip(source, actual):
                for expected, value in zip(left, right):
                    if isinstance(value, (float, int)):
                        self.assertAlmostEqual(float(expected), value)
                    else:
                        self.assertEqual(expected, value or '')
            workbook.close()

    def test_write_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = report_window(Path(tmp))
            with patch('stock_simulator.excel_export.write_performance_workbook', side_effect=PermissionError('locked')):
                self.assertIsNone(MainWindow._export_performance_report(window, 'Excel'))
            self.assertIn('失败', window._update_status.call_args.args[0])
            self.assertEqual(list(Path(tmp).iterdir()), [])
