"""Dashboard: headline metrics, charts and highlight tables."""
from __future__ import annotations

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalBarSeries,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...db import Database, DatabaseError
from ...repositories import StatsRepository
from .. import style
from ..qtmodels import Column, TableModel
from ..widgets import StatCard, configure_table, fit_columns

PRICE_COLUMNS = [
    Column("ID", align_right=True),
    Column("Medicine"),
    Column("Price \u20b9", align_right=True),
    Column("Manufacturer"),
]
COMPOSITION_COLUMNS = [
    Column("Composition"),
    Column("Used by", align_right=True),
]


def _shorten(text: str, limit: int = 26) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


class DashboardPage(QWidget):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.db = db
        self.repo = StatsRepository(db)
        self._loaded = False

        self.medicines_card = StatCard("Medicines")
        self.manufacturers_card = StatCard("Manufacturers")
        self.compositions_card = StatCard("Compositions")
        self.price_card = StatCard("Average price")

        self.bands_chart = self._chart_host()
        self.pie_chart = self._chart_host()
        self.mfr_chart = self._chart_host()

        self.expensive_model = TableModel(PRICE_COLUMNS, self)
        self.expensive_table = QTableView()
        configure_table(self.expensive_table, self.expensive_model)
        fit_columns(self.expensive_table, stretch=(1, 3), contents=(0, 2), last_stretch=False)
        self.expensive_table.horizontalHeader().setSectionsClickable(False)

        self.composition_model = TableModel(COMPOSITION_COLUMNS, self)
        self.composition_table = QTableView()
        configure_table(self.composition_table, self.composition_model)
        fit_columns(self.composition_table, stretch=(0,), contents=(1,), last_stretch=False)
        self.composition_table.horizontalHeader().setSectionsClickable(False)

        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

        content = QWidget()
        content.setObjectName("page")
        grid = QGridLayout(content)
        grid.setContentsMargins(*style.PAGE_MARGINS)
        grid.setSpacing(12)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        for card in (
            self.medicines_card,
            self.manufacturers_card,
            self.compositions_card,
            self.price_card,
        ):
            cards.addWidget(card, 1)

        grid.addLayout(cards, 0, 0, 1, 2)
        grid.addWidget(self._section("Price distribution (\u20b9)", self.bands_chart), 1, 0)
        grid.addWidget(self._section("Composition mix", self.pie_chart), 1, 1)
        grid.addWidget(self._section("Top manufacturers by product count", self.mfr_chart), 2, 0)
        grid.addWidget(self._section("Most expensive medicines", self.expensive_table), 2, 1)
        grid.addWidget(self._section("Most used compositions", self.composition_table), 3, 0)
        grid.addWidget(self.status_label, 3, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 360)
        grid.setColumnMinimumWidth(1, 360)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _chart_host() -> QChartView:
        view = QChartView()
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(250)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        view.setChart(QChart())
        return view

    def _section(self, title: str, widget: QWidget) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        # Let the grid's stretch factors decide the column widths instead of
        # the (large) size hints of tables and charts.
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("subtitle")
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return frame

    def _mode(self) -> str:
        return style.current_mode()

    def _axis_styles(self, axis: QValueAxis | QBarCategoryAxis) -> None:
        color = QColor(style.THEMES[self._mode()]["text_dim"])
        axis.setLabelsBrush(QBrush(color))
        axis.setLinePenColor(color)
        axis.setGridLineColor(QColor(style.THEMES[self._mode()]["border"]))
        axis.setTitleBrush(QBrush(color))

    def _build_bar_chart(
        self,
        categories: list[str],
        values: list[int],
        color: str,
        horizontal: bool = False,
    ) -> QChart:
        chart = QChart()
        chart.setBackgroundVisible(False)
        bar_set = QBarSet("count")
        bar_set.setColor(QColor(color))
        bar_set.append([float(v) for v in values])
        series = QHorizontalBarSeries() if horizontal else QBarSeries()
        series.append(bar_set)
        chart.addSeries(series)

        cat_axis = QBarCategoryAxis()
        cat_axis.append(categories)
        value_axis = QValueAxis()
        value_axis.setLabelFormat("%d")
        if horizontal:
            chart.addAxis(cat_axis, Qt.AlignmentFlag.AlignLeft)
            chart.addAxis(value_axis, Qt.AlignmentFlag.AlignBottom)
        else:
            chart.addAxis(cat_axis, Qt.AlignmentFlag.AlignBottom)
            chart.addAxis(value_axis, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(cat_axis)
        series.attachAxis(value_axis)
        self._axis_styles(cat_axis)
        self._axis_styles(value_axis)
        chart.legend().setVisible(False)
        return chart

    def _build_pie_chart(self, slices: list[tuple[str, int]]) -> QChart:
        chart = QChart()
        chart.setBackgroundVisible(False)
        series = QPieSeries()
        series.setPieSize(0.85)
        colors = style.chart_colors(self._mode())
        for index, (label, value) in enumerate(slices):
            if value <= 0:
                continue
            short = label.split()[0] if label else label
            slice_ = series.append(short, float(value))
            slice_.setColor(QColor(colors[index % len(colors)]))
            # Call-out labels would stretch the layout: keep the chart compact
            # and show the numbers in the legend instead.
            slice_.setLabelVisible(False)
            slice_.setLabel(f"{short} ({value:,})")
        chart.addSeries(series)
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        return chart
    # -- data ----------------------------------------------------------------
    def refresh(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        try:
            counts = self.repo.counts()
            price = self.repo.price_summary()
            bands = self.repo.price_bands()
            split = self.repo.composition_split()
            top_mfr = self.repo.top_manufacturers(10)
            expensive = self.repo.most_expensive(10)
            used = self.repo.most_used_compositions(12)
        except DatabaseError as exc:
            style.apply_label_state(self.status_label, "error")
            self.status_label.setText(f"Dashboard unavailable: {exc}")
            return

        self.medicines_card.set_value(f"{counts['medicines']:,}", "rows in medicines")
        self.manufacturers_card.set_value(f"{counts['manufacturers']:,}", "unique makers")
        self.compositions_card.set_value(f"{counts['compositions']:,}", "unique compositions")
        self.price_card.set_value(
            config.format_money(price["avg"]),
            f"min {config.format_money(price['min'])} / "
            f"max {config.format_money(price['max'])}",
        )

        mode_colors = style.chart_colors(self._mode())
        bands_chart = self._build_bar_chart(
            [label for label, _count in bands],
            [count for _label, count in bands],
            mode_colors[0],
        )
        self.bands_chart.setChart(bands_chart)

        pie = self._build_pie_chart(split)
        self.pie_chart.setChart(pie)

        mfr_chart = self._build_bar_chart(
            [_shorten(name) for name, _n in top_mfr],
            [n for _name, n in top_mfr],
            mode_colors[1],
            horizontal=True,
        )
        self.mfr_chart.setChart(mfr_chart)

        self.expensive_model.set_rows(expensive)
        self.composition_model.set_rows(used)

        self.status_label.setObjectName("muted")
        self.status_label.setText(
            f"Database: {self.db.path}  |  refreshed on tab activation "
            "- use Refresh to update."
        )
        self._loaded = True
