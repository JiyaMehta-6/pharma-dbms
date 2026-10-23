"""Versioned schema migrations: fresh stamp, idempotency, upgrade path."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from tests.support import TempDbTestCase, write_csv

from pharma_db import services
from pharma_db.db import Database


class FreshDatabaseTest(TempDbTestCase):
    def test_rebuild_stamps_current_version(self) -> None:
        self.assertEqual(services.current_version(self.db), services.CURRENT_VERSION)

    def test_migrate_is_noop_on_fresh_database(self) -> None:
        before = self.db.query("SELECT version FROM schema_migrations")
        self.assertEqual(services.migrate(self.db), services.CURRENT_VERSION)
        after = self.db.query("SELECT version FROM schema_migrations")
        self.assertEqual(
            [tuple(r) for r in before], [tuple(r) for r in after]
        )

    def test_migration_table_records_applied_at(self) -> None:
        row = self.db.query_one(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        )
        assert row is not None
        self.assertEqual(row["version"], services.CURRENT_VERSION)
        self.assertTrue(row["applied_at"])


class LegacyUpgradeTest(unittest.TestCase):
    """A pre-migration database (no schema_migrations) is upgraded in place."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory(prefix="pharma_migrate_")
        self.root = Path(self._tmp.name)
        self.csv_path = write_csv(self.root / "medicines.csv")
        self.db_path = self.root / "legacy.db"
        self._build_legacy()
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def _build_legacy(self) -> None:
        """Create a database with the old (pre-CHECK) schema and no migrations."""
        con = sqlite3.connect(str(self.db_path))
        try:
            con.executescript(
                """
                CREATE TABLE manufacturers (
                    manufacturer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    manufacturer_name TEXT NOT NULL UNIQUE
                );
                CREATE TABLE compositions (
                    composition_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    composition_text TEXT NOT NULL UNIQUE
                );
                CREATE TABLE medicines (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    price_rs REAL NOT NULL,
                    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(manufacturer_id),
                    type TEXT NOT NULL,
                    pack_size_label TEXT,
                    composition1_id INTEGER NOT NULL REFERENCES compositions(composition_id),
                    composition2_id INTEGER REFERENCES compositions(composition_id)
                );
                INSERT INTO manufacturers (manufacturer_name) VALUES ('Legacy Mfr');
                INSERT INTO compositions (composition_text) VALUES ('Legacy Comp');
                INSERT INTO medicines (id, name, price_rs, manufacturer_id, type,
                                       pack_size_label, composition1_id, composition2_id)
                VALUES (1, 'Legacy Med', 10.0, 1, 'allopathy', NULL, 1, NULL);
                """
            )
            con.commit()
        finally:
            con.close()

    def test_legacy_reports_version_zero(self) -> None:
        self.assertEqual(services.current_version(self.db), 0)

    def test_migrate_adds_auth_tables_and_stamps(self) -> None:
        version = services.migrate(self.db)
        self.assertEqual(version, services.CURRENT_VERSION)
        tables = {
            r["name"]
            for r in self.db.query(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertIn("users", tables)
        self.assertIn("audit_log", tables)
        self.assertIn("schema_migrations", tables)

    def test_migrate_preserves_existing_data(self) -> None:
        services.migrate(self.db)
        count = self.db.scalar("SELECT COUNT(*) FROM medicines")
        self.assertEqual(count, 1)
        name = self.db.scalar("SELECT name FROM medicines WHERE id = 1")
        self.assertEqual(name, "Legacy Med")

    def test_migrate_is_idempotent(self) -> None:
        services.migrate(self.db)
        rows_before = self.db.query(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        self.assertEqual(services.migrate(self.db), services.CURRENT_VERSION)
        rows_after = self.db.query(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        self.assertEqual(
            [tuple(r) for r in rows_before], [tuple(r) for r in rows_after]
        )


class FailureRollbackTest(unittest.TestCase):
    """A failing migration leaves the version unchanged."""

    def test_failed_migration_not_recorded(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="pharma_fail_") as tmp:
            root = Path(tmp)
            csv_path = write_csv(root / "medicines.csv")
            db = Database(root / "test.db")
            services.rebuild_database(db, csv_path=csv_path)
            original = dict(services.MIGRATIONS)
            try:
                services.MIGRATIONS[99] = ("SELECT * FROM missing_table;",)
                with self.assertRaises(sqlite3.Error):
                    services.migrate(db)
                self.assertNotIn(
                    99,
                    [
                        int(r[0])
                        for r in db.query("SELECT version FROM schema_migrations")
                    ],
                )
            finally:
                services.MIGRATIONS.clear()
                services.MIGRATIONS.update(original)
                db.close()


if __name__ == "__main__":
    unittest.main()
