"""Database wrapper behaviour."""
from __future__ import annotations

import sqlite3
import unittest

from tests.support import TempDbTestCase

from pharma_db.db import Database, DatabaseError


class DatabaseTest(TempDbTestCase):
    def test_missing_file_raises(self) -> None:
        missing = Database(self.root / "nope.db")
        with self.assertRaises(DatabaseError):
            missing.connection()
        missing.close()

    def test_query_returns_row_objects(self) -> None:
        row = self.db.query_one("SELECT 1 AS one, 'x' AS two")
        assert row is not None
        self.assertEqual(row["one"], 1)
        self.assertEqual(row["two"], "x")

    def test_scalar(self) -> None:
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM medicines"), 10)
        self.assertIsNone(self.db.scalar("SELECT NULL"))

    def test_execute_commits_and_returns_rowcount(self) -> None:
        changed = self.db.execute(
            "UPDATE medicines SET price_rs = 7 WHERE id = ?", (7,)
        )
        self.assertEqual(changed, 1)
        self.assertEqual(self.db.scalar("SELECT price_rs FROM medicines WHERE id = 7"), 7)

    def test_transaction_rolls_back_on_error(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as con:
                con.execute("UPDATE medicines SET price_rs = 0 WHERE id = 1")
                raise RuntimeError("boom")
        self.assertEqual(self.db.scalar("SELECT price_rs FROM medicines WHERE id = 1"), 10.5)

    def test_integrity_check(self) -> None:
        self.assertEqual(self.db.integrity_check(), ["ok"])

    def test_file_info(self) -> None:
        info = self.db.file_info()
        self.assertEqual(info["path"], str(self.db.path))
        self.assertGreater(info["size_bytes"], 0)
        self.assertEqual(info["journal_mode"], "wal")
        self.assertGreater(info["page_size"], 0)
        self.assertEqual(info["page_count_from_size"], info["size_bytes"] // info["page_size"])

    def test_backup_to_creates_readable_copy(self) -> None:
        dest = self.root / "backups" / "copy.db"
        result = self.db.backup_to(dest)
        self.assertEqual(result, dest)
        self.assertTrue(dest.is_file())
        probe = Database(dest)
        self.assertEqual(probe.scalar("SELECT COUNT(*) FROM medicines"), 10)
        probe.close()

    def test_vacuum_and_wal_checkpoint(self) -> None:
        self.db.vacuum()
        self.assertEqual(self.db.integrity_check(), ["ok"])
        result = self.db.wal_checkpoint()
        self.assertEqual(len(result), 3)

    def test_path_switch_closes_old_connection(self) -> None:
        other = Database(self.root / "other.db")
        con = sqlite3.connect(str(other.path))
        con.execute("CREATE TABLE t (a INTEGER)")
        con.commit()
        con.close()

        self.db.path = other.path
        try:
            self.assertEqual(self.db.path, other.path)
            self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM t"), 0)
        finally:
            self.db.path = self.root / "test.db"  # restore for sibling tests

    def test_reopen_after_close(self) -> None:
        self.db.close()
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM medicines"), 10)


    def test_exists_flag(self) -> None:
        self.assertTrue(self.db.exists)
        missing = Database(self.root / "absent.db")
        self.assertFalse(missing.exists)
        missing.close()


if __name__ == "__main__":
    unittest.main()
