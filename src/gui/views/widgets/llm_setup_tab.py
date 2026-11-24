"""Local LLM Setup and Management Tab for Windows and Linux.

Provides first-time setup instructions, binary detection, server control,
model preloading, and live hardware resource monitoring.
Local LLM is optional and disabled by default.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.common.builder import UI
from gui.common.icons import Actions, Status
from gui.common.theme import DARK_THEME
from gui.common.widgets import make_description_label
from gui.models.model_service import ModelService

class LLMSetupTab(QWidget):
    """View component for configuring optional local Ollama inference, setup guidance, and diagnostics."""

    start_server_requested = pyqtSignal()
    stop_server_requested = pyqtSignal()
    preload_requested = pyqtSignal(str)
    unload_requested = pyqtSignal(str)
    local_llm_toggled = pyqtSignal(bool)

    def __init__(self, model_service: ModelService, parent=None):
        super().__init__(parent)
        self.model_service = model_service
        self._setup_ui()
        self.refresh_diagnostics()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # 1. Feature Toggle & Explanation Card
        toggle_card = QFrame()
        toggle_card.setProperty("panelFrame", True)
        toggle_layout = QVBoxLayout(toggle_card)

        toggle_row = QHBoxLayout()
        self.chk_enable_local = (
            UI.checkbox("Enable Local LLM Inference (Optional)")
            .tooltip("Check to enable local model inference. When unchecked, you can use any cloud LLM via file_list.json.")
            .build(self)
        )
        self.chk_enable_local.setStyleSheet("font-size: 14px; font-weight: bold; color: #60a5fa;")
        self.chk_enable_local.setChecked(self.model_service.is_enabled)
        self.chk_enable_local.toggled.connect(self._on_toggle_local)
        toggle_row.addWidget(self.chk_enable_local)
        toggle_row.addStretch()

        self.btn_refresh = (
            UI.button("Refresh Detection")
            .icon(Actions.REFRESH)
            .tooltip("Re-check system PATH and server status")
            .on_click(self.refresh_diagnostics)
            .build(self)
        )
        toggle_row.addWidget(self.btn_refresh)
        toggle_layout.addLayout(toggle_row)

        desc_text = (
            "ℹ️ <b>Local LLM is optional:</b> You do not need to install Ollama or a local model to use this pipeline. "
            "You can export your music file list (Phase 0) to JSON, feed it into ChatGPT, Claude, Gemini, or any other LLM, "
            "and load the resulting rename_plan.json back into Phase 2 for safe validation, apply, and rollback."
        )
        toggle_layout.addWidget(make_description_label(desc_text))
        layout.addWidget(toggle_card)

        # 2. System Status & Binary Detection Frame
        status_group = QGroupBox("1. Environment Diagnostics & Detection (Windows & Linux)")
        status_layout = QVBoxLayout(status_group)

        diag_grid = QHBoxLayout()
        diag_grid.setSpacing(16)

        # OS and Binary status
        v1 = QVBoxLayout()
        self.lbl_os = QLabel(f"Platform: {self.model_service.os_type.capitalize()}")
        self.lbl_os.setStyleSheet("font-weight: bold; font-size: 12.5px;")
        v1.addWidget(self.lbl_os)

        self.lbl_bin_status = QLabel("Ollama Binary: Checking...")
        self.lbl_bin_status.setStyleSheet("font-size: 12px;")
        v1.addWidget(self.lbl_bin_status)
        diag_grid.addLayout(v1)

        # Server and Model status
        v2 = QVBoxLayout()
        self.lbl_server_status = QLabel("Server: Offline")
        self.lbl_server_status.setStyleSheet("font-size: 12px;")
        v2.addWidget(self.lbl_server_status)

        self.lbl_models_found = QLabel("Installed Models: 0")
        self.lbl_models_found.setStyleSheet("font-size: 12px;")
        v2.addWidget(self.lbl_models_found)
        diag_grid.addLayout(v2)

        status_layout.addLayout(diag_grid)
        layout.addWidget(status_group)

        # 3. First-Time Setup & Installation Guide Frame
        self.setup_group = QGroupBox("2. First-Time Setup Instructions")
        setup_layout = QVBoxLayout(self.setup_group)

        info = self.model_service.get_installation_instructions()
        lbl_install_guide = QLabel(
            f"If Ollama is not installed yet on your system ({info['os']}), you can set it up with one command:"
        )
        lbl_install_guide.setStyleSheet("color: #94a3b8; font-size: 12px;")
        setup_layout.addWidget(lbl_install_guide)

        cmd_row = QHBoxLayout()
        self.txt_cmd = QLineEdit(info["quick_command"])
        self.txt_cmd.setReadOnly(True)
        self.txt_cmd.setStyleSheet("""
            QLineEdit {
                background-color: #17181c;
                border: 1px solid #3d424d;
                border-radius: 4px;
                padding: 4px 8px;
                color: #4ade80;
                font-family: monospace;
                font-size: 12px;
            }
        """)
        cmd_row.addWidget(self.txt_cmd)

        self.btn_copy_cmd = (
            UI.button("Copy Command")
            .icon(Actions.COPY)
            .tooltip("Copy install command to clipboard")
            .on_click(self._copy_command)
            .build(self)
        )
        cmd_row.addWidget(self.btn_copy_cmd)
        setup_layout.addLayout(cmd_row)

        lbl_steps = QLabel(info["instructions"])
        lbl_steps.setStyleSheet("color: #cbd5e1; font-family: monospace; font-size: 11.5px; margin-top: 4px;")
        setup_layout.addWidget(lbl_steps)

        layout.addWidget(self.setup_group)

        # 4. Local Server Controls & Model Management
        control_group = QGroupBox("3. Local Model Server Control & In-Memory Management")
        ctrl_layout = QVBoxLayout(control_group)

        ctrl_row = QHBoxLayout()
        lbl_m = QLabel("Select Model:")
        lbl_m.setStyleSheet("font-weight: 500;")
        ctrl_row.addWidget(lbl_m)

        self.combo_models = (
            UI.combobox()
            .items(["qwen2.5:14b", "qwen2.5:7b", "llama3.2:latest"])
            .min_width(220)
            .build(self)
        )
        ctrl_row.addWidget(self.combo_models)

        self.btn_start = (
            UI.button("Start Daemon")
            .icon(Actions.PLAY)
            .role("success")
            .tooltip("Launch background Ollama server")
            .on_click(self.start_server_requested.emit)
            .build(self)
        )
        ctrl_row.addWidget(self.btn_start)

        self.btn_stop = (
            UI.button("Stop Daemon")
            .icon(Actions.STOP)
            .role("danger")
            .tooltip("Stop Ollama server process to free system memory")
            .on_click(self.stop_server_requested.emit)
            .build(self)
        )
        ctrl_row.addWidget(self.btn_stop)

        self.btn_preload = (
            UI.button("Preload")
            .icon(Actions.REFRESH)
            .tooltip("Load model weights into RAM")
            .on_click(lambda: self.preload_requested.emit(self.combo_models.currentText()))
            .build(self)
        )
        ctrl_row.addWidget(self.btn_preload)

        self.btn_unload = (
            UI.button("Unload")
            .tooltip("Evict model from memory")
            .on_click(lambda: self.unload_requested.emit(self.combo_models.currentText()))
            .build(self)
        )
        ctrl_row.addWidget(self.btn_unload)

        ctrl_row.addStretch()
        ctrl_layout.addLayout(ctrl_row)

        # Resource meters row
        res_row = QHBoxLayout()
        res_row.setSpacing(16)

        lbl_c = QLabel("Inference CPU:")
        res_row.addWidget(lbl_c)
        self.val_cpu = QLabel("0.0%")
        self.val_cpu.setStyleSheet("font-weight: bold; color: #60a5fa;")
        res_row.addWidget(self.val_cpu)

        lbl_r = QLabel("Inference RAM:")
        res_row.addWidget(lbl_r)
        self.val_ram = QLabel("0.0 GB (0%)")
        self.val_ram.setStyleSheet("font-weight: bold; color: #4ade80;")
        res_row.addWidget(self.val_ram)

        lbl_s = QLabel("System Free RAM:")
        res_row.addWidget(lbl_s)
        self.val_sys = QLabel("0.0 GB")
        self.val_sys.setStyleSheet("font-weight: bold; color: #cbd5e1;")
        res_row.addWidget(self.val_sys)

        res_row.addStretch()
        ctrl_layout.addLayout(res_row)

        layout.addWidget(control_group)
        layout.addStretch()

    def _on_toggle_local(self, checked: bool):
        self.model_service.is_enabled = checked
        self.local_llm_toggled.emit(checked)

    def _copy_command(self):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.txt_cmd.text())
            self.btn_copy_cmd.setText("Copied!")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self.btn_copy_cmd.setText("Copy Command"))

    def refresh_diagnostics(self):
        """Checks Ollama installation, server status, and updates UI labels."""
        bin_path = self.model_service.find_ollama_binary()
        if bin_path:
            self.lbl_bin_status.setText(f"Ollama Binary: [Installed] {bin_path}")
            self.lbl_bin_status.setStyleSheet("color: #4ade80; font-size: 12px; font-weight: 500;")
            self.setup_group.setVisible(False)
        else:
            self.lbl_bin_status.setText("Ollama Binary: Not Found on system")
            self.lbl_bin_status.setStyleSheet("color: #f87171; font-size: 12px; font-weight: 500;")
            self.setup_group.setVisible(True)

        is_running = self.model_service.is_server_running()
        if is_running:
            ver = self.model_service.get_server_version()
            self.lbl_server_status.setText(f"Server: Online (v{ver}) on localhost:11434")
            self.lbl_server_status.setStyleSheet("color: #4ade80; font-size: 12px; font-weight: 500;")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_preload.setEnabled(True)

            models = self.model_service.get_available_models()
            self.lbl_models_found.setText(f"Installed Models: {len(models)} ({', '.join(models[:3])})")
            if models:
                current = self.combo_models.currentText()
                self.combo_models.clear()
                self.combo_models.addItems(models)
                if current in models:
                    self.combo_models.setCurrentText(current)
        else:
            self.lbl_server_status.setText("Server: Stopped / Offline")
            self.lbl_server_status.setStyleSheet("color: #94a3b8; font-size: 12px;")
            self.btn_start.setEnabled(bin_path is not None)
            self.btn_stop.setEnabled(False)
            self.btn_preload.setEnabled(False)
            self.btn_unload.setEnabled(False)

    def update_resource_stats(self, stats: dict):
        """Live updates CPU/RAM numbers from background monitor."""
        cpu = stats.get("model_cpu_percent", 0.0)
        ram_gb = stats.get("model_ram_gb", 0.0)
        ram_pct = stats.get("model_ram_percent", 0.0)
        avail_gb = stats.get("sys_ram_available_gb", 0.0)

        self.val_cpu.setText(f"{cpu}%")
        self.val_ram.setText(f"{ram_gb} GB ({ram_pct}%)")
        self.val_sys.setText(f"{avail_gb} GB")

        loaded = stats.get("loaded_models", [])
        self.btn_unload.setEnabled(bool(loaded))

    def get_selected_model(self) -> str:
        return self.combo_models.currentText()

    def is_local_enabled(self) -> bool:
        return self.chk_enable_local.isChecked()
