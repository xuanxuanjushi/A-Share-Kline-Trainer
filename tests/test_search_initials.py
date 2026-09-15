import unittest
from stock_simulator.stock_info import StockInfoReader, stock_name_initials
from stock_simulator.test_trade import test_window_anchor


class SearchAndViewRegressionTests(unittest.TestCase):
    def test_bank_queries_resolve_with_correct_pronunciation(self):
        reader = StockInfoReader('.')
        reader._name_cache = {
            'sh600036': '招商银行', 'sh601288': '农业银行',
            'sh601398': '工商银行', 'sz000001': '平安银行',
        }
        for query, code in [('zsyh', 'sh600036'), ('nyyh', 'sh601288'),
                            ('GSYH', 'sh601398'), ('payh', 'sz000001')]:
            with self.subTest(query=query):
                self.assertEqual(reader.resolve_code_query(query), code)
                self.assertEqual(reader.find_code_matches(query, []), [])
        self.assertEqual(reader.resolve_code_query('600036'), 'sh600036')

    def test_other_names_and_prefixes_keep_existing_behavior(self):
        for name, expected in [('云南白药', 'YNBY'), ('ST平安银行', 'PAYH'),
                               ('*ST农业银行', 'NYYH'), ('中国银行', 'ZGYH')]:
            with self.subTest(name=name):
                self.assertEqual(stock_name_initials(name), expected)

    def test_test_entry_preserves_existing_short_future_space(self):
        for distance in (0, 1, 3, 11, 12, 25):
            with self.subTest(distance=distance):
                self.assertEqual(test_window_anchor(50, 50 + distance, 200, 60),
                                 (50 + distance, distance))

    def test_test_entry_handles_end_and_empty_data(self):
        self.assertEqual(test_window_anchor(199, 199, 200, 60), (199, 0))
        self.assertEqual(test_window_anchor(0, 0, 0, 60), (0, 0))
