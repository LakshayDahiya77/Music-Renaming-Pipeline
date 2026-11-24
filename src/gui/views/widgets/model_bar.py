"""Model control panel showing start/stop controls, status badge, and resource meters."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from gui.common.builder import UI
from gui.common.icons import Actions, Status
from gui.common.theme import DARK_THEME

class ModelBar(QFrame):
    """Top bar managing Ollama model state and displaying CPU/RAM metrics."""

    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    load_requested = pyqtSignal(str)
    unload_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("headerCard", True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        # Status indicator
        self.status_dot = QLabel(Status.OFFLINE)
        self.status_dot.setStyleSheet(f"color: {DARK_THEME['error']}; font-size: 16px;")
        layout.addWidget(self.status_dot)

        self.status_label = QLabel("Server: Stopped")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self.status_label)

        # Model Selector
        lbl_model = QLabel("Model:")
        lbl_model.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; margin-left: 6px; font-size: 12px;")
        layout.addWidget(lbl_model)

        self.model_combo = (
            UI.combobox()
            .items([
                "movie-renamer",
                "richardyoung/qwen3-14b-abliterated:Q4_K_M",
                "richardyoung/qwen3-14b-abliterated:latest",
            ])
            .min_width(170)
            .build(self)
        )
        layout.addWidget(self.model_combo)

        # Action Buttons created with Fluent Builder
        self.btn_start = (
            UI.button("Start Server")
            .icon(Actions.PLAY)
            .role("success")
            .tooltip("Launch the local Ollama server process")
            .on_click(self.start_requested.emit)
            .build(self)
        )
        layout.addWidget(self.btn_start)

        self.btn_stop = (
            UI.button("Stop Server")
            .icon(Actions.STOP)
            .role("danger")
            .tooltip("Stop Ollama server and terminate inference engine to free RAM")
            .on_click(self.stop_requested.emit)
            .build(self)
        )
        layout.addWidget(self.btn_stop)

        self.btn_load = (
            UI.button("Preload")
            .icon(Actions.REFRESH)
            .tooltip("Pre-warm and load the 14B model into RAM")
            .on_click(lambda: self.load_requested.emit(self.model_combo.currentText()))
            .build(self)
        )
        layout.addWidget(self.btn_load)

        self.btn_unload = (
            UI.button("Unload")
            .tooltip("Evict model weights from RAM")
            .on_click(lambda: self.unload_requested.emit(self.model_combo.currentText()))
            .build(self)
        )
        layout.addWidget(self.btn_unload)

        layout.addSpacing(12)

        # Resource Usage Widget
        res_container = QWidget()
        res_layout = QHBoxLayout(res_container)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.setSpacing(12)

        lbl_cpu = QLabel("Model CPU:")
        lbl_cpu.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 12px;")
        res_layout.addWidget(lbl_cpu)
        self.cpu_val = QLabel("0.0%")
        self.cpu_val.setStyleSheet(f"font-weight: bold; color: {DARK_THEME['accent']}; font-size: 12px;")
        res_layout.addWidget(self.cpu_val)

        lbl_ram = QLabel("Model RAM:")
        lbl_ram.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 12px;")
        res_layout.addWidget(lbl_ram)
        self.ram_val = QLabel("0.0 GB (0%)")
        self.ram_val.setStyleSheet(f"font-weight: bold; color: {DARK_THEME['success']}; font-size: 12px;")
        res_layout.addWidget(self.ram_val)

        lbl_avail = QLabel("Sys Free:")
        lbl_avail.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 12px;")
        res_layout.addWidget(lbl_avail)
        self.avail_val = QLabel("0.0 GB")
        self.avail_val.setStyleSheet(f"font-weight: bold; color: {DARK_THEME['text']}; font-size: 12px;")
        res_layout.addWidget(self.avail_val)

        layout.addWidget(res_container)
        layout.addStretch()

    def update_stats(self, stats: dict):
        server_running = stats.get("server_running", False)
        loaded = stats.get("loaded_models", [])

        if not server_running:
            self.status_dot.setText(Status.OFFLINE)
            self.status_dot.setStyleSheet(f"color: {DARK_THEME['error']}; font-size: 16px;")
            self.status_label.setText("Server: Stopped")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_load.setEnabled(False)
            self.btn_unload.setEnabled(False)
            self.cpu_val.setText("0.0%")
            self.ram_val.setText("0.0 GB")
        else:
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_load.setEnabled(True)

            if loaded:
                model_name = loaded[0]
                self.status_dot.setText(Status.ONLINE)
                self.status_dot.setStyleSheet(f"color: {DARK_THEME['success']}; font-size: 16px;")
                self.status_label.setText(f"Online: {model_name}")
                self.btn_unload.setEnabled(True)
            else:
                self.status_dot.setText(Status.IDLE)
                self.status_dot.setStyleSheet(f"color: {DARK_THEME['warning']}; font-size: 16px;")
                self.status_label.setText("Server Online (Model Idle)")
                self.btn_unload.setEnabled(False)

            cpu = stats.get("model_cpu_percent", 0.0)
            ram_gb = stats.get("model_ram_gb", 0.0)
            ram_pct = stats.get("model_ram_percent", 0.0)
            avail_gb = stats.get("sys_ram_available_gb", 0.0)

            self.cpu_val.setText(f"{cpu}%")
            self.ram_val.setText(f"{ram_gb} GB ({ram_pct}%)")
            self.avail_val.setText(f"{avail_gb} GB")

    def get_selected_model(self) -> str:
        return self.model_combo.currentText()
