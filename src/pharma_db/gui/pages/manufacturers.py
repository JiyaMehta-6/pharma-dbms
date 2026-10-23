"""Manufacturer management: create, rename, inspect and delete."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ...db import Database
from ...models import Manufacturer
from ...repositories import InUseError, ManufacturerRepository, NotFoundError, ValidationError
from .. import dialogs
from ..qtmodels import Column
from .base import ListPage

COLUMNS = [
    Column("ID", key="manufacturer_id", align_right=True),
    Column("Manufacturer", key="manufacturer_name"),
    Column("Medicines", key="medicine_count", align_right=True),
    Column("Compositions", key="composition_count", align_right=True),
]


class ManufacturersPage(ListPage):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(db, COLUMNS, "Search manufacturer name...", parent)
        self.repo = ManufacturerRepository(db)
        self.hint_label.setText("Deleting is blocked while a manufacturer still has medicines.")

    def fetch(self, text: str, limit: int, offset: int):
        return self.repo.list(
            text,
            limit=limit,
            offset=offset,
            order_by=self.order_by,
            descending=self.descending,
        )

    def on_total(self, total: int) -> None:
        if not self.search_edit.text().strip():
            self.hint_label.setText(
                f"{total:,} manufacturer(s) - deleting is blocked while a manufacturer "
                "still has medicines."
            )

    def add_row(self) -> None:
        dialog = dialogs.ManufacturerDialog(Manufacturer(), self)
        if dialog.exec():
            try:
                new_id = self.repo.save(dialog.payload())
            except (ValidationError, Exception) as exc:  # noqa: B014
                dialogs.warn(self, "Cannot save manufacturer", str(exc))
                return
            self.refresh()
            dialogs.info(self, "Manufacturer added", f"Created manufacturer id {new_id}.")

    def edit_row(self) -> None:
        records = self.selected_records()
        if not records:
            dialogs.info(self, "Edit manufacturer", "Select a row to edit.")
            return
        try:
            manufacturer = self.repo.get(int(records[0][0]))
        except NotFoundError:
            dialogs.warn(self, "Edit manufacturer", "That manufacturer no longer exists.")
            self.refresh()
            return
        dialog = dialogs.ManufacturerDialog(manufacturer, self)
        if dialog.exec():
            try:
                self.repo.save(dialog.payload())
            except ValidationError as exc:
                dialogs.warn(self, "Cannot save manufacturer", str(exc))
                return
            self.refresh()

    def delete_rows(self) -> None:
        records = self.selected_records()
        if not records:
            dialogs.info(self, "Delete manufacturer", "Select at least one row to delete.")
            return
        names = ", ".join(str(r[1]) for r in records[:4])
        if len(records) > 4:
            names += f" and {len(records) - 4} more"
        if not dialogs.confirm(
            self,
            "Delete manufacturer",
            f"Delete {len(records)} manufacturer(s): {names}?",
        ):
            return
        blocked: list[str] = []
        deleted = 0
        for record in records:
            try:
                self.repo.delete(int(record[0]))
                deleted += 1
            except InUseError:
                blocked.append(str(record[1]))
            except NotFoundError:
                continue
        self.refresh()
        if blocked:
            dialogs.warn(
                self,
                "Some rows were kept",
                "Still referenced by medicines (delete their medicines first):\n"
                + "\n".join(blocked[:10]),
            )
        elif deleted:
            dialogs.info(self, "Deleted", f"Removed {deleted} manufacturer(s).")
