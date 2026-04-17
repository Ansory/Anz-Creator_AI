"""
Anz-Creator Launcher.
Dijalankan oleh user setelah di-compile ke Anz-Creator.exe via PyInstaller.

Flow:
  1. Start FastAPI server di thread terpisah (in-process, bukan subprocess)
  2. Tunggu sampai server ready (polling http://localhost:PORT/api/health)
  3. Buka browser Chrome ke localhost
  4. Server berjalan sampai user tutup app (tray icon / kill process)

PENTING:
- Tidak boleh ada input() atau print() ke stdout karena --noconsole tidak punya stdin/stdout
- Semua log → ke file launcher.log di folder exe
- Error fatal → ditampilkan via tkinter messagebox
"""
from __future__ import annotations

import os
import sys
import time
import logging
import threading
import traceback
import webbrowser
from pathlib import Path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def app_root() -> Path:
    """Lokasi folder exe (atau script saat dev mode)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def bundle_root() -> Path:
    """Lokasi file-file yang di-bundle PyInstaller (--add-data extract di _MEIPASS)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent


# ---------------------------------------------------------------------------
# Logging setup (file-based, no stdout)
# ---------------------------------------------------------------------------
LOG_FILE = app_root() / "launcher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
    ],
)
log = logging.getLogger("anz-creator")


# ---------------------------------------------------------------------------
# Error dialog (used when something fatal happens in --noconsole mode)
# ---------------------------------------------------------------------------
def show_error_dialog(title: str, message: str) -> None:
    """Show native Windows error dialog. Safe to call from --noconsole exe."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        # last-resort fallback to Win32 MessageBox via ctypes
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        except Exception:
            pass  # nothing more we can do


# ---------------------------------------------------------------------------
# Server readiness check
# ---------------------------------------------------------------------------
def wait_for_server(port: int, timeout: float = 20.0) -> bool:
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Chrome browser opening
# ---------------------------------------------------------------------------
def open_chrome(url: str) -> None:
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in chrome_paths:
        if path and os.path.exists(path):
            try:
                webbrowser.register("chrome", None, webbrowser.BackgroundBrowser(path))
                webbrowser.get("chrome").open(url, new=2)
                log.info(f"Opened Chrome at {path}")
                return
            except Exception as e:
                log.warning(f"Failed to open Chrome at {path}: {e}")
                continue

    # fallback: default browser
    log.info("Chrome not found, using default browser")
    webbrowser.open(url, new=2)


# ---------------------------------------------------------------------------
# Server runner (in-process, runs in separate thread)
# ---------------------------------------------------------------------------
def run_server(port: int) -> None:
    """
    Import server module and run uvicorn in this process.
    Saat di-bundle PyInstaller --onefile, server.py sudah di-extract ke _MEIPASS,
    jadi kita perlu sys.path.insert supaya bisa di-import.
    """
    try:
        # ensure bundled modules are importable
        bundle = bundle_root()
        if str(bundle) not in sys.path:
            sys.path.insert(0, str(bundle))

        # set working directory to app_root (so outputs/, .env etc are beside exe)
        os.chdir(str(app_root()))

        # Set port via env var (server.py reads SERVER_PORT)
        os.environ["SERVER_PORT"] = str(port)

        log.info(f"Starting server on port {port} (bundle={bundle}, cwd={os.getcwd()})")

        # Import server module — this triggers FastAPI app creation
        import server as server_module  # noqa

        # Run uvicorn programmatically
        import uvicorn

        config = uvicorn.Config(
            server_module.app,
            host="127.0.0.1",
            port=port,
            log_config=None,   # avoid uvicorn messing with our logging
            access_log=False,
        )
        uv_server = uvicorn.Server(config)
        uv_server.run()

    except Exception as e:
        log.error(f"Server crashed: {e}\n{traceback.format_exc()}")
        show_error_dialog(
            "Anz-Creator: Server Error",
            f"Server gagal berjalan:\n\n{e}\n\nCek launcher.log untuk detail.",
        )
        # force-exit the whole process so the browser tab isn't left hanging
        os._exit(1)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def main() -> int:
    try:
        root = app_root()
        port = int(os.getenv("SERVER_PORT", "8080"))

        log.info("=" * 60)
        log.info("Anz-Creator Launcher starting")
        log.info(f"App root: {root}")
        log.info(f"Bundle root: {bundle_root()}")
        log.info(f"Python: {sys.executable}")
        log.info(f"Frozen: {getattr(sys, 'frozen', False)}")
        log.info(f"Port: {port}")
        log.info("=" * 60)

        # Start server in background thread (daemon so it dies with main)
        server_thread = threading.Thread(
            target=run_server,
            args=(port,),
            daemon=True,
            name="anz-server",
        )
        server_thread.start()

        # Wait for server to be reachable
        if wait_for_server(port, timeout=20.0):
            log.info(f"✓ Server ready at http://localhost:{port}")
            open_chrome(f"http://localhost:{port}")
        else:
            log.error("Server timeout — tidak ready dalam 20 detik")
            show_error_dialog(
                "Anz-Creator: Startup Timeout",
                f"Server tidak bisa start di port {port} dalam 20 detik.\n\n"
                f"Kemungkinan penyebab:\n"
                f"  • Port {port} sudah dipakai aplikasi lain\n"
                f"  • Firewall blocking localhost\n"
                f"  • File .env bermasalah\n\n"
                f"Cek launcher.log di folder exe untuk detail.",
            )
            return 1

        # Keep launcher alive — server thread is daemon, so we need to block here
        # This blocks until the server thread dies (user closes app via task manager,
        # tray icon, or OS signal)
        try:
            while server_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Keyboard interrupt, shutting down")

        return 0

    except Exception as e:
        log.error(f"Fatal error in main(): {e}\n{traceback.format_exc()}")
        show_error_dialog(
            "Anz-Creator: Fatal Error",
            f"Terjadi error fatal saat startup:\n\n{e}\n\n"
            f"Cek launcher.log di folder exe untuk detail.",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
