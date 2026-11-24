"""Apply & Rollback view with safety checks, verification status, and activity log."""

from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.common.builder import UI
from gui.common.icons import Actions
from gui.common.theme import DARK_THEME
from gui.common.widgets import make_description_label
from gui.models.plan_model import PlanTableModel
from gui.views.widgets.diff_dialog import DiffDialog

class ApplyTab(QWidget):
    """View component for previewing diffs, applying renames & tags safely, executing rollbacks,
    and verifying disk state."""

    execute_requested = pyqtSignal(bool, bool)  # dry_run, update_tags
    rollback_requested = pyqtSignal(Path)
    verification_requested = pyqtSignal()

    def __init__(self, plan_model: PlanTableModel, parent=None):
        super().__init__(parent)
        self.model = plan_model
        self.base_dir = ""
        self._setup_ui()

    def set_base_dir(self, directory: str):
        self.base_dir = directory
        self.lbl_target_dir.setText(f"Music Target Directory: {directory or 'None selected'}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Overview & Safety Card
        card = QFrame()
        card.setProperty("panelFrame", True)
        card_layout = QVBoxLayout(card)

        self.lbl_target_dir = QLabel("Music Target Directory: None selected")
        self.lbl_target_dir.setStyleSheet("font-weight: bold; font-size: 13px; color: #60a5fa;")
        card_layout.addWidget(self.lbl_target_dir)

        notice_text = (
            "⚠️ <b>Safety Guarantee:</b> Changes are never applied blindly. "
            "All renames and audio tags are validated deterministically, diffs can be previewed without touching disk, "
            "streaming rollback logs record original paths and original tags, and Phase 4 Verification verifies disk integrity."
        )
        self.lbl_safety_notice = make_description_label(notice_text)
        card_layout.addWidget(self.lbl_safety_notice)

        self.lbl_plan_summary = QLabel("Ready: 0 | Flagged Review: 0 | Excluded: 0")
        self.lbl_plan_summary.setStyleSheet("font-weight: bold; font-size: 12px; color: #4ade80; margin-top: 6px;")
        card_layout.addWidget(self.lbl_plan_summary)

        layout.addWidget(card)

        # Actions Row
        action_layout = QHBoxLayout()

        self.btn_diff = (
            UI.button("Dry-Run Preview (Diff)")
            .icon(Actions.DIFF)
            .role("primary")
            .tooltip("Preview before/after paths and tag updates without touching disk")
            .on_click(self._preview_diff)
            .build(self)
        )
        action_layout.addWidget(self.btn_diff)

        self.chk_update_tags = (
            UI.checkbox("Write & Update Audio Tags")
            .tooltip("When checked, embedded tags (Title, Artist, Album, Track, Year) will be written to audio files")
            .build(self)
        )
        self.chk_update_tags.setChecked(True)
        self.chk_update_tags.setStyleSheet("color: #60a5fa; font-weight: bold; font-size: 12px;")
        action_layout.addWidget(self.chk_update_tags)

        self.chk_confirm = (
            UI.checkbox("I understand this will rename files on disk")
            .tooltip("Safety lock: check this box to enable the execute button")
            .build(self)
        )
        self.chk_confirm.setStyleSheet("color: #f87171; font-weight: bold; font-size: 12px;")
        action_layout.addWidget(self.chk_confirm)

        self.btn_execute = (
            UI.button("Execute Renames & Tags")
            .icon(Actions.CHECK)
            .role("danger")
            .tooltip("Apply all ready renames and tags on disk with automatic rollback logging & verification")
            .on_click(self._execute_renames)
            .build(self)
        )
        action_layout.addWidget(self.btn_execute)

        action_layout.addSpacing(16)

        self.btn_rollback = (
            UI.button("Rollback from Log...")
            .icon(Actions.ROLLBACK)
            .tooltip("Select a previous rollback_log_*.jsonl to undo renames AND restore original tags")
            .on_click(self._trigger_rollback)
            .build(self)
        )
        action_layout.addWidget(self.btn_rollback)

        self.btn_verify = (
            UI.button("Run Verification Now")
            .icon(Actions.SCAN)
            .tooltip("Verify that files exist on disk, are playable, and audio tags match expected plan")
            .on_click(self.verification_requested.emit)
            .build(self)
        )
        action_layout.addWidget(self.btn_verify)

        action_layout.addStretch()
        layout.addLayout(action_layout)

        # Verification Status Card
        self.verify_card = QFrame()
        self.verify_card.setProperty("panelFrame", True)
        vc_layout = QHBoxLayout(self.verify_card)
        vc_layout.setContentsMargins(10, 6, 10, 6)

        lbl_v_title = QLabel("Phase 4 Verification Status:")
        lbl_v_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #a0aec0;")
        vc_layout.addWidget(lbl_v_title)

        self.lbl_verify_status = QLabel("Not run yet. Verification automatically runs after execution.")
        self.lbl_verify_status.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        vc_layout.addWidget(self.lbl_verify_status)
        vc_layout.addStretch()

        layout.addWidget(self.verify_card)

        # Activity Log Area
        log_group = QGroupBox("Execution • Activity Log")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_THEME['window']};
                color: {DARK_THEME['text']};
                border: 1px solid {DARK_THEME['border']};
                font-family: monospace;
                font-size: 12.5px;
            }}
        """)
        log_layout.addWidget(self.log_text)

        layout.addWidget(log_group)

    def log(self, message: str):
        self.log_text.append(message)
        scrollbar = self.log_text.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def update_summary(self):
        items = self.model.get_items()
        ready = sum(1 for i in items if i.status in ("ready", "modified") and not i.is_excluded)
        review = sum(1 for i in items if i.status == "review" and not i.is_excluded)
        excluded = sum(1 for i in items if i.is_excluded)
        self.lbl_plan_summary.setText(f"Ready: {ready} | Flagged Review: {review} | Excluded: {excluded}")

    def update_verification_display(self, total: int, passed: int, failed: int, warnings: int, report_file: str):
        if failed > 0:
            color = "#f87171"
            status_text = f"❌ FAILED ({failed} errors, {warnings} warnings, {passed}/{total} passed)"
        elif warnings > 0:
            color = "#facc15"
            status_text = f"⚠️ WARNINGS ({warnings} warnings, {passed}/{total} passed)"
        else:
            color = "#4ade80"
            status_text = f"✅ PASSED (All {passed}/{total} files and tags verified on disk)"

        self.lbl_verify_status.setText(f"{status_text} • Report: {Path(report_file).name if report_file else 'None'}")
        self.lbl_verify_status.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color};")

    def _preview_diff(self):
        active_items = self.model.get_active_items()
        if not active_items:
            QMessageBox.information(self, "Empty Plan", "There are no active items in the plan to preview.")
            return
        dialog = DiffDialog(active_items, self.base_dir, self)
        dialog.exec()

    def _execute_renames(self):
        if not self.chk_confirm.isChecked():
            QMessageBox.warning(
                self,
                "Confirmation Required",
                "Please check the safety lock: 'I understand this will rename files on disk' before proceeding.",
            )
            return

        active_items = self.model.get_active_items()
        ready_items = [i for i in active_items if i.status in ("ready", "modified")]

        if not ready_items:
            QMessageBox.warning(self, "No Valid Items", "No items are in 'Ready' or 'Modified' status.")
            return

        update_tags = self.chk_update_tags.isChecked()
        tag_note = " (and update audio tags)" if update_tags else " (without modifying tags)"
        reply = QMessageBox.question(
            self,
            "Confirm Music Execution",
            f"Are you sure you want to execute renaming for {len(ready_items)} file(s){tag_note} in:\n{self.base_dir}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.execute_requested.emit(False, update_tags)

    def _trigger_rollback(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Rollback Log File",
            self.base_dir,
            "Rollback Logs (*.jsonl *.json);;All Files (*)",
        )
        if file_path:
            self.rollback_requested.emit(Path(file_path))
