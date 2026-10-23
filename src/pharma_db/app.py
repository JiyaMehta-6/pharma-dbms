"""Application bootstrap: settings, database resolution, main window."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from . import config, services
from .auth import AuthError, AuthService, User
from .db import Database
from .gui import dialogs, style
from .gui.main_window import MainWindow
from .gui.workers import run_task


def _choose_db_path(settings: QSettings) -> Path:
    stored = settings.value("ui/db_path")
    if stored:
        candidate = Path(str(stored)).expanduser()
        if candidate.is_file():
            return candidate
    default = config.resolve_db_path()
    if default.is_file():
        return default
    return default


def _ensure_database(app: QApplication) -> Path | None:
    """Return a usable database path, offering to build one when missing."""
    path = _choose_db_path(QSettings())
    if path.is_file():
        return path

    csv = config.source_csv()
    if not csv.exists():
        QMessageBox.critical(
            None,
            config.APP_NAME,
            f"No database and no source CSV found.\n\n"
            f"Expected database: {path}\nExpected CSV: {csv}",
        )
        return None

    answer = QMessageBox.question(
        None,
        config.APP_NAME,
        f"The database is missing:\n{path}\n\n"
        f"Build it now from\n{csv}?\n\n"
        "Importing the catalogue takes a moment.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return None

    db = Database(path)

    def task(progress):
        return services.rebuild_database(db, progress=progress)

    result = run_task(
        None,
        "Building database",
        f"Importing {csv.name} ...",
        task,
        on_error=lambda message: QMessageBox.critical(None, "Build failed", message),
    )
    if result is None:
        return None
    db.close()
    return path


def _login(db: Database) -> User | None:
    """Prompt for credentials, bootstrapping an admin when no users exist."""
    auth = AuthService(db)
    try:
        needs_bootstrap = auth.user_count() == 0
    except Exception:  # noqa: BLE001 - treat unusable auth tables as bootstrap
        needs_bootstrap = True

    while True:
        credentials = dialogs.ask_login(None, needs_bootstrap)
        if credentials is None:
            return None
        username, password = credentials
        try:
            if needs_bootstrap:
                auth.create_user(username, password, role="admin")
                return auth.authenticate(username, password)
            return auth.authenticate(username, password)
        except (AuthError, Exception) as exc:  # noqa: BLE001 - surface any failure
            dialogs.warn(None, "Sign in failed", str(exc))
            needs_bootstrap = auth.user_count() == 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    app = QApplication(args)
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.APP_ORG)
    app.setApplicationVersion(config.APP_VERSION)

    settings = QSettings()
    style.apply_theme(app, str(settings.value("ui/theme", "light")))

    db_path = _ensure_database(app)
    if db_path is None:
        return 1

    db = Database(db_path)
    services.migrate(db)
    user = _login(db)
    if user is None:
        db.close()
        return 1
    window = MainWindow(db, user=user)
    window.show()
    try:
        code = app.exec()
    finally:
        db.close()
    return int(code)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
