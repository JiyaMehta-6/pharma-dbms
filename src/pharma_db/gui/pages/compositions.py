"""Composition management: create, rename, inspect and delete."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ...db import Database
from ...models import Composition
from ...repositories import (
    CompositionRepository,
    InUseError,
    NotFoundError,
    ValidationError,
)
from .. import dialogs
from ..qtmodels import Column
from .base import ListPage

COLUMNS = [
    Column("ID", key="composition_id", align_right=True),
    Column("Composition", key="composition_text"),
    Column("Used by", key="usage_count", align_right=True),
]


class CompositionsPage(ListPage):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(db, COLUMNS, "Search composition (e.g. Paracetamol)...", parent)
        self.repo = CompositionRepository(db)
        self.hint_label.setText(
            "'Used by' counts medicines that list this composition."
        )

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
                f"{total:,} composition(s) - deleting is blocked while a composition "
                "is still used by medicines."
            )

    def add_row(self) -> None:
        dialog = dialogs.CompositionDialog(Composition(), self)
        if dialog.exec():
            try:
                new_id = self.repo.save(dialog.payload())
            except (ValidationError, Exception) as exc:  # noqa: B014
                dialogs.warn(self, "Cannot save composition", str(exc))
                return
            if hasattr(self, "_compositions"):
                del self._compositions
            self.refresh()
            dialogs.info(self, "Composition added", f"Created composition id {new_id}.")

    def edit_row(self) -> None:
        records = self.selected_records()
        if not records:
            dialogs.info(self, "Edit composition", "Select a row to edit.")
            return
        try:
            composition = self.repo.get(int(records[0][0]))
        except NotFoundError:
            dialogs.warn(self, "Edit composition", "That composition no longer exists.")
            self.refresh()
            return
        dialog = dialogs.CompositionDialog(composition, self)
        if dialog.exec():
            try:
                self.repo.save(dialog.payload())
            except ValidationError as exc:
                dialogs.warn(self, "Cannot save composition", str(exc))
                return
            self.refresh()

    def delete_rows(self) -> None:
        records = self.selected_records()
        if not records:
            dialogs.info(self, "Delete composition", "Select at least one row to delete.")
            return
        names = ", ".join(str(r[1]) for r in records[:4])
        if len(records) > 4:
            names += f" and {len(records) - 4} more"
        if not dialogs.confirm(
            self,
            "Delete composition",
            f"Delete {len(records)} composition(s): {names}?",
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
                "Still used by medicines (reassign those medicines first):\n"
                + "\n".join(blocked[:10]),
            )
        elif deleted:
            dialogs.info(self, "Deleted", f"Removed {deleted} composition(s).")
