"""Path discovery and formatting helpers."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from pharma_db import config


class ConfigTest(unittest.TestCase):
    def test_project_root_has_pyproject(self) -> None:
        root = config.project_root()
        self.assertTrue((root / "pyproject.toml").is_file(), root)
        self.assertEqual(root, Path(__file__).resolve().parents[1])

    def test_data_paths_live_under_root(self) -> None:
        root = config.project_root()
        self.assertEqual(config.data_dir(), root / "Data")
        self.assertEqual(config.csv_path(), root / "Data" / config.CSV_FILENAME)
        self.assertEqual(config.default_db_path(), root / "Data" / config.DB_FILENAME)
        self.assertEqual(config.backup_dir(), root / "Data" / "Backups")

    def test_env_override_wins(self) -> None:
        with mock.patch.dict(os.environ, {"PHARMA_DB_PATH": "/tmp/custom.db"}):
            self.assertEqual(config.resolve_db_path(), Path("/tmp/custom.db"))

    def test_default_used_without_override(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "PHARMA_DB_PATH"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(config.resolve_db_path(), config.default_db_path())

    def test_format_money(self) -> None:
        self.assertEqual(config.format_money(1234.5), "\u20b91,234.50")
        self.assertEqual(config.format_money(None), "")

    def test_page_size_constants(self) -> None:
        self.assertIn(config.DEFAULT_PAGE_SIZE, config.PAGE_SIZES)
        self.assertEqual(sorted(config.PAGE_SIZES), list(config.PAGE_SIZES))


if __name__ == "__main__":
    unittest.main()
