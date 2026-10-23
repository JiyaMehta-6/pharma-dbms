"""Medicine browser: filter, sort, page, create, edit, delete and export."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ... import services
from ...auth import AuthService, User
from ...db import Database, DatabaseError
from ...models import Medicine, PageRequest, ValidationError
from ...repositories import MedicineRepository
from .. import dialogs
from ..qtmodels import Column, TableModel
from ..style import PAGE_MARGINS
from ..widgets import PaginationBar, configure_table, fit_columns
from ..workers import run_task

COLUMNS = [
    Column("ID", key="id", align_right=True),
    Column("Name", key="name"),
    Column("Price \u20b9", key="price_rs", align_right=True),
    Column("Manufacturer", key="manufacturer_name"),
    Column("Type", key="type"),
    Column("Pack", key="pack_size_label"),
    Column("Composition 1", key="short_composition1"),
    Column("Composition 2", key="short_composition2"),
    Column("Unit rate \u20b9", key="unit_rate", align_right=True),
]


class MedicinesPage(QWidget):
    refreshed = Signal(int)

    def __init__(
        self, db: Database, parent: QWidget | None = None, user: "User | None" = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.db = db
        self.user = user
        self._audit = AuthService(db)
        self.repo = MedicineRepository(db)
        self.request = PageRequest()
        self._manufacturer_names: list[str] = []
        self._block = False

        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Medicine name or composition  (Ctrl+F)")
        self.search_edit.setClearButtonEnabled(True)

        self.manufacturer_combo = QComboBox()
        self.manufacturer_combo.setPlaceholderText("Any manufacturer")
        self.manufacturer_combo.setEditable(True)
        self.manufacturer_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.manufacturer_combo.setCurrentText("")
        self.manufacturer_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.manufacturer_combo.setMinimumContentsLength(14)
        completer = self.manufacturer_combo.completer()
        if completer is not None:
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.min_spin = self._price_spin()
        self.max_spin = self._price_spin()

        self.apply_btn = QPushButton("Search")
        self.apply_btn.setObjectName("primary")
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setFlat(True)

        self.model = TableModel(COLUMNS, self)
        self.table = QTableView()
        configure_table(self.table, self.model)
        fit_columns(self.table, stretch=(1, 3, 6, 7), contents=(0, 2, 4, 8))
        self.table.horizontalHeader().setSortIndicator(1, Qt.SortOrder.AscendingOrder)
        self.table.doubleClicked.connect(lambda _: self.edit_selected())

        self.pager = PaginationBar()

        self.add_btn = QPushButton("Add")
        self.add_btn.setObjectName("primary")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("danger")
        self.export_btn = QPushButton("Export CSV")
        self.export_html_btn = QPushButton("Export HTML")
        self.export_json_btn = QPushButton("Export JSON")
        self.refresh_btn = QPushButton("Refresh")
        self.sort_label = QLabel("")
        self.sort_label.setObjectName("muted")

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self._debounced_refresh)

        self._build_layout()
        self._connect()

    # -- construction --------------------------------------------------------
    def _price_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 100_000_000.0)
        spin.setDecimals(2)
        spin.setPrefix("\u20b9 ")
        spin.setSpecialValueText("any")
        spin.setKeyboardTracking(False)
        return spin

    def _build_layout(self) -> None:
        card = QWidget()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("Search"), 0, 0)
        grid.addWidget(self.search_edit, 0, 1, 1, 3)
        grid.addWidget(QLabel("Manufacturer"), 0, 4)
        grid.addWidget(self.manufacturer_combo, 0, 5)

        grid.addWidget(QLabel("Min price"), 1, 0)
        grid.addWidget(self.min_spin, 1, 1)
        grid.addWidget(QLabel("Max price"), 1, 2)
        grid.addWidget(self.max_spin, 1, 3)
        grid.addWidget(self.apply_btn, 1, 4)
        grid.addWidget(self.reset_btn, 1, 5)

        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(5, 2)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.add_btn)
        actions.addWidget(self.edit_btn)
        actions.addWidget(self.delete_btn)
        actions.addStretch(1)
        actions.addWidget(self.sort_label)
        actions.addWidget(self.refresh_btn)
        actions.addWidget(self.export_btn)
        actions.addWidget(self.export_html_btn)
        actions.addWidget(self.export_json_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(10)
        layout.addWidget(self.error_label)
        layout.addWidget(card)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.pager)
        layout.addLayout(actions)

    def _connect(self) -> None:
        self.apply_btn.clicked.connect(self.apply_filters)
        self.reset_btn.clicked.connect(self.reset_filters)
        self.refresh_btn.clicked.connect(self.refresh)
        self.add_btn.clicked.connect(self.add_medicine)
        self.edit_btn.clicked.connect(self.edit_selected)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.export_btn.clicked.connect(self.export_csv)
        self.export_html_btn.clicked.connect(self.export_html)
        self.export_json_btn.clicked.connect(self.export_json)
        self.search_edit.returnPressed.connect(self.apply_filters)
        self.search_edit.textChanged.connect(self._schedule_refresh)
        self.manufacturer_combo.currentTextChanged.connect(self._schedule_refresh)
        self.min_spin.valueChanged.connect(self._schedule_refresh)
        self.max_spin.valueChanged.connect(self._schedule_refresh)
        self.pager.pageRequested.connect(lambda _page: self.refresh())
        self.pager.pageSizeRequested.connect(lambda _size: self.refresh())
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)

    # -- helpers -------------------------------------------------------------
    @property
    def columns(self) -> list[Column]:
        return COLUMNS

    def focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.search_edit.hasFocus():
            self.reset_filters()
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def _schedule_refresh(self, *_args) -> None:
        if self._block:
            return
        self._debounce.start()

    def _debounced_refresh(self) -> None:
        self.request.text = self.search_edit.text()
        self.request.manufacturer = self.manufacturer_combo.currentText()
        self.request.price_min = self.min_spin.value() or None
        self.request.price_max = self.max_spin.value() or None
        self.request.offset = 0
        self.pager.set_page(1)
        self.refresh()

    def apply_filters(self) -> None:
        self._debounce.stop()
        self._debounced_refresh()

    def reset_filters(self) -> None:
        self._block = True
        self.search_edit.clear()
        self.manufacturer_combo.setCurrentText("")
        self.min_spin.setValue(0)
        self.max_spin.setValue(0)
        self._block = False
        self.request = PageRequest(order_by=self.request.order_by, descending=self.request.descending)
        self.pager.set_page(1)
        self.refresh()

    def _read_request(self) -> PageRequest:
        req = self.request
        req.text = self.search_edit.text()
        req.manufacturer = self.manufacturer_combo.currentText()
        req.price_min = self.min_spin.value() or None
        req.price_max = self.max_spin.value() or None
        req.limit = self.pager.page_size
        req.offset = self.pager.offset
        return req

    def _on_header_clicked(self, section: int) -> None:
        column = COLUMNS[section] if 0 <= section < len(COLUMNS) else None
        if column is None or column.key is None:
            return
        if self.request.order_by == column.key:
            self.request.descending = not self.request.descending
        else:
            self.request.order_by = column.key
            self.request.descending = column.key in ("price_rs", "unit_rate")
        order = (
            Qt.SortOrder.DescendingOrder
            if self.request.descending
            else Qt.SortOrder.AscendingOrder
        )
        self.table.horizontalHeader().setSortIndicator(section, order)
        self._update_sort_label()
        self.refresh()

    def _update_sort_label(self) -> None:
        key = self.request.order_by
        title = next((c.title for c in COLUMNS if c.key == key), key)
        direction = "desc" if self.request.descending else "asc"
        self.sort_label.setText(f"Sorted by {title} ({direction})")

    def load_manufacturers(self, keep: str | None = None) -> None:
        current = keep if keep is not None else self.manufacturer_combo.currentText()
        names = self.repo.all_names()
        self._manufacturer_names = names
        self._block = True
        self.manufacturer_combo.clear()
        self.manufacturer_combo.addItems(["", *names])
        self.manufacturer_combo.setCurrentText(current)
        self._block = False

    # -- data ----------------------------------------------------------------
    def refresh(self) -> None:
        self._show_error("")
        try:
            req = self._read_request()
            result = self.repo.search(req)
        except DatabaseError as exc:
            self.model.clear()
            self.pager.set_total(0)
            self._show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.model.clear()
            self.pager.set_total(0)
            self._show_error(f"{type(exc).__name__}: {exc}")
            return
        self.model.set_rows(result.rows)
        self.pager.set_total(result.total, keep_page=True)
        self._update_sort_label()
        self.refreshed.emit(result.total)

    def selected_ids(self) -> list[int]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        ids: list[int] = []
        for row in rows:
            record = self.model.row_at(row)
            if record:
                ids.append(int(record[0]))
        return ids

    def _log(self, action: str, entity_id: int | None, detail: str = "") -> None:
        try:
            self._audit.record_audit(
                self.user, action, "medicine", entity_id, detail
            )
        except Exception:  # noqa: BLE001 - audit must never break the UI action
            pass

    def add_medicine(self) -> None:
        dialog = dialogs.MedicineDialog(
            Medicine(type="allopathy"),
            self._manufacturer_names or self.repo.all_names(),
            self._composition_cache(),
            self,
        )
        if dialog.exec():
            try:
                new_id = self.repo.save(dialog.payload())
            except (ValidationError, DatabaseError) as exc:
                dialogs.warn(self, "Cannot save medicine", str(exc))
                return
            self._log("create", new_id, dialog.payload().name)
            self.load_manufacturers()
            self.refresh()
            dialogs.info(self, "Medicine added", f"Created medicine id {new_id}.")

    def edit_selected(self) -> None:
        ids = self.selected_ids()
        if not ids:
            dialogs.info(self, "Edit medicine", "Select a row to edit.")
            return
        self._edit_id(ids[0])

    def _edit_id(self, medicine_id: int) -> None:
        medicine = self.repo.get(medicine_id)
        if medicine is None:
            dialogs.warn(self, "Edit medicine", f"Medicine {medicine_id} no longer exists.")
            self.refresh()
            return
        dialog = dialogs.MedicineDialog(
            medicine,
            self._manufacturer_names or self.repo.all_names(),
            self._composition_cache(),
            self,
        )
        if dialog.exec():
            try:
                payload = dialog.payload()
                self.repo.save(payload)
            except (ValidationError, DatabaseError) as exc:
                dialogs.warn(self, "Cannot save medicine", str(exc))
                return
            self._log("update", medicine_id, payload.name)
            self.load_manufacturers()
            self.refresh()

    def delete_selected(self) -> None:
        ids = self.selected_ids()
        if not ids:
            dialogs.info(self, "Delete medicine", "Select at least one row to delete.")
            return
        label = "this medicine" if len(ids) == 1 else f"these {len(ids)} medicines"
        if not dialogs.confirm(
            self,
            "Delete medicine",
            f"Permanently delete {label}? This cannot be undone.",
        ):
            return
        for medicine_id in ids:
            self.repo.delete(medicine_id)
            self._log("delete", medicine_id)
        self.refresh()

    def export_csv(self) -> None:
        default_name = "medicines-export.csv"
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export results to CSV", default_name, "CSV files (*.csv)"
        )
        if not dest:
            return
        path = Path(dest)
        sql, params = self.repo.export_sql(self._read_request())

        def task(progress):
            return services.export_result_to_csv(
                self.db.path, sql, params, path, progress
            )

        def done(count: int) -> None:
            dialogs.info(
                self, "Export finished", f"Wrote {count:,} row(s) to\n{path}"
            )

        run_task(
            self,
            "Export to CSV",
            f"Exporting filtered medicine rows to\n{path.name}",
            task,
            on_success=done,
        )

    def export_html(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export results to HTML", "medicines-export.html", "HTML files (*.html)"
        )
        if not dest:
            return
        path = Path(dest)
        sql, params = self.repo.export_sql(self._read_request())

        def task(_progress):
            return services.export_result_to_html(
                self.db.path, sql, params, path, title="Medicines report"
            )

        def done(count: int) -> None:
            dialogs.info(self, "Export finished", f"Wrote {count:,} row(s) to\n{path}")

        run_task(
            self, "Export to HTML", f"Exporting to {path.name}", task, on_success=done
        )

    def export_json(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export results to JSON", "medicines-export.json", "JSON files (*.json)"
        )
        if not dest:
            return
        path = Path(dest)
        sql, params = self.repo.export_sql(self._read_request())

        def task(_progress):
            return services.export_result_to_json(
                self.db.path, sql, params, path, title="Medicines report"
            )

        def done(count: int) -> None:
            dialogs.info(self, "Export finished", f"Wrote {count:,} row(s) to\n{path}")

        run_task(
            self, "Export to JSON", f"Exporting to {path.name}", task, on_success=done
        )

    def _composition_cache(self) -> list[str]:
        if not hasattr(self, "_compositions"):
            from ...repositories import CompositionRepository

            self._compositions = CompositionRepository(self.db).all_texts()
        return self._compositions
