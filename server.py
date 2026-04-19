"""
Anz-Creator FastAPI Server.
Default port: 2712
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── ROOT & BUNDLE resolution ────────────────────────────────────────────────
# ROOT  = folder tempat user menjalankan app (sebelah .exe di frozen mode)
# BUNDLE = folder resource ter-bundle (_MEIPASS di frozen mode)
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT))
else:
    ROOT = Path(__file__).resolve().parent
    BUNDLE = ROOT

# Pastikan bundle bisa di-import (version.py / core/ saat frozen)
if str(BUNDLE) not in sys.path:
    sys.path.insert(0, str(BUNDLE))

# ── Load .env dari ROOT (lokasi user) ────────────────────────────────────────
load_dotenv(dotenv_path=ROOT / ".env", override=True)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("anz-creator.server")

# ── Imports internal (setelah sys.path di-set) ───────────────────────────────
from core.api_rotator import AllKeysExhaustedError, get_rotator
from core.short_maker import ShortMaker, ShortMakerOptions
from core.story_teller import StoryTeller, StoryTellerOptions

# ── Version ──────────────────────────────────────────────────────────────────
try:
    from version import VERSION
except ImportError:
    VERSION = "dev"

# ── Config ───────────────────────────────────────────────────────────────────
# Static dir: utamakan yang ada di ROOT (user replaceable), fallback ke BUNDLE
_static_root = ROOT / "static"
_static_bundle = BUNDLE / "static"
STATIC_DIR = _static_root if _static_root.exists() else _static_bundle

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(ROOT / "outputs"))).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = OUTPUT_DIR / ".uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.getenv("SERVER_PORT", "2712"))

# ── Rotator: load keys dari .env + keys.json ─────────────────────────────────
_rotator = get_rotator()


def _sync_env_keys() -> int:
    """
    Baca GEMINI_API_KEYS dari .env dan tambahkan ke rotator.
    Dipanggil saat startup. Duplikat otomatis di-skip oleh rotator.
    """
    env_keys = os.getenv("GEMINI_API_KEYS", "").strip()
    if not env_keys:
        return 0
    keys = [k.strip() for k in env_keys.split(",") if k.strip()]
    added = _rotator.add_keys(keys, label_prefix="env-")
    if added:
        logger.info(f"[startup] {added} key baru dari .env ditambahkan ke rotator")
    else:
        logger.info("[startup] Key dari .env sudah ada di rotator (tidak ada duplikat)")
    return added


_sync_env_keys()

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Anz-Creator", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_csp_header(request, call_next):
    response = await call_next(request)
    # Terapkan CSP longgar hanya untuk localhost (aplikasi desktop)
    if request.client and request.client.host == "127.0.0.1":
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' ws: wss: http: https:; "
            "frame-src 'self' https://www.youtube.com https://youtube.com; "
            "media-src 'self' blob:; "
            "worker-src 'self' blob:;"
        )
        response.headers["Content-Security-Policy"] = csp
    return response


JOBS: Dict[str, Dict[str, Any]] = {}


def _new_job() -> str:
    jid = uuid.uuid4().hex
    JOBS[jid] = {
        "id": jid,
        "status": "queued",
        "progress": [],
        "result": None,
        "error": None,
        "created_at": time.time(),
    }
    return jid


def _log_to_job(jid: str, msg: str) -> None:
    if jid in JOBS:
        JOBS[jid]["progress"].append({"t": time.time(), "msg": msg})


def _ensure_keys_available() -> None:
    r = get_rotator()
    stats = r.get_stats()
    if stats.get("total", 0) == 0:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "NO_KEYS",
                "message": "Belum ada Gemini API key. Buka menu 'API Manager' untuk menambahkan key.",
                "hint": "Dapatkan free API key di https://aistudio.google.com/app/apikey",
            },
        )
    if stats.get("active", 0) == 0:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "KEYS_EXHAUSTED",
                "message": f"Semua {stats['total']} API key sudah mencapai limit quota atau tidak valid.",
                "hint": "Free tier Gemini: 15 RPM, 1500 requests/hari per key.",
            },
        )


def _format_exception_error(e: Exception) -> Dict[str, Any]:
    tb = traceback.format_exc()
    logger.error(f"Request failed: {e}\n{tb}")
    return {
        "code": e.__class__.__name__,
        "message": str(e) or "Unknown error",
        "traceback": tb.split("\n")[-10:],
    }


# ── Schemas ───────────────────────────────────────────────────────────────────
class KeysAddBody(BaseModel):
    keys: List[str]


class KeysModeBody(BaseModel):
    mode: str


class ShortMakerBody(BaseModel):
    source: str
    source_type: str = "url"
    transform_mode: str = "blur"
    aspect: str = "9:16"
    quality: str = "1080p"
    caption_ai: bool = True
    topic: str = "free"
    duration_preset: str = "auto"
    custom_start: float = 0.0
    custom_end: float = 0.0
    encoding: str = "balanced"
    use_gpu: bool = False
    bypass_copyright: bool = False
    language: str = "id"


class StoryTellerBody(BaseModel):
    title: str
    genre: str = "Drama"
    style: str = "Dramatis"
    length: str = "medium"
    language: str = "id"
    tts_voice: str = "female"
    tts_speed: str = "normal"
    bgm_mood: str = "epic"
    aspect: str = "9:16"
    quality: str = "1080p"
    use_footage: bool = True


class FindViralBody(BaseModel):
    source: str
    source_type: str = "url"
    topic: str = "free"
    language: str = "id"


# ── System endpoints ──────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "online", "version": VERSION, "port": PORT}


@app.get("/api/system/resources")
def system_resources():
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": round(cpu, 1),
        "ram_percent": round(mem.percent, 1),
        "ram_used_gb": round(mem.used / (1024 ** 3), 2),
        "ram_total_gb": round(mem.total / (1024 ** 3), 2),
    }


def _exit_process() -> None:
    """Shutdown proses secara cross-platform."""
    try:
        sig = getattr(signal, "SIGTERM", None)
        if sig is not None and os.name != "nt":
            os.kill(os.getpid(), sig)
            return
    except Exception:
        pass
    os._exit(0)


@app.post("/api/system/shutdown")
async def system_shutdown():
    async def _do():
        await asyncio.sleep(0.6)
        _exit_process()

    asyncio.create_task(_do())
    return {"ok": True, "message": "Server shutting down..."}


def _restart_command() -> list[str]:
    """
    Bangun command untuk re-spawn server:
    - Frozen (.exe): jalankan .exe lagi (single file launcher)
    - Dev: python server.py
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve())]


@app.post("/api/system/restart")
async def system_restart():
    async def _do():
        await asyncio.sleep(0.6)
        try:
            kwargs: Dict[str, Any] = {"cwd": str(ROOT)}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(
                    subprocess, "DETACHED_PROCESS", 0x00000008
                ) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen(_restart_command(), **kwargs)
        except Exception as e:
            logger.error(f"Restart spawn failed: {e}")
        await asyncio.sleep(1.2)
        _exit_process()

    asyncio.create_task(_do())
    return {"ok": True, "message": "Server restarting..."}


# ── Keys ──────────────────────────────────────────────────────────────────────
@app.get("/api/keys")
def list_keys():
    r = get_rotator()
    return {"keys": r.list_keys_public(), "stats": r.get_stats(), "mode": r.get_mode()}


@app.post("/api/keys/add")
def add_keys(body: KeysAddBody):
    r = get_rotator()
    added = r.add_keys(body.keys)
    return {"added": added, "stats": r.get_stats()}


@app.post("/api/keys/import")
async def import_keys_file(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="ignore")
    keys = [line.strip() for line in content.splitlines() if line.strip()]
    r = get_rotator()
    added = r.add_keys(keys)
    return {"added": added, "stats": r.get_stats()}


@app.delete("/api/keys/{masked}")
def remove_key(masked: str):
    r = get_rotator()
    ok = r.remove_key(masked)
    return {"removed": ok, "stats": r.get_stats()}


@app.post("/api/keys/clear")
def clear_keys():
    r = get_rotator()
    n = r.clear_all()
    return {"cleared": n}


@app.post("/api/keys/mode")
def set_mode(body: KeysModeBody):
    r = get_rotator()
    try:
        r.set_mode(body.mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"mode": r.get_mode()}


# ── Upload ────────────────────────────────────────────────────────────────────
@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "Filename kosong.")
    safe = f"{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    dst = UPLOAD_DIR / safe
    with open(dst, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": str(dst), "name": file.filename, "size": dst.stat().st_size}


# ── Short Maker ───────────────────────────────────────────────────────────────
@app.post("/api/short-maker/find-viral")
def short_maker_find_viral(body: FindViralBody):
    _ensure_keys_available()
    if not body.source or not body.source.strip():
        raise HTTPException(
            400,
            detail={"code": "MISSING_SOURCE", "message": "URL YouTube atau file path wajib diisi."},
        )
    sm = ShortMaker(get_rotator(), OUTPUT_DIR)
    try:
        result = sm.find_viral_moments(body.source, body.source_type, body.topic, body.language)
        return {"ok": True, "data": result}
    except AllKeysExhaustedError as e:
        raise HTTPException(503, detail={"code": "KEYS_EXHAUSTED", "message": str(e)})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=_format_exception_error(e))


@app.post("/api/short-maker/start")
async def short_maker_start(body: ShortMakerBody):
    _ensure_keys_available()
    jid = _new_job()

    async def run():
        JOBS[jid]["status"] = "running"
        try:
            opts = ShortMakerOptions(**body.model_dump())
            sm = ShortMaker(get_rotator(), OUTPUT_DIR)
            result = await asyncio.to_thread(sm.process, opts, lambda m: _log_to_job(jid, m))
            JOBS[jid]["result"] = {
                "output_path": result.output_path,
                "output_url": _to_url(result.output_path),
                "thumbnail_url": _to_url(result.thumbnail_path),
                "title": result.title,
                "description": result.description,
                "tags": result.tags,
                "pinned_comment": result.pinned_comment,
                "duration": result.duration,
                "start_seconds": result.start_seconds,
                "end_seconds": result.end_seconds,
            }
            JOBS[jid]["status"] = "done"
        except Exception as e:
            logger.error(f"[short-maker] {e}\n{traceback.format_exc()}")
            JOBS[jid]["status"] = "error"
            JOBS[jid]["error"] = str(e) or e.__class__.__name__

    asyncio.create_task(run())
    return {"job_id": jid}


# ── Story Teller ──────────────────────────────────────────────────────────────
@app.post("/api/story-teller/preview")
def story_preview(body: StoryTellerBody):
    _ensure_keys_available()
    if not body.title or not body.title.strip():
        raise HTTPException(
            400,
            detail={"code": "MISSING_TITLE", "message": "Judul/topik cerita wajib diisi."},
        )
    st = StoryTeller(
        get_rotator(),
        OUTPUT_DIR,
        pexels_key=os.getenv("PEXELS_API_KEY", ""),
        pixabay_key=os.getenv("PIXABAY_API_KEY", ""),
    )
    try:
        opts = StoryTellerOptions(**body.model_dump())
        scenes = st.preview_script(opts)
        return {"ok": True, "scenes": scenes}
    except AllKeysExhaustedError as e:
        raise HTTPException(503, detail={"code": "KEYS_EXHAUSTED", "message": str(e)})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=_format_exception_error(e))


@app.post("/api/story-teller/start")
async def story_start(body: StoryTellerBody):
    _ensure_keys_available()
    jid = _new_job()

    async def run():
        JOBS[jid]["status"] = "running"
        try:
            opts = StoryTellerOptions(**body.model_dump())
            st = StoryTeller(
                get_rotator(),
                OUTPUT_DIR,
                pexels_key=os.getenv("PEXELS_API_KEY", ""),
                pixabay_key=os.getenv("PIXABAY_API_KEY", ""),
            )
            result = await asyncio.to_thread(st.process, opts, lambda m: _log_to_job(jid, m))
            JOBS[jid]["result"] = {
                "output_path": result.output_path,
                "output_url": _to_url(result.output_path),
                "thumbnail_url": _to_url(result.thumbnail_path),
                "script": result.script,
                "scenes": result.scenes,
                "duration": result.duration,
            }
            JOBS[jid]["status"] = "done"
        except Exception as e:
            logger.error(f"[story-teller] {e}\n{traceback.format_exc()}")
            JOBS[jid]["status"] = "error"
            JOBS[jid]["error"] = str(e) or e.__class__.__name__

    asyncio.create_task(run())
    return {"job_id": jid}


# ── Job ───────────────────────────────────────────────────────────────────────
@app.get("/api/job/{jid}")
def job_status(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "Job tidak ditemukan.")
    job = JOBS[jid]
    return {
        "id": job["id"],
        "status": job["status"],
        "progress": job["progress"][-30:],
        "result": job["result"],
        "error": job["error"],
    }


@app.websocket("/ws/job/{jid}")
async def job_ws(ws: WebSocket, jid: str):
    await ws.accept()
    last_idx = 0
    try:
        while True:
            if jid not in JOBS:
                await ws.send_json({"status": "error", "error": "Job not found"})
                break
            job = JOBS[jid]
            new_logs = job["progress"][last_idx:]
            last_idx = len(job["progress"])
            await ws.send_json(
                {
                    "status": job["status"],
                    "logs": new_logs,
                    "result": job["result"],
                    "error": job["error"],
                }
            )
            if job["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.8)
    except WebSocketDisconnect:
        return


# ── Outputs ───────────────────────────────────────────────────────────────────
@app.get("/api/outputs")
def list_outputs():
    items = []
    for p in sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        items.append(
            {
                "name": p.name,
                "url": _to_url(str(p)),
                "size_mb": round(p.stat().st_size / (1024 ** 2), 2),
                "modified": p.stat().st_mtime,
            }
        )
    return {"items": items}


@app.get("/files/{name:path}")
def serve_file(name: str):
    # Mencegah path traversal
    safe = (OUTPUT_DIR / name).resolve()
    try:
        safe.relative_to(OUTPUT_DIR)
    except ValueError:
        raise HTTPException(400, "Path tidak valid.")
    if not safe.exists() or not safe.is_file():
        raise HTTPException(404, "File tidak ditemukan.")
    return FileResponse(safe)


def _to_url(path_str: str) -> str:
    if not path_str:
        return ""
    p = Path(path_str)
    try:
        rel = p.resolve().relative_to(OUTPUT_DIR)
        return f"/files/{rel.as_posix()}"
    except ValueError:
        return ""


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    fav = STATIC_DIR / "favicon.ico"
    if fav.exists():
        return FileResponse(fav, media_type="image/x-icon")
    return Response(status_code=204)


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    logger.warning(f"STATIC_DIR tidak ditemukan: {STATIC_DIR}")


if __name__ == "__main__":
    import uvicorn

    banner = (
        "\n"
        "+----------------------------------------------+\n"
        "|     ANZ-CREATOR  //  AI CONTENT STUDIO       |\n"
        f"|     Port    : {PORT:<30} |\n"
        f"|     URL     : http://localhost:{PORT:<13} |\n"
        f"|     Version : {VERSION:<30} |\n"
        "+----------------------------------------------+\n"
    )
    print(banner)
    uvicorn.run("server:app", host="127.0.0.1", port=PORT, log_level="info")
