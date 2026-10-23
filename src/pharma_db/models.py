"""Domain models with validation used by the repositories and dialogs."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


class ValidationError(ValueError):
    """Raised when user supplied data fails validation."""


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


@dataclass(slots=True)
class Medicine:
    id: int | None = None
    name: str = ""
    price_rs: float = 0.0
    manufacturer_name: str = ""
    type: str = "allopathy"
    pack_size_label: str | None = None
    composition1: str = ""
    composition2: str | None = None

    def validate(self) -> "Medicine":
        name = _clean(self.name)
        if not name:
            raise ValidationError("Medicine name is required.")
        price = self.price_rs
        if isinstance(price, str):
            price = price.replace(",", "").strip()
            try:
                price = float(price)
            except ValueError as exc:
                raise ValidationError("Price must be a number.") from exc
        if not isinstance(price, (int, float)) or not math.isfinite(price):
            raise ValidationError("Price must be a finite number.")
        if price < 0:
            raise ValidationError("Price cannot be negative.")
        manufacturer = _clean(self.manufacturer_name)
        if not manufacturer:
            raise ValidationError("Manufacturer is required.")
        comp1 = _clean(self.composition1)
        if not comp1:
            raise ValidationError("Primary composition is required.")
        comp2 = _clean(self.composition2)
        kind = _clean(self.type) or "allopathy"
        pack = _clean(self.pack_size_label)
        return Medicine(
            id=self.id,
            name=name,
            price_rs=float(price),
            manufacturer_name=manufacturer,
            type=kind,
            pack_size_label=pack,
            composition1=comp1,
            composition2=comp2,
        )


@dataclass(slots=True)
class Manufacturer:
    id: int | None = None
    name: str = ""
    medicine_count: int = 0
    composition_count: int = 0

    def validate(self) -> "Manufacturer":
        name = _clean(self.name)
        if not name:
            raise ValidationError("Manufacturer name is required.")
        if len(name) > 200:
            raise ValidationError("Manufacturer name is too long (max 200 chars).")
        return Manufacturer(id=self.id, name=name)


@dataclass(slots=True)
class Composition:
    id: int | None = None
    text: str = ""
    usage_count: int = 0

    def validate(self) -> "Composition":
        text = _clean(self.text)
        if not text:
            raise ValidationError("Composition text is required.")
        if len(text) > 300:
            raise ValidationError("Composition text is too long (max 300 chars).")
        return Composition(id=self.id, text=text)


@dataclass(slots=True)
class PageRequest:
    """Pagination + ordering request passed to repository search methods."""

    limit: int = 100
    offset: int = 0
    order_by: str = "name"
    descending: bool = False
    text: str = ""
    manufacturer: str = ""
    composition: str = ""
    price_min: float | None = None
    price_max: float | None = None
    type_filter: str = ""

    def ordered_by(self, column: str) -> "PageRequest":
        self.order_by = column
        return self


@dataclass(slots=True)
class PageResult:
    rows: list[tuple] = field(default_factory=list)
    total: int = 0
