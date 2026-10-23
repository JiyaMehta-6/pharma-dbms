"""Capture README screenshots from the real database (real Win32 platform)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
# Use the real platform so fonts render; offscreen gives tofu boxes.

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pharma_db import config  # noqa: E402
from pharma_db.auth import User  # noqa: E402
from pharma_db.db import Database  # noqa: E402
from pharma_db.gui import style  # noqa: E402
from pharma_db.gui.main_window import MainWindow  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    db_path = config.resolve_db_path()
    if not db_path.is_file():
        print(f"database missing: {db_path}")
        return 1

    app = QApplication([])
    app.setApplicationName(config.APP_NAME + " Shots")
    app.setOrganizationName(config.APP_ORG + "-shots")
    QSettings().setValue("ui/theme", "light")
    style.apply_theme(app, "light")

    db = Database(db_path)
    user = User(id=1, username="admin", role="admin")
    window = MainWindow(db, user=user)
    window.resize(1360, 880)
    window.show()

    def pump(ms: int = 400) -> None:
        start = time.monotonic()
        while time.monotonic() - start < ms / 1000:
            app.processEvents()
            time.sleep(0.01)

    window.dashboard.refresh(force=True)
    window.medicines.refresh()
    pump(800)

    shots = [
        ("dashboard", window.dashboard),
        ("medicines", window.medicines),
        ("manufacturers", window.manufacturers),
        ("compositions", window.compositions),
        ("schema", window.schema),
        ("console", window.console),
        ("tools", window.tools),
    ]

    for name, page in shots:
        window.tabs.setCurrentWidget(page)
        if name == "schema":
            window.schema.refresh()
            tables = window.schema.tree.topLevelItem(0)
            if tables is not None:
                for i in range(tables.childCount()):
                    child = tables.child(i)
                    if child.text(0) == "medicines":
                        window.schema.tree.setCurrentItem(child)
                        break
        if name == "console":
            window.console.run()
        if name == "tools":
            window.tools.load_info()
        pump(900)
        app.processEvents()
        pix = window.grab()
        target = OUT / f"{name}.png"
        pix.save(str(target), "PNG")
        print(f"saved {target} ({pix.width()}x{pix.height()})")

    db.close()
    window.deleteLater()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
