import json
import tempfile
import unittest
from pathlib import Path
from stock_simulator.portable_builder import build_portable_folder


class LightPortableTests(unittest.TestCase):
    def test_without_market_data_needs_no_source_and_has_empty_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / 'app.exe'
            exe.write_bytes(b'fake')
            result = build_portable_folder(root / 'out', root / 'missing', frozen=True,
                executable_path=exe, include_market_data=False)
            self.assertFalse((result.directory / 'market_data').exists())
            self.assertEqual(json.loads((result.directory / 'portable_data/settings.json').read_text())['tdx_root'], '')
            self.assertIn('不包含通达信行情', (result.directory / '便携版说明.txt').read_text(encoding='utf-8-sig'))
