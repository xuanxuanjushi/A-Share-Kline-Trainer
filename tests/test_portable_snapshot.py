from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_simulator import config
from stock_simulator.portable_builder import build_portable_folder
from stock_simulator.tdx_reader import DAY_RECORD, TdxDayReader


class PortableSnapshotTests(unittest.TestCase):
    def test_build_contains_market_data_and_survives_move(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            day = source / 'vipdoc/sh/lday/sh600000.day'
            day.parent.mkdir(parents=True)
            day.write_bytes(DAY_RECORD.pack(20260904, 1000, 1100, 900, 1050, 100000., 10000, 0))
            sz_day = source / 'vipdoc/sz/lday/sz000001.day'
            sz_day.parent.mkdir(parents=True)
            sz_day.write_bytes(day.read_bytes())
            hq = source / 'T0002/hq_cache'
            hq.mkdir(parents=True)
            for name in ('gbbq', 'shs.tnf', 'szs.tnf', 'base.dbf'):
                (hq / name).write_bytes(b'test')
            (hq / 'private.txt').write_text('private')
            profile = root / 'profile'
            profile.mkdir()
            (profile / 'settings.json').write_text(json.dumps({'tdx_root': str(source)}))
            (profile / 'performance_history.json').write_text('["private"]')
            executable = root / 'app.exe'
            executable.write_bytes(b'fake runtime')
            result = build_portable_folder(root / 'out', profile, frozen=True, executable_path=executable)
            moved = root / '中文 portable moved'
            shutil.move(str(result.directory), moved)
            shutil.rmtree(source)
            settings_file = moved / 'portable_data/settings.json'
            with patch.object(config, 'application_directory', return_value=moved), patch.object(config, 'CONFIG_PATH', settings_file):
                settings = config.load_settings()
                reader = TdxDayReader(settings.tdx_root)
                self.assertEqual(reader.read_daily_bars('sh600000')[-1].date, '2026-09-04')
                config.save_settings(settings)
                saved = json.loads(settings_file.read_text())
                self.assertFalse(Path(saved['tdx_root']).is_absolute())
                self.assertEqual(config.load_settings().tdx_root, settings.tdx_root)
            reexport = build_portable_folder(root / 'out2', settings_file.parent,
                                            frozen=True, executable_path=moved / '大A日K股票模拟训练器.exe')
            self.assertTrue((reexport.directory / 'market_data/vipdoc/sh/lday/sh600000.day').exists())
            self.assertFalse((moved / 'portable_data/performance_history.json').exists())
            self.assertFalse((Path(settings.tdx_root) / 'T0002/hq_cache/private.txt').exists())
            self.assertTrue((Path(settings.tdx_root) / 'T0002/hq_cache/gbbq').is_file())

    def test_missing_market_source_fails_without_publishing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / 'app.exe'
            executable.write_bytes(b'fake')
            with self.assertRaisesRegex((ValueError, FileNotFoundError), '日K|数据|目录'):
                build_portable_folder(root / 'out', root / 'missing', frozen=True, executable_path=executable)
            self.assertEqual(list((root / 'out').iterdir()), [])

    def test_external_setting_remains_external(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings_file = root / 'settings.json'
            external = str(root / 'external')
            with patch.object(config, 'application_directory', return_value=root), patch.object(config, 'CONFIG_PATH', settings_file):
                config.save_settings(config.AppSettings(tdx_root=external))
                self.assertEqual(config.load_settings().tdx_root, external)
