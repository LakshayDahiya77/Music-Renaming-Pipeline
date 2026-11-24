"""Ollama server manager, cross-platform detector, and resource monitor for Linux & Windows."""

import os
import platform
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import httpx
import psutil

class ModelService:
    """Manages the local Ollama daemon, cross-platform binary detection, installation guidance,
    and tracks CPU/RAM usage of inference processes.
    
    Local LLM is completely optional.
    """

    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host.rstrip("/")
        self._server_process: Optional[subprocess.Popen] = None
        self.is_enabled: bool = False  # Local LLM is optional and not default

    @property
    def os_type(self) -> str:
        """Returns 'windows', 'linux', or 'macos'."""
        system = platform.system().lower()
        if "windows" in system:
            return "windows"
        elif "darwin" in system:
            return "macos"
        return "linux"

    def find_ollama_binary(self) -> Optional[str]:
        """Locates the Ollama executable across Linux and Windows default installation locations."""
        which_path = shutil.which("ollama")
        if which_path and os.path.isfile(which_path):
            return which_path

        if self.os_type == "windows":
            candidates = [
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Ollama" / "ollama.exe",
                Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Ollama" / "ollama.exe",
                Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
            ]
            for cand in candidates:
                if cand.is_file():
                    return str(cand)
        else:  # Linux / macOS
            candidates = [
                Path("/usr/local/bin/ollama"),
                Path("/usr/bin/ollama"),
                Path.home() / ".local" / "bin" / "ollama",
                Path("/var/lib/flatpak/exports/bin/ollama"),
            ]
            for cand in candidates:
                if cand.is_file() and os.access(cand, os.X_OK):
                    return str(cand)

        return None

    def is_ollama_installed(self) -> bool:
        """Checks if the Ollama executable exists on disk."""
        return self.find_ollama_binary() is not None

    def get_installation_instructions(self) -> Dict[str, str]:
        """Returns platform-specific setup instructions and one-click commands."""
        if self.os_type == "windows":
            return {
                "os": "Windows",
                "quick_command": "winget install Ollama.Ollama",
                "download_url": "https://ollama.com/download/OllamaSetup.exe",
                "instructions": (
                    "1. Install via Windows Terminal: run 'winget install Ollama.Ollama'\n"
                    "   OR download the Windows installer from https://ollama.com/download/windows\n"
                    "2. Run Ollama from the Start Menu or command prompt: 'ollama serve'\n"
                    "3. Recommended music models: 'ollama pull qwen2.5:14b' or 'ollama pull qwen2.5:7b'"
                ),
            }
        else:
            return {
                "os": "Linux",
                "quick_command": "curl -fsSL https://ollama.com/install.sh | sh",
                "download_url": "https://ollama.com/download/linux",
                "instructions": (
                    "1. Quick install: run in terminal:\n"
                    "   curl -fsSL https://ollama.com/install.sh | sh\n"
                    "2. Start the service: 'ollama serve' or 'systemctl start ollama'\n"
                    "3. Recommended music models: 'ollama pull qwen2.5:14b' or 'ollama pull qwen2.5:7b'"
                ),
            }

    def is_server_running(self) -> bool:
        """Checks if the Ollama HTTP server is responsive."""
        try:
            resp = httpx.get(f"{self.host}/api/version", timeout=1.0)
            return resp.status_code == 200
        except Exception:
            return False

    def get_server_version(self) -> str:
        """Queries server version string."""
        try:
            resp = httpx.get(f"{self.host}/api/version", timeout=1.0)
            if resp.status_code == 200:
                return resp.json().get("version", "Unknown")
        except Exception:
            pass
        return "Offline"

    def get_loaded_models(self) -> List[str]:
        """Queries Ollama for currently loaded in-memory models."""
        try:
            resp = httpx.get(f"{self.host}/api/ps", timeout=1.5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                return [m.get("name", "") for m in models if m.get("name")]
        except Exception:
            pass
        return []

    def get_available_models(self) -> List[str]:
        """Queries Ollama for installed models on disk."""
        try:
            resp = httpx.get(f"{self.host}/api/tags", timeout=1.5)
            if resp.status_code == 200:
                data = resp.json()
                return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            pass
        return ["qwen2.5:14b", "qwen2.5:7b", "llama3.2:latest"]

    def start_server(self) -> Tuple[bool, str]:
        """Starts the Ollama background daemon."""
        if self.is_server_running():
            return True, "Ollama server is already running."

        ollama_bin = self.find_ollama_binary()
        if not ollama_bin:
            return False, "Ollama executable not found. Please install Ollama first using the instructions below."

        env = os.environ.copy()
        if self.os_type != "windows":
            custom_bin_dir = str(Path.home() / ".local" / "bin")
            if custom_bin_dir not in env.get("PATH", ""):
                env["PATH"] = f"{custom_bin_dir}:{env.get('PATH', '')}"

        try:
            creationflags = 0
            if self.os_type == "windows":
                creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

            self._server_process = subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=(self.os_type != "windows"),
                creationflags=creationflags,
            )

            # Wait up to 5s for response
            for _ in range(25):
                time.sleep(0.2)
                if self.is_server_running():
                    return True, "Ollama server started successfully."

            return False, "Ollama launched but did not respond on localhost:11434 within 5s."
        except Exception as e:
            return False, f"Failed to start Ollama ({ollama_bin}): {e}"

    def stop_server(self) -> Tuple[bool, str]:
        """Stops the Ollama server and frees in-memory models."""
        terminated_count = 0
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info["name"] or "").lower()
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                if "ollama" in name or "llama-server" in name or "llama-server" in cmdline:
                    proc.send_signal(signal.SIGTERM)
                    terminated_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        time.sleep(0.5)
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info["name"] or "").lower()
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                if "ollama" in name or "llama-server" in name or "llama-server" in cmdline:
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        self._server_process = None
        return True, f"Stopped Ollama and {terminated_count} process(es)."

    def preload_model(self, model_name: str) -> Tuple[bool, str]:
        """Pre-loads model weights into RAM."""
        if not self.is_server_running():
            ok, msg = self.start_server()
            if not ok:
                return False, msg

        try:
            resp = httpx.post(
                f"{self.host}/api/generate",
                json={"model": model_name, "prompt": "", "keep_alive": "60m"},
                timeout=60.0,
            )
            if resp.status_code == 200:
                return True, f"Model '{model_name}' pre-loaded into memory."
            return False, f"Ollama error {resp.status_code}: {resp.text}"
        except Exception as e:
            return False, f"Failed to load model '{model_name}': {e}"

    def unload_model(self, model_name: str) -> Tuple[bool, str]:
        """Unloads model weights from memory."""
        if not self.is_server_running():
            return True, "Server is offline; model already unloaded."
        try:
            resp = httpx.post(
                f"{self.host}/api/generate",
                json={"model": model_name, "prompt": "", "keep_alive": 0},
                timeout=10.0,
            )
            if resp.status_code == 200:
                return True, f"Model '{model_name}' evicted from memory."
            return False, f"Failed to unload: {resp.text}"
        except Exception as e:
            return False, f"Error unloading model: {e}"

    def get_resource_stats(self) -> Dict[str, Any]:
        """Returns live CPU %, RAM MB, and system memory stats for inference."""
        server_up = self.is_server_running()
        loaded_models = self.get_loaded_models() if server_up else []

        model_cpu_percent = 0.0
        model_ram_rss = 0

        for proc in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent", "memory_info"]):
            try:
                name = (proc.info["name"] or "").lower()
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                if "ollama" in name or "llama-server" in name or "llama-server" in cmdline:
                    model_cpu_percent += proc.info["cpu_percent"] or 0.0
                    mem_info = proc.info.get("memory_info")
                    if mem_info:
                        model_ram_rss += mem_info.rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        sys_mem = psutil.virtual_memory()

        return {
            "server_running": server_up,
            "ollama_installed": self.is_ollama_installed(),
            "binary_path": self.find_ollama_binary() or "Not Found",
            "server_version": self.get_server_version() if server_up else "Offline",
            "loaded_models": loaded_models,
            "model_cpu_percent": round(model_cpu_percent, 1),
            "model_ram_bytes": model_ram_rss,
            "model_ram_gb": round(model_ram_rss / (1024 ** 3), 2),
            "model_ram_percent": round((model_ram_rss / sys_mem.total) * 100, 1) if sys_mem.total else 0.0,
            "sys_ram_total_gb": round(sys_mem.total / (1024 ** 3), 2),
            "sys_ram_used_gb": round(sys_mem.used / (1024 ** 3), 2),
            "sys_ram_available_gb": round(sys_mem.available / (1024 ** 3), 2),
            "sys_ram_percent": sys_mem.percent,
        }
