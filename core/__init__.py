"""Anz-Creator core package."""
from __future__ import annotations

import sys
from pathlib import Path

# Pastikan root project dapat di-import (untuk akses version.py)
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from version import VERSION as __version__
except Exception:
    __version__ = "dev"
