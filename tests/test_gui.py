"""Offscreen GUI smoke test: every tab builds and reacts to the fixture DB."""
from __future__ import annotations

import unittest

from tests.support import TempDbTestCase, get_qapp

try:

    from pharma_db import config
    from pharma_db.gui import style
    from pharma_db.gui.main_window import MainWindow
    from pharma_db.gui.widgets import PaginationBar

    HAS_QT = True
except Exception:  # noqa: BLE001 - pragma: no cover
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 unavailable")
class MainWindowSmokeTest(TempDbTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.app = get_qapp()
        # Isolate persisted settings so the theme test doesn't collide with a
        # real user profile or leftovers from another test run.
        cls.app.setApplicationName(config.APP_NAME + " Tests")
        cls.app.setOrganizationName(config.APP_ORG + "-tests")
        style.apply_theme(cls.app, "light")
        cls.window = MainWindow(cls.db)
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.window.db.close()
        cls.window.deleteLater()
        cls.app.processEvents()
        super().tearDownClass()

    def test_all_tabs_present(self) -> None:
        labels = [self.window.tabs.tabText(i) for i in range(self.window.tabs.count())]
        self.assertEqual(
            labels,
            [
                "Dashboard",
                "Medicines",
                "Manufacturers",
                "Compositions",
                "Schema",
                "SQL Console",
                "Tools",
            ],
        )

    def test_title_shows_database_name(self) -> None:
        self.assertIn("test.db", self.window.windowTitle())

    def test_dashboard_populates(self) -> None:
        page = self.window.dashboard
        self.window.tabs.setCurrentWidget(page)
        page.refresh(force=True)
        self.app.processEvents()
        self.assertEqual(page.medicines_card.value_label.text(), "10")
        self.assertEqual(page.manufacturers_card.value_label.text(), "4")
        self.assertEqual(page.compositions_card.value_label.text(), "12")
        self.assertEqual(page.expensive_model.rowCount(), 10)
        self.assertEqual(page.expensive_model.row_at(0)[1], "Theta 1000")
        self.assertEqual(page.composition_model.rowCount(), 12)

    def test_medicines_search_sort_and_page(self) -> None:
        page = self.window.medicines
        self.window.tabs.setCurrentWidget(page)
        page.refresh()
        self.assertEqual(page.pager.total, 10)
        self.assertEqual(len(page.model.rows), 10)

        page.search_edit.setText("paracetamol")
        page.apply_filters()
        self.assertEqual(page.pager.total, 5)
        self.assertEqual(len(page.model.rows), 5)

        page.search_edit.clear()
        page.apply_filters()
        page.pager.set_page_size(4)  # emits pageSizeRequested -> refresh
        page.pager.goto(2)
        page.refresh()
        self.assertEqual(page.pager.page, 2)
        self.assertEqual(len(page.model.rows), 4)

        page._on_header_clicked(2)  # price_rs
        self.assertEqual(page.request.order_by, "price_rs")
        self.assertTrue(page.request.descending)
        prices = [row[2] for row in page.model.rows]
        self.assertEqual(prices, sorted(prices, reverse=True))

        page.reset_filters()
        page.pager.set_page_size(100)
        self.assertEqual(page.pager.total, 10)
        self.assertEqual(len(page.model.rows), 10)

    def test_manufacturers_and_compositions_refresh(self) -> None:
        mfrs = self.window.manufacturers
        self.window.tabs.setCurrentWidget(mfrs)
        mfrs.refresh()
        self.assertEqual(mfrs.model.rowCount(), 4)

        comps = self.window.compositions
        self.window.tabs.setCurrentWidget(comps)
        comps.refresh()
        self.assertEqual(comps.model.rowCount(), 12)

    def test_schema_page_lists_objects(self) -> None:
        page = self.window.schema
        self.window.tabs.setCurrentWidget(page)
        page.refresh()
        self.app.processEvents()
        self.assertGreater(page.tree.topLevelItemCount(), 0)
        tables = page.tree.topLevelItem(0)
        self.assertEqual(tables.text(0), "Tables")
        self.assertGreater(tables.childCount(), 0)
        # refresh() auto-selects the first table, which overwrites info_label
        # with the per-object summary.
        self.assertIn("column(s)", page.info_label.text())

    def test_console_runs_sql(self) -> None:
        page = self.window.console
        self.window.tabs.setCurrentWidget(page)
        page.editor.setPlainText("SELECT COUNT(*) AS n FROM medicines;")
        page.run()
        self.app.processEvents()
        self.assertIn("1 row(s)", page.status_label.text())
        self.assertEqual(page.result_model.row_at(0)[0], 10)

    def test_console_error_does_not_crash(self) -> None:
        page = self.window.console
        page.editor.setPlainText("SELECT * FROM no_such_table;")
        page.run()
        self.app.processEvents()
        self.assertIn("stopped at first error", page.status_label.text())
        self.assertGreater(page.message_list.count(), 0)
        page.clear()

    @property
    def _settings(self):
        return self.window._settings

    def test_theme_roundtrip(self) -> None:
        self.window.set_theme("dark")
        self.app.processEvents()
        self._settings.sync()
        self.assertEqual(self._settings.value("ui/theme"), "dark")
        self.window.set_theme("light")
        self.app.processEvents()
        self._settings.sync()
        self.assertEqual(self._settings.value("ui/theme"), "light")


@unittest.skipUnless(HAS_QT, "PySide6 unavailable")
class PaginationBarTest(unittest.TestCase):
    def test_pagination_logic(self) -> None:
        app = get_qapp()
        bar = PaginationBar()
        events: list[int] = []
        bar.pageRequested.connect(events.append)

        bar.set_page_size(50)
        bar.set_total(95)
        self.assertEqual(bar.page_count, 2)
        self.assertEqual(bar.page, 1)
        self.assertEqual(bar.offset, 0)

        bar.goto(2)
        self.assertEqual(events[-1], 2)
        self.assertEqual(bar.page, 2)
        self.assertEqual(bar.offset, 50)

        bar.set_total(10, keep_page=True)
        self.assertEqual(bar.page, 1)  # clamped back to the single page

        bar.goto(0)
        self.assertEqual(bar.page, 1)
        bar.goto(999)
        self.assertEqual(bar.page, 1)
        del app


if __name__ == "__main__":
    unittest.main()
