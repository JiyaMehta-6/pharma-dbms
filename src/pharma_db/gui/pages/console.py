"""SQL console: editor with line numbers, results grid and message log."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import config, services
from ...db import Database, DatabaseError
from ..qtmodels import Column, TableModel
from ..style import PAGE_MARGINS
from ..widgets import configure_table, fit_columns
from ..workers import run_task

MAX_ROWS = 10000


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    """Plain text editor with a line-number gutter and error highlighting."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line_area = LineNumberArea(self)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(11)
        self.setFont(font)
        self.setTabStopDistance(
            self.fontMetrics().horizontalAdvance(" ") * 4
        )
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.blockCountChanged.connect(self._update_margins)
        self.updateRequest.connect(self._update_area)
        self._update_margins()
        self._error_line: int | None = None

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margins(self, *_args) -> None:
        self.setViewportMargins(self.line_number_area_width() + 6, 0, 0, 0)

    def _update_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margins()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_margins()

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(0, 0, 0, 0))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        width = self._line_area.width() - 6
        height = self.fontMetrics().height()
        palette_color = self.palette().color(self.palette().ColorRole.PlaceholderText)
        error_color = QColor("#e05252")
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(
                    error_color
                    if self._error_line == block_number + 1
                    else palette_color
                )
                painter.drawText(
                    0, top, width, height, Qt.AlignmentFlag.AlignRight, number
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1
        painter.end()

    def mark_error_line(self, line: int | None) -> None:
        self._error_line = line
        self.viewport().update()

    def line_for_statement(self, sql: str) -> int | None:
        head = sql.strip().splitlines()[0][:60] if sql.strip() else ""
        if not head:
            return None
        for index, text in enumerate(self.toPlainText().splitlines(), start=1):
            if head in text:
                return index
        return None


class SqlConsolePage(QWidget):
    refreshed = Signal(int)

    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.db = db
        self._last_select: tuple[str, tuple] | None = None

        self.editor = CodeEditor()
        self.editor.setPlaceholderText(
            "Write SQL here, e.g.\n"
            "SELECT * FROM v_medicines_dtl WHERE name LIKE '%cet%' LIMIT 50;\n\n"
            "F5 or Ctrl+Enter runs the script."
        )
        self.editor.setPlainText(
            "-- Pharma DBMS SQL console  (F5 / Ctrl+Enter to run)\n"
            "SELECT COUNT(*) AS medicines FROM medicines;\n"
            "SELECT manufacturer_name, COUNT(*) AS products\n"
            "FROM medicines m JOIN manufacturers mf USING (manufacturer_id)\n"
            "GROUP BY manufacturer_id ORDER BY products DESC LIMIT 10;\n"
        )

        self.run_btn = QPushButton("Run  (F5)")
        self.run_btn.setObjectName("primary")
        self.clear_btn = QPushButton("Clear")
        self.load_btn = QPushButton("Open SQL...")
        self.save_btn = QPushButton("Save SQL...")
        self.export_btn = QPushButton("Export result...")
        self.export_btn.setEnabled(False)
        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("muted")

        self.result_model = TableModel([], self)
        self.result_table = QTableView()
        configure_table(self.result_table, self.result_model)
        self.result_table.horizontalHeader().setSectionsClickable(False)

        self.message_list = QListWidget()
        self.message_list.setAlternatingRowColors(True)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.result_table, "Results")
        self.tabs.addTab(self.message_list, "Messages")

        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        top_bar.addWidget(self.run_btn)
        top_bar.addWidget(self.clear_btn)
        top_bar.addStretch(1)
        top_bar.addWidget(self.load_btn)
        top_bar.addWidget(self.save_btn)
        top_bar.addWidget(self.export_btn)

        editor_wrap = QWidget()
        editor_layout = QVBoxLayout(editor_wrap)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addWidget(self.editor, 1)

        bottom_wrap = QWidget()
        bottom_layout = QVBoxLayout(bottom_wrap)
        bottom_layout.setContentsMargins(0, 8, 0, 0)
        bottom_layout.addWidget(self.tabs, 1)
        bottom_layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(editor_wrap)
        splitter.addWidget(bottom_wrap)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([340, 260])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(8)
        layout.addLayout(top_bar)
        layout.addWidget(splitter, 1)

        self.run_btn.clicked.connect(self.run)
        self.clear_btn.clicked.connect(self.clear)
        self.load_btn.clicked.connect(self.load_sql)
        self.save_btn.clicked.connect(self.save_sql)
        self.export_btn.clicked.connect(self.export_result)
        QShortcut(QKeySequence("F5"), self, activated=self.run)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.run)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.run)

    # -- actions -------------------------------------------------------------
    def clear(self) -> None:
        self.editor.clear()
        self.result_model.clear()
        self.message_list.clear()
        self.status_label.setText("Ready.")
        self._last_select = None
        self.export_btn.setEnabled(False)
        self.editor.mark_error_line(None)

    def run(self) -> None:
        script = self.editor.toPlainText()
        if not script.strip():
            self.status_label.setText("Nothing to run.")
            return

        def task(progress):
            return services.run_script(self.db, script, MAX_ROWS, progress)

        results = run_task(
            self,
            "Running SQL",
            "Executing statements...",
            task,
            on_error=lambda message: self._show_error(message),
        )
        if results is None:
            return
        self._present(results)

    def _show_error(self, message: str) -> None:
        self.message_list.clear()
        item = QListWidgetItem(f"ERROR: {message}")
        item.setForeground(QColor("#e05252"))
        self.message_list.addItem(item)
        self.status_label.setText("Failed.")
        if isinstance(message, DatabaseError):
            self.editor.mark_error_line(None)

    def _present(self, results: list[services.StatementResult]) -> None:
        self.message_list.clear()
        total_rows = 0
        total_time = 0.0
        failed = False
        shown_result = None
        for index, result in enumerate(results, start=1):
            total_time += result.elapsed
            head = " ".join(result.sql.split())[:80]
            if result.error:
                failed = True
                line = result.sql
                message = f"{index}. ERROR: {result.error}\n   > {head}"
                item = QListWidgetItem(message)
                item.setForeground(QColor("#e05252"))
                self.message_list.addItem(item)
                self.editor.mark_error_line(self.editor.line_for_statement(line))
                break
            text = f"{index}. {result.message} in {result.elapsed * 1000:.1f} ms - {head}"
            item = QListWidgetItem(text)
            if result.rows:
                total_rows += len(result.rows)
                shown_result = result
            self.message_list.addItem(item)

        if shown_result is not None:
            self.result_model.columns = [
                Column(title, key=title) for title in shown_result.columns
            ]
            self.result_model.set_rows(shown_result.rows)
            fit_columns(self.result_table, stretch=(), contents=tuple(
                range(len(shown_result.columns))
            ))
            self.result_table.resizeColumnsToContents()
            self._last_select = (
                shown_result.sql,
                tuple(),
            )
            self.export_btn.setEnabled(bool(shown_result.columns))
            self.tabs.setCurrentIndex(0)
        else:
            self.result_model.clear()
            self._last_select = None
            self.export_btn.setEnabled(False)
            self.tabs.setCurrentIndex(1)

        status = f"{len(results)} statement(s), {total_rows} row(s), {total_time * 1000:.1f} ms"
        if failed:
            status += " - stopped at first error"
        self.status_label.setText(status)
        if not failed:
            self.editor.mark_error_line(None)
        self.refreshed.emit(total_rows)

    def export_result(self) -> None:
        if self._last_select is None:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export query result", "sql-result.csv", "CSV files (*.csv)"
        )
        if not dest:
            return
        path = Path(dest)
        sql, params = self._last_select

        def task(progress):
            return services.export_result_to_csv(
                self.db.path, sql, params, path, progress
            )

        run_task(
            self,
            "Export to CSV",
            f"Writing result to {path.name}",
            task,
            on_success=lambda count: self.status_label.setText(
                f"Exported {count:,} row(s) to {path}"
            ),
        )

    def load_sql(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self, "Open SQL file", str(config.project_root()), "SQL files (*.sql);;All files (*)"
        )
        if not source:
            return
        self.editor.setPlainText(Path(source).read_text(encoding="utf-8"))

    def save_sql(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save SQL file", "query.sql", "SQL files (*.sql)"
        )
        if not dest:
            return
        Path(dest).write_text(self.editor.toPlainText(), encoding="utf-8")
        self.status_label.setText(f"Saved {dest}")

    def focus_editor(self) -> None:
        self.editor.setFocus()
