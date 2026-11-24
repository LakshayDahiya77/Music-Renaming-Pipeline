"""Plan editor view with proposed music filenames, inline editing, batch execution and filtering."""

from pathlib import Path
from typing import Optional
from PyQt6.QtCore import QModelIndex, QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gui.common.builder import UI
from gui.common.icons import Actions, Files, Status
from gui.common.logger import app_logger
from gui.common.theme import DARK_THEME
from gui.common.widgets import SearchFilterWidget
from gui.models.plan_model import PlanItem, PlanTableModel, get_display_folder
from gui.views.delegates.badge_delegate import BadgeDelegate

class PlanFilterProxyModel(QSortFilterProxyModel):
    """Multi-criteria proxy filter for plan items (confidence, status, and search query)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_confidence = "all"
        self.filter_status = "all"
        self.search_text = ""

    def set_confidence_filter(self, conf: str):
        self.filter_confidence = conf.lower()
        self.invalidateFilter()

    def set_status_filter(self, stat: str):
        self.filter_status = stat.lower()
        self.invalidateFilter()

    def set_search_query(self, query: str):
        self.search_text = query.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        source_model: PlanTableModel = self.sourceModel()
        items = source_model.get_items()
        if not (0 <= source_row < len(items)):
            return False

        item = items[source_row]

        if self.filter_confidence != "all":
            if item.confidence.lower() != self.filter_confidence:
                return False

        if self.filter_status != "all":
            if self.filter_status == "review" and item.status != "review":
                return False
            elif self.filter_status == "modified" and not item.is_modified:
                return False
            elif self.filter_status == "excluded" and not item.is_excluded:
                return False
            elif self.filter_status == "collision" and item.status != "collision":
                return False
            elif self.filter_status == "ready" and item.status != "ready":
                return False

        if self.search_text:
            text_match = (
                self.search_text in item.proposed_name.lower()
                or self.search_text in item.original_name.lower()
                or self.search_text in item.old_path.lower()
                or self.search_text in item.reasoning.lower()
                or self.search_text in item.artist.lower()
                or self.search_text in item.title.lower()
                or self.search_text in item.album.lower()
                or self.search_text in item.folder.lower()
            )
            if not text_match:
                return False

        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        col = left.column()
        # Col 0 (#), 5 (Track), 6 (Confidence), 7 (Status)
        if col in (0, 5, 6, 7):
            left_val = left.data(Qt.ItemDataRole.UserRole)
            right_val = right.data(Qt.ItemDataRole.UserRole)
            if left_val is not None and right_val is not None:
                return left_val < right_val

        left_str = str(left.data(Qt.ItemDataRole.DisplayRole) or "").lower()
        right_str = str(right.data(Qt.ItemDataRole.DisplayRole) or "").lower()
        return left_str < right_str

class PlanTab(QWidget):
    """View component for configuring AI planning, importing external plans, and editing proposed titles."""

    plan_requested = pyqtSignal(Path, int, int)
    stop_requested = pyqtSignal()
    save_plan_requested = pyqtSignal()
    reload_plan_requested = pyqtSignal()
    import_plan_requested = pyqtSignal(Path)

    def __init__(self, plan_model: PlanTableModel, parent=None):
        super().__init__(parent)
        self.model = plan_model
        self.is_local_llm_enabled = False

        self.proxy_model = PlanFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)

        self._setup_ui()

    def set_local_llm_enabled(self, enabled: bool):
        self.is_local_llm_enabled = enabled
        if enabled:
            self.btn_start_plan.setText("Run Local AI Renamer")
            self.btn_start_plan.setToolTip("Start local LLM inference batches using Ollama")
        else:
            self.btn_start_plan.setText("Run AI Renamer (Offline)")
            self.btn_start_plan.setToolTip("Local LLM is disabled. Click to view cloud LLM instructions or enable local LLM.")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # AI Configuration Bar
        cfg_frame = QFrame()
        cfg_frame.setProperty("panelFrame", True)
        cfg_layout = QHBoxLayout(cfg_frame)
        cfg_layout.setSpacing(10)

        lbl_rules = QLabel("Naming Rules:")
        cfg_layout.addWidget(lbl_rules)

        self.rules_input = (
            UI.line_edit("Renaming Rules.txt")
            .tooltip("Path to music naming specification document")
            .build(self)
        )
        cfg_layout.addWidget(self.rules_input)

        self.btn_browse_rules = (
            UI.button("Browse...")
            .icon(Actions.BROWSE)
            .on_click(self._browse_rules)
            .build(self)
        )
        cfg_layout.addWidget(self.btn_browse_rules)

        lbl_batch = QLabel("Batch Size:")
        cfg_layout.addWidget(lbl_batch)

        self.spin_batch = (
            UI.spinbox(10)
            .range(1, 50)
            .tooltip("Inference batch size")
            .build(self)
        )
        cfg_layout.addWidget(self.spin_batch)

        lbl_limit = QLabel("Limit:")
        cfg_layout.addWidget(lbl_limit)

        self.spin_limit = (
            UI.spinbox(0)
            .range(0, 100000)
            .special_value_text("All")
            .tooltip("Max items to plan in this run (0 for all remaining)")
            .build(self)
        )
        cfg_layout.addWidget(self.spin_limit)

        self.btn_start_plan = (
            UI.button("Run AI Renamer")
            .icon(Actions.PLAY)
            .role("success")
            .tooltip("Start local LLM batch inference")
            .on_click(self._trigger_plan)
            .build(self)
        )
        cfg_layout.addWidget(self.btn_start_plan)

        self.btn_stop_plan = (
            UI.button("Stop")
            .icon(Actions.STOP)
            .role("danger")
            .enabled(False)
            .tooltip("Pause planner after current batch finishes")
            .on_click(self.stop_requested.emit)
            .build(self)
        )
        cfg_layout.addWidget(self.btn_stop_plan)

        layout.addWidget(cfg_frame)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1f1f26;
                border: 1px solid #323240;
                border-radius: 4px;
                height: 16px;
                text-align: center;
                color: #ffffff;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background-color: #16a34a;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Filter & Action Toolbar
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)

        # Search
        self.search_widget = SearchFilterWidget(placeholder="Search proposed name, artist, title, or reasoning...")
        self.search_widget.text_changed.connect(self.proxy_model.set_search_query)
        action_bar.addWidget(self.search_widget)

        # Confidence Filter
        lbl_conf = QLabel("Confidence:")
        action_bar.addWidget(lbl_conf)
        self.combo_conf = (
            UI.combobox()
            .items(["All", "High", "Medium", "Low"])
            .on_text_change(self.proxy_model.set_confidence_filter)
            .build(self)
        )
        action_bar.addWidget(self.combo_conf)

        # Status Filter
        lbl_stat = QLabel("Status:")
        action_bar.addWidget(lbl_stat)
        self.combo_stat = (
            UI.combobox()
            .items(["All", "Ready", "Review", "Modified", "Collision", "Excluded"])
            .on_text_change(self.proxy_model.set_status_filter)
            .build(self)
        )
        action_bar.addWidget(self.combo_stat)

        # Action Buttons
        self.btn_delete = (
            UI.button("Exclude")
            .icon(Actions.DELETE)
            .tooltip("Exclude selected file(s) from renaming plan")
            .on_click(self._exclude_selected)
            .build(self)
        )
        action_bar.addWidget(self.btn_delete)

        self.btn_restore = (
            UI.button("Restore")
            .icon(Actions.RESTORE)
            .tooltip("Restore excluded file(s)")
            .on_click(self._restore_selected)
            .build(self)
        )
        action_bar.addWidget(self.btn_restore)

        self.btn_reset = (
            UI.button("Original")
            .icon(Actions.REVERT)
            .tooltip("Reset proposed name back to original filename")
            .on_click(self._reset_selected)
            .build(self)
        )
        action_bar.addWidget(self.btn_reset)

        self.btn_import_plan = (
            UI.button("Import Plan JSON...")
            .icon(Actions.OPEN)
            .tooltip("Import a rename_plan.json created by ChatGPT, Claude, Gemini, or external tools")
            .on_click(self._import_external_plan)
            .build(self)
        )
        action_bar.addWidget(self.btn_import_plan)

        self.btn_save = (
            UI.button("Save Plan")
            .icon(Actions.SAVE)
            .tooltip("Save current plan to rename_plan.json")
            .on_click(self.save_plan_requested.emit)
            .build(self)
        )
        action_bar.addWidget(self.btn_save)

        self.btn_reload = (
            UI.button("Reload")
            .icon(Actions.REFRESH)
            .tooltip("Reload plan from rename_plan.json")
            .on_click(self.reload_plan_requested.emit)
            .build(self)
        )
        action_bar.addWidget(self.btn_reload)

        layout.addLayout(action_bar)

        # Table View
        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        # Badge delegates on Confidence (col 6) and Status (col 7)
        badge_delegate = BadgeDelegate(self.table)
        self.table.setItemDelegateForColumn(6, badge_delegate)
        self.table.setItemDelegateForColumn(7, badge_delegate)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # #
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)      # Original Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)      # Proposed Name
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)      # Artist
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)      # Title
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) # Track
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents) # Confidence
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents) # Status
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)      # Reasoning
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Interactive)      # Folder

        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setMinimumSectionSize(22)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(1, 300)
        self.table.setColumnWidth(2, 340)
        self.table.setColumnWidth(3, 140)
        self.table.setColumnWidth(4, 180)
        self.table.setColumnWidth(5, 50)
        self.table.setColumnWidth(6, 95)
        self.table.setColumnWidth(7, 90)

        # Vertical Splitter: Master Table + Detail Inspector
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.table)
        self.inspector_widget = self._build_inspector_widget()
        self.splitter.addWidget(self.inspector_widget)

        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([380, 260])
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)

        layout.addWidget(self.splitter)

        self.table.selectionModel().currentRowChanged.connect(self._on_table_row_changed)
        self.model.dataChanged.connect(self._on_model_data_changed)
        self.model.modelReset.connect(self._on_model_reset)

        # Summary Bar
        self.lbl_stats = QLabel("Total: 0 | Ready: 0 | Needs Review: 0 | Collisions: 0 | Excluded: 0")
        self.lbl_stats.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-weight: 500; font-size: 12px;")
        layout.addWidget(self.lbl_stats)

    def _browse_rules(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Renaming Rules Document", "Renaming Rules.txt", "Text / Markdown (*.txt *.md);;All Files (*)"
        )
        if file_path:
            self.rules_input.setText(file_path)

    def _trigger_plan(self):
        if not self.is_local_llm_enabled:
            reply = QMessageBox.information(
                self,
                "Local LLM is Optional / Disabled",
                "Local LLM inference is currently disabled.\n\n"
                "• To use Local LLM (Ollama): Enable it in tab '4. Local LLM Setup'.\n"
                "• To use Cloud LLMs (ChatGPT, Claude, Gemini): Export your file list in tab '1. Scanner • Raw Files', "
                "follow the prompts in 'input_output_format.txt', and click 'Import Plan JSON...' here.",
                QMessageBox.StandardButton.Ok,
            )
            return

        rules_str = self.rules_input.text().strip()
        if not rules_str:
            QMessageBox.warning(self, "Missing Rules", "Please specify a naming rules file.")
            return

        batch_size = self.spin_batch.value()
        limit = self.spin_limit.value()
        self.plan_requested.emit(Path(rules_str), batch_size, limit)

    def _import_external_plan(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import External Rename Plan JSON",
            "data/rename_plan.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if file_path:
            count = self.model.load_from_file(Path(file_path))
            self.update_stats_summary()
            app_logger.success(f"Imported {count} items from plan file '{Path(file_path).name}'", source="PlanModel")
            QMessageBox.information(
                self,
                "Plan Imported",
                f"Successfully loaded {count} music rename proposals from:\n{file_path}",
            )
            self.import_plan_requested.emit(Path(file_path))

    def _get_selected_source_rows(self) -> list[int]:
        selected_indexes = self.table.selectionModel().selectedRows()
        source_rows = []
        for proxy_idx in selected_indexes:
            source_idx = self.proxy_model.mapToSource(proxy_idx)
            source_rows.append(source_idx.row())
        return source_rows

    def _exclude_selected(self):
        rows = self._get_selected_source_rows()
        if rows:
            self.model.toggle_exclude(rows)
            app_logger.action(f"Toggled exclusion for {len(rows)} selected row(s)", source="User")

    def _restore_selected(self):
        rows = self._get_selected_source_rows()
        if rows:
            self.model.toggle_exclude(rows)
            app_logger.action(f"Restored {len(rows)} selected row(s)", source="User")

    def _reset_selected(self):
        rows = self._get_selected_source_rows()
        if rows:
            self.model.reset_to_original(rows)
            app_logger.action(f"Reset {len(rows)} selected row(s) to original names", source="User")

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #202028;
                color: #e2e8f0;
                border: 1px solid #383848;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #3b82f6;
                color: #ffffff;
            }
        """)

        act_edit = menu.addAction(f"{Actions.EDIT} Edit Proposed Name (Double-click)")
        act_edit.triggered.connect(self._edit_current_cell)

        act_exclude = menu.addAction(f"{Actions.DELETE} Exclude from Plan (Del)")
        act_exclude.triggered.connect(self._exclude_selected)

        act_restore = menu.addAction(f"{Actions.RESTORE} Restore Excluded")
        act_restore.triggered.connect(self._restore_selected)

        act_reset = menu.addAction(f"{Actions.REVERT} Reset to Original Name")
        act_reset.triggered.connect(self._reset_selected)

        menu.addSeparator()
        act_reasoning = menu.addAction("💡 View Full AI Reasoning & Tags")
        act_reasoning.triggered.connect(self._show_reasoning_dialog)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _edit_current_cell(self):
        indexes = self.table.selectionModel().selectedRows()
        if indexes:
            proxy_idx = self.proxy_model.index(indexes[0].row(), 2)
            self.table.edit(proxy_idx)

    def _show_reasoning_dialog(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return
        source_idx = self.proxy_model.mapToSource(indexes[0])
        item = self.model.get_items()[source_idx.row()]

        tag_preview = []
        if item.new_tags:
            for k, v in item.new_tags.items():
                if v:
                    tag_preview.append(f"<b>{k}:</b> {v}")
        tag_str = "<br>".join(tag_preview) if tag_preview else "None"

        msg = QMessageBox(self)
        msg.setWindowTitle(f"Music Plan Details: {item.original_name}")
        msg.setText(
            f"<b>Original Path:</b> {item.old_path}<br>"
            f"<b>Proposed Name:</b> {item.proposed_name}<br>"
            f"<b>Confidence:</b> {item.confidence.upper()}<br><br>"
            f"<b>Proposed Audio Tags:</b><br>{tag_str}<br><br>"
            f"<b>Reasoning:</b><br>{item.reasoning}"
        )
        msg.exec()

    def update_stats_summary(self):
        items = self.model.get_items()
        total = len(items)
        ready = sum(1 for i in items if i.status in ("ready", "modified") and not i.is_excluded)
        review = sum(1 for i in items if i.status == "review" and not i.is_excluded)
        collision = sum(1 for i in items if i.status == "collision" and not i.is_excluded)
        excluded = sum(1 for i in items if i.is_excluded)

        self.lbl_stats.setText(
            f"Total: {total} | Ready: {ready} | Needs Review: {review} | Collisions: {collision} | Excluded: {excluded}"
        )
        if items and self.proxy_model.rowCount() > 0 and not self.table.selectionModel().hasSelection():
            self.table.selectRow(0)

    def set_planning_active(self, active: bool):
        self.btn_start_plan.setEnabled(not active)
        self.btn_stop_plan.setEnabled(active)
        self.progress_bar.setVisible(active)

    # Master-Detail Inspector
    def _build_inspector_widget(self) -> QWidget:
        self.insp_stack = QStackedWidget()
        self.insp_stack.setMinimumHeight(200)

        empty_widget = QFrame()
        empty_layout = QVBoxLayout(empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_empty = QLabel("👆 Select a music file from the table above to inspect, diff, and edit filenames")
        lbl_empty.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 13px; font-style: italic;")
        empty_layout.addWidget(lbl_empty)
        self.insp_stack.addWidget(empty_widget)

        detail_panel = QFrame()
        detail_panel.setStyleSheet(f"""
            QFrame#detailInspector {{
                background-color: #212328;
                border: 1px solid {DARK_THEME['border']};
                border-radius: 6px;
            }}
            QLabel.fieldTitle {{
                color: #8fa0b5;
                font-size: 10.5px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }}
            QLineEdit.monospaceField {{
                background-color: #17181c;
                border: 1px solid #3d424d;
                border-radius: 4px;
                padding: 4px 8px;
                color: #ffffff;
                font-family: monospace;
                font-size: 11.5px;
            }}
            QLineEdit.monospaceFieldReadOnly {{
                background-color: #16171b;
                border: 1px solid #2d3038;
                border-radius: 4px;
                padding: 4px 8px;
                color: #cbd5e1;
                font-family: monospace;
                font-size: 11.5px;
            }}
            QPlainTextEdit.reasoningBox {{
                background-color: #16171b;
                border: 1px solid #2d3038;
                border-radius: 4px;
                padding: 4px 8px;
                color: #cbd5e1;
                font-size: 11.5px;
            }}
        """)
        detail_panel.setObjectName("detailInspector")

        vbox = QVBoxLayout(detail_panel)
        vbox.setContentsMargins(10, 8, 10, 8)
        vbox.setSpacing(5)

        # Header bar
        header_bar = QHBoxLayout()
        header_bar.setSpacing(6)

        lbl_section = QLabel("DETAIL INSPECTOR")
        lbl_section.setStyleSheet("font-weight: 800; color: #62a0ea; font-size: 11px; margin-right: 4px;")
        header_bar.addWidget(lbl_section)

        self.insp_badge_index = QLabel("#-")
        self.insp_badge_index.setStyleSheet("background-color: #2a2d36; color: #ffffff; border-radius: 4px; padding: 2px 7px; font-weight: bold; font-size: 11px;")
        header_bar.addWidget(self.insp_badge_index)

        self.insp_badge_status = QLabel("STATUS")
        self.insp_badge_status.setStyleSheet("border-radius: 4px; padding: 2px 7px; font-weight: bold; font-size: 11px;")
        header_bar.addWidget(self.insp_badge_status)

        self.insp_badge_confidence = QLabel("CONFIDENCE")
        self.insp_badge_confidence.setStyleSheet("border-radius: 4px; padding: 2px 7px; font-weight: bold; font-size: 11px;")
        header_bar.addWidget(self.insp_badge_confidence)

        header_bar.addStretch()

        self.btn_insp_revert = UI.button("Revert").icon(Actions.REVERT).on_click(self._insp_revert).build(self)
        header_bar.addWidget(self.btn_insp_revert)

        self.btn_insp_exclude = UI.button("Exclude").icon(Actions.DELETE).on_click(self._insp_exclude).build(self)
        header_bar.addWidget(self.btn_insp_exclude)

        self.btn_insp_apply = UI.button("Apply Edit").icon(Actions.SAVE).role("accent").on_click(self._apply_inspector_edit).build(self)
        header_bar.addWidget(self.btn_insp_apply)

        vbox.addLayout(header_bar)

        # Original
        lbl_orig = QLabel("ORIGINAL PATH:")
        lbl_orig.setProperty("class", "fieldTitle")
        vbox.addWidget(lbl_orig)

        self.insp_edit_original = QLineEdit()
        self.insp_edit_original.setReadOnly(True)
        self.insp_edit_original.setProperty("class", "monospaceFieldReadOnly")
        vbox.addWidget(self.insp_edit_original)

        # Proposed
        lbl_prop = QLabel("PROPOSED FILENAME (EDITABLE — Press Enter or click Apply Edit):")
        lbl_prop.setProperty("class", "fieldTitle")
        lbl_prop.setStyleSheet("color: #62a0ea; font-weight: 700;")
        vbox.addWidget(lbl_prop)

        self.insp_edit_proposed = QLineEdit()
        self.insp_edit_proposed.setProperty("class", "monospaceField")
        self.insp_edit_proposed.returnPressed.connect(self._apply_inspector_edit)
        vbox.addWidget(self.insp_edit_proposed)

        # Tags summary
        lbl_tags = QLabel("PROPOSED AUDIO TAGS TO WRITE:")
        lbl_tags.setProperty("class", "fieldTitle")
        vbox.addWidget(lbl_tags)

        self.insp_edit_tags = QLineEdit()
        self.insp_edit_tags.setReadOnly(True)
        self.insp_edit_tags.setProperty("class", "monospaceFieldReadOnly")
        vbox.addWidget(self.insp_edit_tags)

        # Reasoning
        lbl_reason = QLabel("AI REASONING & PARSING LOGIC:")
        lbl_reason.setProperty("class", "fieldTitle")
        vbox.addWidget(lbl_reason)

        self.insp_txt_reasoning = QPlainTextEdit()
        self.insp_txt_reasoning.setReadOnly(True)
        self.insp_txt_reasoning.setProperty("class", "reasoningBox")
        self.insp_txt_reasoning.setMaximumHeight(55)
        vbox.addWidget(self.insp_txt_reasoning)

        self.insp_stack.addWidget(detail_panel)
        self._current_source_row: Optional[int] = None

        return self.insp_stack

    def _on_table_row_changed(self, current: QModelIndex, previous: QModelIndex):
        if not current.isValid():
            self.insp_stack.setCurrentIndex(0)
            self._current_source_row = None
            return

        source_idx = self.proxy_model.mapToSource(current)
        if not source_idx.isValid():
            self.insp_stack.setCurrentIndex(0)
            self._current_source_row = None
            return

        self._current_source_row = source_idx.row()
        self._populate_inspector(self._current_source_row)

    def _populate_inspector(self, row: int):
        items = self.model.get_items()
        if not (0 <= row < len(items)):
            self.insp_stack.setCurrentIndex(0)
            return

        item = items[row]
        self.insp_stack.setCurrentIndex(1)

        self.insp_badge_index.setText(f"#{item.index}")
        self.insp_badge_status.setText(item.status.upper())
        self.insp_badge_confidence.setText(item.confidence.upper())

        self.insp_edit_original.setText(item.old_path)
        self.insp_edit_proposed.setText(item.proposed_name)

        tag_preview = []
        if item.new_tags:
            for k, v in item.new_tags.items():
                if v:
                    tag_preview.append(f"{k}: {v}")
        self.insp_edit_tags.setText(", ".join(tag_preview) if tag_preview else "None")
        self.insp_txt_reasoning.setPlainText(item.reasoning)

    def _apply_inspector_edit(self):
        if self._current_source_row is None:
            return
        new_text = self.insp_edit_proposed.text().strip()
        if not new_text:
            return
        source_idx = self.model.index(self._current_source_row, 2)
        self.model.setData(source_idx, new_text, Qt.ItemDataRole.EditRole)

    def _insp_revert(self):
        if self._current_source_row is not None:
            self.model.reset_to_original([self._current_source_row])
            self._populate_inspector(self._current_source_row)

    def _insp_exclude(self):
        if self._current_source_row is not None:
            self.model.toggle_exclude([self._current_source_row])
            self._populate_inspector(self._current_source_row)

    def _on_model_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex):
        if self._current_source_row is not None and top_left.row() <= self._current_source_row <= bottom_right.row():
            self._populate_inspector(self._current_source_row)

    def _on_model_reset(self):
        self.update_stats_summary()
