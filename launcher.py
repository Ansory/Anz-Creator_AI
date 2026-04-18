"""
Anz-Creator Launcher.
Dijalankan oleh user setelah di-compile ke Anz-Creator.exe via PyInstaller.
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


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent


LOG_FILE = app_root() / "launcher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")],
)
log = logging.getLogger("anz-creator")


def show_error_dialog(title: str, message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        except Exception:
            pass


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
    log.info("Chrome not found, using default browser")
    webbrowser.open(url, new=2)


def run_server(port: int) -> None:
    try:
        bundle = bundle_root()
        if str(bundle) not in sys.path:
            sys.path.insert(0, str(bundle))

        os.chdir(str(app_root()))
        os.environ["SERVER_PORT"] = str(port)

        log.info(f"Starting server on port {port} (bundle={bundle}, cwd={os.getcwd()})")

        import server as server_module  # noqa
        import uvicorn

        config = uvicorn.Config(
            server_module.app,
            host="127.0.0.1",
            port=port,
            log_config=None,
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
        os._exit(1)


def main() -> int:
    try:
        root = app_root()

        # FIX: default port 2712, baca dari .env dulu kalau ada
        env_file = root / ".env"
        port = 2712  # default
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("SERVER_PORT="):
                    try:
                        port = int(line.split("=", 1)[1].strip())
                    except ValueError:
                        pass
                    break
        # env var override
        port = int(os.getenv("SERVER_PORT", str(port)))

        log.info("=" * 60)
        log.info("Anz-Creator Launcher starting")
        log.info(f"App root: {root}")
        log.info(f"Bundle root: {bundle_root()}")
        log.info(f"Python: {sys.executable}")
        log.info(f"Frozen: {getattr(sys, 'frozen', False)}")
        log.info(f"Port: {port}")
        log.info("=" * 60)

        server_thread = threading.Thread(
            target=run_server,
            args=(port,),
            daemon=True,
            name="anz-server",
        )
        server_thread.start()

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
