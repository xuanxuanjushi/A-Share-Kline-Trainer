from __future__ import annotations

import unittest
from pathlib import Path

from stock_simulator import config as config_module


class TestEnvironmentIsolationTests(unittest.TestCase):
    def test_test_runner_never_uses_the_real_user_data_directory(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        real_user_data_dir = (project_root / "config").resolve()

        self.assertNotEqual(config_module.CONFIG_PATH.resolve().parent, real_user_data_dir)


if __name__ == "__main__":
    unittest.main()
