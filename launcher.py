"""
Anz-Creator Launcher.
Dijalankan oleh user setelah di-compile ke Anz-Creator.exe via PyInstaller.

Flow:
  1. Start FastAPI server sebagai subprocess
  2. Tunggu sampai server ready (polling http://localhost:PORT/api/health)
  3. Buka browser Chrome ke localhost
  4. Tunggu server selesai (user close window)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ketika di-bundle PyInstaller, _MEIPASS berisi path extract
def app_root() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller bundle
        return Path(sys.executable).parent
    return Path(__file__).parent


def wait_for_server(port: int, timeout: float = 15.0) -> bool:
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
                return
            except Exception:
                continue
    # fallback: browser default
    webbrowser.open(url, new=2)


def main() -> int:
    root = app_root()
    port = int(os.getenv("SERVER_PORT", "8080"))

    server_script = root / "server.py"
    if not server_script.exists():
        print(f"[ERROR] server.py tidak ditemukan di {root}")
        input("Tekan Enter untuk keluar...")
        return 1

    print("┌─────────────────────────────────────────┐")
    print("│  ANZ-CREATOR :: Booting server...       │")
    print("└─────────────────────────────────────────┘")

    python_exec = sys.executable
    # Start uvicorn via server.py
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    proc = subprocess.Popen(
        [python_exec, str(server_script)],
        cwd=str(root),
        creationflags=creationflags,
    )

    try:
        if wait_for_server(port):
            print(f"✓ Server ready at http://localhost:{port}")
            open_chrome(f"http://localhost:{port}")
        else:
            print("[WARN] Server belum ready, mencoba buka browser anyway...")
            open_chrome(f"http://localhost:{port}")
        proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    return proc.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
