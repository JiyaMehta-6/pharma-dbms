"""Main application window: menus, toolbar, tabs and DB file switching."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStyle,
    QTabWidget,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from ..auth import User

from .. import config
from ..db import Database, DatabaseError
from . import style
from .dialogs import confirm, info, warn
from .pages import (
    CompositionsPage,
    DashboardPage,
    ManufacturersPage,
    MedicinesPage,
    SchemaPage,
    SqlConsolePage,
    ToolsPage,
)


class MainWindow(QMainWindow):
    def __init__(self, db: Database, user: "User | None" = None) -> None:
        super().__init__()
        self.db = db
        self.user = user
        self._settings = QSettings()
        self.setWindowTitle(f"{config.APP_NAME} - {self.db.path.name}")
        self.resize(1360, 880)

        self.tabs = QTabWidget()
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)

        self.dashboard = DashboardPage(db, self)
        self.medicines = MedicinesPage(db, self, user=user)
        self.manufacturers = ManufacturersPage(db, self)
        self.compositions = CompositionsPage(db, self)
        self.schema = SchemaPage(db, self)
        self.console = SqlConsolePage(db, self)
        self.tools = ToolsPage(db, self)

        for page, label in (
            (self.dashboard, "Dashboard"),
            (self.medicines, "Medicines"),
            (self.manufacturers, "Manufacturers"),
            (self.compositions, "Compositions"),
            (self.schema, "Schema"),
            (self.console, "SQL Console"),
            (self.tools, "Tools"),
        ):
            self.tabs.addTab(page, label)

        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.path_label = QLabel(str(self.db.path))
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.path_label.setObjectName("muted")
        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        self.statusBar().addPermanentWidget(self.path_label, 1)
        self.statusBar().addPermanentWidget(self.count_label)
        if self.user is not None:
            self.user_label = QLabel(f"{self.user.username} ({self.user.role})")
            self.user_label.setObjectName("muted")
            self.statusBar().addPermanentWidget(self.user_label)

        self.setCentralWidget(self.tabs)
        self._build_menus()
        self._build_toolbar()

        self.tools.rebuilt.connect(self._after_db_change)
        self.tools.restored.connect(self._after_db_change)

        self._activate_current_page()

    # -- chrome --------------------------------------------------------------
    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open database...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_database)
        file_menu.addAction(open_action)

        rebuild_action = QAction("Rebuild from &CSV...", self)
        rebuild_action.triggered.connect(
            lambda: (self.tabs.setCurrentWidget(self.tools), self.tools.rebuild())
        )
        file_menu.addAction(rebuild_action)

        backup_action = QAction("Create &backup now", self)
        backup_action.triggered.connect(
            lambda: (self.tabs.setCurrentWidget(self.tools), self.tools.create_backup())
        )
        file_menu.addAction(backup_action)

        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = self.menuBar().addMenu("&View")
        refresh_action = QAction("&Refresh current tab", self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self.refresh_current)
        view_menu.addAction(refresh_action)

        focus_action = QAction("Focus &search", self)
        focus_action.setShortcut(QKeySequence("Ctrl+F"))
        focus_action.triggered.connect(self.focus_search)
        view_menu.addAction(focus_action)

        console_action = QAction("Focus SQL &console", self)
        console_action.setShortcut(QKeySequence("Ctrl+L"))
        console_action.triggered.connect(lambda: self.tabs.setCurrentWidget(self.console))
        view_menu.addAction(console_action)

        view_menu.addSeparator()
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        for label, mode in (("Light theme", "light"), ("Dark theme", "dark")):
            action = QAction(label, self, checkable=True)
            action.setData(mode)
            action.triggered.connect(lambda _c, m=mode: self.set_theme(m))
            self.theme_group.addAction(action)
            view_menu.addAction(action)
        stored = str(self._settings.value("ui/theme", "light"))
        for action in self.theme_group.actions():
            if action.data() == stored:
                action.setChecked(True)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.about)
        help_menu.addAction(about_action)

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        style_obj = self.style()

        refresh = QAction(
            style_obj.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "Refresh", self
        )
        refresh.triggered.connect(self.refresh_current)
        bar.addAction(refresh)

        search = QAction(
            style_obj.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),
            "Search",
            self,
        )
        search.setShortcut(QKeySequence("Ctrl+F"))
        search.triggered.connect(self.focus_search)
        bar.addAction(search)

        sql = QAction(
            style_obj.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), "SQL", self
        )
        sql.triggered.connect(lambda: self.tabs.setCurrentWidget(self.console))
        bar.addAction(sql)

        open_db = QAction(
            style_obj.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Open DB",
            self,
        )
        open_db.triggered.connect(self.open_database)
        bar.addAction(open_db)

    # -- behaviour -----------------------------------------------------------
    @Slot()
    def _on_tab_changed(self, _index: int) -> None:
        self._activate_current_page()

    def _activate_current_page(self) -> None:
        page = self.tabs.currentWidget()
        if page is None:
            return
        name = self.tabs.tabText(self.tabs.currentIndex())
        if name == "SQL Console":
            return
        refresh = getattr(page, "refresh", None)
        if not callable(refresh):
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if name == "Dashboard":
                refresh(force=True)  # type: ignore[call-arg]
            else:
                refresh()
        except DatabaseError as exc:
            self.statusBar().showMessage(str(exc), 8000)
        finally:
            QApplication.restoreOverrideCursor()

    def refresh_current(self) -> None:
        self._activate_current_page()
        self.statusBar().showMessage("Refreshed", 2500)

    def focus_search(self) -> None:
        page = self.tabs.currentWidget()
        focus = getattr(page, "focus_search", None)
        if callable(focus):
            focus()
        else:
            self.tabs.setCurrentWidget(self.medicines)
            self.medicines.focus_search()

    @Slot()
    def open_database(self) -> None:
        start_dir = str(self.db.path.parent)
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Open SQLite database",
            start_dir,
            "SQLite databases (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.resolve() == self.db.path.resolve():
            return
        try:
            probe = Database(path)
            probe.scalar("SELECT COUNT(*) FROM sqlite_master")
            probe.close()
        except Exception as exc:  # noqa: BLE001
            warn(self, "Cannot open database", f"{path} is not a usable SQLite file:\n{exc}")
            return
        self.db.path = path
        self._settings.setValue("ui/db_path", str(path))
        self.setWindowTitle(f"{config.APP_NAME} - {path.name}")
        self.path_label.setText(str(path))
        self._after_db_change()
        info(self, "Database switched", f"Now using\n{path}")

    def set_theme(self, mode: str) -> None:
        app = QApplication.instance()
        if app is None:
            return
        applied = style.apply_theme(app, mode)  # type: ignore[arg-type]
        self._settings.setValue("ui/theme", applied)
        for action in self.theme_group.actions():
            action.setChecked(action.data() == applied)
        self.dashboard.refresh(force=True)

    def _after_db_change(self) -> None:
        for page in (
            self.dashboard,
            self.medicines,
            self.manufacturers,
            self.compositions,
            self.schema,
            self.tools,
        ):
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception as exc:  # noqa: BLE001
                    self.statusBar().showMessage(str(exc), 8000)
        self.path_label.setText(str(self.db.path))
        self.count_label.setText("")

    def about(self) -> None:
        counts = ""
        try:
            counts = (
                f"{self.db.scalar('SELECT COUNT(*) FROM medicines'):,} medicines, "
                f"{self.db.scalar('SELECT COUNT(*) FROM manufacturers'):,} manufacturers, "
                f"{self.db.scalar('SELECT COUNT(*) FROM compositions'):,} compositions"
            )
        except DatabaseError:
            counts = "database unavailable"
        QMessageBox.about(
            self,
            f"About {config.APP_NAME}",
            f"<b>{config.APP_NAME}</b> {config.APP_VERSION}<br>"
            "Desktop DBMS for the Indian medicine catalogue.<br><br>"
            f"Database: <code>{self.db.path}</code><br>{counts}<br>"
            f"Source CSV: <code>{config.source_csv().name}</code><br>"
            "Built with Python + PySide6 (Qt 6) and SQLite.",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.console.editor.document().isModified():
            if not confirm(
                self,
                "Quit",
                "The SQL console has unsaved edits. Close the application anyway?",
            ):
                event.ignore()
                return
        self.db.close()
        event.accept()
