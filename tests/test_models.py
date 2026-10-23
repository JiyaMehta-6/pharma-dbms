"""Validation rules of the domain models."""
from __future__ import annotations

import unittest

from pharma_db.models import (
    Composition,
    Manufacturer,
    Medicine,
    PageRequest,
    ValidationError,
)


class MedicineValidationTest(unittest.TestCase):
    def valid(self, **overrides) -> Medicine:
        data = dict(
            name="Alpha Tab",
            price_rs=10.5,
            manufacturer_name="Mfr A",
            composition1="Paracetamol (100mg)",
        )
        data.update(overrides)
        return Medicine(**data)

    def test_valid_medicine_is_normalised(self) -> None:
        med = self.valid(
            name="  Alpha   Tab  ",
            manufacturer_name=" Mfr  A ",
            composition1=" Paracetamol  (100mg) ",
            composition2="",
            pack_size_label=" strip  of 10 ",
        ).validate()
        self.assertEqual(med.name, "Alpha Tab")
        self.assertEqual(med.manufacturer_name, "Mfr A")
        self.assertEqual(med.composition1, "Paracetamol (100mg)")
        self.assertIsNone(med.composition2)
        self.assertEqual(med.pack_size_label, "strip of 10")

    def test_string_price_is_parsed(self) -> None:
        med = self.valid(price_rs="1,234.50").validate()
        self.assertEqual(med.price_rs, 1234.5)

    def test_rejects_missing_name(self) -> None:
        with self.assertRaises(ValidationError):
            self.valid(name="   ").validate()

    def test_rejects_negative_price(self) -> None:
        with self.assertRaises(ValidationError):
            self.valid(price_rs=-1).validate()

    def test_rejects_non_finite_price(self) -> None:
        with self.assertRaises(ValidationError):
            self.valid(price_rs=float("inf")).validate()

    def test_rejects_missing_manufacturer(self) -> None:
        with self.assertRaises(ValidationError):
            self.valid(manufacturer_name="").validate()

    def test_rejects_missing_primary_composition(self) -> None:
        with self.assertRaises(ValidationError):
            self.valid(composition1="").validate()


class ManufacturerAndCompositionTest(unittest.TestCase):
    def test_manufacturer_requires_name(self) -> None:
        with self.assertRaises(ValidationError):
            Manufacturer(name="").validate()

    def test_manufacturer_rejects_overlong_name(self) -> None:
        with self.assertRaises(ValidationError):
            Manufacturer(name="x" * 201).validate()

    def test_manufacturer_validate_drops_counts(self) -> None:
        mfr = Manufacturer(id=3, name="Mfr A", medicine_count=9, composition_count=4)
        validated = mfr.validate()
        self.assertEqual(validated.id, 3)
        self.assertEqual(validated.medicine_count, 0)

    def test_composition_rules(self) -> None:
        self.assertEqual(Composition(text="  A  B ").validate().text, "A B")
        with self.assertRaises(ValidationError):
            Composition(text="").validate()
        with self.assertRaises(ValidationError):
            Composition(text="x" * 301).validate()


class PageRequestTest(unittest.TestCase):
    def test_ordered_by_is_fluent(self) -> None:
        req = PageRequest().ordered_by("price_rs")
        self.assertEqual(req.order_by, "price_rs")
        self.assertIs(req.order_by, req.order_by)


if __name__ == "__main__":
    unittest.main()
