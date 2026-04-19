"""
Anz-Creator Launcher.
Auto start server + open browser.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path


def app_root() -> Path:
    """Folder tempat user menjalankan app (sebelah .exe di frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundle_root() -> Path:
    """Folder resource ter-bundle (_MEIPASS di frozen)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", str(app_root())))
    return Path(__file__).resolve().parent


LOG_FILE = app_root() / "launcher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("anz-creator")


def show_error_dialog(title: str, message: str) -> None:
    """Dialog error cross-platform, tapi utamanya untuk Windows."""
    # Coba tkinter dulu (kalau tersedia)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
        return
    except Exception:
        pass
    # Fallback: MessageBox Windows
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
            return
        except Exception:
            pass
    # Fallback terakhir: print
    print(f"[{title}] {message}", file=sys.stderr)


def ensure_env_file(root: Path) -> None:
    """Auto-setup .env dari .env.example kalau belum ada."""
    env_path = root / ".env"
    if env_path.exists():
        log.info(f".env sudah ada: {env_path}")
        return

    import shutil

    for cand in (root / ".env.example", bundle_root() / ".env.example"):
        if cand.exists():
            shutil.copy(cand, env_path)
            log.info(f".env dibuat dari {cand}")
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
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("SERVER_PORT="):
                    return int(line.split("=", 1)[1].strip())
        except (ValueError, OSError):
            pass
    try:
        return int(os.getenv("SERVER_PORT", "2712"))
    except ValueError:
        return 2712


def wait_for_server(port: int, timeout: float = 25.0) -> bool:
    import urllib.error
    import urllib.request

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


def open_browser(url: str) -> None:
    """Open Chrome di Windows, fallback default browser."""
    if os.name == "nt":
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
    log.info("Falling back to default browser")
    try:
        webbrowser.open(url, new=2)
    except Exception as e:
        log.warning(f"Open browser failed: {e}")


def run_server(port: int) -> None:
    try:
        bundle = bundle_root()
        if str(bundle) not in sys.path:
            sys.path.insert(0, str(bundle))

        os.chdir(str(app_root()))
        os.environ["SERVER_PORT"] = str(port)

        log.info(f"Starting server port={port} bundle={bundle} cwd={os.getcwd()}")

        import uvicorn

        import server as server_module  # noqa: F401

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

        ensure_env_file(root)

        port = read_port_from_env(root)
        log.info(f"Port: {port}")

        server_thread = threading.Thread(
            target=run_server,
            args=(port,),
            daemon=True,
            name="anz-server",
        )
        server_thread.start()

        if wait_for_server(port, timeout=25.0):
            log.info(f"Server ready -> http://localhost:{port}")
            open_browser(f"http://localhost:{port}")
        else:
            log.error("Server timeout")
            show_error_dialog(
                "Anz-Creator: Startup Timeout",
                f"Server tidak bisa start di port {port} dalam 25 detik.\n\n"
                f"Kemungkinan penyebab:\n"
                f"  - Port {port} sudah dipakai aplikasi lain\n"
                f"  - Firewall blocking localhost\n"
                f"  - File .env bermasalah\n\n"
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
