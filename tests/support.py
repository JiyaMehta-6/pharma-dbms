"""Shared fixtures for the Pharma DBMS test-suite.

Tests never touch the real database: each fixture builds a small SQLite file
in a temporary directory from a 10-row CSV using the same
``services.rebuild_database`` code path the GUI uses.
"""
from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

# Headless-safe default; harmless when a real display is available.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pharma_db import services
from pharma_db.db import Database

CSV_HEADER = [
    "id",
    "name",
    "price",
    "Is_discontinued",
    "manufacturer_name",
    "type",
    "pack_size_label",
    "short_composition1",
    "short_composition2",
]

CSV_ROWS: list[list[object]] = [
    [1, "Alpha Tab 100", 10.5, "FALSE", "Mfr A", "allopathy",
     "strip of 10 tablets", "Paracetamol (100mg)", "Caffeine (50mg)"],
    [2, "Alpha Tab 500", 55.0, "FALSE", "Mfr A", "allopathy",
     "strip of 10 tablets", "Paracetamol (500mg)", ""],
    [3, "Beta Cap 250", 250.75, "FALSE", "Mfr B", "allopathy",
     "bottle of 30 capsules", "Ibuprofen (250mg)", "Cetirizine (10mg)"],
    [4, "Gamma Syrup", 99.0, "FALSE", "Mfr B", "allopathy",
     "bottle of 100 ml syrup", "Ambroxol (30mg/5ml)", "Levosalbutamol (1mg/5ml)"],
    [5, "Delta Injection 5mg", 1200.0, "FALSE", "Mfr C", "allopathy",
     "vial of 2 ml injection", "Ringer Lactate (NA)", ""],
    [6, "Epsilon Cream", 80.25, "FALSE", "Mfr C", "allopathy",
     "tube of 15 gm cream", "Mometasone (0.1%)", ""],
    [7, "Zeta Tab 10", 5.0, "FALSE", "Mfr D", "allopathy",
     "strip of 10 tablets", "Paracetamol (10mg)", ""],
    [8, "Eta Cap 20", 20.0, "FALSE", "Mfr D", "allopathy",
     "strip of 5 capsules", "Paracetamol (10mg)", "Caffeine (50mg)"],
    [9, "Theta 1000", 2500.0, "FALSE", "Mfr A", "allopathy",
     "box of 1 vial", "Amoxicillin (1000mg)", ""],
    [10, "Iota Syrup 50", 50.0, "FALSE", "Mfr B", "allopathy",
     "bottle of 60 ml syrup", "Paracetamol (125mg/5ml)", ""],
]


def make_temp_file(suffix: str = "") -> Path:
    """Return a path to an unused temp file.

    ``tempfile.mkstemp`` returns an open file descriptor. If it is left open,
    Windows holds an exclusive lock on the file and later cleanup (or a
    re-write through the same path) fails with PermissionError. Close it
    immediately; callers only need the name.
    """
    fd, name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(name)


def write_csv(path: Path, rows: list[list[object]] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows if rows is not None else CSV_ROWS)
    return path


def build_test_db(root: Path) -> tuple[Database, Path]:
    csv_path = write_csv(root / "medicines.csv")
    db = Database(root / "test.db")
    services.rebuild_database(db, csv_path=csv_path)
    return db, csv_path


class TempDbTestCase(unittest.TestCase):
    """Base class providing a freshly rebuilt temporary database."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="pharma_tests_")
        cls.root = Path(cls._tmp.name)
        cls.db, cls.csv_path = build_test_db(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()
        cls._tmp.cleanup()

    def rebuild(self) -> dict[str, int]:
        return services.rebuild_database(self.db, csv_path=self.csv_path)


class FixtureCsvTestCase(unittest.TestCase):
    """Isolated database built from a caller-supplied CSV.

    Unlike :class:`TempDbTestCase`, the fixture CSV is written to a private
    temp directory on every test, so a class that rebuilds with custom rows
    cannot poison the shared fixture that other test classes rely on.
    """

    fixture_rows: ClassVar[list[list[object]] | None] = None

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="pharma_case_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.csv_path = write_csv(self.root / "medicines.csv", self.fixture_rows)
        self.db = Database(self.root / "test.db")
        self.addCleanup(self.db.close)
        services.rebuild_database(self.db, csv_path=self.csv_path)

    def rebuild(self) -> dict[str, int]:
        return services.rebuild_database(self.db, csv_path=self.csv_path)


def get_qapp():
    from PySide6.QtWidgets import QApplication

    from pharma_db import config

    app = QApplication.instance()
    if app is None:
        app = QApplication(["pharma-tests"])
    # QSettings needs an org/app scope for round-tripping theme/db path.
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.APP_ORG)
    return app
