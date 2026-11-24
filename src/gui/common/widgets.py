"""Reusable UI widgets and shorthand helpers."""

from typing import Optional
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from gui.common.icons import Actions, Files
from gui.common.theme import DARK_THEME

def simple_line() -> QFrame:
    """Creates a sunken horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    line.setStyleSheet(f"background-color: {DARK_THEME['border']}; border: none; height: 1px;")
    return line

def make_description_label(text: str) -> QLabel:
    """Creates a muted, word-wrapped description label."""
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 11px;")
    return lbl

class SearchFilterWidget(QWidget):
    """Compound search input with search icon, clear button, and debounced text change signal."""

    text_changed = pyqtSignal(str)
    search_cleared = pyqtSignal()

    def __init__(self, placeholder: str = "Search...", parent: Optional[QWidget] = None, max_width: int = 360):
        super().__init__(parent)
        if max_width > 0:
            self.setMaximumWidth(max_width)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Icon
        self.icon_lbl = QLabel(Files.SEARCH)
        self.icon_lbl.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 13px; padding-left: 4px;")
        layout.addWidget(self.icon_lbl)

        # Line edit
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_THEME['base']};
                border: 1px solid {DARK_THEME['border']};
                border-radius: 4px;
                color: {DARK_THEME['text']};
                padding: 3px 6px;
                font-size: 13px;
                min-height: 22px;
            }}
            QLineEdit:focus {{
                border-color: {DARK_THEME['accent']};
            }}
        """)
        layout.addWidget(self.edit)

        # Clear button
        self.btn_clear = QPushButton(Actions.CLOSE)
        self.btn_clear.setToolTip("Clear search")
        self.btn_clear.setFixedSize(22, 22)
        self.btn_clear.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {DARK_THEME['text_secondary']};
                font-size: 12px;
            }}
            QPushButton:hover {{
                color: {DARK_THEME['error']};
            }}
        """)
        self.btn_clear.setVisible(False)
        self.btn_clear.clicked.connect(self.clear)
        layout.addWidget(self.btn_clear)

        # Debounce timer (150ms)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._emit_debounced)

        self.edit.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self, text: str):
        self.btn_clear.setVisible(bool(text))
        self._timer.start()

    def _emit_debounced(self):
        self.text_changed.emit(self.edit.text().strip())

    def clear(self):
        self.edit.clear()
        self.btn_clear.setVisible(False)
        self.search_cleared.emit()
        self.text_changed.emit("")

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, text: str):
        self.edit.setText(text)
