"""Fluent Builder Pattern UI Namespace for concise, consistent widget creation."""

from typing import Any, Callable, Optional
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QWidget,
)

class ButtonBuilder:
    def __init__(self, text: str = ""):
        self._text = text
        self._icon: Optional[str] = None
        self._tooltip: str = ""
        self._flat: bool = False
        self._checkable: bool = False
        self._checked: bool = False
        self._on_click: Optional[Callable] = None
        self._min_width: Optional[int] = None
        self._max_width: Optional[int] = None
        self._min_height: Optional[int] = None
        self._fixed_width: Optional[int] = None
        self._fixed_size: Optional[tuple[int, int]] = None
        self._object_name: Optional[str] = None
        self._style: Optional[str] = None
        self._role: Optional[str] = None
        self._cursor: Optional[Qt.CursorShape] = Qt.CursorShape.PointingHandCursor
        self._enabled: bool = True
        self._visible: bool = True

    def icon(self, icon_char: str) -> "ButtonBuilder":
        self._icon = icon_char
        return self

    def tooltip(self, text: str) -> "ButtonBuilder":
        self._tooltip = text
        return self

    def flat(self, is_flat: bool = True) -> "ButtonBuilder":
        self._flat = is_flat
        return self

    def checkable(self, is_checkable: bool = True) -> "ButtonBuilder":
        self._checkable = is_checkable
        return self

    def checked(self, is_checked: bool = True) -> "ButtonBuilder":
        self._checked = is_checked
        return self

    def on_click(self, callback: Callable) -> "ButtonBuilder":
        self._on_click = callback
        return self

    def min_height(self, h: int) -> "ButtonBuilder":
        self._min_height = h
        return self

    def min_width(self, w: int) -> "ButtonBuilder":
        self._min_width = w
        return self

    def max_width(self, w: int) -> "ButtonBuilder":
        self._max_width = w
        return self

    def fixed_width(self, w: int) -> "ButtonBuilder":
        self._fixed_width = w
        return self

    def fixed_size(self, w: int, h: int) -> "ButtonBuilder":
        self._fixed_size = (w, h)
        return self

    def object_name(self, name: str) -> "ButtonBuilder":
        self._object_name = name
        return self

    def role(self, role_name: str) -> "ButtonBuilder":
        self._role = role_name
        return self

    def style(self, css: str) -> "ButtonBuilder":
        self._style = css
        return self

    def cursor(self, cursor_shape: Qt.CursorShape) -> "ButtonBuilder":
        self._cursor = cursor_shape
        return self

    def enabled(self, is_enabled: bool) -> "ButtonBuilder":
        self._enabled = is_enabled
        return self

    def visible(self, is_visible: bool) -> "ButtonBuilder":
        self._visible = is_visible
        return self

    def build(self, parent: Optional[QWidget] = None) -> QPushButton:
        label = f"{self._icon} {self._text}" if self._icon and self._text else (self._icon or self._text)
        btn = QPushButton(label, parent)
        if self._tooltip:
            btn.setToolTip(self._tooltip)
        if self._flat:
            btn.setFlat(True)
        if self._checkable:
            btn.setCheckable(True)
            btn.setChecked(self._checked)
        if self._on_click:
            btn.clicked.connect(self._on_click)
        if self._min_height is not None:
            btn.setMinimumHeight(self._min_height)
        if self._min_width is not None:
            btn.setMinimumWidth(self._min_width)
        if self._max_width is not None:
            btn.setMaximumWidth(self._max_width)
        if self._fixed_width is not None:
            btn.setFixedWidth(self._fixed_width)
        if self._fixed_size is not None:
            btn.setFixedSize(*self._fixed_size)
        if self._object_name:
            btn.setObjectName(self._object_name)
        if self._role:
            btn.setProperty("buttonRole", self._role)
        if self._style:
            btn.setStyleSheet(self._style)
        if self._cursor:
            btn.setCursor(QCursor(self._cursor))
        btn.setEnabled(self._enabled)
        btn.setVisible(self._visible)
        return btn

class LineEditBuilder:
    def __init__(self, text: str = ""):
        self._text = text
        self._placeholder: str = ""
        self._tooltip: str = ""
        self._min_width: Optional[int] = None
        self._max_width: Optional[int] = None
        self._style: Optional[str] = None
        self._on_change: Optional[Callable] = None
        self._on_return: Optional[Callable] = None
        self._read_only: bool = False

    def placeholder(self, text: str) -> "LineEditBuilder":
        self._placeholder = text
        return self

    def tooltip(self, text: str) -> "LineEditBuilder":
        self._tooltip = text
        return self

    def min_width(self, w: int) -> "LineEditBuilder":
        self._min_width = w
        return self

    def max_width(self, w: int) -> "LineEditBuilder":
        self._max_width = w
        return self

    def style(self, css: str) -> "LineEditBuilder":
        self._style = css
        return self

    def read_only(self, is_read_only: bool = True) -> "LineEditBuilder":
        self._read_only = is_read_only
        return self

    def on_change(self, callback: Callable) -> "LineEditBuilder":
        self._on_change = callback
        return self

    def on_return(self, callback: Callable) -> "LineEditBuilder":
        self._on_return = callback
        return self

    def build(self, parent: Optional[QWidget] = None) -> QLineEdit:
        line_edit = QLineEdit(self._text, parent)
        if self._placeholder:
            line_edit.setPlaceholderText(self._placeholder)
        if self._tooltip:
            line_edit.setToolTip(self._tooltip)
        if self._min_width is not None:
            line_edit.setMinimumWidth(self._min_width)
        if self._max_width is not None:
            line_edit.setMaximumWidth(self._max_width)
        if self._read_only:
            line_edit.setReadOnly(True)
        if self._style:
            line_edit.setStyleSheet(self._style)
        if self._on_change:
            line_edit.textChanged.connect(self._on_change)
        if self._on_return:
            line_edit.returnPressed.connect(self._on_return)
        return line_edit

class SpinBoxBuilder:
    def __init__(self, value: int = 0):
        self._value = value
        self._min_val: int = 0
        self._max_val: int = 100
        self._step: int = 1
        self._suffix: str = ""
        self._special_text: Optional[str] = None
        self._tooltip: str = ""
        self._min_width: Optional[int] = None
        self._max_width: Optional[int] = None
        self._on_change: Optional[Callable] = None

    def range(self, min_val: int, max_val: int) -> "SpinBoxBuilder":
        self._min_val = min_val
        self._max_val = max_val
        return self

    def value(self, val: int) -> "SpinBoxBuilder":
        self._value = val
        return self

    def step(self, s: int) -> "SpinBoxBuilder":
        self._step = s
        return self

    def suffix(self, s: str) -> "SpinBoxBuilder":
        self._suffix = s
        return self

    def special_value_text(self, text: str) -> "SpinBoxBuilder":
        self._special_text = text
        return self

    def tooltip(self, text: str) -> "SpinBoxBuilder":
        self._tooltip = text
        return self

    def min_width(self, w: int) -> "SpinBoxBuilder":
        self._min_width = w
        return self

    def max_width(self, w: int) -> "SpinBoxBuilder":
        self._max_width = w
        return self

    def on_change(self, callback: Callable) -> "SpinBoxBuilder":
        self._on_change = callback
        return self

    def build(self, parent: Optional[QWidget] = None) -> QSpinBox:
        sb = QSpinBox(parent)
        sb.setRange(self._min_val, self._max_val)
        sb.setValue(self._value)
        sb.setSingleStep(self._step)
        if self._suffix:
            sb.setSuffix(self._suffix)
        if self._special_text:
            sb.setSpecialValueText(self._special_text)
        if self._tooltip:
            sb.setToolTip(self._tooltip)
        if self._min_width is not None:
            sb.setMinimumWidth(self._min_width)
        if self._max_width is not None:
            sb.setMaximumWidth(self._max_width)
        if self._on_change:
            sb.valueChanged.connect(self._on_change)
        return sb

class ComboBoxBuilder:
    def __init__(self):
        self._items: list[str] = []
        self._tooltip: str = ""
        self._min_width: Optional[int] = None
        self._max_width: Optional[int] = None
        self._on_change: Optional[Callable] = None
        self._on_text_change: Optional[Callable] = None

    def items(self, item_list: list[str]) -> "ComboBoxBuilder":
        self._items = item_list
        return self

    def tooltip(self, text: str) -> "ComboBoxBuilder":
        self._tooltip = text
        return self

    def min_width(self, w: int) -> "ComboBoxBuilder":
        self._min_width = w
        return self

    def max_width(self, w: int) -> "ComboBoxBuilder":
        self._max_width = w
        return self

    def on_change(self, callback: Callable) -> "ComboBoxBuilder":
        self._on_change = callback
        return self

    def on_text_change(self, callback: Callable) -> "ComboBoxBuilder":
        self._on_text_change = callback
        return self

    def build(self, parent: Optional[QWidget] = None) -> QComboBox:
        cb = QComboBox(parent)
        cb.addItems(self._items)
        if self._tooltip:
            cb.setToolTip(self._tooltip)
        if self._min_width is not None:
            cb.setMinimumWidth(self._min_width)
        if self._max_width is not None:
            cb.setMaximumWidth(self._max_width)
        if self._on_change:
            cb.currentIndexChanged.connect(self._on_change)
        if self._on_text_change:
            cb.currentTextChanged.connect(self._on_text_change)
        return cb

class CheckBoxBuilder:
    def __init__(self, text: str = ""):
        self._text = text
        self._checked: bool = False
        self._tooltip: str = ""
        self._on_change: Optional[Callable] = None

    def checked(self, is_checked: bool = True) -> "CheckBoxBuilder":
        self._checked = is_checked
        return self

    def tooltip(self, text: str) -> "CheckBoxBuilder":
        self._tooltip = text
        return self

    def on_change(self, callback: Callable) -> "CheckBoxBuilder":
        self._on_change = callback
        return self

    def build(self, parent: Optional[QWidget] = None) -> QCheckBox:
        cb = QCheckBox(self._text, parent)
        cb.setChecked(self._checked)
        if self._tooltip:
            cb.setToolTip(self._tooltip)
        if self._on_change:
            cb.toggled.connect(self._on_change)
        return cb

class UI:
    """Central entry point for the Fluent Builder pattern."""

    @staticmethod
    def button(text: str = "") -> ButtonBuilder:
        return ButtonBuilder(text)

    @staticmethod
    def line_edit(text: str = "") -> LineEditBuilder:
        return LineEditBuilder(text)

    @staticmethod
    def spinbox(value: int = 0) -> SpinBoxBuilder:
        return SpinBoxBuilder(value)

    @staticmethod
    def combobox() -> ComboBoxBuilder:
        return ComboBoxBuilder()

    @staticmethod
    def checkbox(text: str = "") -> CheckBoxBuilder:
        return CheckBoxBuilder(text)
