"""Concurrency: WAL allows a reader connection during a writer transaction."""
from __future__ import annotations

import threading
import unittest
from pathlib import Path

from tests.support import TempDbTestCase, write_csv

from pharma_db import services
from pharma_db.db import Database
from pharma_db.models import Medicine
from pharma_db.repositories import MedicineRepository


class WalModeTest(TempDbTestCase):
    def test_live_connection_uses_wal(self) -> None:
        # PRAGMAS includes journal_mode=WAL, applied on every connect.
        mode = self.db.scalar("PRAGMA journal_mode")
        self.assertEqual(mode, "wal")

    def test_fresh_handle_after_rebuild_is_wal(self) -> None:
        self.rebuild()
        probe = Database(self.db.path)
        try:
            self.assertEqual(probe.scalar("PRAGMA journal_mode"), "wal")
        finally:
            probe.close()

    def test_rebuild_cleans_up_wal_sidecars(self) -> None:
        # rebuild_database switches to DELETE mode and checkpoints so the
        # file can be copied or shipped without the -wal/-shm sidecars that
        # WAL mode leaves behind.
        self.rebuild()
        self.assertFalse(Path(str(self.db.path) + "-wal").exists())
        self.assertFalse(Path(str(self.db.path) + "-shm").exists())


class DualConnectionTest(unittest.TestCase):
    """A second Database handle can read while the first holds a write txn."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory(prefix="pharma_conc_")
        self.root = Path(self._tmp.name)
        self.csv_path = write_csv(self.root / "medicines.csv")
        self.db_path = self.root / "test.db"
        bootstrap = Database(self.db_path)
        services.rebuild_database(bootstrap, csv_path=self.csv_path)
        bootstrap.close()
        self.writer = Database(self.db_path)
        self.reader = Database(self.db_path)

    def tearDown(self) -> None:
        self.writer.close()
        self.reader.close()
        self._tmp.cleanup()

    def test_reader_sees_data_during_open_write_transaction(self) -> None:
        write_started = threading.Event()
        release_write = threading.Event()
        read_done = threading.Event()
        results: dict[str, object] = {}

        def writer_task() -> None:
            with self.writer.transaction() as con:
                con.execute(
                    "INSERT INTO medicines (name, price_rs, manufacturer_id, type,"
                    " pack_size_label, composition1_id, composition2_id)"
                    " VALUES ('Concurrent Med', 12.5,"
                    " (SELECT manufacturer_id FROM manufacturers LIMIT 1),"
                    " 'allopathy', NULL,"
                    " (SELECT composition_id FROM compositions LIMIT 1), NULL)"
                )
                write_started.set()
                release_write.wait(timeout=10)

        def reader_task() -> None:
            write_started.wait(timeout=10)
            try:
                results["count"] = int(
                    self.reader.scalar("SELECT COUNT(*) FROM medicines")
                )
                results["error"] = None
            except Exception as exc:  # captured for assertion
                results["error"] = exc
            finally:
                read_done.set()

        writer_thread = threading.Thread(target=writer_task)
        reader_thread = threading.Thread(target=reader_task)
        writer_thread.start()
        reader_thread.start()
        self.assertTrue(read_done.wait(timeout=15), "reader did not finish")
        release_write.set()
        writer_thread.join(timeout=15)
        reader_thread.join(timeout=15)

        self.assertIsNone(results.get("error"), results.get("error"))
        # WAL readers see the last committed snapshot: the 10 fixture rows.
        self.assertEqual(results.get("count"), 10)
        self.assertEqual(
            int(self.writer.scalar("SELECT COUNT(*) FROM medicines")), 11
        )

    def test_concurrent_readers_agree(self) -> None:
        counts: list[int] = []
        lock = threading.Lock()

        def reader() -> None:
            value = int(self.reader.scalar("SELECT COUNT(*) FROM medicines"))
            with lock:
                counts.append(value)

        threads = [threading.Thread(target=reader) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(counts, [10] * 8)

    def test_writes_serialize_across_handles(self) -> None:
        for index in range(5):
            MedicineRepository(self.writer).save(
                Medicine(
                    name=f"Serial {index}",
                    price_rs=1.0,
                    manufacturer_name="Mfr A",
                    composition1="Paracetamol (100mg)",
                )
            )
        self.assertEqual(
            int(self.reader.scalar("SELECT COUNT(*) FROM medicines")), 15
        )


if __name__ == "__main__":
    unittest.main()
