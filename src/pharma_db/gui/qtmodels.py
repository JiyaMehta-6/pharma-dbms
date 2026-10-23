"""Reusable Qt item models for database result grids."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

Formatter = Callable[[Any], str]


@dataclass(slots=True)
class Column:
    title: str
    key: str | None = None
    align_right: bool = False
    fmt: Formatter | None = None
    stretch: bool = False


class TableModel(QAbstractTableModel):
    """Read-only model over a list of tuples described by :class:`Column`."""

    def __init__(self, columns: Sequence[Column], parent: Any = None) -> None:
        super().__init__(parent)
        self.columns = list(columns)
        self.rows: list[tuple] = []

    def set_rows(self, rows: Sequence[Sequence[Any]]) -> None:
        self.beginResetModel()
        self.rows = [tuple(r) for r in rows]
        self.endResetModel()

    def clear(self) -> None:
        self.set_rows([])

    def row_at(self, row: int) -> tuple | None:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None

    def index_of(self, row: tuple) -> int:
        try:
            return self.rows.index(row)
        except ValueError:
            return -1

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        column = self.columns[index.column()]
        if index.column() >= len(row):
            return None
        value = row[index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if value is None:
                return ""
            if column.fmt is not None:
                return column.fmt(value)
            if isinstance(value, float):
                return f"{value:,.2f}"
            if isinstance(value, bool):
                return "Yes" if value else "No"
            return str(value)
        if role == Qt.ItemDataRole.UserRole:
            return value
        if role == Qt.ItemDataRole.TextAlignmentRole and column.align_right:
            return (
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            )
        if role == Qt.ItemDataRole.ToolTipRole and value is not None:
            return str(value)
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.columns):
                return self.columns[section].title
            return None
        return section + 1

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Client-side fallback sort (server-side sorting is preferred)."""
        if not self.rows or not (0 <= column < len(self.columns)):
            return
        self.layoutAboutToBeChanged.emit()
        reverse = order == Qt.SortOrder.DescendingOrder
        self.rows.sort(
            key=lambda r: (r[column] is None, r[column] if r[column] is not None else 0),
            reverse=reverse,
        )
        self.layoutChanged.emit()


class DictModel(QAbstractTableModel):
    """Model over a list of dicts (used by the schema/preview panes)."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.headers: list[str] = []
        self.rows: list[dict[str, Any]] = []

    def set_data(self, headers: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.headers = list(headers)
        self.rows = [dict(r) for r in rows]
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role not in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
        ):
            return None
        value = self.rows[index.row()].get(self.headers[index.column()])
        if value is None:
            return ""
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.headers):
                return self.headers[section]
        return None
