"""Central logging service with Qt signal bridge and file logging."""

import datetime
from pathlib import Path
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal

class LogSignalEmitter(QObject):
    """Qt signal emitter for thread-safe cross-thread UI log dispatching."""
    log_emitted = pyqtSignal(dict)

class AppLogger:
    """Thread-safe application logger writing to memory buffer, disk file, and Qt signals."""

    _instance: Optional["AppLogger"] = None

    def __init__(self):
        self.emitter = LogSignalEmitter()
        self.history: list[dict] = []
        self.max_history = 5000

        # Ensure data/ directory exists for file log
        self.log_file = Path("data/app.log")
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    @classmethod
    def instance(cls) -> "AppLogger":
        if cls._instance is None:
            cls._instance = AppLogger()
        return cls._instance

    def log(self, level: str, message: str, source: str = "System"):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "timestamp": now_str,
            "level": level.upper(),
            "source": source,
            "message": str(message),
        }

        # Store in in-memory ring buffer
        self.history.append(record)
        if len(self.history) > self.max_history:
            self.history.pop(0)

        # Write to data/app.log
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] [{level.upper():7s}] [{source:12s}] {message}\n")
        except Exception:
            pass

        # Emit Qt signal for live GUI updates
        self.emitter.log_emitted.emit(record)

    def info(self, message: str, source: str = "App"):
        self.log("INFO", message, source)

    def action(self, message: str, source: str = "User"):
        self.log("ACTION", message, source)

    def warning(self, message: str, source: str = "Warning"):
        self.log("WARNING", message, source)

    def error(self, message: str, source: str = "Error"):
        self.log("ERROR", message, source)

    def success(self, message: str, source: str = "Success"):
        self.log("SUCCESS", message, source)

# Global singleton instance
app_logger = AppLogger.instance()
