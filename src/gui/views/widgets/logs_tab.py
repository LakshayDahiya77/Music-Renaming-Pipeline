"""System and execution logging panel with real-time stream, level filters, and export."""

from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.common.builder import UI
from gui.common.icons import Actions
from gui.common.logger import app_logger
from gui.common.theme import DARK_THEME

class LogsTab(QWidget):
    """View component displaying application execution logs, audit trail, and user actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_level = "ALL"
        self._search_text = ""
        self._auto_scroll = True

        self._setup_ui()
        self._load_initial_history()

        # Connect live log stream
        app_logger.emitter.log_emitted.connect(self._on_log_emitted)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. Filter & Action Toolbar
        toolbar = QFrame()
        toolbar.setProperty("panelFrame", True)
        bar_layout = QHBoxLayout(toolbar)
        bar_layout.setContentsMargins(8, 6, 8, 6)
        bar_layout.setSpacing(10)

        # Filter Level
        lbl_level = QLabel("Level:")
        lbl_level.setStyleSheet("font-weight: 600; color: #a0aec0; font-size: 12px;")
        bar_layout.addWidget(lbl_level)

        self.combo_level = QComboBox()
        self.combo_level.addItems(["All Levels", "INFO", "ACTION", "SUCCESS", "WARNING", "ERROR"])
        self.combo_level.currentTextChanged.connect(self._on_level_changed)
        bar_layout.addWidget(self.combo_level)

        # Search filter
        lbl_search = QLabel("Search:")
        lbl_search.setStyleSheet("font-weight: 600; color: #a0aec0; font-size: 12px;")
        bar_layout.addWidget(lbl_search)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter logs by text or source...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #17181c;
                border: 1px solid #363942;
                border-radius: 4px;
                padding: 4px 8px;
                color: #f1f5f9;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #62a0ea;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        bar_layout.addWidget(self.search_input, stretch=1)

        # Auto-scroll checkbox
        self.chk_autoscroll = QCheckBox("Auto-Scroll")
        self.chk_autoscroll.setChecked(True)
        self.chk_autoscroll.setStyleSheet("font-weight: 500; font-size: 12px; color: #cbd5e1;")
        self.chk_autoscroll.toggled.connect(lambda v: setattr(self, "_auto_scroll", v))
        bar_layout.addWidget(self.chk_autoscroll)

        # Action Buttons
        self.btn_copy = (
            UI.button("Copy All")
            .icon(Actions.COPY)
            .tooltip("Copy all visible logs to clipboard")
            .on_click(self._copy_all_logs)
            .build(self)
        )
        bar_layout.addWidget(self.btn_copy)

        self.btn_export = (
            UI.button("Export...")
            .icon(Actions.SAVE)
            .tooltip("Save log history to a text file")
            .on_click(self._export_logs)
            .build(self)
        )
        bar_layout.addWidget(self.btn_export)

        self.btn_clear = (
            UI.button("Clear")
            .icon(Actions.DELETE)
            .tooltip("Clear log viewer display")
            .on_click(self._clear_logs)
            .build(self)
        )
        bar_layout.addWidget(self.btn_clear)

        layout.addWidget(toolbar)

        # 2. Main Log Console
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("""
            QTextEdit {
                background-color: #16171b;
                border: 1px solid #2e313a;
                border-radius: 6px;
                padding: 8px;
                color: #e2e8f0;
                font-family: 'DejaVu Sans Mono', 'Consolas', 'Courier New', monospace;
                font-size: 11.5px;
                line-height: 1.45;
            }
        """)
        layout.addWidget(self.log_console, stretch=1)

        # 3. Bottom Stats Bar
        self.lbl_stats = QLabel("Total: 0 entries | Info: 0 | Actions: 0 | Warnings: 0 | Errors: 0")
        self.lbl_stats.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-weight: 500; font-size: 11.5px;")
        layout.addWidget(self.lbl_stats)

    def _format_record_html(self, record: dict) -> str:
        level = record.get("level", "INFO")
        ts = record.get("timestamp", "")
        source = record.get("source", "System")
        msg = record.get("message", "")

        level_colors = {
            "INFO": "#60a5fa",       # Blue
            "ACTION": "#c084fc",     # Purple / Lavender
            "SUCCESS": "#4ade80",    # Green
            "WARNING": "#fbbf24",    # Amber
            "ERROR": "#f87171",      # Red
            "CRITICAL": "#ef4444",   # Deep Red
        }
        color = level_colors.get(level, "#cbd5e1")

        # HTML safe escape
        clean_msg = (
            msg.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>&nbsp;&nbsp;&nbsp;&nbsp;")
        )

        return (
            f'<div style="margin-bottom: 2px;">'
            f'<span style="color: #64748b;">[{ts}]</span> '
            f'<span style="color: {color}; font-weight: 700;">[{level:7s}]</span> '
            f'<span style="color: #94a3b8;">[{source:10s}]</span> '
            f'<span style="color: #f1f5f9;">{clean_msg}</span>'
            f'</div>'
        )

    def _load_initial_history(self):
        self._refresh_view()

    def _matches_filter(self, record: dict) -> bool:
        level = record.get("level", "INFO")
        if self._filter_level != "ALL" and level != self._filter_level:
            return False

        if self._search_text:
            text = f"{record.get('timestamp', '')} {level} {record.get('source', '')} {record.get('message', '')}".lower()
            if self._search_text not in text:
                return False

        return True

    def _refresh_view(self):
        self.log_console.clear()
        html_parts = []
        matching_count = 0

        info_cnt = 0
        action_cnt = 0
        warn_cnt = 0
        err_cnt = 0

        for r in app_logger.history:
            lvl = r.get("level", "")
            if lvl == "INFO":
                info_cnt += 1
            elif lvl in ("ACTION", "SUCCESS"):
                action_cnt += 1
            elif lvl == "WARNING":
                warn_cnt += 1
            elif lvl in ("ERROR", "CRITICAL"):
                err_cnt += 1

            if self._matches_filter(r):
                html_parts.append(self._format_record_html(r))
                matching_count += 1

        if html_parts:
            self.log_console.setHtml("".join(html_parts))

        if self._auto_scroll:
            cursor = self.log_console.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_console.setTextCursor(cursor)

        self.lbl_stats.setText(
            f"Total: {len(app_logger.history)} entries (Showing: {matching_count}) | "
            f"Info: {info_cnt} | Actions: {action_cnt} | Warnings: {warn_cnt} | Errors: {err_cnt}"
        )

    @pyqtSlot(dict)
    def _on_log_emitted(self, record: dict):
        if self._matches_filter(record):
            self.log_console.append(self._format_record_html(record))

            if self._auto_scroll:
                cursor = self.log_console.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                self.log_console.setTextCursor(cursor)

        # Update stats
        total = len(app_logger.history)
        info_cnt = sum(1 for r in app_logger.history if r.get("level") == "INFO")
        action_cnt = sum(1 for r in app_logger.history if r.get("level") in ("ACTION", "SUCCESS"))
        warn_cnt = sum(1 for r in app_logger.history if r.get("level") == "WARNING")
        err_cnt = sum(1 for r in app_logger.history if r.get("level") in ("ERROR", "CRITICAL"))
        self.lbl_stats.setText(
            f"Total: {total} entries | Info: {info_cnt} | Actions: {action_cnt} | Warnings: {warn_cnt} | Errors: {err_cnt}"
        )

    def _on_level_changed(self, text: str):
        self._filter_level = "ALL" if text == "All Levels" else text.upper()
        self._refresh_view()

    def _on_search_changed(self, text: str):
        self._search_text = text.strip().lower()
        self._refresh_view()

    def _clear_logs(self):
        self.log_console.clear()
        self.lbl_stats.setText(f"Total: {len(app_logger.history)} entries (Display cleared)")

    def _copy_all_logs(self):
        plain_text = self.log_console.toPlainText()
        if not plain_text:
            return
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(plain_text)
            orig_text = self.btn_copy.text()
            self.btn_copy.setText("✓ Copied")
            QTimer.singleShot(1200, lambda: self.btn_copy.setText(orig_text))

    def _export_logs(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Log File", "data/execution_log.txt", "Log Files (*.log *.txt);;All Files (*)"
        )
        if not file_path:
            return
        try:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.log_console.toPlainText())
            QMessageBox.information(self, "Logs Exported", f"Successfully exported logs to {p.resolve()}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Could not export logs: {e}")
