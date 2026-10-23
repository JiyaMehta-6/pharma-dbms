"""Application services: CSV rebuild, SQL runner, export and backups."""
from __future__ import annotations

import shutil
import sqlite3
import unittest
from unittest import mock

from tests.support import TempDbTestCase, write_csv

from pharma_db import services
from pharma_db.models import Medicine, PageRequest
from pharma_db.repositories import MedicineRepository


class RebuildDatabaseTest(TempDbTestCase):
    def test_rebuild_restores_pristine_state(self) -> None:
        repo = MedicineRepository(self.db)
        repo.save(
            Medicine(
                name="Pollution Row",
                price_rs=1.0,
                manufacturer_name="Mfr Z",
                composition1="Junk (1mg)",
            )
        )
        self.assertEqual(repo.count(PageRequest()), 11)

        stats = self.rebuild()

        self.assertEqual(
            stats,
            {
                "medicines": 10,
                "manufacturers": 4,
                "compositions": 12,
                "orphan_manufacturers": 0,
                "orphan_compositions": 0,
            },
        )
        self.assertEqual(repo.count(PageRequest()), 10)

    def test_rebuild_reports_progress(self) -> None:
        seen: list[tuple[str, int, int]] = []
        services.rebuild_database(
            self.db, csv_path=self.csv_path, progress=lambda m, a, b: seen.append((m, a, b))
        )
        self.assertTrue(seen)
        self.assertEqual(seen[-1][0], "Finished")

    def test_rebuild_missing_csv(self) -> None:
        with self.assertRaises(FileNotFoundError):
            services.rebuild_database(self.db, csv_path=self.root / "missing.csv")

    def test_rebuild_rejects_csv_without_header(self) -> None:
        empty = self.root / "empty.csv"
        empty.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            services.rebuild_database(self.db, csv_path=empty)

    def test_rebuild_rejects_missing_composition(self) -> None:
        bad = self.root / "bad.csv"
        write_csv(
            bad,
            [[1, "X", 1.0, "FALSE", "Mfr A", "allopathy", "strip", "", ""]],
        )
        with self.assertRaises(ValueError):
            services.rebuild_database(self.db, csv_path=bad)

    def test_rebuild_collapses_identical_composition_pair(self) -> None:
        # The catalogue lists the same composition in both slots for a few
        # rows; that is one composition, and the CHECK rejects a pair.
        twin = self.root / "twin.csv"
        write_csv(
            twin,
            [
                [1, "Twin Tab", 10.0, "FALSE", "Mfr A", "allopathy",
                 "strip of 10 tablets", "Amlodipine (5mg)", "Amlodipine (5mg)"],
            ],
        )
        services.rebuild_database(self.db, csv_path=twin)
        con = sqlite3.connect(str(self.db.path))
        try:
            row = con.execute(
                "SELECT composition1_id, composition2_id FROM medicines WHERE id = 1"
            ).fetchone()
        finally:
            con.close()
        self.assertIsNotNone(row[0])
        self.assertIsNone(row[1])


class SplitStatementsTest(unittest.TestCase):
    def test_plain_split(self) -> None:
        self.assertEqual(
            services.split_statements("SELECT 1; SELECT 2;"),
            ["SELECT 1", "SELECT 2"],
        )

    def test_semicolons_in_quotes_stay(self) -> None:
        script = "SELECT ';' AS a; SELECT 2"
        self.assertEqual(
            services.split_statements(script),
            ["SELECT ';' AS a", "SELECT 2"],
        )

    def test_escaped_quotes(self) -> None:
        script = "SELECT 'it''s; fine'; SELECT 2"
        self.assertEqual(
            services.split_statements(script),
            ["SELECT 'it''s; fine'", "SELECT 2"],
        )

    def test_line_and_block_comments(self) -> None:
        script = "SELECT 1 -- trailing; comment\n; /* block; comment */ SELECT 2"
        self.assertEqual(
            services.split_statements(script),
            ["SELECT 1", "SELECT 2"],
        )

    def test_empty_script_and_trailing_tail(self) -> None:
        self.assertEqual(services.split_statements("   \n  "), [])
        self.assertEqual(services.split_statements("SELECT 1"), ["SELECT 1"])

    def test_dollar_free_double_quoted_ident(self) -> None:
        script = 'SELECT "a;b" FROM t; SELECT 2'
        self.assertEqual(
            services.split_statements(script),
            ['SELECT "a;b" FROM t', "SELECT 2"],
        )


class RunScriptTest(TempDbTestCase):
    def test_select_returns_rows_and_columns(self) -> None:
        results = services.run_script(self.db, "SELECT id, name FROM medicines WHERE id = 1;")
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result.ok)
        self.assertEqual(result.columns, ["id", "name"])
        self.assertEqual(result.rows, [(1, "Alpha Tab 100")])
        self.assertEqual(result.message, "1 row(s)")
        self.assertGreaterEqual(result.elapsed, 0.0)

    def test_multiple_statements_keep_last_select(self) -> None:
        results = services.run_script(
            self.db, "SELECT 1 AS a; SELECT 2 AS b, 3 AS c;"
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[-1].columns, ["b", "c"])
        self.assertEqual(results[-1].rows, [(2, 3)])

    def test_ddl_and_dml_messages(self) -> None:
        results = services.run_script(
            self.db,
            "CREATE TABLE scratch (a INTEGER); "
            "INSERT INTO scratch (a) VALUES (1); "
            "SELECT * FROM scratch; DROP TABLE scratch;",
        )
        self.assertEqual([r.error for r in results], [None, None, None, None])
        self.assertIn("1 row(s) affected", results[1].message)
        self.assertIsNone(
            self.db.query_one(
                "SELECT name FROM sqlite_master WHERE name = 'scratch'"
            )
        )

    def test_error_stops_the_script(self) -> None:
        results = services.run_script(
            self.db, "SELECT 1; SELECT * FROM does_not_exist; SELECT 2;"
        )
        self.assertEqual(len(results), 2)
        self.assertIsNone(results[0].error)
        self.assertIsNotNone(results[1].error)
        self.assertIn("does_not_exist", results[1].error or "")

    def test_transaction_control_statements_do_not_autocommit(self) -> None:
        results = services.run_script(self.db, "BEGIN; ROLLBACK;")
        self.assertEqual([r.error for r in results], [None, None])

    def test_max_rows_truncation(self) -> None:
        results = services.run_script(self.db, "SELECT * FROM medicines;", max_rows=3)
        self.assertEqual(len(results[0].rows), 3)
        self.assertTrue(results[0].truncated)
        self.assertIn("3 row(s)", results[0].message)

    def test_empty_script_returns_nothing(self) -> None:
        self.assertEqual(services.run_script(self.db, "  ;  ; "), [])


class ExportResultTest(TempDbTestCase):
    def test_export_writes_header_and_rows(self) -> None:
        sql, params = MedicineRepository(self.db).export_sql(
            PageRequest(text="paracetamol")
        )
        dest = self.root / "export.csv"
        written = services.export_result_to_csv(self.db.path, sql, params, dest)
        self.assertEqual(written, 5)
        lines = dest.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0].split(",")[0], "id")

    def test_export_empty_result_has_header_only(self) -> None:
        dest = self.root / "empty.csv"
        written = services.export_result_to_csv(
            self.db.path, "SELECT id, name FROM medicines WHERE 1 = 0", [], dest
        )
        self.assertEqual(written, 0)
        self.assertEqual(dest.read_text(encoding="utf-8-sig").splitlines(), ["id,name"])


class BackupLifecycleTest(TempDbTestCase):
    def setUp(self) -> None:
        self.backup_root = self.root / "backups"
        if self.backup_root.is_dir():
            shutil.rmtree(self.backup_root)
        patcher = mock.patch("pharma_db.config.backup_dir", return_value=self.backup_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_backup_to_explicit_path(self) -> None:
        dest = self.backup_root / "named.db"
        result = services.create_backup(self.db, dest)
        self.assertEqual(result, dest)
        probe = sqlite3.connect(str(dest))
        try:
            self.assertEqual(probe.execute("SELECT COUNT(*) FROM medicines").fetchone()[0], 10)
        finally:
            probe.close()

    def test_create_backup_uses_configured_dir_and_disambiguates(self) -> None:
        first = services.create_backup(self.db)
        self.assertEqual(first.parent, self.backup_root)
        second = services.create_backup(self.db)
        self.assertNotEqual(first, second)
        self.assertEqual(len(services.list_backups()), 2)

    def test_list_backups_missing_dir(self) -> None:
        # backup_dir() is patched for the whole class, so point it somewhere new.
        with mock.patch("pharma_db.config.backup_dir", return_value=self.root / "nope"):
            self.assertEqual(services.list_backups(), [])

    def test_restore_roundtrip(self) -> None:
        backup = services.create_backup(self.db)
        before = self.db.scalar("SELECT COUNT(*) FROM medicines")
        MedicineRepository(self.db).save(
            Medicine(
                name="Post-backup row",
                price_rs=2.0,
                manufacturer_name="Mfr A",
                composition1="Paracetamol (100mg)",
            )
        )
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM medicines"), before + 1)

        services.restore_backup(self.db, backup)

        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM medicines"), before)
        self.assertEqual(self.db.integrity_check(), ["ok"])

    def test_restore_rejects_corrupt_backup(self) -> None:
        bad = self.root / "corrupt.db"
        bad.write_bytes(b"this is not a sqlite file")
        with self.assertRaises(sqlite3.DatabaseError):
            services.restore_backup(self.db, bad)

    def test_delete_backup(self) -> None:
        backup = services.create_backup(self.db)
        services.delete_backup(backup)
        self.assertFalse(backup.exists())
        self.assertEqual(
            [b for b in services.list_backups() if b["path"] == backup], []
        )


class NormCompTest(unittest.TestCase):
    def test_norm_comp(self) -> None:
        self.assertIsNone(services.norm_comp(None))
        self.assertIsNone(services.norm_comp("   "))
        self.assertEqual(services.norm_comp("  A   B  "), "A B")


if __name__ == "__main__":
    unittest.main()
