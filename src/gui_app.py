#!/usr/bin/env python3
"""Launcher for the Local LLM Movie Renamer PyQt6 GUI."""

import sys
from pathlib import Path

# Ensure 'src' directory is in Python module search path
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from gui.app import run_app

if __name__ == "__main__":
    sys.exit(run_app())
