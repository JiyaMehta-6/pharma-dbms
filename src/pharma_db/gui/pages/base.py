"""Shared base for the manufacturer / composition list pages."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...db import Database, DatabaseError
from ...models import PageResult
from ..qtmodels import Column, TableModel
from ..style import PAGE_MARGINS
from ..widgets import PaginationBar, configure_table, fit_columns


class ListPage(QWidget):
    """Searchable, sortable, paginated CRUD grid with a hook-based API."""

    refreshed = Signal(int)

    def __init__(
        self,
        db: Database,
        columns: list[Column],
        search_placeholder: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.db = db
        self.columns = columns
        self.order_by = columns[0].key or ""
        self.descending = False

        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(search_placeholder)
        self.search_edit.setClearButtonEnabled(True)

        self.model = TableModel(columns, self)
        self.table = QTableView()
        configure_table(self.table, self.model)
        fit_columns(
            self.table,
            stretch=tuple(
                i for i, col in enumerate(columns) if len(col.title) > 6
            ),
            contents=tuple(i for i, col in enumerate(columns) if len(col.title) <= 6),
        )
        start_column = next(
            (i for i, col in enumerate(columns) if col.key == self.order_by), 0
        )
        self.table.horizontalHeader().setSortIndicator(
            start_column, Qt.SortOrder.AscendingOrder
        )
        self.pager = PaginationBar()

        self.add_btn = QPushButton("Add")
        self.add_btn.setObjectName("primary")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("danger")
        self.refresh_btn = QPushButton("Refresh")
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("muted")
        self.hint_label.setWordWrap(True)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self.apply_filters)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.refresh_btn)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self.add_btn)
        bottom.addWidget(self.edit_btn)
        bottom.addWidget(self.delete_btn)
        bottom.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(10)
        layout.addWidget(self.error_label)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.pager)
        layout.addLayout(bottom)
        layout.addWidget(self.hint_label)

        self.search_edit.textChanged.connect(self._schedule)
        self.search_edit.returnPressed.connect(self.apply_filters)
        self.refresh_btn.clicked.connect(self.refresh)
        self.add_btn.clicked.connect(self.add_row)
        self.edit_btn.clicked.connect(self.edit_row)
        self.delete_btn.clicked.connect(self.delete_rows)
        self.pager.pageRequested.connect(lambda _p: self.refresh())
        self.pager.pageSizeRequested.connect(lambda _s: self.refresh())
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.doubleClicked.connect(lambda _i: self.edit_row())

    # -- hooks ---------------------------------------------------------------
    def fetch(self, text: str, limit: int, offset: int) -> PageResult:
        raise NotImplementedError

    def add_row(self) -> None:
        raise NotImplementedError

    def edit_row(self) -> None:
        raise NotImplementedError

    def delete_rows(self) -> None:
        raise NotImplementedError

    def on_total(self, total: int) -> None:
        """Optional hook once a refresh has completed."""

    # -- shared behaviour ----------------------------------------------------
    def focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def _schedule(self, *_args) -> None:
        self._debounce.start()

    def apply_filters(self) -> None:
        self._debounce.stop()
        self.pager.set_page(1)
        self.refresh()

    def refresh(self) -> None:
        self._show_error("")
        try:
            result = self.fetch(
                self.search_edit.text(),
                self.pager.page_size,
                self.pager.offset,
            )
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
        self.refreshed.emit(result.total)
        self.on_total(result.total)

    def _on_header_clicked(self, section: int) -> None:
        if not (0 <= section < len(self.columns)):
            return
        key = self.columns[section].key
        if not key:
            return
        if self.order_by == key:
            self.descending = not self.descending
        else:
            self.order_by = key
            self.descending = False
        order = (
            Qt.SortOrder.DescendingOrder if self.descending else Qt.SortOrder.AscendingOrder
        )
        self.table.horizontalHeader().setSortIndicator(section, order)
        self.refresh()

    def selected_records(self) -> list[tuple]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        out = []
        for row in rows:
            record = self.model.row_at(row)
            if record:
                out.append(record)
        return out
