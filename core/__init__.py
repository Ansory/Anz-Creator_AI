"""Anz-Creator core package."""
try:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from version import VERSION
    __version__ = VERSION
except Exception:
    __version__ = "dev"
