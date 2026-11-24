"""Raw music files scanner tab with fast QTableView, search filter, and export options dialog."""

import csv
import json
from pathlib import Path
from typing import List, Optional
from PyQt6.QtCore import QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gui.common.builder import UI
from gui.common.icons import Actions, Files
from gui.common.theme import DARK_THEME
from gui.common.widgets import SearchFilterWidget
from gui.models.scan_model import ScanTableModel
from metadata import AVAILABLE_EXPORT_ATTRIBUTES, DEFAULT_SELECTED_ATTRIBUTES

class ExportAttributesDialog(QDialog):
    """Modal dialog allowing users to choose output format and select which attributes to export."""

    def __init__(self, parent=None, default_output: str = "data/file_list.json"):
        super().__init__(parent)
        self.setWindowTitle("Export Music File List")
        self.resize(580, 500)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_THEME['window']};
                color: {DARK_THEME['text']};
            }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {DARK_THEME['border']};
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 1. Output Path and Format
        format_group = QGroupBox("1. Output Destination & Format")
        fg_layout = QVBoxLayout(format_group)

        row_dest = QHBoxLayout()
        lbl_dest = QLabel("Destination File:")
        lbl_dest.setFixedWidth(110)
        row_dest.addWidget(lbl_dest)

        self.edit_output = QLineEdit(default_output)
        row_dest.addWidget(self.edit_output)

        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._browse_save_file)
        row_dest.addWidget(self.btn_browse)
        fg_layout.addLayout(row_dest)

        row_fmt = QHBoxLayout()
        lbl_fmt = QLabel("File Format:")
        lbl_fmt.setFixedWidth(110)
        row_fmt.addWidget(lbl_fmt)

        self.combo_format = QComboBox()
        self.combo_format.addItems([
            "JSON (*.json) — Best for LLM Prompts",
            "JSON Lines (*.jsonl) — Streaming Record Format",
            "CSV (*.csv) — Spreadsheet Table",
            "Plain Text (*.txt) — Delimited Text",
        ])
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        row_fmt.addWidget(self.combo_format)
        fg_layout.addLayout(row_fmt)

        layout.addWidget(format_group)

        # 2. Attribute Selection
        attr_group = QGroupBox("2. Choose Music Attributes to Export")
        ag_layout = QVBoxLayout(attr_group)

        # Preset buttons
        preset_row = QHBoxLayout()
        btn_all = QPushButton("Select All")
        btn_all.clicked.connect(lambda: self._set_all_checks(True))
        preset_row.addWidget(btn_all)

        btn_common = QPushButton("Common Tags (Default)")
        btn_common.clicked.connect(self._set_common_checks)
        preset_row.addWidget(btn_common)

        btn_minimal = QPushButton("Minimal (Path & Title)")
        btn_minimal.clicked.connect(self._set_minimal_checks)
        preset_row.addWidget(btn_minimal)

        btn_none = QPushButton("Clear All")
        btn_none.clicked.connect(lambda: self._set_all_checks(False))
        preset_row.addWidget(btn_none)
        preset_row.addStretch()
        ag_layout.addLayout(preset_row)

        # Scrollable area of checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.grid_layout = QGridLayout(scroll_content)
        self.grid_layout.setSpacing(6)

        self.checkbox_map = {}
        row = 0
        col = 0
        for attr_key, attr_label, attr_desc in AVAILABLE_EXPORT_ATTRIBUTES:
            cb = QCheckBox(f"{attr_label} ({attr_key})")
            cb.setToolTip(attr_desc)
            cb.setChecked(attr_key in DEFAULT_SELECTED_ATTRIBUTES)
            self.checkbox_map[attr_key] = cb
            self.grid_layout.addWidget(cb, row, col)
            col += 1
            if col > 1:
                col = 0
                row += 1

        scroll.setWidget(scroll_content)
        ag_layout.addWidget(scroll)
        layout.addWidget(attr_group)

        # Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_export = QPushButton("Export File List")
        self.btn_export.setStyleSheet("background-color: #16a34a; font-weight: bold; color: white;")
        self.btn_export.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_export)

        layout.addLayout(btn_box)

    def _browse_save_file(self):
        curr_text = self.edit_output.text().strip()
        fpath, _ = QFileDialog.getSaveFileName(
            self,
            "Choose Export File Location",
            curr_text or "file_list.json",
            "JSON Files (*.json);;JSON Lines (*.jsonl);;CSV Files (*.csv);;Text Files (*.txt);;All Files (*)",
        )
        if fpath:
            self.edit_output.setText(fpath)

    def _on_format_changed(self, idx: int):
        curr = self.edit_output.text().strip()
        p = Path(curr)
        exts = [".json", ".jsonl", ".csv", ".txt"]
        if idx < len(exts):
            new_path = p.with_suffix(exts[idx])
            self.edit_output.setText(str(new_path))

    def _set_all_checks(self, checked: bool):
        for cb in self.checkbox_map.values():
            cb.setChecked(checked)

    def _set_common_checks(self):
        for k, cb in self.checkbox_map.items():
            cb.setChecked(k in DEFAULT_SELECTED_ATTRIBUTES)

    def _set_minimal_checks(self):
        minimal = {"relative_path", "filename", "artist", "title", "album"}
        for k, cb in self.checkbox_map.items():
            cb.setChecked(k in minimal)

    def get_selected_attributes(self) -> List[str]:
        selected = [k for k, cb in self.checkbox_map.items() if cb.isChecked()]
        if "relative_path" not in selected:
            selected.insert(0, "relative_path")
        return selected

    def get_output_path(self) -> Path:
        return Path(self.edit_output.text().strip() or "data/file_list.json")

    def get_format(self) -> str:
        idx = self.combo_format.currentIndex()
        return ["json", "jsonl", "csv", "txt"][idx]

class ScanFilterProxyModel(QSortFilterProxyModel):
    """Proxy filter with numeric and case-insensitive natural sorting for music files."""

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        col = left.column()
        # Col 0: #, Col 5: Year, Col 6: Track, Col 8: Bitrate, Col 10: Size
        if col in (0, 5, 6, 8, 10):
            left_val = left.data(Qt.ItemDataRole.UserRole)
            right_val = right.data(Qt.ItemDataRole.UserRole)
            if left_val is not None and right_val is not None:
                return left_val < right_val

        left_str = str(left.data(Qt.ItemDataRole.DisplayRole) or "").lower()
        right_str = str(right.data(Qt.ItemDataRole.DisplayRole) or "").lower()
        return left_str < right_str

class RawFilesTab(QWidget):
    """View component for directory scanning, viewing music files, and exporting attributes."""

    scan_requested = pyqtSignal(Path, Path, int)
    export_requested = pyqtSignal(Path, list, str)  # output_path, attributes, format

    def __init__(self, table_model: ScanTableModel, parent=None):
        super().__init__(parent)
        self.model = table_model

        self.proxy_model = ScanFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy_model.setFilterKeyColumn(-1)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Input Frame
        input_frame = QFrame()
        input_frame.setProperty("panelFrame", True)
        input_layout = QVBoxLayout(input_frame)
        input_layout.setSpacing(8)

        # Base directory row
        dir_row = QHBoxLayout()
        lbl_dir = QLabel("Music Directory:")
        lbl_dir.setFixedWidth(110)
        dir_row.addWidget(lbl_dir)

        self.dir_input = (
            UI.line_edit()
            .placeholder("/path/to/music/library (mp3, flac, m4a, aac, dsf)")
            .tooltip("Select base directory containing music files")
            .build(self)
        )
        dir_row.addWidget(self.dir_input)

        self.btn_browse_dir = (
            UI.button("Browse...")
            .icon(Actions.BROWSE)
            .tooltip("Choose directory from file picker")
            .on_click(self._browse_dir)
            .build(self)
        )
        dir_row.addWidget(self.btn_browse_dir)
        input_layout.addLayout(dir_row)

        # Output file & limit row
        opts_row = QHBoxLayout()
        lbl_out = QLabel("Output File List:")
        lbl_out.setFixedWidth(110)
        opts_row.addWidget(lbl_out)

        self.out_input = (
            UI.line_edit("data/file_list.json")
            .tooltip("Path where scanned relative paths and tags will be saved")
            .build(self)
        )
        opts_row.addWidget(self.out_input)

        self.btn_browse_out = (
            UI.button("Browse...")
            .icon(Actions.BROWSE)
            .on_click(self._browse_output)
            .build(self)
        )
        opts_row.addWidget(self.btn_browse_out)

        lbl_limit = QLabel("Scan Limit:")
        opts_row.addWidget(lbl_limit)

        self.spin_limit = (
            UI.spinbox(0)
            .range(0, 500000)
            .special_value_text("All")
            .tooltip("Limit number of scanned files (0 for unlimited)")
            .build(self)
        )
        opts_row.addWidget(self.spin_limit)

        self.btn_scan = (
            UI.button("Scan Music Library")
            .icon(Actions.SCAN)
            .role("primary")
            .tooltip("Recursively scans directory and extracts audio metadata & codec details")
            .on_click(self._trigger_scan)
            .build(self)
        )
        opts_row.addWidget(self.btn_scan)

        input_layout.addLayout(opts_row)
        layout.addWidget(input_frame)

        # Filter & Summary Bar
        bar_layout = QHBoxLayout()
        self.search_widget = SearchFilterWidget(placeholder="Filter files by artist, title, album, codec, or folder...")
        self.search_widget.text_changed.connect(self.proxy_model.setFilterRegularExpression)
        bar_layout.addWidget(self.search_widget)

        self.btn_export = (
            UI.button("Export File List...")
            .icon(Actions.SAVE)
            .tooltip("Export scanned music files to JSON, CSV, or TXT with custom attribute selection")
            .on_click(self._open_export_dialog)
            .build(self)
        )
        bar_layout.addWidget(self.btn_export)

        self.lbl_summary = QLabel("0 music files found")
        self.lbl_summary.setStyleSheet(f"font-weight: bold; color: {DARK_THEME['accent']}; margin-left: 10px;")
        bar_layout.addWidget(self.lbl_summary)

        layout.addLayout(bar_layout)

        # Table View
        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # #
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)      # Filename
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)      # Artist
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)      # Title
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)      # Album
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) # Year
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents) # Track
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents) # Codec
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents) # Bitrate
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents) # Duration
        header.setSectionResizeMode(10, QHeaderView.ResizeMode.ResizeToContents) # Size
        header.setSectionResizeMode(11, QHeaderView.ResizeMode.Interactive)     # Folder

        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setMinimumSectionSize(22)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(1, 300)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 200)
        self.table.setColumnWidth(4, 160)

        layout.addWidget(self.table)

    def _browse_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Music Library Directory")
        if directory:
            self.dir_input.setText(directory)

    def _browse_output(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Output File List",
            self.out_input.text() or "data/file_list.json",
            "JSON Files (*.json);;JSON Lines (*.jsonl);;All Files (*)",
        )
        if file_path:
            self.out_input.setText(file_path)

    def _trigger_scan(self):
        dir_str = self.dir_input.text().strip()
        if not dir_str:
            QMessageBox.warning(self, "Select Directory", "Please select a target music directory to scan.")
            return
        out_str = self.out_input.text().strip() or "data/file_list.json"
        limit = self.spin_limit.value() if self.spin_limit.value() > 0 else 0
        self.scan_requested.emit(Path(dir_str), Path(out_str), limit)

    def _open_export_dialog(self):
        items = self.model.get_items()
        if not items:
            QMessageBox.information(self, "No Files", "No scanned files to export. Please run a scan first.")
            return

        default_out = self.out_input.text().strip() or "data/file_list.json"
        dialog = ExportAttributesDialog(self, default_output=default_out)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            out_path = dialog.get_output_path()
            attrs = dialog.get_selected_attributes()
            fmt = dialog.get_format()
            self.export_requested.emit(out_path, attrs, fmt)

    def update_summary(self, count: int, total_bytes: int):
        from metadata import format_file_size
        size_str = format_file_size(total_bytes)
        self.lbl_summary.setText(f"{count} music files found • {size_str}")

    def set_target_dir(self, directory: str):
        self.dir_input.setText(directory)

    def get_target_dir(self) -> str:
        return self.dir_input.text().strip()
