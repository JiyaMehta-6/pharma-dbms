"""Application services: CSV import, backups, export and the SQL runner."""
from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Callable, Sequence

from . import config
from .db import Database

ProgressFn = Callable[[str, int, int], None]

SCHEMA = """
PRAGMA journal_mode=WAL;
DROP VIEW IF EXISTS v_medicines_dtl;
DROP VIEW IF EXISTS v_manufacturer_composition_counts;
DROP VIEW IF EXISTS v_medicines;
DROP TABLE IF EXISTS medicines;
DROP TABLE IF EXISTS compositions;
DROP TABLE IF EXISTS manufacturers;
DROP TABLE IF EXISTS schema_migrations;

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
    price_rs REAL NOT NULL CHECK (price_rs >= 0),
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(manufacturer_id),
    type TEXT NOT NULL DEFAULT 'allopathy',
    pack_size_label TEXT,
    composition1_id INTEGER NOT NULL REFERENCES compositions(composition_id),
    composition2_id INTEGER REFERENCES compositions(composition_id),
    CHECK (composition2_id IS NULL OR composition2_id <> composition1_id)
);

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_medicines_manufacturer ON medicines(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_medicines_name ON medicines(name);
CREATE INDEX IF NOT EXISTS idx_medicines_price ON medicines(price_rs);
CREATE INDEX IF NOT EXISTS idx_medicines_composition1 ON medicines(composition1_id);
CREATE INDEX IF NOT EXISTS idx_medicines_composition2 ON medicines(composition2_id);
CREATE INDEX IF NOT EXISTS idx_manufacturers_name ON manufacturers(manufacturer_name);
CREATE INDEX IF NOT EXISTS idx_compositions_text ON compositions(composition_text);

CREATE VIEW IF NOT EXISTS v_medicines AS
SELECT m.id, m.name, m.price_rs,
       mf.manufacturer_name, m.type, m.pack_size_label,
       c1.composition_text AS short_composition1,
       c2.composition_text AS short_composition2
FROM medicines m
JOIN manufacturers mf ON m.manufacturer_id = mf.manufacturer_id
JOIN compositions c1 ON m.composition1_id = c1.composition_id
LEFT JOIN compositions c2 ON m.composition2_id = c2.composition_id;

CREATE VIEW IF NOT EXISTS v_manufacturer_composition_counts AS
SELECT
    mf.manufacturer_id,
    mf.manufacturer_name,
    COUNT(DISTINCT u.cid) AS composition_count,
    (SELECT COUNT(*) FROM medicines m2 WHERE m2.manufacturer_id = mf.manufacturer_id) AS medicine_count
FROM manufacturers mf
LEFT JOIN (
    SELECT manufacturer_id, composition1_id AS cid FROM medicines
    UNION
    SELECT manufacturer_id, composition2_id AS cid FROM medicines WHERE composition2_id IS NOT NULL
) u ON u.manufacturer_id = mf.manufacturer_id
GROUP BY mf.manufacturer_id, mf.manufacturer_name;

CREATE VIEW IF NOT EXISTS v_medicines_dtl AS
SELECT
    id, name, price_rs, manufacturer_name, type,
    pack_size_label, short_composition1, short_composition2,
    pack_qty,
    CASE WHEN pack_qty IS NOT NULL AND pack_qty <> 0
         THEN ROUND(price_rs / pack_qty, 2)
         ELSE NULL END AS unit_rate
FROM (
    SELECT v.*,
        CASE WHEN INSTR(v.pack_size_label, 'of ') > 0
             THEN NULLIF(CAST(SUBSTR(v.pack_size_label, INSTR(v.pack_size_label, 'of ') + 3) AS REAL), 0)
             ELSE NULL END AS pack_qty
    FROM v_medicines v
);
"""

CURRENT_VERSION = 2

# version -> one or more idempotent SQL statements. Migration 1 is a no-op for
# freshly rebuilt databases (the baseline schema already matches version 1);
# it exists so the version table is stamped and upgrades always have a floor.
MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ");",
    ),
    2: (
        "CREATE TABLE IF NOT EXISTS users ("
        " user_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " username TEXT NOT NULL UNIQUE,"
        " password_hash TEXT NOT NULL,"
        " salt TEXT NOT NULL,"
        " role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),"
        " created_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ");",
        "CREATE TABLE IF NOT EXISTS audit_log ("
        " audit_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " user_id INTEGER REFERENCES users(user_id),"
        " action TEXT NOT NULL,"
        " entity TEXT NOT NULL,"
        " entity_id INTEGER,"
        " detail TEXT,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ");",
        "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);",
    ),
}


def _noop(_: str, __: int, ___: int) -> None:
    return None


def norm_comp(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.strip().split())
    return text or None


# --------------------------------------------------------------------------
# CSV -> database rebuild
# --------------------------------------------------------------------------
def rebuild_database(
    db: Database,
    csv_path: Path | None = None,
    progress: ProgressFn | None = None,
) -> dict[str, int]:
    """Recreate the SQLite database from the source CSV.

    The shared connection is closed first so the file can be replaced.
    """
    report = progress or _noop
    csv_file = Path(csv_path or config.source_csv())
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV not found: {csv_file}")

    db.close()
    target = db.path
    for suffix in ("", "-wal", "-shm"):
        stale = Path(str(target) + suffix)
        if stale.exists():
            try:
                stale.unlink()
            except PermissionError:
                pass

    report("Reading CSV", 0, 0)
    manufacturers: dict[str, int] = {}
    compositions: dict[str, int] = {}
    med_rows: list[tuple] = []
    price_col = ""

    with open(csv_file, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError("CSV has no header row")
        price_col = fieldnames[2]
        for index, row in enumerate(reader, start=1):
            name = row["manufacturer_name"].strip()
            mfr_id = manufacturers.get(name)
            if mfr_id is None:
                mfr_id = len(manufacturers) + 1
                manufacturers[name] = mfr_id
            comp1 = _composition_id(compositions, row["short_composition1"])
            comp2 = _composition_id(compositions, row["short_composition2"])
            if comp1 is None:
                raise ValueError(f"Missing short_composition1 in row id={row.get('id')}")
            if comp2 == comp1:
                # The catalogue lists the same composition in both slots for a
                # handful of rows; that is a single composition, not a pair.
                comp2 = None
            med_rows.append(
                (
                    int(row["id"]),
                    row["name"],
                    float(row[price_col]),
                    mfr_id,
                    row["type"],
                    row["pack_size_label"] or None,
                    comp1,
                    comp2,
                )
            )
            if index % 25000 == 0:
                report("Reading CSV", index, 0)

    total = len(med_rows)
    report("Creating tables", total, total)
    con = sqlite3.connect(str(target))
    try:
        con.execute("PRAGMA foreign_keys=OFF;")
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO manufacturers (manufacturer_id, manufacturer_name) VALUES (?, ?)",
            [(mid, name) for name, mid in manufacturers.items()],
        )
        con.executemany(
            "INSERT INTO compositions (composition_id, composition_text) VALUES (?, ?)",
            [(cid, text) for text, cid in compositions.items()],
        )
        con.executemany(
            """INSERT INTO medicines
               (id, name, price_rs, manufacturer_id, type,
                pack_size_label, composition1_id, composition2_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            med_rows,
        )
        con.commit()
        report("Creating indexes", total, total)
        con.executescript(INDEXES)
        con.execute("PRAGMA foreign_keys=ON;")
        con.commit()
        _stamp_baseline(con)

        stats = {
            "medicines": _scalar(con, "SELECT COUNT(*) FROM medicines"),
            "manufacturers": _scalar(con, "SELECT COUNT(*) FROM manufacturers"),
            "compositions": _scalar(con, "SELECT COUNT(*) FROM compositions"),
            "orphan_manufacturers": _scalar(
                con,
                "SELECT COUNT(*) FROM medicines m LEFT JOIN manufacturers mf "
                "ON m.manufacturer_id = mf.manufacturer_id "
                "WHERE mf.manufacturer_id IS NULL",
            ),
            "orphan_compositions": _scalar(
                con,
                "SELECT COUNT(*) FROM medicines m LEFT JOIN compositions c "
                "ON m.composition1_id = c.composition_id WHERE c.composition_id IS NULL",
            ),
        }
        if stats["orphan_manufacturers"] or stats["orphan_compositions"]:
            raise RuntimeError(f"Integrity failure after rebuild: {stats}")
        if stats["medicines"] != total:
            raise RuntimeError(
                f"Row count mismatch: csv={total} db={stats['medicines']}"
            )
        # A caller may still hold an open connection to the old file (the GUI
        # and tests keep a Database handle live during a rebuild). On Windows
        # that pins -wal/-shm, so the unlink above fails and this checkpoint
        # raises "database table is locked". The database was already rebuilt
        # and committed at this point, so a failed checkpoint is cosmetic:
        # the stale -wal is removed on the next successful clean close.
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except sqlite3.OperationalError:
            pass
        con.execute("PRAGMA journal_mode=DELETE;")
        con.commit()
    finally:
        con.close()

    report("Finished", total, total)
    db.reopen()
    return stats


def _composition_id(compositions: dict[str, int], raw: str | None) -> int | None:
    text = norm_comp(raw)
    if text is None:
        return None
    cid = compositions.get(text)
    if cid is None:
        cid = len(compositions) + 1
        compositions[text] = cid
    return cid


def _scalar(con: sqlite3.Connection, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


# --------------------------------------------------------------------------
# Migrations
# --------------------------------------------------------------------------
def _stamp_baseline(con: sqlite3.Connection) -> None:
    """Record the just-rebuilt database as being at the current schema version."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ");"
    )
    con.execute(
        "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
        (CURRENT_VERSION,),
    )


def current_version(db: Database) -> int:
    """Highest recorded migration version, or 0 for a pre-migration database."""
    exists = db.query_one(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name = 'schema_migrations'"
    )
    if exists is None:
        return 0
    return int(db.scalar("SELECT COALESCE(MAX(version), 0) FROM schema_migrations") or 0)


def migrate(db: Database) -> int:
    """Apply every pending migration in order; returns the new version.

    Each migration runs inside its own transaction and is recorded only on
    success, so a failure leaves the database at the previous version.
    """
    applied = current_version(db)
    for version in sorted(MIGRATIONS):
        if version <= applied:
            continue
        with db.transaction() as con:
            for statement in MIGRATIONS[version]:
                con.execute(statement)
            con.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (version,),
            )
        applied = version
    return applied


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
def export_result_to_csv(
    db_path: Path,
    sql: str,
    params: Sequence[Any],
    dest: Path,
    progress: ProgressFn | None = None,
    chunk: int = 5000,
) -> int:
    """Stream a query result into ``dest``; returns the number of rows written."""
    report = progress or _noop
    written = 0
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(sql, tuple(params))
        columns = [d[0] for d in cur.description or []]
        with open(dest, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            report("Exporting", 0, 0)
            while True:
                rows = cur.fetchmany(chunk)
                if not rows:
                    break
                writer.writerows(rows)
                written += len(rows)
                report("Exporting", written, 0)
            cur.close()
    finally:
        con.close()
    return written


def export_result_to_html(
    db_path: Path,
    sql: str,
    params: Sequence[Any],
    dest: Path,
    title: str = "Report",
) -> int:
    """Render a query result as a self-contained HTML report; returns row count."""
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(sql, tuple(params))
        columns = [d[0] for d in cur.description or []]
        rows = cur.fetchall()
        cur.close()
    finally:
        con.close()

    head = "".join(f"<th>{escape(str(c))}</th>" for c in columns)
    body = []
    for row in rows:
        cells = "".join(
            f"<td>{'' if v is None else escape(str(v))}</td>" for v in row
        )
        body.append(f"<tr>{cells}</tr>")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<title>{escape(title)}</title><style>"
        "body{font-family:system-ui,sans-serif;margin:2rem;color:#1b2430}"
        "h1{font-size:1.3rem}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #d5dbe5;padding:6px 10px;text-align:left}"
        "th{background:#f6f8fb}tr:nth-child(even){background:#fafbfd}"
        "footer{margin-top:1rem;color:#5b6b7f;font-size:.85rem}"
        "</style></head><body>"
        f"<h1>{escape(title)}</h1>"
        f"<p>{len(rows):,} row(s)</p>"
        f"<table><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
        f"<footer>Generated {stamp} by {escape(config.APP_NAME)} "
        f"{escape(config.APP_VERSION)}</footer>"
        "</body></html>"
    )
    dest.write_text(html, encoding="utf-8")
    return len(rows)


def export_result_to_json(
    db_path: Path,
    sql: str,
    params: Sequence[Any],
    dest: Path,
    title: str = "Report",
) -> int:
    """Render a query result as a JSON document; returns row count."""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, tuple(params))
        columns = [d[0] for d in cur.description or []]
        records = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
    finally:
        con.close()
    payload = {
        "title": title,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "app": f"{config.APP_NAME} {config.APP_VERSION}",
        "row_count": len(records),
        "columns": columns,
        "rows": records,
    }
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return len(records)


# --------------------------------------------------------------------------
# Backups
# --------------------------------------------------------------------------
def create_backup(db: Database, dest: Path | None = None) -> Path:
    if dest is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = config.backup_dir() / f"indian_medicine-{stamp}.db"
        counter = 1
        while dest.exists():
            dest = config.backup_dir() / f"indian_medicine-{stamp}-{counter}.db"
            counter += 1
    return db.backup_to(dest)


def list_backups() -> list[dict[str, Any]]:
    directory = config.backup_dir()
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.db"), reverse=True):
        stat = path.stat()
        out.append(
            {
                "path": path,
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime),
            }
        )
    return out


def restore_backup(db: Database, source: Path) -> None:
    """Replace the live database file with a backup (validated first)."""
    probe = sqlite3.connect(str(source))
    try:
        result = probe.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Backup failed integrity check: {result}")
    finally:
        probe.close()

    db.close()
    target = db.path
    for suffix in ("-wal", "-shm"):
        stale = Path(str(target) + suffix)
        if stale.exists():
            try:
                stale.unlink()
            except PermissionError:
                pass
    shutil.copy2(source, target)
    db.reopen()


def delete_backup(path: Path) -> None:
    path.unlink()


def vacuum(db: Database) -> None:
    db.vacuum()


# --------------------------------------------------------------------------
# SQL statement handling (used by the console)
# --------------------------------------------------------------------------
@dataclass
class StatementResult:
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    rowcount: int = -1
    message: str = ""
    elapsed: float = 0.0
    error: str | None = None
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


_TXN_START = re.compile(r"^\s*(BEGIN|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE)\b", re.I)


def split_statements(script: str) -> list[str]:
    """Split a SQL script on ``;`` while respecting quotes and comments."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(script)
    while i < n:
        ch = script[i]
        if ch in "'\"`":
            quote = ch
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(script[i])
                if script[i] == quote:
                    if i + 1 < n and script[i + 1] == quote:
                        buf.append(script[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "-" and i + 1 < n and script[i + 1] == "-":
            while i < n and script[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and script[i + 1] == "*":
            i += 2
            while i + 1 < n and not (script[i] == "*" and script[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def run_script(
    db: Database,
    script: str,
    max_rows: int = 10000,
    progress: ProgressFn | None = None,
) -> list[StatementResult]:
    """Execute statements sequentially, stopping at the first error."""
    report = progress or _noop
    statements = split_statements(script)
    results: list[StatementResult] = []
    if not statements:
        return results

    with db.locked() as con:
        total = len(statements)
        for index, stmt in enumerate(statements, start=1):
            result = StatementResult(sql=stmt)
            started = time.perf_counter()
            try:
                cur = con.execute(stmt)
                if cur.description:
                    result.columns = [d[0] for d in cur.description]
                    fetched = cur.fetchmany(max_rows + 1)
                    if len(fetched) > max_rows:
                        result.rows = [tuple(r) for r in fetched[:max_rows]]
                        result.truncated = True
                    else:
                        result.rows = [tuple(r) for r in fetched]
                    result.message = f"{len(result.rows)} row(s)"
                    cur.close()
                else:
                    result.rowcount = cur.rowcount if cur.rowcount is not None else -1
                    result.message = f"{result.rowcount} row(s) affected"
                    if not _TXN_START.match(stmt):
                        con.commit()
            except sqlite3.Error as exc:
                result.error = str(exc)
                result.message = "ERROR"
                try:
                    con.rollback()
                except sqlite3.Error:
                    pass
            result.elapsed = time.perf_counter() - started
            results.append(result)
            report("Running SQL", index, total)
            if result.error:
                break
    return results
