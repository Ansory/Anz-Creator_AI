"""Anz-Creator core package."""
from __future__ import annotations

import sys
from pathlib import Path

# Memastikan root project terdeteksi aman
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    # Coba baca version langsung dari file jika module gagal
    version_file = _root / "version.py"
    if version_file.exists():
        with open(version_file, "r", encoding="utf-8") as f:
            exec(f.read())
    else:
        __version__ = "1.0.0"
except Exception:
    __version__ = "dev"
