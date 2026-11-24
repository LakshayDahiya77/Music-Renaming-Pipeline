"""PyQt6 GUI Application initialization."""

import signal
import sys
from pathlib import Path

# Ensure 'src' is in sys.path
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from gui.controllers.app_controller import AppController
from gui.models.model_service import ModelService
from gui.models.plan_model import PlanTableModel
from gui.models.scan_model import ScanTableModel
from gui.views.main_window import MainWindow

def run_app():
    """Starts the PyQt6 MVC desktop application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Local LLM Movie Renamer")
    app.setOrganizationName("MovieRenamer")

    # Allow clean Ctrl+C terminal interrupts
    signal.signal(signal.SIGINT, lambda *args: app.quit())
    sigint_timer = QTimer()
    sigint_timer.timeout.connect(lambda: None)
    sigint_timer.start(500)

    # Initialize MVC Components
    model_service = ModelService()
    scan_model = ScanTableModel()
    plan_model = PlanTableModel()

    main_window = MainWindow(scan_model, plan_model, model_service)
    controller = AppController(main_window, scan_model, plan_model, model_service)

    # Clean shutdown hook
    app.aboutToQuit.connect(controller.shutdown)

    main_window.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(run_app())
