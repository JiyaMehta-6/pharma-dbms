"""Data-access layer: every SQL statement of the application lives here."""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Sequence

from .db import Database, DatabaseError, Row
from .models import (
    Composition,
    Manufacturer,
    Medicine,
    PageRequest,
    PageResult,
    ValidationError,
)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

LIKE_SPECIAL = re.compile(r"([\\%_])")


class NotFoundError(LookupError):
    pass


class InUseError(RuntimeError):
    """Raised when a referenced row cannot be deleted."""


def like_pattern(text: str) -> str:
    """Escape LIKE metacharacters and wrap the text in wildcards."""
    escaped = LIKE_SPECIAL.sub(r"\\\1", text.strip())
    return f"%{escaped}%"


def safe_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValidationError(f"Unsafe SQL identifier: {name!r}")
    return name


class MedicineRepository:
    SORTABLE = {
        "id": "v.id",
        "name": "v.name",
        "price_rs": "v.price_rs",
        "manufacturer_name": "v.manufacturer_name",
        "type": "v.type",
        "pack_size_label": "v.pack_size_label",
        "short_composition1": "v.short_composition1",
        "short_composition2": "v.short_composition2",
        "unit_rate": "v.unit_rate",
    }
    BASE_SQL = """
        FROM v_medicines_dtl v
        WHERE 1 = 1
    """
    SELECT_SQL = """
        SELECT v.id, v.name, v.price_rs, v.manufacturer_name, v.type,
               v.pack_size_label, v.short_composition1, v.short_composition2,
               v.unit_rate
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def _filters(self, req: PageRequest) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if req.text.strip():
            pattern = like_pattern(req.text)
            clauses.append(
                "(v.name LIKE ? ESCAPE '\\' "
                "OR v.short_composition1 LIKE ? ESCAPE '\\' "
                "OR v.short_composition2 LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern])
        if req.manufacturer.strip():
            clauses.append("v.manufacturer_name LIKE ? ESCAPE '\\'")
            params.append(like_pattern(req.manufacturer))
        if req.composition.strip():
            pattern = like_pattern(req.composition)
            clauses.append(
                "(v.short_composition1 LIKE ? ESCAPE '\\' "
                "OR v.short_composition2 LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern])
        if req.price_min is not None:
            clauses.append("v.price_rs >= ?")
            params.append(req.price_min)
        if req.price_max is not None:
            clauses.append("v.price_rs <= ?")
            params.append(req.price_max)
        if req.type_filter.strip():
            clauses.append("v.type = ?")
            params.append(req.type_filter.strip())
        return ("".join(f"\n        AND {c}" for c in clauses), params)

    def count(self, req: PageRequest) -> int:
        extra, params = self._filters(req)
        return int(self.db.scalar(f"SELECT COUNT(*) {self.BASE_SQL}{extra}", params) or 0)

    def search(self, req: PageRequest) -> PageResult:
        extra, params = self._filters(req)
        total = self.count(req)
        order = self.SORTABLE.get(req.order_by, "v.name")
        direction = "DESC" if req.descending else "ASC"
        sql = (
            f"{self.SELECT_SQL}{self.BASE_SQL}{extra} "
            f"ORDER BY {order} {direction}, v.id ASC LIMIT ? OFFSET ?"
        )
        rows = self.db.query(sql, [*params, req.limit, req.offset])
        return PageResult(rows=[tuple(r) for r in rows], total=total)

    def export_sql(self, req: PageRequest) -> tuple[str, list[Any]]:
        """Full (unpaginated) query matching ``req`` - used by CSV export."""
        extra, params = self._filters(req)
        order = self.SORTABLE.get(req.order_by, "v.name")
        direction = "DESC" if req.descending else "ASC"
        sql = f"{self.SELECT_SQL}{self.BASE_SQL}{extra} ORDER BY {order} {direction}, v.id ASC"
        return sql, params

    def get(self, medicine_id: int) -> Medicine | None:
        row = self.db.query_one(
            "SELECT id, name, price_rs, manufacturer_name, type, pack_size_label, "
            "short_composition1, short_composition2 FROM v_medicines WHERE id = ?",
            (medicine_id,),
        )
        if row is None:
            return None
        return Medicine(
            id=row["id"],
            name=row["name"],
            price_rs=row["price_rs"],
            manufacturer_name=row["manufacturer_name"],
            type=row["type"],
            pack_size_label=row["pack_size_label"],
            composition1=row["short_composition1"],
            composition2=row["short_composition2"],
        )

    def save(self, medicine: Medicine) -> int:
        data = medicine.validate()
        with self.db.transaction() as con:
            mfr_id = _resolve(con, "manufacturers", "manufacturer_name", data.manufacturer_name)
            c1 = _resolve(con, "compositions", "composition_text", data.composition1)
            c2 = (
                _resolve(con, "compositions", "composition_text", data.composition2)
                if data.composition2
                else None
            )
            if data.id is None:
                cur = con.execute(
                    "INSERT INTO medicines "
                    "(name, price_rs, manufacturer_id, type, pack_size_label, "
                    " composition1_id, composition2_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        data.name,
                        data.price_rs,
                        mfr_id,
                        data.type,
                        data.pack_size_label,
                        c1,
                        c2,
                    ),
                )
                return int(cur.lastrowid)
            con.execute(
                "UPDATE medicines SET name = ?, price_rs = ?, manufacturer_id = ?, "
                "type = ?, pack_size_label = ?, composition1_id = ?, composition2_id = ? "
                "WHERE id = ?",
                (
                    data.name,
                    data.price_rs,
                    mfr_id,
                    data.type,
                    data.pack_size_label,
                    c1,
                    c2,
                    data.id,
                ),
            )
            return data.id

    def delete(self, medicine_id: int) -> int:
        return self.db.execute("DELETE FROM medicines WHERE id = ?", (medicine_id,))


class ManufacturerRepository:
    LIST_SQL = """
        SELECT mf.manufacturer_id, mf.manufacturer_name,
               COALESCE(c.n, 0) AS medicine_count
        FROM manufacturers mf
        LEFT JOIN (
            SELECT manufacturer_id, COUNT(*) AS n FROM medicines GROUP BY manufacturer_id
        ) c ON c.manufacturer_id = mf.manufacturer_id
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _extra(text: str) -> tuple[str, list[Any]]:
        if not text.strip():
            return "", []
        return " WHERE mf.manufacturer_name LIKE ? ESCAPE '\\'", [like_pattern(text)]

    def count(self, text: str = "") -> int:
        extra, params = self._extra(text)
        base = "FROM manufacturers mf" + extra
        return int(self.db.scalar(f"SELECT COUNT(*) {base}", params) or 0)

    def list(
        self,
        text: str = "",
        *,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "manufacturer_name",
        descending: bool = False,
    ) -> PageResult:
        extra, params = self._extra(text)
        order = {
            "manufacturer_id": "mf.manufacturer_id",
            "manufacturer_name": "mf.manufacturer_name",
            "medicine_count": "medicine_count",
        }.get(order_by, "mf.manufacturer_name")
        direction = "DESC" if descending else "ASC"
        sql = (
            f"{self.LIST_SQL}{extra} ORDER BY {order} {direction}, mf.manufacturer_id ASC "
            "LIMIT ? OFFSET ?"
        )
        rows = self.db.query(sql, [*params, limit, offset])
        out = [tuple(r) for r in rows]
        comp_counts = self.composition_counts([r[0] for r in out])
        enriched = [(r[0], r[1], r[2], comp_counts.get(r[0], 0)) for r in out]
        return PageResult(rows=enriched, total=self.count(text))

    def composition_counts(self, ids: Sequence[int]) -> dict[int, int]:
        result: dict[int, int] = {i: 0 for i in ids}
        if not ids:
            return result
        placeholders = ",".join("?" for _ in ids)
        sql = f"""
            SELECT manufacturer_id, COUNT(DISTINCT cid) AS n FROM (
                SELECT manufacturer_id, composition1_id AS cid FROM medicines
                  WHERE manufacturer_id IN ({placeholders})
                UNION
                SELECT manufacturer_id, composition2_id AS cid FROM medicines
                  WHERE manufacturer_id IN ({placeholders})
                    AND composition2_id IS NOT NULL
            ) GROUP BY manufacturer_id
        """
        for row in self.db.query(sql, [*ids, *ids]):
            result[row[0]] = int(row[1])
        return result

    def all_names(self) -> list[str]:
        rows = self.db.query(
            "SELECT manufacturer_name FROM manufacturers ORDER BY manufacturer_name"
        )
        return [r[0] for r in rows]

    def get(self, manufacturer_id: int) -> Manufacturer:
        row = self.db.query_one(
            "SELECT manufacturer_id, manufacturer_name FROM manufacturers "
            "WHERE manufacturer_id = ?",
            (manufacturer_id,),
        )
        if row is None:
            raise NotFoundError(f"Manufacturer {manufacturer_id} not found")
        return Manufacturer(id=row["manufacturer_id"], name=row["manufacturer_name"])

    def resolve_or_create(self, name: str, con: sqlite3.Connection | None = None) -> int:
        target = con or self.db.connection()
        row = target.execute(
            "SELECT manufacturer_id FROM manufacturers WHERE manufacturer_name = ?",
            (name,),
        ).fetchone()
        if row:
            return int(row[0])
        cur = target.execute(
            "INSERT OR IGNORE INTO manufacturers (manufacturer_name) VALUES (?)", (name,)
        )
        if cur.rowcount == 0:
            row = target.execute(
                "SELECT manufacturer_id FROM manufacturers WHERE manufacturer_name = ?",
                (name,),
            ).fetchone()
            return int(row[0])
        return int(cur.lastrowid)

    def usage_count(self, manufacturer_id: int) -> int:
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM medicines WHERE manufacturer_id = ?",
                (manufacturer_id,),
            )
            or 0
        )

    def save(self, manufacturer: Manufacturer) -> int:
        data = manufacturer.validate()
        with self.db.transaction() as con:
            try:
                if data.id is None:
                    cur = con.execute(
                        "INSERT INTO manufacturers (manufacturer_name) VALUES (?)",
                        (data.name,),
                    )
                    return int(cur.lastrowid)
                con.execute(
                    "UPDATE manufacturers SET manufacturer_name = ? WHERE manufacturer_id = ?",
                    (data.name, data.id),
                )
                return data.id
            except sqlite3.IntegrityError as exc:
                raise ValidationError(
                    f"A manufacturer named '{data.name}' already exists."
                ) from exc

    def delete(self, manufacturer_id: int) -> int:
        if self.usage_count(manufacturer_id):
            raise InUseError(
                "Manufacturer is referenced by medicines; reassign or delete those rows first."
            )
        deleted = self.db.execute(
            "DELETE FROM manufacturers WHERE manufacturer_id = ?", (manufacturer_id,)
        )
        if not deleted:
            raise NotFoundError(f"Manufacturer {manufacturer_id} not found")
        return deleted


class CompositionRepository:
    LIST_SQL = """
        SELECT c.composition_id, c.composition_text,
               COALESCE(a.n, 0) + COALESCE(b.n, 0) AS usage_count
        FROM compositions c
        LEFT JOIN (
            SELECT composition1_id AS cid, COUNT(*) AS n FROM medicines GROUP BY composition1_id
        ) a ON a.cid = c.composition_id
        LEFT JOIN (
            SELECT composition2_id AS cid, COUNT(*) AS n FROM medicines
            WHERE composition2_id IS NOT NULL GROUP BY composition2_id
        ) b ON b.cid = c.composition_id
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _extra(text: str) -> tuple[str, list[Any]]:
        if not text.strip():
            return "", []
        return " WHERE c.composition_text LIKE ? ESCAPE '\\'", [like_pattern(text)]

    def count(self, text: str = "") -> int:
        extra, params = self._extra(text)
        return int(
            self.db.scalar(
                f"SELECT COUNT(*) FROM compositions c{extra}", params
            )
            or 0
        )

    def list(
        self,
        text: str = "",
        *,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "composition_text",
        descending: bool = False,
    ) -> PageResult:
        extra, params = self._extra(text)
        order = {
            "composition_id": "c.composition_id",
            "composition_text": "c.composition_text",
            "usage_count": "usage_count",
        }.get(order_by, "c.composition_text")
        direction = "DESC" if descending else "ASC"
        sql = (
            f"{self.LIST_SQL}{extra} ORDER BY {order} {direction}, c.composition_id ASC "
            "LIMIT ? OFFSET ?"
        )
        rows = self.db.query(sql, [*params, limit, offset])
        return PageResult(
            rows=[tuple(r) for r in rows], total=self.count(text)
        )

    def all_texts(self) -> list[str]:
        rows = self.db.query(
            "SELECT composition_text FROM compositions ORDER BY composition_text"
        )
        return [r[0] for r in rows]

    def get(self, composition_id: int) -> Composition:
        row = self.db.query_one(
            "SELECT composition_id, composition_text FROM compositions "
            "WHERE composition_id = ?",
            (composition_id,),
        )
        if row is None:
            raise NotFoundError(f"Composition {composition_id} not found")
        return Composition(id=row["composition_id"], text=row["composition_text"])

    def resolve_or_create(self, text: str, con: sqlite3.Connection | None = None) -> int:
        target = con or self.db.connection()
        row = target.execute(
            "SELECT composition_id FROM compositions WHERE composition_text = ?", (text,)
        ).fetchone()
        if row:
            return int(row[0])
        cur = target.execute(
            "INSERT OR IGNORE INTO compositions (composition_text) VALUES (?)", (text,)
        )
        if cur.rowcount == 0:
            row = target.execute(
                "SELECT composition_id FROM compositions WHERE composition_text = ?",
                (text,),
            ).fetchone()
            return int(row[0])
        return int(cur.lastrowid)

    def usage_count(self, composition_id: int) -> int:
        return int(
            self.db.scalar(
                "SELECT (SELECT COUNT(*) FROM medicines WHERE composition1_id = ?) + "
                "(SELECT COUNT(*) FROM medicines WHERE composition2_id = ?)",
                (composition_id, composition_id),
            )
            or 0
        )

    def save(self, composition: Composition) -> int:
        data = composition.validate()
        with self.db.transaction() as con:
            try:
                if data.id is None:
                    cur = con.execute(
                        "INSERT INTO compositions (composition_text) VALUES (?)",
                        (data.text,),
                    )
                    return int(cur.lastrowid)
                con.execute(
                    "UPDATE compositions SET composition_text = ? WHERE composition_id = ?",
                    (data.text, data.id),
                )
                return data.id
            except sqlite3.IntegrityError as exc:
                raise ValidationError(
                    f"A composition '{data.text}' already exists."
                ) from exc

    def delete(self, composition_id: int) -> int:
        if self.usage_count(composition_id):
            raise InUseError(
                "Composition is referenced by medicines; reassign or delete those rows first."
            )
        deleted = self.db.execute(
            "DELETE FROM compositions WHERE composition_id = ?", (composition_id,)
        )
        if not deleted:
            raise NotFoundError(f"Composition {composition_id} not found")
        return deleted


class SchemaRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def objects(self) -> list[dict[str, str]]:
        rows = self.db.query(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY CASE type "
            "WHEN 'table' THEN 0 WHEN 'view' THEN 1 ELSE 2 END, name"
        )
        return [{"type": r["type"], "name": r["name"], "sql": r["sql"] or ""} for r in rows]

    def columns(self, name: str) -> list[dict[str, Any]]:
        ident = safe_ident(name)
        rows = self.db.query(f"PRAGMA table_info({ident})")
        return [
            {
                "cid": r["cid"],
                "name": r["name"],
                "type": r["type"],
                "notnull": bool(r["notnull"]),
                "default": r["dflt_value"],
                "pk": bool(r["pk"]),
            }
            for r in rows
        ]

    def row_count(self, name: str) -> int:
        ident = safe_ident(name)
        return int(self.db.scalar(f'SELECT COUNT(*) FROM "{ident}"') or 0)

    def preview(self, name: str, limit: int = 100) -> tuple[list[str], list[tuple]]:
        ident = safe_ident(name)
        cur = self.db.connection().execute(f'SELECT * FROM "{ident}" LIMIT ?', (limit,))
        try:
            columns = [d[0] for d in cur.description or []]
            rows = [tuple(r) for r in cur.fetchall()]
        finally:
            cur.close()
        return columns, rows

    def indexes(self, name: str) -> list[dict[str, Any]]:
        ident = safe_ident(name)
        rows = self.db.query(f"PRAGMA index_list({ident})")
        return [
            {
                "name": r["name"],
                "unique": bool(r["unique"]),
                "origin": r["origin"],
                "partial": bool(r["partial"]),
            }
            for r in rows
        ]


class StatsRepository:
    PRICE_BANDS = (
        (0, 50, "0 - 50"),
        (50, 100, "50 - 100"),
        (100, 250, "100 - 250"),
        (250, 500, "250 - 500"),
        (500, 1000, "500 - 1000"),
        (1000, None, "1000+"),
    )

    def __init__(self, db: Database) -> None:
        self.db = db

    def counts(self) -> dict[str, int]:
        return {
            "medicines": int(self.db.scalar("SELECT COUNT(*) FROM medicines") or 0),
            "manufacturers": int(self.db.scalar("SELECT COUNT(*) FROM manufacturers") or 0),
            "compositions": int(self.db.scalar("SELECT COUNT(*) FROM compositions") or 0),
        }

    def price_summary(self) -> dict[str, float]:
        row = self.db.query_one(
            "SELECT MIN(price_rs), MAX(price_rs), AVG(price_rs) FROM medicines "
            "WHERE price_rs > 0"
        ) or (None, None, None)
        return {
            "min": float(row[0] or 0),
            "max": float(row[1] or 0),
            "avg": float(row[2] or 0),
        }

    def price_bands(self) -> list[tuple[str, int]]:
        clauses = []
        params: list[Any] = []
        for low, high, label in self.PRICE_BANDS:
            if high is None:
                clauses.append("price_rs >= ?")
                params.append(low)
            else:
                clauses.append("price_rs >= ? AND price_rs < ?")
                params.extend([low, high])
        sql = "SELECT band, SUM(n) FROM (" + " UNION ALL ".join(
            f"SELECT {i} AS band, COUNT(*) AS n FROM medicines WHERE {c}"
            for i, c in enumerate(clauses)
        ) + ") GROUP BY band ORDER BY band"
        rows = self.db.query(sql, params)
        counts = {int(r[0]): int(r[1]) for r in rows}
        return [(label, counts.get(i, 0)) for i, (_, _, label) in enumerate(self.PRICE_BANDS)]

    def composition_split(self) -> list[tuple[str, int]]:
        rows = self.db.query(
            "SELECT CASE WHEN short_composition2 IS NULL THEN 'Single composition' "
            "ELSE 'Dual composition' END AS k, COUNT(*) "
            "FROM v_medicines GROUP BY k"
        )
        counts = {r[0]: int(r[1]) for r in rows}
        return [
            ("Single composition", counts.get("Single composition", 0)),
            ("Dual composition", counts.get("Dual composition", 0)),
        ]

    def top_manufacturers(self, limit: int = 10) -> list[tuple[str, int]]:
        rows = self.db.query(
            "SELECT mf.manufacturer_name, COUNT(*) AS n FROM medicines m "
            "JOIN manufacturers mf ON mf.manufacturer_id = m.manufacturer_id "
            "GROUP BY m.manufacturer_id ORDER BY n DESC, mf.manufacturer_name ASC LIMIT ?",
            (limit,),
        )
        return [(r[0], int(r[1])) for r in rows]

    def most_expensive(self, limit: int = 10) -> list[tuple]:
        rows = self.db.query(
            "SELECT v.id, v.name, v.price_rs, v.manufacturer_name "
            "FROM v_medicines_dtl v ORDER BY v.price_rs DESC LIMIT ?",
            (limit,),
        )
        return [tuple(r) for r in rows]

    def most_used_compositions(self, limit: int = 10) -> list[tuple[str, int]]:
        rows = self.db.query(
            "SELECT c.composition_text, "
            "COALESCE(a.n, 0) + COALESCE(b.n, 0) AS n "
            "FROM compositions c "
            "LEFT JOIN (SELECT composition1_id AS cid, COUNT(*) AS n FROM medicines "
            "           GROUP BY composition1_id) a ON a.cid = c.composition_id "
            "LEFT JOIN (SELECT composition2_id AS cid, COUNT(*) AS n FROM medicines "
            "           WHERE composition2_id IS NOT NULL GROUP BY composition2_id) b "
            "  ON b.cid = c.composition_id "
            "ORDER BY n DESC, c.composition_text ASC LIMIT ?",
            (limit,),
        )
        return [(r[0], int(r[1])) for r in rows]


def _resolve(con: sqlite3.Connection, table: str, column: str, value: str) -> int:
    """Return the id of ``value`` in ``table``, inserting it when missing."""
    row = con.execute(f"SELECT * FROM {table} WHERE {column} = ?", (value,)).fetchone()
    if row is not None:
        return int(row[0])
    cur = con.execute(f"INSERT OR IGNORE INTO {table} ({column}) VALUES (?)", (value,))
    if cur.rowcount == 0:
        row = con.execute(f"SELECT * FROM {table} WHERE {column} = ?", (value,)).fetchone()
        if row is None:  # pragma: no cover - defensive
            raise DatabaseError(f"Could not resolve {value!r} in {table}")
        return int(row[0])
    return int(cur.lastrowid)


__all__ = [
    "CompositionRepository",
    "DatabaseError",
    "InUseError",
    "ManufacturerRepository",
    "MedicineRepository",
    "NotFoundError",
    "Row",
    "SchemaRepository",
    "StatsRepository",
    "ValidationError",
]
