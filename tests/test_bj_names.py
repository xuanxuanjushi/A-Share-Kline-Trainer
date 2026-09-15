import tempfile
import unittest
from pathlib import Path

from stock_simulator.stock_info import StockInfoReader


class BeijingNameTests(unittest.TestCase):
    def test_beijing_names_from_own_tnf_before_and_after_cache_load(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'T0002/hq_cache'
            folder.mkdir(parents=True)
            record = bytearray(360)
            record[:6] = b'920008'
            name = '测试北交'.encode('gbk')
            record[31:31+len(name)] = name
            (folder / 'bjs.tnf').write_bytes(bytes(50) + record)
            reader = StockInfoReader(root)
            self.assertEqual(reader.name_for('bj920008'), '测试北交')
            reader._load_name_cache()
            self.assertEqual(reader.name_for('bj920008'), '测试北交')
            self.assertEqual(reader.name_for('sz920008'), '')
