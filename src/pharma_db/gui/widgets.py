"""Small reusable widgets shared by the management pages."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .. import config
from .qtmodels import TableModel


class PaginationBar(QWidget):
    """Prev/next paging controls plus a page-size selector."""

    pageRequested = Signal(int)
    pageSizeRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._page = 1
        self._page_size = config.DEFAULT_PAGE_SIZE
        self._total = 0

        self.first_btn = QPushButton("<<")
        self.prev_btn = QPushButton("<")
        self.next_btn = QPushButton(">")
        self.last_btn = QPushButton(">>")
        for button in (self.first_btn, self.prev_btn, self.next_btn, self.last_btn):
            button.setFixedWidth(34)
            button.setFlat(True)

        self.info_label = QLabel("0 rows")
        self.info_label.setObjectName("muted")
        self.page_label = QLabel("Page 1 of 1")
        self.page_label.setMinimumWidth(130)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.size_combo = QComboBox()
        for size in config.PAGE_SIZES:
            self.size_combo.addItem(f"{size} / page", size)
        index = self.size_combo.findData(self._page_size)
        if index >= 0:
            self.size_combo.setCurrentIndex(index)

        self.jump_combo = QComboBox()
        self.jump_combo.setMinimumWidth(90)
        self.jump_combo.setEditable(True)
        self.jump_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(6)
        layout.addWidget(self.info_label)
        layout.addStretch(1)
        layout.addWidget(self.first_btn)
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.page_label)
        layout.addWidget(self.next_btn)
        layout.addWidget(self.last_btn)
        layout.addSpacing(10)
        layout.addWidget(QLabel("Go to page:"))
        layout.addWidget(self.jump_combo)
        layout.addSpacing(6)
        layout.addWidget(self.size_combo)

        self.first_btn.clicked.connect(lambda: self.goto(1))
        self.prev_btn.clicked.connect(lambda: self.goto(self._page - 1))
        self.next_btn.clicked.connect(lambda: self.goto(self._page + 1))
        self.last_btn.clicked.connect(lambda: self.goto(self.page_count))
        self.size_combo.currentIndexChanged.connect(self._size_changed)
        self.jump_combo.activated.connect(self._jump_changed)
        self.jump_combo.lineEdit().returnPressed.connect(self._jump_typed)

        self.set_total(0)

    @property
    def page(self) -> int:
        return self._page

    @property
    def page_size(self) -> int:
        return self._page_size

    @property
    def offset(self) -> int:
        return (self._page - 1) * self._page_size

    @property
    def page_count(self) -> int:
        if self._total <= 0:
            return 1
        return (self._total + self._page_size - 1) // self._page_size

    @property
    def total(self) -> int:
        return self._total

    def set_total(self, total: int, keep_page: bool = False) -> None:
        self._total = max(0, int(total))
        if not keep_page:
            self._page = 1
        self._page = min(self._page, self.page_count)
        self._update_labels()

    def set_page(self, page: int) -> None:
        self._page = min(max(1, int(page)), self.page_count)
        self._update_labels()

    def goto(self, page: int) -> None:
        target = min(max(1, int(page)), self.page_count)
        if target == self._page:
            self._update_labels()
            return
        self._page = target
        self._update_labels()
        self.pageRequested.emit(self._page)

    def set_page_size(self, size: int) -> None:
        """Select a page size (updates the combo and emits the request)."""
        index = self.size_combo.findData(int(size))
        if index < 0:
            self.size_combo.addItem(f"{int(size)} / page", int(size))
            index = self.size_combo.findData(int(size))
        if index >= 0 and self.size_combo.currentIndex() != index:
            self.size_combo.setCurrentIndex(index)
        elif index >= 0:
            # Same size already selected; still apply it so callers that skip
            # the signal path get consistent state.
            self._size_changed(index)

    def _size_changed(self, index: int) -> None:
        size = self.size_combo.itemData(index)
        if not size:
            return
        self._page_size = int(size)
        self._page = 1
        self._update_labels()
        self.pageSizeRequested.emit(self._page_size)

    def _jump_changed(self, index: int) -> None:
        self.goto(self.jump_combo.itemData(index))

    def _jump_typed(self) -> None:
        raw = self.jump_combo.currentText().strip()
        if raw.isdigit():
            self.goto(int(raw))
        else:
            self.jump_combo.setEditText(str(self._page))

    def _update_labels(self) -> None:
        pages = self.page_count
        self.page_label.setText(f"Page {self._page} of {pages:,}")
        self.info_label.setText(f"{self._total:,} row(s)")
        self.first_btn.setEnabled(self._page > 1)
        self.prev_btn.setEnabled(self._page > 1)
        self.next_btn.setEnabled(self._page < pages)
        self.last_btn.setEnabled(self._page < pages)
        self.jump_combo.setEnabled(pages > 1)

        self.jump_combo.blockSignals(True)
        self.jump_combo.clear()
        limit = min(pages, 300)
        start = max(1, min(self._page - 50, pages - limit + 1))
        for number in range(start, start + limit):
            self.jump_combo.addItem(str(number), number)
        self.jump_combo.setEditText(str(self._page))
        self.jump_combo.blockSignals(False)


class StatCard(QFrame):
    """Dashboard metric tile."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.value_label = QLabel("0")
        self.value_label.setObjectName("statValue")
        self.title_label = QLabel(label)
        self.title_label.setObjectName("statLabel")
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("statLabel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        layout.addWidget(self.value_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.hint_label)

    def set_value(self, value: str, hint: str = "") -> None:
        self.value_label.setText(value)
        self.hint_label.setText(hint)


def configure_table(view: QTableView, model: TableModel) -> None:
    """Apply the common look-and-behaviour used by every data grid."""
    view.setModel(model)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
    view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
    view.setSortingEnabled(False)
    view.setWordWrap(False)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(26)
    header = view.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionsClickable(True)
    header.setSortIndicatorShown(True)
    header.setMinimumSectionSize(56)


def fit_columns(
    view: QTableView,
    *,
    stretch: tuple[int, ...] = (),
    contents: tuple[int, ...] = (),
    last_stretch: bool = True,
) -> None:
    """Mix stretch / auto-size / fixed widths for a grid's columns."""
    header = view.horizontalHeader()
    model = view.model()
    count = model.columnCount() if model else 0
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for index in contents:
        if index < count:
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
    for index in stretch:
        if index < count:
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
    if last_stretch and count:
        header.setSectionResizeMode(count - 1, QHeaderView.ResizeMode.Stretch)
    bold = QFont()
    bold.setBold(True)
    header.setFont(bold)
