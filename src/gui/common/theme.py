"""Central Dark Theme palette and QSS stylesheet definitions."""

DARK_THEME = {
    # Base Surfaces
    "window": "#202225",
    "base": "#2d2f33",
    "alternate": "#282a2e",
    "text": "#ffffff",
    "text_secondary": "#a0a0a0",
    # Accents & Interactions
    "accent": "#62a0ea",
    "accent_hover": "#76b4fe",
    "accent_pressed": "#4e8cd6",
    # Semantics
    "success": "#4caf50",
    "warning": "#ffc107",
    "error": "#f44336",
    "info": "#2196f3",
    # UI Elements & Borders
    "border": "#4a4d52",
    "handle": "#4a4d52",
    "link": "#72b1ff",
    "selection": "#62a0ea",
    # Buttons
    "button_primary_bg": "#62a0ea",
    "button_primary_fg": "#ffffff",
    "button_danger_bg": "#d32f2f",
    "button_danger_fg": "#ffffff",
    "button_success_bg": "#4caf50",
    "button_success_fg": "#ffffff",
    # Derived States
    "window_lighter_150": "#303337",
    "window_lighter_125": "#282a2e",
    "window_darker_115": "#1c1e20",
    "window_darker_130": "#191a1c",
    "error_lighter_110": "#ff5346",
    "error_darker_110": "#de3d31",
    "search_container_bg": "rgba(98, 160, 234, 0.10)",
}

APP_THEME_QSS = f"""
/* Global Styling */
QMainWindow, QDialog {{
    background-color: {DARK_THEME["window"]};
    color: {DARK_THEME["text"]};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}}

QWidget {{
    color: {DARK_THEME["text"]};
}}

/* Card & Frame Dynamic Properties */
QFrame[headerCard="true"] {{
    background-color: {DARK_THEME["base"]};
    border: 1px solid {DARK_THEME["border"]};
    border-radius: 6px;
    padding: 6px 10px;
}}

QFrame[panelFrame="true"] {{
    background-color: {DARK_THEME["base"]};
    border: 1px solid {DARK_THEME["border"]};
    border-radius: 6px;
    padding: 6px 10px;
}}

QFrame[configRowFrame="true"] {{
    background-color: {DARK_THEME["alternate"]};
    border-bottom: 1px solid {DARK_THEME["border"]};
    padding: 3px;
}}

/* GroupBoxes */
QGroupBox {{
    border: 1px solid {DARK_THEME["border"]};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 12px;
    font-weight: bold;
    color: {DARK_THEME["text"]};
    font-size: 12.5px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    background-color: {DARK_THEME["window"]};
    color: {DARK_THEME["accent"]};
}}

/* PushButtons & Roles */
QPushButton {{
    background-color: {DARK_THEME["base"]};
    color: {DARK_THEME["text"]};
    border: 1px solid {DARK_THEME["border"]};
    border-radius: 4px;
    padding: 3px 10px;
    font-weight: 500;
    font-size: 12px;
    min-height: 24px;
}}
QPushButton:hover {{
    background-color: {DARK_THEME["alternate"]};
    border-color: {DARK_THEME["accent"]};
}}
QPushButton:pressed {{
    background-color: {DARK_THEME["window_darker_115"]};
}}
QPushButton:disabled {{
    background-color: {DARK_THEME["window_darker_130"]};
    color: {DARK_THEME["text_secondary"]};
    border-color: {DARK_THEME["border"]};
}}

QPushButton[buttonRole="primary"] {{
    background-color: {DARK_THEME["button_primary_bg"]};
    color: {DARK_THEME["button_primary_fg"]};
    border-color: {DARK_THEME["accent_pressed"]};
    font-weight: bold;
}}
QPushButton[buttonRole="primary"]:hover {{
    background-color: {DARK_THEME["accent_hover"]};
    border-color: {DARK_THEME["accent"]};
}}
QPushButton[buttonRole="primary"]:pressed {{
    background-color: {DARK_THEME["accent_pressed"]};
}}

QPushButton[buttonRole="success"] {{
    background-color: {DARK_THEME["button_success_bg"]};
    color: {DARK_THEME["button_success_fg"]};
    border-color: #388e3c;
    font-weight: bold;
}}
QPushButton[buttonRole="success"]:hover {{
    background-color: #66bb6a;
}}
QPushButton[buttonRole="success"]:pressed {{
    background-color: #2e7d32;
}}

QPushButton[buttonRole="danger"] {{
    background-color: {DARK_THEME["button_danger_bg"]};
    color: {DARK_THEME["button_danger_fg"]};
    border-color: #b71c1c;
    font-weight: bold;
}}
QPushButton[buttonRole="danger"]:hover {{
    background-color: {DARK_THEME["error_lighter_110"]};
}}
QPushButton[buttonRole="danger"]:pressed {{
    background-color: {DARK_THEME["error_darker_110"]};
}}

/* LineEdits, SpinBoxes, ComboBoxes */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {DARK_THEME["base"]};
    border: 1px solid {DARK_THEME["border"]};
    border-radius: 4px;
    color: {DARK_THEME["text"]};
    padding: 3px 6px;
    font-size: 13px;
    min-height: 24px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {DARK_THEME["accent"]};
}}
QLineEdit::placeholder {{
    color: {DARK_THEME["text_secondary"]};
    font-size: 12px;
}}

/* Tables */
QTableView, QTableWidget {{
    background-color: {DARK_THEME["window"]};
    alternate-background-color: {DARK_THEME["alternate"]};
    gridline-color: {DARK_THEME["border"]};
    color: {DARK_THEME["text"]};
    border: 1px solid {DARK_THEME["border"]};
    border-radius: 4px;
    font-size: 13.5px;
}}
QTableView::item {{
    padding: 0px 6px;
    border: none;
}}
QTableView::item:selected, QTableWidget::item:selected {{
    background-color: {DARK_THEME["selection"]};
    color: #ffffff;
}}
QTableView::item:hover:!selected {{
    background-color: {DARK_THEME["alternate"]};
}}
QHeaderView::section {{
    background-color: {DARK_THEME["window"]};
    color: {DARK_THEME["text_secondary"]};
    padding: 3px 6px;
    border: none;
    border-right: 1px solid {DARK_THEME["border"]};
    border-bottom: 1px solid {DARK_THEME["border"]};
    font-weight: bold;
    font-size: 12px;
}}

/* Progress Bar */
QProgressBar {{
    background-color: {DARK_THEME["base"]};
    border: 1px solid {DARK_THEME["border"]};
    border-radius: 4px;
    height: 16px;
    text-align: center;
    color: {DARK_THEME["text"]};
    font-size: 11px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {DARK_THEME["accent"]}, stop:1 {DARK_THEME["accent_hover"]});
    border-radius: 3px;
}}

/* Tab Widget */
QTabWidget::pane {{
    border-top: 1px solid {DARK_THEME["border"]};
    background-color: {DARK_THEME["window"]};
}}
QTabBar::tab {{
    background-color: {DARK_THEME["window"]};
    color: {DARK_THEME["text_secondary"]};
    padding: 7px 18px;
    font-weight: bold;
    font-size: 13px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {DARK_THEME["text"]};
    background-color: {DARK_THEME["window"]};
    border-bottom: 2px solid {DARK_THEME["accent"]};
}}
QTabBar::tab:hover:!selected {{
    color: {DARK_THEME["text"]};
    background-color: {DARK_THEME["alternate"]};
}}

/* Scrollbars */
QScrollBar:vertical {{
    background-color: {DARK_THEME["window"]};
    width: 12px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background-color: {DARK_THEME["handle"]};
    min-height: 20px;
    border-radius: 4px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {DARK_THEME["accent_pressed"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* Tooltips */
QToolTip {{
    background-color: {DARK_THEME["base"]};
    color: {DARK_THEME["text"]};
    border: 1px solid {DARK_THEME["border"]};
    padding: 4px 6px;
    font-size: 12px;
}}
"""
