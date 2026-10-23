"""Run blocking work off the GUI thread behind a modal busy dialog."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QEventLoop, QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

ProgressFn = Callable[[str, int, int], None]


class FunctionWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int)

    def __init__(self, fn: Callable[[ProgressFn], Any]) -> None:
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn(self._emit_progress)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(result)

    def _emit_progress(self, stage: str, done: int, total: int) -> None:
        self.progress.emit(stage, int(done), int(total))


class BusyDialog(QDialog):
    """Indeterminate progress dialog with a live status line."""

    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setModal(True)
        self.setMinimumWidth(420)

        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("muted")
        self.detail_label.setWordWrap(True)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.setVisible(False)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(self.message_label)
        layout.addWidget(self.bar)
        layout.addWidget(self.detail_label)
        layout.addWidget(buttons)

    def set_status(self, stage: str, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(min(100, int(done * 100 / total)))
        else:
            self.bar.setRange(0, 0)
        text = stage
        if done or total:
            text = f"{stage} - {done:,}" + (f" / {total:,}" if total else "")
        self.detail_label.setText(text)


def run_task(
    parent: QWidget | None,
    title: str,
    message: str,
    fn: Callable[[ProgressFn], Any],
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_progress: ProgressFn | None = None,
) -> Any:
    """Execute ``fn(progress)`` in a thread; block with a modal busy dialog.

    The nested event loop keeps the UI alive, application modality prevents
    re-entrant access to the database while ``fn`` runs.  Returns the task
    result, or ``None`` when it failed.
    """
    from PySide6.QtWidgets import QApplication

    dialog = BusyDialog(title, message, parent)
    thread = QThread()
    worker = FunctionWorker(fn)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    result_box: dict[str, Any] = {"result": None, "error": None}

    def handle_progress(stage: str, done: int, total: int) -> None:
        dialog.set_status(stage, done, total)
        if on_progress is not None:
            on_progress(stage, done, total)

    def handle_success(result: Any) -> None:
        result_box["result"] = result
        loop.quit()

    def handle_error(message: str) -> None:
        result_box["error"] = message
        loop.quit()

    worker.progress.connect(handle_progress)
    worker.finished.connect(handle_success)
    worker.failed.connect(handle_error)

    loop = QEventLoop()
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    dialog.show()
    thread.start()
    try:
        loop.exec()
    finally:
        thread.quit()
        thread.wait(3000)
        worker.deleteLater()
        thread.deleteLater()
        dialog.hide()
        dialog.deleteLater()
        QApplication.restoreOverrideCursor()

    error = result_box["error"]
    if error is not None:
        if on_error is not None:
            on_error(error)
        elif parent is not None:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(parent, title, error)
        return None

    value = result_box["result"]
    if on_success is not None:
        on_success(value)
    return value
