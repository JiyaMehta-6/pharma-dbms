"""Qt themes (light / dark) applied to the whole application."""
from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#eef1f6",
        "surface": "#ffffff",
        "surface_alt": "#f6f8fb",
        "border": "#d5dbe5",
        "text": "#1b2430",
        "text_dim": "#5b6b7f",
        "accent": "#1d63d1",
        "accent_hover": "#1751ad",
        "accent_text": "#ffffff",
        "danger": "#c0392b",
        "success": "#1f8a4c",
        "warn": "#b7791f",
        "input_bg": "#ffffff",
        "sel_bg": "#d7e5fb",
        "sel_text": "#101828",
        "chart1": "#1d63d1",
        "chart2": "#f39c12",
        "chart3": "#27ae60",
        "chart4": "#8e44ad",
        "chart5": "#e74c3c",
        "chart6": "#16a5c8",
    },
    "dark": {
        "bg": "#0f141b",
        "surface": "#171e27",
        "surface_alt": "#1d2632",
        "border": "#2c3846",
        "text": "#e6edf5",
        "text_dim": "#93a3b5",
        "accent": "#4d90f0",
        "accent_hover": "#6aa5f5",
        "accent_text": "#08111f",
        "danger": "#ef6c60",
        "success": "#4cc38a",
        "warn": "#e0a458",
        "input_bg": "#111823",
        "sel_bg": "#26405f",
        "sel_text": "#f2f7ff",
        "chart1": "#4d90f0",
        "chart2": "#f0a742",
        "chart3": "#4cc38a",
        "chart4": "#b07ce8",
        "chart5": "#ef6c60",
        "chart6": "#3ec6e0",
    },
}

CHART_KEYS = ("chart1", "chart2", "chart3", "chart4", "chart5", "chart6")

PAGE_MARGINS = (16, 8, 16, 8)


def chart_colors(mode: str) -> list[str]:
    palette = THEMES.get(mode, THEMES["light"])
    return [palette[key] for key in CHART_KEYS]


LABEL_STATES = {
    "error": "danger",
    "success": "success",
    "muted": "text_dim",
    "text": "text",
}


def apply_label_state(label: Any, state: str | None) -> None:
    """Colour a QLabel after construction (objectName changes are not restyled)."""
    if state is None:
        label.setStyleSheet("")
        return
    key = LABEL_STATES.get(state, "text")
    color = THEMES[current_mode()].get(key, "#000000")
    label.setStyleSheet(f"color: {color};")


def current_mode(app: QApplication | None = None) -> str:
    app = app or QApplication.instance()
    if app is None:
        return "light"
    return str(app.property("pharma_theme") or "light")


def apply_theme(app: QApplication, mode: str) -> str:
    mode = mode if mode in THEMES else "light"
    c = THEMES[mode]
    app.setProperty("pharma_theme", mode)
    app.setStyle("Fusion")
    app.setPalette(_palette(c))
    app.setStyleSheet(_qss(c))
    return mode


def _qss(c: dict[str, str]) -> str:
    return f"""
    QWidget {{
        color: {c['text']};
        font-size: 13px;
    }}
    QMainWindow, QDialog {{ background: {c['bg']}; }}
    QWidget#page {{ background: {c['bg']}; }}

    QLabel#title {{ font-size: 19px; font-weight: 700; }}
    QLabel#subtitle {{ color: {c['text_dim']}; font-size: 12px; }}
    QLabel#muted {{ color: {c['text_dim']}; }}
    QLabel#error {{ color: {c['danger']}; }}
    QLabel#success {{ color: {c['success']}; }}
    QLabel#statValue {{ font-size: 24px; font-weight: 700; }}
    QLabel#statLabel {{ color: {c['text_dim']}; font-size: 12px; }}

    QFrame#card, QWidget#card, QGroupBox {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        margin-top: 14px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {c['text_dim']};
        font-weight: 600;
    }}

    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {c['input_bg']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 5px 8px;
        selection-background-color: {c['sel_bg']};
        selection-color: {c['sel_text']};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
    QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border: 1px solid {c['accent']};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        selection-background-color: {c['sel_bg']};
        selection-color: {c['sel_text']};
        outline: none;
    }}

    QPushButton {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 6px 14px;
        min-height: 20px;
    }}
    QPushButton:hover {{ background: {c['surface_alt']}; border-color: {c['accent']}; }}
    QPushButton:pressed {{ background: {c['bg']}; }}
    QPushButton:disabled {{ color: {c['text_dim']}; background: {c['surface_alt']}; }}
    QPushButton#primary {{
        background: {c['accent']};
        color: {c['accent_text']};
        border: 1px solid {c['accent']};
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
    QPushButton#danger {{ color: {c['danger']}; border-color: {c['danger']}; }}
    QPushButton#danger:hover {{ background: {c['danger']}; color: {c['accent_text']}; }}
    QPushButton#flat {{ background: transparent; border: none; }}
    QPushButton#flat:hover {{ background: {c['surface_alt']}; border-radius: 6px; }}

    QTableView, QTreeView, QListView, QListWidget, QTreeWidget {{
        background: {c['surface']};
        alternate-background-color: {c['surface_alt']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        gridline-color: {c['border']};
        selection-background-color: {c['sel_bg']};
        selection-color: {c['sel_text']};
        outline: none;
    }}
    QTableView::item, QTreeView::item, QListView::item {{ padding: 3px 4px; }}
    QHeaderView::section {{
        background: {c['surface_alt']};
        color: {c['text_dim']};
        border: none;
        border-right: 1px solid {c['border']};
        border-bottom: 1px solid {c['border']};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QHeaderView::section:hover {{ color: {c['text']}; background: {c['sel_bg']}; }}

    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: 8px;
        background: {c['surface']};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {c['text_dim']};
        padding: 8px 16px;
        margin-right: 4px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
    }}
    QTabBar::tab:selected {{
        background: {c['surface']};
        color: {c['accent']};
        border: 1px solid {c['border']};
        border-bottom: none;
        font-weight: 600;
    }}
    QTabBar::tab:hover:!selected {{ color: {c['text']}; }}

    QMenuBar {{
        background: {c['surface']};
        border-bottom: 1px solid {c['border']};
        padding: 2px 6px;
    }}
    QMenuBar::item:selected {{ background: {c['sel_bg']}; border-radius: 4px; }}
    QMenu {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        padding: 4px;
    }}
    QMenu::item {{ padding: 6px 26px 6px 14px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c['sel_bg']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}

    QToolBar {{
        background: {c['surface']};
        border: none;
        border-bottom: 1px solid {c['border']};
        spacing: 6px;
        padding: 4px 8px;
    }}
    QStatusBar {{
        background: {c['surface']};
        border-top: 1px solid {c['border']};
        color: {c['text_dim']};
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border']};
        border-radius: 6px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 12px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {c['border']};
        border-radius: 6px;
        min-width: 30px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSplitter::handle {{ background: {c['border']}; }}
    QSplitter::handle:horizontal {{ width: 2px; }}
    QSplitter::handle:vertical {{ height: 2px; }}

    QProgressBar {{
        background: {c['surface_alt']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        height: 14px;
        text-align: center;
    }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}

    QCheckBox {{ spacing: 6px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['border']};
        border-radius: 4px; background: {c['input_bg']}; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}

    QToolTip {{
        background: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border']};
        padding: 4px 6px;
    }}
    QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px;
        background: {c['accent']}; }}
    """


def _palette(c: dict[str, str]) -> QPalette:
    def role(name: str) -> QColor:
        return QColor(c[name])

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, role("bg"))
    palette.setColor(QPalette.ColorRole.WindowText, role("text"))
    palette.setColor(QPalette.ColorRole.Base, role("surface"))
    palette.setColor(QPalette.ColorRole.AlternateBase, role("surface_alt"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, role("surface"))
    palette.setColor(QPalette.ColorRole.ToolTipText, role("text"))
    palette.setColor(QPalette.ColorRole.Text, role("text"))
    palette.setColor(QPalette.ColorRole.Button, role("surface"))
    palette.setColor(QPalette.ColorRole.ButtonText, role("text"))
    palette.setColor(QPalette.ColorRole.BrightText, role("danger"))
    palette.setColor(QPalette.ColorRole.Link, role("accent"))
    palette.setColor(QPalette.ColorRole.Highlight, role("sel_bg"))
    palette.setColor(QPalette.ColorRole.HighlightedText, role("sel_text"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, role("text_dim"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, role("text_dim"))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, role("text_dim")
    )
    return palette
