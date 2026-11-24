"""Dry-run diff viewer dialog displaying side-by-side comparison of planned renames."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from gui.common.theme import DARK_THEME
from gui.models.plan_model import PlanItem

class DiffDialog(QDialog):
    """Shows a clear dry-run comparison table of before and after paths before applying."""

    def __init__(self, items: list[PlanItem], base_dir_str: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dry-Run Rename Preview")
        self.resize(1000, 600)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_THEME['window']};
                color: {DARK_THEME['text']};
            }}
            QTableWidget {{
                background-color: {DARK_THEME['window']};
                gridline-color: {DARK_THEME['border']};
                color: {DARK_THEME['text']};
                border: 1px solid {DARK_THEME['border']};
                font-size: 13px;
            }}
            QHeaderView::section {{
                background-color: {DARK_THEME['base']};
                color: {DARK_THEME['text_secondary']};
                padding: 6px;
                font-weight: bold;
                border: 1px solid {DARK_THEME['border']};
            }}
            QPushButton {{
                background-color: {DARK_THEME['base']};
                color: {DARK_THEME['text']};
                border: 1px solid {DARK_THEME['border']};
                border-radius: 4px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                background-color: {DARK_THEME['alternate']};
                border-color: {DARK_THEME['accent']};
            }}
        """)

        layout = QVBoxLayout(self)

        lbl_info = QLabel(
            f"<b>Base Directory:</b> {base_dir_str}<br>"
            f"<b>Total Files to Rename:</b> {len(items)}"
        )
        layout.addWidget(lbl_info)

        table = QTableWidget(len(items), 3)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(26)
        table.verticalHeader().setMinimumSectionSize(22)
        table.setHorizontalHeaderLabels(["Original Relative Path", "Proposed New Path / Destination", "Action"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.setColumnWidth(0, 420)
        table.setColumnWidth(1, 420)

        for row, item in enumerate(items):
            item_orig = QTableWidgetItem(item.old_path)
            item_dest = QTableWidgetItem(item.final_destination)
            item_act = QTableWidgetItem("Rename" if item.old_path != item.final_destination else "Unchanged")

            if item.old_path != item.final_destination:
                item_dest.setForeground(Qt.GlobalColor.green)
            else:
                item_dest.setForeground(Qt.GlobalColor.gray)

            table.setItem(row, 0, item_orig)
            table.setItem(row, 1, item_dest)
            table.setItem(row, 2, item_act)

        layout.addWidget(table)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("Close Preview")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)
