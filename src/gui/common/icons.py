"""Semantic icon constants and helpers."""

from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton

class Actions:
    PLAY = "▶"
    PAUSE = "⏸"
    STOP = "⏹"
    SCAN = "🔍"
    SAVE = "💾"
    DELETE = "🗑"
    RESTORE = "🔄"
    REFRESH = "🔃"
    REVERT = "↺"
    EDIT = "✏"
    CHECK = "✓"
    DIFF = "🔍"
    ROLLBACK = "⏪"
    BROWSE = "📂"
    OPEN = "📂"
    CLOSE = "✕"
    COPY = "📋"

class Status:
    ONLINE = "●"
    OFFLINE = "○"
    IDLE = "◐"
    READY = "✓"
    WARNING = "⚠️"
    ERROR = "❌"
    SUCCESS = "✓"

class Files:
    FOLDER = "📁"
    FILE = "📄"
    VIDEO = "🎬"
    SEARCH = "🔎"
    DOCUMENT = "📑"

class Navigation:
    UP = "▲"
    DOWN = "▼"
    NEXT = "▶"
    PREV = "◀"

def setup_button(btn: QPushButton, icon_char: str, text: str = ""):
    """Sets text and semantic icon on button."""
    if text:
        btn.setText(f"{icon_char} {text}" if icon_char else text)
    else:
        btn.setText(icon_char)

def setup_label(lbl: QLabel, icon_char: str):
    """Sets icon on label."""
    lbl.setText(icon_char)

def setup_action(action, icon_char: str, text: str = ""):
    """Sets text and semantic icon on a QAction."""
    if text:
        action.setText(f"{icon_char} {text}" if icon_char else text)
    else:
        action.setText(icon_char)
