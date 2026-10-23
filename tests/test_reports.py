"""HTML and JSON report exports alongside the existing CSV exporter."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.support import FixtureCsvTestCase, TempDbTestCase, make_temp_file

from pharma_db import services
from pharma_db.models import PageRequest
from pharma_db.repositories import MedicineRepository


class HtmlExportTest(FixtureCsvTestCase):
    def _export(self, title: str = "Medicines report") -> tuple[Path, int]:
        dest = make_temp_file(suffix=".html")
        sql, params = MedicineRepository(self.db).export_sql(
            self._request()
        )
        count = services.export_result_to_html(
            self.db.path, sql, params, dest, title=title
        )
        self.addCleanup(dest.unlink, missing_ok=True)
        return dest, count

    def _request(self):
        # export_sql is deliberately unpaginated; limit/offset are ignored, so
        # drive the result set with a real filter instead.
        return PageRequest(text="Alpha")

    def test_exports_every_matching_row(self) -> None:
        # "Alpha" matches exactly two fixture medicines.
        dest, count = self._export()
        self.assertEqual(count, 2)
        html = dest.read_text(encoding="utf-8")
        self.assertIn("<table>", html)
        self.assertIn("Alpha Tab 100", html)
        self.assertIn("row(s)", html)

    def test_escapes_html_metacharacters(self) -> None:
        self.db.execute(
            "INSERT INTO manufacturers (manufacturer_name) VALUES ('A & B <Ltd>')"
        )
        mfr_id = int(
            self.db.scalar(
                "SELECT manufacturer_id FROM manufacturers "
                "WHERE manufacturer_name = 'A & B <Ltd>'"
            )
        )
        comp_id = int(
            self.db.scalar("SELECT composition_id FROM compositions LIMIT 1")
        )
        self.db.execute(
            "INSERT INTO medicines (id, name, price_rs, manufacturer_id, type,"
            " pack_size_label, composition1_id, composition2_id)"
            " VALUES (99, '<script>alert(1)</script>', 1.0, ?, 'allopathy',"
            " NULL, ?, NULL)",
            (mfr_id, comp_id),
        )
        # Export only the injected row: export_sql ignores limit/offset, so a
        # name filter is the only way to isolate it.
        sql, params = MedicineRepository(self.db).export_sql(
            PageRequest(text="<script>")
        )
        dest = make_temp_file(suffix=".html")
        services.export_result_to_html(
            self.db.path, sql, params, dest, title="Escape <check>"
        )
        html = dest.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("A &amp; B &lt;Ltd&gt;", html)
        self.assertIn("Escape &lt;check&gt;", html)

    def test_empty_result_still_writes_header(self) -> None:
        dest = make_temp_file(suffix=".html")
        count = services.export_result_to_html(
            self.db.path,
            "SELECT id FROM medicines WHERE 1 = 0",
            [],
            dest,
            title="Empty",
        )
        self.assertEqual(count, 0)
        html = dest.read_text(encoding="utf-8")
        self.assertIn("<table>", html)
        self.assertIn("Empty", html)


class JsonExportTest(TempDbTestCase):
    def _export(self) -> tuple[Path, int]:
        dest = make_temp_file(suffix=".json")
        sql, params = MedicineRepository(self.db).export_sql(PageRequest(text="Alpha"))
        count = services.export_result_to_json(
            self.db.path, sql, params, dest, title="Json report"
        )
        return dest, count

    def test_valid_json_with_expected_shape(self) -> None:
        dest, count = self._export()
        self.assertEqual(count, 2)
        payload = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(payload["title"], "Json report")
        self.assertEqual(payload["row_count"], 2)
        self.assertEqual(len(payload["rows"]), 2)
        self.assertIn("id", payload["columns"])
        self.assertIn("name", payload["columns"])
        self.assertIn("generated_at", payload)
        self.assertIn("app", payload)

    def test_row_values_match_database(self) -> None:
        dest, _ = self._export()
        payload = json.loads(dest.read_text(encoding="utf-8"))
        first = payload["rows"][0]
        db_row = self.db.query_one("SELECT * FROM v_medicines WHERE id = ?", (first["id"],))
        assert db_row is not None
        self.assertEqual(first["name"], db_row["name"])
        self.assertAlmostEqual(first["price_rs"], db_row["price_rs"])

    def test_json_is_roundtrippable(self) -> None:
        dest, _ = self._export()
        text = dest.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text), json.loads(json.dumps(json.loads(text))))


class CsvStillWorksTest(TempDbTestCase):
    def test_csv_export_unchanged(self) -> None:
        dest = make_temp_file(suffix=".csv")
        sql, params = MedicineRepository(self.db).export_sql(
            PageRequest(text="Alpha")
        )
        count = services.export_result_to_csv(self.db.path, sql, params, dest)
        self.assertEqual(count, 2)
        lines = dest.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
