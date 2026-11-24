"""Main Application Window assembling views, navigation tabs, and LLM setup."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.common.theme import APP_THEME_QSS
from gui.models.model_service import ModelService
from gui.models.plan_model import PlanTableModel
from gui.models.scan_model import ScanTableModel
from gui.views.widgets.apply_tab import ApplyTab
from gui.views.widgets.llm_setup_tab import LLMSetupTab
from gui.views.widgets.logs_tab import LogsTab
from gui.views.widgets.plan_tab import PlanTab
from gui.views.widgets.raw_files_tab import RawFilesTab

class MainWindow(QMainWindow):
    """Top-level PyQt6 window coordinating all tabs and settings."""

    def __init__(
        self,
        scan_model: ScanTableModel,
        plan_model: PlanTableModel,
        model_service: ModelService,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Music Renaming & Tagging Pipeline")
        self.resize(1320, 840)
        self.setMinimumSize(1000, 640)

        self.setStyleSheet(APP_THEME_QSS)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Tab Widget
        self.tabs = QTabWidget()

        # Initialize View Tabs
        self.raw_files_tab = RawFilesTab(scan_model, self)
        self.plan_tab = PlanTab(plan_model, self)
        self.apply_tab = ApplyTab(plan_model, self)
        self.llm_setup_tab = LLMSetupTab(model_service, self)
        self.logs_tab = LogsTab(self)

        self.tabs.addTab(self.raw_files_tab, "1. Scanner • Raw Files")
        self.tabs.addTab(self.plan_tab, "2. AI Renamer • Plan Editor")
        self.tabs.addTab(self.apply_tab, "3. Safe Apply • Rollback & Verify")
        self.tabs.addTab(self.llm_setup_tab, "4. Local LLM Setup (Optional)")
        self.tabs.addTab(self.logs_tab, "5. Logs • Activity Console")

        root_layout.addWidget(self.tabs)

        # Status Bar
        self.status_bar = QStatusBar(self)
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #202225;
                color: #a0a0a0;
                border-top: 1px solid #4a4d52;
                font-size: 11px;
            }
        """)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Select target music library directory to scan.")
