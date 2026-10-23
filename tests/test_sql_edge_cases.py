"""SQL and parsing edge cases beyond the happy path already covered."""
from __future__ import annotations

import sqlite3
import unittest
from typing import ClassVar

from tests.support import FixtureCsvTestCase, TempDbTestCase

from pharma_db.models import PageRequest
from pharma_db.repositories import (
    MedicineRepository,
    SchemaRepository,
    StatsRepository,
    like_pattern,
    safe_ident,
)
from pharma_db.models import ValidationError


class LikePatternEdgeCaseTest(TempDbTestCase):
    """LIKE escaping end-to-end: the pattern must never act as a wildcard."""

    def test_percent_and_underscore_are_literal(self) -> None:
        # "100%" must not match "100mg".
        self.assertEqual(like_pattern("100%"), r"%100\%%")

    def test_backslash_is_escaped(self) -> None:
        self.assertEqual(like_pattern("a\\b"), r"%a\\b%")

    def test_empty_and_whitespace(self) -> None:
        self.assertEqual(like_pattern(""), "%%")
        self.assertEqual(like_pattern("   "), "%%")

    def test_composition_text_is_searched(self) -> None:
        # "100mg" lives in short_composition1, not in the medicine name.
        rows = self.db.query(
            "SELECT name FROM v_medicines_dtl"
            " WHERE short_composition1 LIKE ? ESCAPE '\\'",
            (like_pattern("100mg"),),
        )
        names = [r["name"] for r in rows]
        self.assertIn("Alpha Tab 100", names)

    def test_user_percent_does_not_wildcard_match(self) -> None:
        # Searching the literal "100%" must not match the names that the
        # unescaped pattern "%100%%" would match as a wildcard.
        unescaped = self.db.query(
            "SELECT name FROM v_medicines_dtl WHERE name LIKE ?",
            ("%100%%",),
        )
        self.assertTrue(unescaped, "the unescaped wildcard should match names")

        escaped = self.db.query(
            "SELECT name FROM v_medicines_dtl"
            " WHERE name LIKE ? ESCAPE '\\'",
            (like_pattern("100%"),),
        )
        self.assertEqual(escaped, [])


class PackQtyParsingTest(FixtureCsvTestCase):
    """The v_medicines_dtl pack_qty / unit_rate derivation, edge cases."""

    fixture_rows: ClassVar[list[list[object]]] = [
        [1, "With Of", 100.0, "FALSE", "Mfr A", "allopathy",
         "strip of 10 tablets", "Comp A", ""],
        [2, "No Of", 50.0, "FALSE", "Mfr A", "allopathy",
         "strip", "Comp A", ""],
        [3, "Of At End", 60.0, "FALSE", "Mfr A", "allopathy",
         "pack of", "Comp A", ""],
        [4, "Zero Qty", 30.0, "FALSE", "Mfr A", "allopathy",
         "box of 0 items", "Comp A", ""],
        [5, "Decimal", 99.0, "FALSE", "Mfr A", "allopathy",
         "bottle of 2.5 ml", "Comp A", ""],
        [6, "Of Later", 80.0, "FALSE", "Mfr A", "allopathy",
         "box 12 of 4 tablets", "Comp A", ""],
    ]

    def _row(self, medicine_id: int):
        return self.db.query_one(
            "SELECT pack_qty, unit_rate FROM v_medicines_dtl WHERE id = ?",
            (medicine_id,),
        )

    def test_numeric_after_of_is_parsed(self) -> None:
        row = self._row(1)
        assert row is not None
        self.assertEqual(row["pack_qty"], 10.0)
        self.assertEqual(row["unit_rate"], 10.0)

    def test_label_without_of_yields_null(self) -> None:
        row = self._row(2)
        assert row is not None
        self.assertIsNone(row["pack_qty"])
        self.assertIsNone(row["unit_rate"])

    def test_of_with_no_number_yields_null(self) -> None:
        row = self._row(3)
        assert row is not None
        self.assertIsNone(row["pack_qty"])

    def test_zero_qty_yields_null_rate(self) -> None:
        row = self._row(4)
        assert row is not None
        self.assertIsNone(row["pack_qty"])
        self.assertIsNone(row["unit_rate"])

    def test_decimal_qty(self) -> None:
        row = self._row(5)
        assert row is not None
        self.assertEqual(row["pack_qty"], 2.5)
        self.assertEqual(row["unit_rate"], 39.6)  # 99 / 2.5

    def test_first_of_wins(self) -> None:
        row = self._row(6)
        assert row is not None
        # INSTR finds the FIRST "of ", so the trailing "of 4 tablets" is what
        # gets parsed; the leading "12" is deliberately ignored.
        self.assertEqual(row["pack_qty"], 4.0)


class PriceBandBoundaryTest(FixtureCsvTestCase):
    """Band edges: value equal to a boundary belongs to the higher band."""

    fixture_rows: ClassVar[list[list[object]]] = [
        [1, "At 0", 0.0, "FALSE", "Mfr A", "allopathy", None, "C", ""],
        [2, "Just under 50", 49.99, "FALSE", "Mfr A", "allopathy", None, "C", ""],
        [3, "Exactly 50", 50.0, "FALSE", "Mfr A", "allopathy", None, "C", ""],
        [4, "Exactly 100", 100.0, "FALSE", "Mfr A", "allopathy", None, "C", ""],
        [5, "Exactly 250", 250.0, "FALSE", "Mfr A", "allopathy", None, "C", ""],
        [6, "Exactly 500", 500.0, "FALSE", "Mfr A", "allopathy", None, "C", ""],
        [7, "Exactly 1000", 1000.0, "FALSE", "Mfr A", "allopathy", None, "C", ""],
        [8, "Over 1000", 1000.01, "FALSE", "Mfr A", "allopathy", None, "C", ""],
    ]

    def test_boundaries_land_in_expected_bands(self) -> None:
        # Bands are half-open [low, high), so a boundary value falls into the
        # higher band: 50.0 -> "50 - 100", 100.0 -> "100 - 250", 250.0 ->
        # "250 - 500".  The 0.0 row proves the CHECK (price_rs >= 0) bound is
        # inclusive at the low end.
        bands = dict(StatsRepository(self.db).price_bands())
        self.assertEqual(bands["0 - 50"], 2)      # 0.0, 49.99
        self.assertEqual(bands["50 - 100"], 1)    # 50.0
        self.assertEqual(bands["100 - 250"], 1)   # 100.0
        self.assertEqual(bands["250 - 500"], 1)   # 250.0
        self.assertEqual(bands["500 - 1000"], 1)  # 500.0
        self.assertEqual(bands["1000+"], 2)       # 1000.0, 1000.01
        self.assertEqual(sum(bands.values()), 8)

    def test_negative_price_is_rejected_by_check(self) -> None:
        # Database.execute re-raises the raw sqlite3 error; translation to
        # ValidationError happens one layer up, in MedicineRepository.save.
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO medicines (id, name, price_rs, manufacturer_id,"
                " type, pack_size_label, composition1_id, composition2_id)"
                " VALUES (99, 'Negative', -1.0, 1, 'allopathy', NULL, 1, NULL)"
            )


class SafeIdentTest(unittest.TestCase):
    def test_rejects_quotes_semicolons_and_spaces(self) -> None:
        for bad in ('users"; --', "a b", "1abc", "a-b", ""):
            with self.assertRaises(ValidationError):
                safe_ident(bad)

    def test_accepts_simple_identifiers(self) -> None:
        self.assertEqual(safe_ident("medicines"), "medicines")
        self.assertEqual(safe_ident("_tmp_1"), "_tmp_1")


class SchemaRepositoryGuardTest(TempDbTestCase):
    def test_preview_rejects_bad_table_name(self) -> None:
        repo = SchemaRepository(self.db)
        with self.assertRaises(ValidationError):
            repo.preview("medicines; DROP TABLE medicines")

    def test_row_count_rejects_bad_table_name(self) -> None:
        repo = SchemaRepository(self.db)
        with self.assertRaises(ValidationError):
            repo.row_count('medicines"')


class EmptyAndWhitespaceSearchTest(TempDbTestCase):
    def test_whitespace_only_text_matches_everything(self) -> None:
        repo = MedicineRepository(self.db)
        result = repo.search(PageRequest(text="   ", limit=100))
        self.assertEqual(result.total, 10)

    def test_text_search_is_case_insensitive(self) -> None:
        repo = MedicineRepository(self.db)
        upper = repo.search(PageRequest(text="PARACETAMOL", limit=100))
        lower = repo.search(PageRequest(text="paracetamol", limit=100))
        self.assertEqual(upper.total, lower.total)
        self.assertGreater(upper.total, 0)


if __name__ == "__main__":
    unittest.main()
