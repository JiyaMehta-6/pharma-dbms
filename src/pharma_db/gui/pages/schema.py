"""Schema browser: DDL, columns, indexes and a data preview per object."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...db import Database, DatabaseError
from ...repositories import SchemaRepository
from ..qtmodels import Column, TableModel
from ..style import PAGE_MARGINS
from ..widgets import configure_table, fit_columns

COLUMN_DEFS = [
    Column("#", align_right=True),
    Column("Name"),
    Column("Type"),
    Column("Not null"),
    Column("Default"),
    Column("PK", align_right=True),
]
INDEX_DEFS = [
    Column("Index"),
    Column("Unique"),
    Column("Origin"),
    Column("Partial"),
]
PREVIEW_DEFS: list[Column] = []  # replaced at runtime


class SchemaPage(QWidget):
    PREVIEW_LIMIT = 200

    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.db = db
        self.repo = SchemaRepository(db)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Object", "Type"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 240)
        self.tree.currentItemChanged.connect(lambda *_: self._on_select())

        self.ddl_edit = QPlainTextEdit()
        self.ddl_edit.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.ddl_edit.setFont(font)

        self.copy_btn = QPushButton("Copy DDL")
        self.copy_btn.setFlat(True)
        self.copy_btn.clicked.connect(self._copy_ddl)
        self.ddl_header = QHBoxLayout()
        self.ddl_header.addWidget(QLabel("Definition"))
        self.ddl_header.addStretch(1)
        self.ddl_header.addWidget(self.copy_btn)

        self.columns_model = TableModel(COLUMN_DEFS, self)
        self.columns_table = QTableView()
        configure_table(self.columns_table, self.columns_model)
        fit_columns(self.columns_table, stretch=(1, 4), contents=(0, 2, 3, 5))
        self.columns_table.horizontalHeader().setSectionsClickable(False)

        self.index_model = TableModel(INDEX_DEFS, self)
        self.index_table = QTableView()
        configure_table(self.index_table, self.index_model)
        fit_columns(self.index_table, stretch=(0,), contents=(1, 2, 3))
        self.index_table.horizontalHeader().setSectionsClickable(False)

        self.preview_model = TableModel(PREVIEW_DEFS, self)
        self.preview_table = QTableView()
        configure_table(self.preview_table, self.preview_model)
        self.preview_table.horizontalHeader().setSectionsClickable(False)

        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        self.preview_header = QHBoxLayout()
        self.preview_header.addWidget(QLabel(f"Data (first {self.PREVIEW_LIMIT} rows)"))
        self.preview_header.addStretch(1)
        self.preview_header.addWidget(self.count_label)

        self.info_label = QLabel("Select an object to inspect it.")
        self.info_label.setObjectName("muted")

        self.tabs = QTabWidget()
        definition_page = QWidget()
        def_layout = QVBoxLayout(definition_page)
        def_layout.setContentsMargins(8, 8, 8, 8)
        def_layout.addLayout(self.ddl_header)
        def_layout.addWidget(self.ddl_edit, 1)
        self.tabs.addTab(definition_page, "Definition")
        self.tabs.addTab(self._wrap(self.columns_table), "Columns")
        self.tabs.addTab(self._wrap(self.index_table), "Indexes")
        data_page = QWidget()
        data_layout = QVBoxLayout(data_page)
        data_layout.setContentsMargins(8, 8, 8, 8)
        data_layout.addLayout(self.preview_header)
        data_layout.addWidget(self.preview_table, 1)
        self.tabs.addTab(data_page, "Data")

        self.refresh_btn = QPushButton("Refresh schema")
        self.refresh_btn.clicked.connect(self.refresh)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(self.info_label)
        right_layout.addWidget(self.tabs, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([260, 780])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(QLabel("Database objects"))
        top.addStretch(1)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)

    @staticmethod
    def _wrap(widget: QWidget) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(widget)
        return page

    # -- behaviour -----------------------------------------------------------
    def refresh(self) -> None:
        self.tree.clear()
        try:
            objects = self.repo.objects()
        except DatabaseError as exc:
            self.info_label.setText(f"Cannot read schema: {exc}")
            return
        groups: dict[str, QTreeWidgetItem] = {}
        for key, label in (("table", "Tables"), ("view", "Views"), ("index", "Indexes")):
            groups[key] = QTreeWidgetItem([label, ""])
            self.tree.addTopLevelItem(groups[key])
        for obj in objects:
            kind = obj["type"]
            if kind not in groups:
                continue
            child = QTreeWidgetItem([obj["name"], kind])
            child.setData(0, Qt.ItemDataRole.UserRole, obj)
            groups[kind].addChild(child)
        for item in groups.values():
            item.setExpanded(True)
        self.info_label.setText(f"{len(objects)} object(s)")
        self.tree.setCurrentItem(
            self.tree.topLevelItem(0).child(0)
            if self.tree.topLevelItem(0) and self.tree.topLevelItem(0).childCount()
            else None
        )

    def _on_select(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        obj = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(obj, dict):
            return
        name = obj["name"]
        kind = obj["type"]
        self.ddl_edit.setPlainText(obj["sql"] or "-- no DDL recorded")
        self.index_model.clear()
        self.columns_model.clear()
        self.preview_model.clear()
        self.count_label.setText("")
        if kind == "index":
            self.info_label.setText(f"Index {name}")
            return
        try:
            columns = self.repo.columns(name)
            self.columns_model.set_rows(
                [
                    (
                        col["cid"],
                        col["name"],
                        col["type"],
                        col["notnull"],
                        col["default"],
                        col["pk"],
                    )
                    for col in columns
                ]
            )
            indexes = self.repo.indexes(name)
            if kind == "table":
                self.index_model.set_rows(
                    [
                        (idx["name"], idx["unique"], idx["origin"], idx["partial"])
                        for idx in indexes
                    ]
                )
            headers, rows = self.repo.preview(name, self.PREVIEW_LIMIT)
            self.preview_model.columns = [Column(title) for title in headers]
            self.preview_model.set_rows(rows)
            count = self.repo.row_count(name)
            self.count_label.setText(f"{count:,} row(s) total")
            self.info_label.setText(
                f"{kind.title()} {name} - {len(columns)} column(s), {count:,} row(s)"
            )
        except Exception as exc:  # noqa: BLE001
            self.info_label.setText(f"{name}: {type(exc).__name__}: {exc}")

    def _copy_ddl(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = self.ddl_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
