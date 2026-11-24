#!/usr/bin/env bash
# ==============================================================================
# Local LLM Music Renaming & Tagging Pipeline - Linux Launcher
# Launches the PyQt6 GUI application using the local environment.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure local user bin is on PATH for Ollama
if [ -d "$HOME/.local/bin" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi

# Detect Python environment
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "[ERROR] Python was not found on your system."
    echo "Please install Python 3.10+ or set up the virtual environment in .venv."
    exit 1
fi

# Add modular source code directory to Python module search path
export PYTHONPATH="$SCRIPT_DIR/src:${PYTHONPATH:-}"

# Launch PyQt6 GUI
exec "$PYTHON_BIN" "$SCRIPT_DIR/src/gui_app.py" "$@"
