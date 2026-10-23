"""Repository layer: search, CRUD, integrity guards and statistics."""
from __future__ import annotations

import unittest

from tests.support import TempDbTestCase

from pharma_db.models import (
    Composition,
    Manufacturer,
    Medicine,
    PageRequest,
    ValidationError,
)
from pharma_db.repositories import (
    CompositionRepository,
    InUseError,
    ManufacturerRepository,
    MedicineRepository,
    NotFoundError,
    SchemaRepository,
    StatsRepository,
    like_pattern,
    safe_ident,
)

PARACETAMOL_ROWS = {1, 2, 7, 8, 10}  # rows whose name or composition mentions it
BASE_COUNTS = {"medicines": 10, "manufacturers": 4, "compositions": 12}


class SqlHelpersTest(unittest.TestCase):
    def test_like_pattern_escapes_metacharacters(self) -> None:
        self.assertEqual(like_pattern("50%_x"), "%50\\%\\_x%")
        self.assertEqual(like_pattern(" a\\b "), "%a\\\\b%")

    def test_safe_ident_accepts_plain_names(self) -> None:
        self.assertEqual(safe_ident("medicines"), "medicines")
        self.assertEqual(safe_ident("_tmp1"), "_tmp1")

    def test_safe_ident_rejects_injection(self) -> None:
        for bad in ("medicines; DROP TABLE x", 'a"', "1abc", "", "a b"):
            with self.assertRaises(ValidationError, msg=bad):
                safe_ident(bad)


class MedicineRepositoryTest(TempDbTestCase):
    def setUp(self) -> None:
        self.repo = MedicineRepository(self.db)

    def tearDown(self) -> None:
        # Several tests insert rows; restore the fixture so the next test in
        # this shared class-level database still sees the baseline counts.
        self.db.execute("DELETE FROM medicines WHERE id > 10")
        self.db.execute("DELETE FROM manufacturers WHERE manufacturer_id > 4")
        self.db.execute("DELETE FROM compositions WHERE composition_id > 12")

    def test_counts_all_rows(self) -> None:
        self.assertEqual(self.repo.count(PageRequest()), 10)

    def test_text_filter_matches_name_or_composition(self) -> None:
        result = self.repo.search(PageRequest(text="paracetamol", limit=100))
        ids = {r[0] for r in result.rows}
        self.assertEqual(result.total, len(PARACETAMOL_ROWS))
        self.assertEqual(ids, PARACETAMOL_ROWS)

    def test_text_filter_escapes_percent(self) -> None:
        result = self.repo.search(PageRequest(text="100%", limit=100))
        self.assertEqual(result.total, 0)

    def test_manufacturer_filter(self) -> None:
        result = self.repo.search(PageRequest(manufacturer="Mfr B", limit=100))
        self.assertEqual(result.total, 3)  # rows 3, 4, 10

    def test_price_range_filter(self) -> None:
        result = self.repo.search(
            PageRequest(price_min=80, price_max=100, limit=100)
        )
        prices = sorted(r[2] for r in result.rows)
        self.assertEqual(prices, [80.25, 99.0])

    def test_type_filter(self) -> None:
        self.assertEqual(
            self.repo.count(PageRequest(type_filter="allopathy")), 10
        )
        self.assertEqual(self.repo.count(PageRequest(type_filter="ayurveda")), 0)

    def test_paging_windows(self) -> None:
        page1 = self.repo.search(PageRequest(limit=3, offset=0))
        page2 = self.repo.search(PageRequest(limit=3, offset=3))
        self.assertEqual(len(page1.rows), 3)
        self.assertEqual(page1.total, 10)
        self.assertEqual(page1.rows[0][0], 1)
        self.assertEqual(page2.rows[0][0], 5)  # Alpha Tab 500 sorts 4th by name

    def test_server_side_sorting(self) -> None:
        cheap = self.repo.search(PageRequest(order_by="price_rs", limit=100))
        self.assertEqual(cheap.rows[0][0], 7)  # Zeta Tab 10, 5.0
        costly = self.repo.search(
            PageRequest(order_by="price_rs", descending=True, limit=100)
        )
        self.assertEqual(costly.rows[0][0], 9)  # Theta 1000, 2500.0

    def test_unknown_sort_column_falls_back_to_name(self) -> None:
        result = self.repo.search(PageRequest(order_by="nope", limit=100))
        self.assertEqual(result.rows[0][1], "Alpha Tab 100")

    def test_get_returns_none_for_missing(self) -> None:
        self.assertIsNone(self.repo.get(999))

    def test_get_maps_columns(self) -> None:
        med = self.repo.get(3)
        assert med is not None
        self.assertEqual(med.name, "Beta Cap 250")
        self.assertEqual(med.price_rs, 250.75)
        self.assertEqual(med.manufacturer_name, "Mfr B")
        self.assertEqual(med.composition1, "Ibuprofen (250mg)")
        self.assertEqual(med.composition2, "Cetirizine (10mg)")

    def test_save_inserts_new_medicine(self) -> None:
        new_id = self.repo.save(
            Medicine(
                name="Omega Tab",
                price_rs=42.0,
                manufacturer_name="Mfr E",
                composition1="Ibuprofen (400mg)",
            )
        )
        self.assertGreater(new_id, 0)
        med = self.repo.get(new_id)
        assert med is not None
        self.assertEqual(med.manufacturer_name, "Mfr E")
        # New manufacturer and composition were auto-created.
        self.assertEqual(ManufacturerRepository(self.db).count("Mfr E"), 1)
        self.assertEqual(CompositionRepository(self.db).count("Ibuprofen (400mg)"), 1)

    def test_save_reuses_existing_mfr_and_composition(self) -> None:
        before_mfr = ManufacturerRepository(self.db).count()
        before_comp = CompositionRepository(self.db).count()
        self.repo.save(
            Medicine(
                name="Omega Tab 2",
                price_rs=43.0,
                manufacturer_name="Mfr A",
                composition1="Paracetamol (100mg)",
            )
        )
        self.assertEqual(ManufacturerRepository(self.db).count(), before_mfr)
        self.assertEqual(CompositionRepository(self.db).count(), before_comp)

    def test_save_updates_existing_row(self) -> None:
        med = self.repo.get(5)
        assert med is not None
        med.price_rs = 999.0
        med.name = "Delta Injection 5mg (revised)"
        self.repo.save(med)
        again = self.repo.get(5)
        assert again is not None
        self.assertEqual(again.price_rs, 999.0)
        self.assertEqual(again.name, "Delta Injection 5mg (revised)")
        # Restore the fixture values for the other tests in this class.
        self.db.execute(
            "UPDATE medicines SET price_rs = 1200.0,"
            " name = 'Delta Injection 5mg' WHERE id = 5"
        )

    def test_save_rejects_invalid_data(self) -> None:
        with self.assertRaises(ValidationError):
            self.repo.save(Medicine(name="", price_rs=1))

    def test_delete_removes_row(self) -> None:
        self.assertEqual(self.repo.delete(6), 1)
        self.assertIsNone(self.repo.get(6))
        # Restore the fixture row for the other tests in this class.
        self.db.execute(
            "INSERT INTO medicines (id, name, price_rs, manufacturer_id, type,"
            " pack_size_label, composition1_id, composition2_id)"
            " VALUES (6, 'Epsilon Cream', 80.25, 3, 'allopathy',"
            " 'tube of 15 gm cream', 9, NULL)"
        )

    def test_export_sql_matches_search(self) -> None:
        sql, params = self.repo.export_sql(PageRequest(text="paracetamol"))
        rows = self.db.query(sql, params)
        self.assertEqual(len(rows), len(PARACETAMOL_ROWS))


class ManufacturerRepositoryTest(TempDbTestCase):
    def setUp(self) -> None:
        self.repo = ManufacturerRepository(self.db)

    def tearDown(self) -> None:
        self.db.execute("DELETE FROM medicines WHERE id > 10")
        self.db.execute("DELETE FROM manufacturers WHERE manufacturer_id > 4")
        self.db.execute("DELETE FROM compositions WHERE composition_id > 12")

    def test_list_enriches_with_counts(self) -> None:
        result = self.repo.list(limit=100)
        self.assertEqual(result.total, 4)
        by_name = {r[1]: r for r in result.rows}
        self.assertEqual(by_name["Mfr A"][2], 3)
        self.assertEqual(by_name["Mfr B"][2], 3)
        self.assertEqual(by_name["Mfr C"][2], 2)
        # Mfr A compositions: Paracetamol 100mg, 500mg, Caffeine, Amoxicillin = 4
        self.assertEqual(by_name["Mfr A"][3], 4)

    def test_filter_and_sort(self) -> None:
        result = self.repo.list("mfr c", limit=100)
        self.assertEqual([r[1] for r in result.rows], ["Mfr C"])
        descending = self.repo.list(
            limit=100, order_by="medicine_count", descending=True
        )
        self.assertIn(descending.rows[0][1], ("Mfr A", "Mfr B"))

    def test_composition_counts_cover_empty_ids(self) -> None:
        counts = self.repo.composition_counts([])
        self.assertEqual(counts, {})
        counts = self.repo.composition_counts([9999])
        self.assertEqual(counts, {9999: 0})

    def test_all_names_sorted(self) -> None:
        self.assertEqual(self.repo.all_names(), ["Mfr A", "Mfr B", "Mfr C", "Mfr D"])

    def test_get_and_missing(self) -> None:
        mfr = self.repo.get(1)
        self.assertEqual(mfr.name, "Mfr A")
        with self.assertRaises(NotFoundError):
            self.repo.get(999)

    def test_resolve_or_create_is_idempotent(self) -> None:
        first = self.repo.resolve_or_create("Mfr New")
        second = self.repo.resolve_or_create("Mfr New")
        self.assertEqual(first, second)
        self.assertEqual(self.repo.count("Mfr New"), 1)
        self.db.execute("DELETE FROM manufacturers WHERE manufacturer_id = ?", (first,))

    def test_save_rejects_duplicate_name(self) -> None:
        with self.assertRaises(ValidationError):
            self.repo.save(Manufacturer(name="Mfr A"))

    def test_save_creates_and_updates(self) -> None:
        new_id = self.repo.save(Manufacturer(name="Mfr New"))
        self.repo.save(Manufacturer(id=new_id, name="Mfr New Renamed"))
        self.assertEqual(self.repo.get(new_id).name, "Mfr New Renamed")
        self.db.execute("DELETE FROM manufacturers WHERE manufacturer_id = ?", (new_id,))

    def test_delete_blocked_when_in_use(self) -> None:
        with self.assertRaises(InUseError):
            self.repo.delete(1)  # Mfr A owns medicines

    def test_delete_removes_unused(self) -> None:
        new_id = self.repo.save(Manufacturer(name="Mfr Orphan"))
        self.assertEqual(self.repo.delete(new_id), 1)
        with self.assertRaises(NotFoundError):
            self.repo.delete(new_id)


class CompositionRepositoryTest(TempDbTestCase):
    def setUp(self) -> None:
        self.repo = CompositionRepository(self.db)

    def tearDown(self) -> None:
        self.db.execute("DELETE FROM medicines WHERE id > 10")
        self.db.execute("DELETE FROM manufacturers WHERE manufacturer_id > 4")
        self.db.execute("DELETE FROM compositions WHERE composition_id > 12")

    def test_usage_counts(self) -> None:
        row = self.db.query_one(
            "SELECT composition_id FROM compositions "
            "WHERE composition_text LIKE 'Paracetamol (10mg)%'"
        )
        assert row is not None
        # usage_count = composition1 hits (rows 7, 8) + composition2 hits (none)
        self.assertEqual(self.repo.usage_count(row["composition_id"]), 2)

    def test_list_sorted_and_filtered(self) -> None:
        result = self.repo.list(limit=100)
        texts = [r[1] for r in result.rows]
        self.assertEqual(texts, sorted(texts))
        filtered = self.repo.list("caffeine", limit=100)
        self.assertEqual(filtered.total, 1)

    def test_save_and_get(self) -> None:
        new_id = self.repo.save(Composition(text="Azithromycin (500mg)"))
        self.assertEqual(self.repo.get(new_id).text, "Azithromycin (500mg)")

    def test_save_rejects_duplicate(self) -> None:
        with self.assertRaises(ValidationError):
            self.repo.save(Composition(text="Caffeine (50mg)"))

    def test_delete_blocked_when_referenced(self) -> None:
        row = self.db.query_one(
            "SELECT composition_id FROM compositions "
            "WHERE composition_text LIKE 'Paracetamol%'"
        )
        assert row is not None
        with self.assertRaises(InUseError):
            self.repo.delete(row["composition_id"])

    def test_delete_removes_unused(self) -> None:
        new_id = self.repo.save(Composition(text="Unused compound"))
        self.assertEqual(self.repo.delete(new_id), 1)
        with self.assertRaises(NotFoundError):
            self.repo.get(new_id)


class SchemaRepositoryTest(TempDbTestCase):
    def setUp(self) -> None:
        self.repo = SchemaRepository(self.db)

    def test_objects_include_tables_views_indexes(self) -> None:
        objects = self.repo.objects()
        kinds = {(o["type"], o["name"]) for o in objects}
        self.assertIn(("table", "medicines"), kinds)
        self.assertIn(("view", "v_medicines"), kinds)
        self.assertIn(("index", "idx_medicines_name"), kinds)

    def test_columns(self) -> None:
        columns = self.repo.columns("medicines")
        names = [c["name"] for c in columns]
        self.assertEqual(
            names,
            [
                "id",
                "name",
                "price_rs",
                "manufacturer_id",
                "type",
                "pack_size_label",
                "composition1_id",
                "composition2_id",
            ],
        )
        self.assertTrue(columns[0]["pk"])
        self.assertTrue(columns[1]["notnull"])

    def test_columns_rejects_bad_ident(self) -> None:
        with self.assertRaises(ValidationError):
            self.repo.columns("medicines; DROP TABLE medicines")

    def test_row_count_and_preview(self) -> None:
        self.assertEqual(self.repo.row_count("manufacturers"), 4)
        columns, rows = self.repo.preview("compositions", limit=3)
        self.assertEqual(columns, ["composition_id", "composition_text"])
        self.assertEqual(len(rows), 3)

    def test_indexes(self) -> None:
        names = {i["name"] for i in self.repo.indexes("medicines")}
        self.assertIn("idx_medicines_name", names)


class StatsRepositoryTest(TempDbTestCase):
    def setUp(self) -> None:
        self.repo = StatsRepository(self.db)

    def test_counts(self) -> None:
        self.assertEqual(
            self.repo.counts(),
            {"medicines": 10, "manufacturers": 4, "compositions": 12},
        )

    def test_price_summary(self) -> None:
        summary = self.repo.price_summary()
        self.assertEqual(summary["min"], 5.0)
        self.assertEqual(summary["max"], 2500.0)
        self.assertAlmostEqual(summary["avg"], (10.5 + 55 + 250.75 + 99 + 1200
                                               + 80.25 + 5 + 20 + 2500 + 50) / 10)

    def test_price_bands_cover_every_row(self) -> None:
        bands = self.repo.price_bands()
        self.assertEqual(sum(n for _, n in bands), 10)
        labels = [label for label, _ in bands]
        self.assertIn("0 - 50", labels)
        self.assertIn("1000+", labels)

    def test_composition_split(self) -> None:
        split = dict(self.repo.composition_split())
        self.assertEqual(
            split, {"Single composition": 6, "Dual composition": 4}
        )

    def test_top_manufacturers(self) -> None:
        top = self.repo.top_manufacturers(2)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0], ("Mfr A", 3))

    def test_most_expensive_first_row(self) -> None:
        costly = self.repo.most_expensive(1)[0]
        self.assertEqual(costly[1], "Theta 1000")
        self.assertEqual(costly[2], 2500.0)

    def test_most_used_compositions(self) -> None:
        used = self.repo.most_used_compositions(2)
        # Caffeine (50mg) and Paracetamol (10mg) both appear twice; the tie
        # breaks alphabetically, so Caffeine comes first.
        self.assertEqual(
            used, [("Caffeine (50mg)", 2), ("Paracetamol (10mg)", 2)]
        )


if __name__ == "__main__":
    unittest.main()
