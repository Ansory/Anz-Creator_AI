"""
Anz-Creator Launcher.
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


def ensure_env_file(root: Path) -> None:
    """
    Auto-setup .env dari .env.example kalau .env belum ada.
    Dijalankan sekali saat pertama kali exe dibuka.
    """
    env_path = root / ".env"
    example_path = root / ".env.example"

    if env_path.exists():
        log.info(f".env sudah ada: {env_path}")
        return

    # Coba copy dari .env.example
    if example_path.exists():
        import shutil
        shutil.copy(example_path, env_path)
        log.info(f".env dibuat dari .env.example: {env_path}")
        return

    # Fallback: buat .env minimal dari bundle
    bundle = bundle_root()
    bundle_example = bundle / ".env.example"
    if bundle_example.exists():
        import shutil
        shutil.copy(bundle_example, env_path)
        log.info(f".env dibuat dari bundle .env.example: {env_path}")
        return

    # Last resort: tulis default minimal
    log.warning(".env.example tidak ditemukan, membuat .env default...")
    env_path.write_text(
        "# === ANZ-CREATOR Environment Variables ===\n\n"
        "# Gemini API Keys (isi di sini atau via menu API Manager di aplikasi)\n"
        "GEMINI_API_KEYS=\n\n"
        "# Pexels API Key (https://www.pexels.com/api/)\n"
        "PEXELS_API_KEY=\n\n"
        "# Pixabay API Key (https://pixabay.com/api/docs/)\n"
        "PIXABAY_API_KEY=\n\n"
        "# Server port\n"
        "SERVER_PORT=2712\n\n"
        "# Output directory\n"
        "OUTPUT_DIR=./outputs\n",
        encoding="utf-8",
    )
    log.info(f".env default dibuat: {env_path}")


def read_port_from_env(root: Path) -> int:
    """Baca SERVER_PORT dari .env, fallback ke 2712."""
    env_path = root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SERVER_PORT="):
                try:
                    return int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
    return int(os.getenv("SERVER_PORT", "2712"))


def wait_for_server(port: int, timeout: float = 25.0) -> bool:
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
                log.info(f"Opened Chrome: {path}")
                return
            except Exception as e:
                log.warning(f"Failed Chrome at {path}: {e}")
    log.info("Chrome not found, using default browser")
    webbrowser.open(url, new=2)


def run_server(port: int) -> None:
    try:
        bundle = bundle_root()
        if str(bundle) not in sys.path:
            sys.path.insert(0, str(bundle))

        os.chdir(str(app_root()))
        os.environ["SERVER_PORT"] = str(port)

        log.info(f"Starting server port={port} bundle={bundle} cwd={os.getcwd()}")

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

        log.info("=" * 60)
        log.info("Anz-Creator Launcher starting")
        log.info(f"App root : {root}")
        log.info(f"Bundle   : {bundle_root()}")
        log.info(f"Python   : {sys.executable}")
        log.info(f"Frozen   : {getattr(sys, 'frozen', False)}")
        log.info("=" * 60)

        # ── AUTO-SETUP .env ──────────────────────────────────────
        # Kalau .env belum ada, buat otomatis dari .env.example
        ensure_env_file(root)

        # ── BACA PORT ────────────────────────────────────────────
        port = read_port_from_env(root)
        log.info(f"Port: {port}")

        # ── START SERVER ─────────────────────────────────────────
        server_thread = threading.Thread(
            target=run_server,
            args=(port,),
            daemon=True,
            name="anz-server",
        )
        server_thread.start()

        # ── TUNGGU SIAP ──────────────────────────────────────────
        if wait_for_server(port, timeout=25.0):
            log.info(f"✓ Server ready → http://localhost:{port}")
            open_chrome(f"http://localhost:{port}")
        else:
            log.error("Server timeout")
            show_error_dialog(
                "Anz-Creator: Startup Timeout",
                f"Server tidak bisa start di port {port} dalam 25 detik.\n\n"
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
            log.info("Keyboard interrupt")

        return 0

    except Exception as e:
        log.error(f"Fatal: {e}\n{traceback.format_exc()}")
        show_error_dialog(
            "Anz-Creator: Fatal Error",
            f"Error fatal saat startup:\n\n{e}\n\nCek launcher.log untuk detail.",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
