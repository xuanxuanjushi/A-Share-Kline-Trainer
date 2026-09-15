from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="stock-simulator-tests-") as temporary_root:
        from stock_simulator import config as config_module

        config_module.CONFIG_PATH = Path(temporary_root) / "settings.json"
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
