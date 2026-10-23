"""SQLite connection handling shared by the GUI and CLI entry points."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

Row = sqlite3.Row

PRAGMAS = (
    "PRAGMA foreign_keys=ON;",
    "PRAGMA busy_timeout=5000;",
    "PRAGMA journal_mode=WAL;",
)


class DatabaseError(RuntimeError):
    """Raised when the database cannot be opened or a query fails."""


class Database:
    """Thread-guarded wrapper around a single SQLite connection.

    ``check_same_thread=False`` is used so background tasks (backup,
    integrity check, rebuild) can use the connection; an internal re-entrant
    lock serialises access and the GUI disables itself while long work runs.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._con: sqlite3.Connection | None = None

    # -- lifecycle -----------------------------------------------------------
    @property
    def path(self) -> Path:
        return self._path

    @path.setter
    def path(self, value: str | Path) -> None:
        with self._lock:
            self.close_unlocked()
            self._path = Path(value)

    @property
    def exists(self) -> bool:
        return self._path.is_file()

    def connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._con is None:
                if not self._path.is_file():
                    raise DatabaseError(f"Database file not found: {self._path}")
                try:
                    self._con = sqlite3.connect(
                        str(self._path),
                        check_same_thread=False,
                        timeout=5.0,
                    )
                except sqlite3.Error as exc:  # pragma: no cover - defensive
                    raise DatabaseError(str(exc)) from exc
                self._con.row_factory = sqlite3.Row
                for pragma in PRAGMAS:
                    self._con.execute(pragma)
            return self._con

    def close(self) -> None:
        with self._lock:
            self.close_unlocked()

    def close_unlocked(self) -> None:
        if self._con is not None:
            try:
                self._con.commit()
                self._con.close()
            except sqlite3.Error:
                pass
            finally:
                self._con = None

    def reopen(self) -> None:
        self.close()

    # -- queries -------------------------------------------------------------
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        with self._lock:
            cur = self.connection().execute(sql, tuple(params))
            try:
                return cur.fetchall()
            finally:
                cur.close()

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Row | None:
        with self._lock:
            cur = self.connection().execute(sql, tuple(params))
            try:
                return cur.fetchone()
            finally:
                cur.close()

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.query_one(sql, params)
        return None if row is None else row[0]

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run a statement and commit; returns ``cursor.rowcount``."""
        with self._lock:
            con = self.connection()
            try:
                cur = con.execute(sql, tuple(params))
                con.commit()
                return cur.rowcount
            except sqlite3.Error:
                con.rollback()
                raise

    def executescript(self, script: str) -> None:
        with self._lock:
            con = self.connection()
            try:
                con.executescript(script)
                con.commit()
            except sqlite3.Error:
                con.rollback()
                raise

    @contextmanager
    def locked(self) -> Iterator[sqlite3.Connection]:
        """Hold the connection lock for a multi-statement operation."""
        with self._lock:
            yield self.connection()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con = self.connection()
            try:
                con.execute("BEGIN")
            except sqlite3.OperationalError:
                pass
            try:
                yield con
            except BaseException:
                con.rollback()
                raise
            else:
                con.commit()

    # -- maintenance ---------------------------------------------------------
    def integrity_check(self) -> list[str]:
        with self._lock:
            rows = self.connection().execute("PRAGMA integrity_check").fetchall()
        return [r[0] for r in rows]

    def file_info(self) -> dict[str, Any]:
        size = self._path.stat().st_size if self._path.exists() else 0
        with self._lock:
            if self._con is None:
                info = {
                    "journal_mode": "",
                    "page_size": 0,
                    "page_count": 0,
                    "freelist_count": 0,
                    "encoding": "",
                    "user_version": 0,
                }
            else:
                con = self._con
                info = {
                    "journal_mode": con.execute("PRAGMA journal_mode").fetchone()[0],
                    "page_size": con.execute("PRAGMA page_size").fetchone()[0],
                    "page_count": con.execute("PRAGMA page_count").fetchone()[0],
                    "freelist_count": con.execute("PRAGMA freelist_count").fetchone()[0],
                    "encoding": con.execute("PRAGMA encoding").fetchone()[0],
                    "user_version": con.execute("PRAGMA user_version").fetchone()[0],
                }
        info.update(
            {
                "path": str(self._path),
                "size_bytes": size,
                "page_count_from_size": (
                    size // info["page_size"] if info["page_size"] else 0
                ),
            }
        )
        return info

    def backup_to(self, dest: str | Path) -> Path:
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            src = self.connection()
            target = sqlite3.connect(str(dest_path))
            try:
                src.backup(target)
            finally:
                target.close()
        return dest_path

    def vacuum(self) -> None:
        with self._lock:
            self.connection().execute("VACUUM")

    def wal_checkpoint(self) -> tuple[int, int, int]:
        with self._lock:
            row = self.connection().execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return tuple(row)  # type: ignore[return-value]
