"""Maintenance tools: database info, integrity, vacuum, rebuild, backups."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import config, services
from ...auth import AuthService
from ...db import Database, DatabaseError
from .. import dialogs, style
from ..workers import run_task


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.1f} {unit}" if unit != "B" else f"{int(value):,} B"
        value /= 1024
    return f"{value:,.1f} GB"


class ToolsPage(QWidget):
    rebuilt = Signal()
    restored = Signal()

    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.db = db

        self.info_rows: dict[str, QLabel] = {}
        info_card = self._card("Database file")
        info_layout = info_card.layout()
        for key in (
            "path",
            "size",
            "page_size",
            "page_count",
            "freelist",
            "journal",
            "encoding",
        ):
            row = QHBoxLayout()
            row.setSpacing(10)
            name = QLabel({
                "path": "Path",
                "size": "Size",
                "page_size": "Page size",
                "page_count": "Pages",
                "freelist": "Free pages",
                "journal": "Journal mode",
                "encoding": "Encoding",
            }[key])
            name.setMinimumWidth(110)
            name.setObjectName("muted")
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            row.addWidget(name)
            row.addWidget(value, 1)
            info_layout.addLayout(row)
            self.info_rows[key] = value

        self.integrity_label = QLabel("Not checked yet.")
        self.integrity_label.setObjectName("muted")
        self.integrity_label.setWordWrap(True)

        self.check_btn = QPushButton("Integrity check")
        self.vacuum_btn = QPushButton("VACUUM")
        self.checkpoint_btn = QPushButton("WAL checkpoint")
        self.rebuild_btn = QPushButton("Rebuild from CSV...")
        self.rebuild_btn.setObjectName("danger")
        maintenance = QHBoxLayout()
        maintenance.setSpacing(8)
        maintenance.addWidget(self.check_btn)
        maintenance.addWidget(self.vacuum_btn)
        maintenance.addWidget(self.checkpoint_btn)
        maintenance.addStretch(1)
        maintenance.addWidget(self.rebuild_btn)

        maint_card = self._card("Maintenance")
        maint_layout = maint_card.layout()
        hint = QLabel(
            "Integrity check validates every page, VACUUM reclaims free pages, "
            "and 'Rebuild from CSV' recreates the database from "
            f"{config.source_csv().name} (all edits are lost)."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        maint_layout.addWidget(hint)
        maint_layout.addLayout(maintenance)
        maint_layout.addWidget(self.integrity_label)

        self.backup_table = QTableWidget(0, 3)
        self.backup_table.setHorizontalHeaderLabels(["Backup file", "Size", "Modified"])
        self.backup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.backup_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.backup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backup_table.setAlternatingRowColors(True)
        self.backup_table.verticalHeader().setVisible(False)
        header = self.backup_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self.create_btn = QPushButton("Create backup")
        self.create_btn.setObjectName("primary")
        self.restore_btn = QPushButton("Restore selected")
        self.delete_btn = QPushButton("Delete selected")
        self.delete_btn.setObjectName("danger")
        self.open_folder_btn = QPushButton("Open folder")
        backup_actions = QHBoxLayout()
        backup_actions.setSpacing(8)
        backup_actions.addWidget(self.create_btn)
        backup_actions.addWidget(self.restore_btn)
        backup_actions.addWidget(self.delete_btn)
        backup_actions.addStretch(1)
        backup_actions.addWidget(self.open_folder_btn)

        backup_card = self._card("Backups")
        backup_layout = backup_card.layout()
        backup_layout.addWidget(self.backup_table, 1)
        backup_layout.addLayout(backup_actions)
        self.backup_count_label = QLabel("")
        self.backup_count_label.setObjectName("muted")
        backup_layout.addWidget(self.backup_count_label)

        self.audit_table = QTableWidget(0, 5)
        self.audit_table.setHorizontalHeaderLabels(
            ["When", "User", "Action", "Entity", "Detail"]
        )
        self.audit_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.audit_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.audit_table.setAlternatingRowColors(True)
        self.audit_table.verticalHeader().setVisible(False)
        audit_header = self.audit_table.horizontalHeader()
        audit_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        audit_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        audit_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        audit_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        audit_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        audit_card = self._card("Audit log (recent changes)")
        audit_layout = audit_card.layout()
        audit_layout.addWidget(self.audit_table, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*style.PAGE_MARGINS)
        layout.setSpacing(12)
        layout.addWidget(info_card)
        layout.addWidget(maint_card)
        layout.addWidget(backup_card)
        layout.addWidget(audit_card, 1)

        self.check_btn.clicked.connect(self.check_integrity)
        self.vacuum_btn.clicked.connect(self.vacuum)
        self.checkpoint_btn.clicked.connect(self.checkpoint)
        self.rebuild_btn.clicked.connect(self.rebuild)
        self.create_btn.clicked.connect(self.create_backup)
        self.restore_btn.clicked.connect(self.restore_backup)
        self.delete_btn.clicked.connect(self.delete_backup)
        self.open_folder_btn.clicked.connect(self.open_backup_folder)

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _card(title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 8, 14, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("subtitle")
        layout.addWidget(label)
        return card

    def refresh(self) -> None:
        self.load_info()
        self.load_backups()
        self.load_audit()

    def load_audit(self) -> None:
        try:
            rows = AuthService(self.db).recent_audit(50)
        except Exception as exc:  # noqa: BLE001 - auth tables may not exist yet
            self.audit_table.setRowCount(0)
            self.audit_table.setToolTip(str(exc))
            return
        self.audit_table.setRowCount(len(rows))
        for row_index, entry in enumerate(rows):
            values = [
                str(entry.get("created_at", "")),
                str(entry.get("username", "")),
                str(entry.get("action", "")),
                f"{entry.get('entity', '')} #{entry.get('entity_id') or ''}",
                str(entry.get("detail", "")),
            ]
            for column, value in enumerate(values):
                self.audit_table.setItem(
                    row_index, column, QTableWidgetItem(value)
                )

    def load_info(self) -> None:
        try:
            info = self.db.file_info()
        except DatabaseError as exc:
            self.info_rows["path"].setText(str(exc))
            return
        self.info_rows["path"].setText(str(info["path"]))
        self.info_rows["size"].setText(_human_size(int(info["size_bytes"])))
        self.info_rows["page_size"].setText(f"{int(info['page_size']):,} bytes")
        self.info_rows["page_count"].setText(f"{int(info['page_count']):,}")
        self.info_rows["freelist"].setText(f"{int(info['freelist_count']):,}")
        self.info_rows["journal"].setText(str(info["journal_mode"]))
        self.info_rows["encoding"].setText(str(info["encoding"]))

    def load_backups(self) -> None:
        backups = services.list_backups()
        self.backup_table.setRowCount(len(backups))
        for row, item in enumerate(backups):
            name_item = QTableWidgetItem(item["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, str(item["path"]))
            size_item = QTableWidgetItem(_human_size(int(item["size_bytes"])))
            when = item["modified"]
            date_item = QTableWidgetItem(when.strftime("%Y-%m-%d %H:%M:%S"))
            self.backup_table.setItem(row, 0, name_item)
            self.backup_table.setItem(row, 1, size_item)
            self.backup_table.setItem(row, 2, date_item)
        noun = "backup" if len(backups) == 1 else "backups"
        self.backup_count_label.setText(
            f"{len(backups)} {noun} in {config.backup_dir()}"
        )
        self.restore_btn.setEnabled(bool(backups))
        self.delete_btn.setEnabled(bool(backups))

    def _selected_backup(self) -> Path | None:
        row = self.backup_table.currentRow()
        if row < 0:
            return None
        item = self.backup_table.item(row, 0)
        raw = item.data(Qt.ItemDataRole.UserRole) if item else None
        return Path(raw) if raw else None

    # -- actions -------------------------------------------------------------
    def check_integrity(self) -> None:
        def task(_progress):
            return self.db.integrity_check()

        def done(result: list[str]) -> None:
            ok = result == ["ok"]
            self.integrity_label.setText(
                "Integrity check passed: every page verified (ok)."
                if ok
                else "Integrity check reported problems:\n" + "\n".join(result)
            )
            style.apply_label_state(self.integrity_label, "success" if ok else "error")

        def failed(message: str) -> None:
            self.integrity_label.setText(f"Check failed: {message}")
            style.apply_label_state(self.integrity_label, "error")

        run_task(
            self,
            "Integrity check",
            "Verifying database pages...",
            task,
            on_success=done,
            on_error=failed,
        )

    def vacuum(self) -> None:
        before = self.db.file_info()["size_bytes"]

        def task(_progress):
            self.db.vacuum()
            return self.db.file_info()["size_bytes"]

        def done(after: int) -> None:
            self.load_info()
            dialogs.info(
                self,
                "VACUUM complete",
                f"Database size: {_human_size(int(before))} -> {_human_size(int(after))}",
            )

        run_task(self, "VACUUM", "Reclaiming unused pages...", task, on_success=done)

    def checkpoint(self) -> None:
        def task(_progress):
            return self.db.wal_checkpoint()

        def done(result: tuple) -> None:
            self.load_info()
            dialogs.info(
                self,
                "WAL checkpoint",
                f"Pages checkpointed: {result[1] if len(result) > 1 else result}",
            )

        run_task(
            self, "WAL checkpoint", "Flushing WAL into the main file...", task,
            on_success=done,
            on_error=lambda msg: dialogs.warn(self, "Checkpoint failed", msg),
        )

    def rebuild(self) -> None:
        if not config.source_csv().exists():
            dialogs.warn(
                self,
                "Rebuild from CSV",
                f"Source CSV not found:\n{config.source_csv()}",
            )
            return
        if not dialogs.confirm(
            self,
            "Rebuild from CSV",
            "This DROPS every table and recreates the database from the CSV.\n"
            "All changes made in this application will be lost.\n\nContinue?",
        ):
            return

        def task(progress):
            return services.rebuild_database(self.db, progress=progress)

        def done(stats: dict) -> None:
            self.load_info()
            dialogs.info(
                self,
                "Rebuild finished",
                "Reloaded {medicines:,} medicines, {manufacturers:,} manufacturers "
                "and {compositions:,} compositions.".format(**stats),
            )
            self.rebuilt.emit()

        run_task(
            self,
            "Rebuild from CSV",
            f"Importing {config.source_csv().name} ...",
            task,
            on_success=done,
        )

    def create_backup(self) -> None:
        def task(_progress):
            return services.create_backup(self.db)

        def done(path: Path) -> None:
            self.load_backups()
            dialogs.info(self, "Backup created", f"Saved to\n{path}")

        run_task(self, "Backup", "Copying database pages...", task, on_success=done)

    def restore_backup(self) -> None:
        source = self._selected_backup()
        if source is None:
            dialogs.info(self, "Restore", "Select a backup to restore.")
            return
        if not dialogs.confirm(
            self,
            "Restore backup",
            f"Replace the current database with\n{source.name}?\n"
            "Current data will be lost.",
        ):
            return

        def task(_progress):
            services.restore_backup(self.db, source)
            return True

        def done(_result: bool) -> None:
            self.load_info()
            self.restored.emit()
            dialogs.info(
                self,
                "Restore complete",
                f"The database was replaced with {source.name}.",
            )

        run_task(
            self,
            "Restore backup",
            f"Restoring {source.name} ...",
            task,
            on_success=done,
            on_error=lambda msg: dialogs.warn(self, "Restore failed", msg),
        )

    def delete_backup(self) -> None:
        source = self._selected_backup()
        if source is None:
            dialogs.info(self, "Delete backup", "Select a backup to delete.")
            return
        if not dialogs.confirm(
            self, "Delete backup", f"Delete {source.name} permanently?"
        ):
            return
        try:
            services.delete_backup(source)
        except OSError as exc:
            dialogs.warn(self, "Delete failed", str(exc))
            return
        self.load_backups()

    def open_backup_folder(self) -> None:
        folder = config.backup_dir()
        folder.mkdir(parents=True, exist_ok=True)
        import os

        os.startfile(str(folder))  # noqa: S606 - Windows shell integration
