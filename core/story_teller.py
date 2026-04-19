"""
Text to Story Telling — Ubah teks/topik jadi video storytelling cinematic.
"""
from __future__ import annotations

import os, re, shutil, sys, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import requests

from . import ffmpeg_utils as ff
from .api_rotator import APIKeyRotator
from .gemini_client import GeminiClient

GENRES = ["Romance", "Thriller", "Motivasi", "Horor", "Drama", "Edukasi", "Komedi"]
STYLES = ["Formal", "Santai", "Dramatis", "Puitis"]
LENGTH_PRESETS = {"short": (60, 6), "medium": (180, 15), "long": (300, 25)}
BGM_MOOD_ALIASES = {"epic": ["epic", "cinematic", "action"], "sad": ["sad", "dark", "emotional"], "calm": ["calm", "romantic", "soft"], "upbeat": ["upbeat", "happy", "motivational"], "none": []}

@dataclass
class StoryTellerOptions:
    title: str; genre: str = "Drama"; style: str = "Dramatis"; length: str = "medium"; language: str = "id"; tts_voice: str = "female"; tts_speed: str = "normal"; bgm_mood: str = "epic"; aspect: str = "9:16"; quality: str = "1080p"; use_footage: bool = True

@dataclass
class Scene:
    index: int; text: str; keyword: str; duration: float = 0.0; footage_path: Optional[str] = None; audio_path: Optional[str] = None; rendered_path: Optional[str] = None

@dataclass
class StoryResult:
    output_path: str; thumbnail_path: str; script: str; scenes: List[Dict] = field(default_factory=list); duration: float = 0.0

class StoryTeller:
    def __init__(self, rotator: APIKeyRotator, output_dir: str | Path = "outputs", pexels_key: str = "", pixabay_key: str = ""):
        self.rotator = rotator; self.gemini = GeminiClient(rotator)
        self.output_dir = Path(output_dir); self.output_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir = self.output_dir / ".work"; self.work_dir.mkdir(exist_ok=True)
        self.pexels_key = pexels_key or os.getenv("PEXELS_API_KEY", "")
        self.pixabay_key = pixabay_key or os.getenv("PIXABAY_API_KEY", "")

    def _generate_script(self, opts: StoryTellerOptions) -> List[Scene]:
        target_dur, n_scenes = LENGTH_PRESETS.get(opts.length, LENGTH_PRESETS["medium"])
        lang = "Bahasa Indonesia" if opts.language == "id" else "English"
        data = self.gemini.generate_json(f"""Buat naskah storytelling cinematic {opts.genre} gaya {opts.style} dalam {lang}. Topik: "{opts.title}". Durasi: ~{target_dur}s ({n_scenes} scene). Output JSON strict: {{"scenes": [{{"text": "...", "keyword": "..."}}]}} (keyword bahasa inggris untuk cari stock video)""")
        return [Scene(i, s.get("text", "").strip(), s.get("keyword", "nature").strip()) for i, s in enumerate(data.get("scenes", [])) if s.get("text")]

    def _search_pexels(self, query: str) -> Optional[str]:
        if not self.pexels_key: return None
        try:
            r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": self.pexels_key}, params={"query": query, "per_page": 5, "orientation": "portrait"}, timeout=15)
            r.raise_for_status()
            for video in r.json().get("videos", []):
                files = sorted(video.get("video_files", []), key=lambda f: (f.get("quality") == "hd", f.get("width", 0)), reverse=True)
                if files: return files[0].get("link")
        except Exception: pass
        return None

    def _search_pixabay(self, query: str) -> Optional[str]:
        if not self.pixabay_key: return None
        try:
            r = requests.get("https://pixabay.com/api/videos/", params={"key": self.pixabay_key, "q": query, "per_page": 5, "safesearch": "true"}, timeout=15)
            r.raise_for_status()
            for hit in r.json().get("hits", []):
                videos = hit.get("videos", {})
                for quality in ("large", "medium", "small"):
                    if videos.get(quality, {}).get("url"): return videos[quality]["url"]
        except Exception: pass
        return None

    def _get_footage(self, keyword: str, dst: Path) -> Optional[Path]:
        for fn in (self._search_pexels, self._search_pixabay):
            url = fn(keyword)
            if not url: continue
            try:
                with requests.get(url, stream=True, timeout=20) as r:
                    r.raise_for_status()
                    with open(dst, "wb") as f:
                        for chunk in r.iter_content(chunk_size=65536): f.write(chunk)
                if dst.stat().st_size > 1024: return dst
            except Exception: continue
        return None

    def _generate_tts(self, text: str, dst: Path, language: str, speed: str) -> Path:
        try: from gtts import gTTS
        except ImportError as e: raise RuntimeError("Instal gTTS: pip install gTTS") from e
        gTTS(text=text, lang="id" if language == "id" else "en", slow=(speed == "slow")).save(str(dst))
        if speed == "fast":
            fast_path = dst.with_name(dst.stem + "_fast.mp3")
            ff.run_ffmpeg(["-i", str(dst), "-filter:a", "atempo=1.25", str(fast_path)])
            fast_path.replace(dst)
        return dst

    def _render_scene(self, scene: Scene, size: tuple[int, int]) -> Path:
        W, H = size
        out = self.work_dir / f"scene_{scene.index:03d}_{uuid.uuid4().hex[:6]}.mp4"
        if scene.footage_path and Path(scene.footage_path).exists():
            vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},zoompan=z='min(zoom+0.0005,1.10)':d=1:s={W}x{H}:fps=30"
            ff.run_ffmpeg(["-stream_loop", "-1", "-i", str(scene.footage_path), "-i", str(scene.audio_path), "-t", f"{scene.duration:.2f}", "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest", str(out)])
        else:
            safe_text = scene.text[:60].replace("'", "").replace(":", "") # Escape ketat untuk fallback text
            ff.run_ffmpeg(["-f", "lavfi", "-i", f"color=c=0x06080f:s={W}x{H}:d={scene.duration:.2f}", "-i", str(scene.audio_path), "-vf", f"drawtext=text='{safe_text}':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2", "-t", f"{scene.duration:.2f}", "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest", str(out)])
        return out

    def process(self, opts: StoryTellerOptions, progress_cb=None) -> StoryResult:
        log = progress_cb if progress_cb else lambda msg: None
        log("AI menulis naskah cerita...")
        scenes = self._generate_script(opts)
        if not scenes: raise RuntimeError("Gagal generate naskah.")
        job_id = uuid.uuid4().hex[:8]

        for i, sc in enumerate(scenes):
            log(f"TTS scene {i+1}/{len(scenes)}...")
            sc.audio_path = str(self._generate_tts(sc.text, self.work_dir / f"aud_{job_id}_{i:03d}.mp3", opts.language, opts.tts_speed))
            sc.duration = max(2.0, ff.get_duration(sc.audio_path) + 0.3)

        if opts.use_footage:
            for i, sc in enumerate(scenes):
                log(f"Cari footage {sc.keyword}...")
                if result := self._get_footage(sc.keyword, self.work_dir / f"foot_{job_id}_{i:03d}.mp4"):
                    sc.footage_path = str(result)

        size = {"1080p": 1080, "720p": 720, "480p": 480}.get(opts.quality, 1080)
        W, H = (int(size * 9 / 16) // 2 * 2, size // 2 * 2) if opts.aspect == "9:16" else (int(size * 16 / 9) // 2 * 2, size // 2 * 2) if opts.aspect == "16:9" else (size, size)

        scene_paths = []
        for i, sc in enumerate(scenes):
            log(f"Render scene {i+1}/{len(scenes)}...")
            sc.rendered_path = str(self._render_scene(sc, (W, H)))
            scene_paths.append(sc.rendered_path)

        concat_path = self.work_dir / f"concat_{job_id}.mp4"
        ff.concat_videos(scene_paths, concat_path)

        srt_path = self.work_dir / f"sub_{job_id}.srt"
        t = 0.0
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, sc in enumerate(scenes, 1):
                f.write(f"{i}\n{int(t//3600):02d}:{int((t%3600)//60):02d}:{t%60:06.3f} --> {int((t+sc.duration)//3600):02d}:{int(((t+sc.duration)%3600)//60):02d}:{(t+sc.duration)%60:06.3f}\n{sc.text}\n\n".replace(".", ","))
                t += sc.duration

        with_sub = self.work_dir / f"sub_{job_id}.mp4"
        try: ff.burn_subtitles(concat_path, with_sub, srt_path, encoding="balanced")
        except Exception as e: log(f"Subtitle gagal: {e}"); with_sub = concat_path

        final_path = self.output_dir / f"story_{job_id}.mp4"
        bgm_path = self._find_bgm(opts.bgm_mood)
        if bgm_path:
            try: ff.mix_audio(with_sub, self.work_dir / f"narr_{job_id}.aac", final_path, bgm=bgm_path)
            except Exception: shutil.copy(with_sub, final_path)
        else: shutil.copy(with_sub, final_path)

        thumb_path = self.output_dir / f"story_{job_id}_thumb.jpg"
        try: ff.extract_frame(final_path, thumb_path, at=2.0)
        except Exception: thumb_path = None

        for p in self.work_dir.glob(f"*_{job_id}*"): p.unlink(missing_ok=True)
        return StoryResult(str(final_path), str(thumb_path) if thumb_path and thumb_path.exists() else "", "\n\n".join(sc.text for sc in scenes), [{"text": sc.text, "keyword": sc.keyword, "duration": sc.duration} for sc in scenes], sum(sc.duration for sc in scenes))

    def _find_bgm(self, mood: str) -> Optional[Path]:
        if not mood or mood == "none": return None
        candidates = BGM_MOOD_ALIASES.get(mood, [mood])
        search_dirs = [Path(__file__).resolve().parent.parent / "assets" / "bgm"]
        if getattr(sys, "frozen", False):
            search_dirs.extend([Path(sys.executable).parent / "assets" / "bgm", Path(sys._MEIPASS) / "assets" / "bgm" if getattr(sys, "_MEIPASS", None) else None])
        for base in filter(None, search_dirs):
            if base.exists():
                for name in candidates:
                    for ext in (".mp3", ".m4a", ".wav"):
                        if (base / f"{name}{ext}").exists(): return base / f"{name}{ext}"
        return None

    def preview_script(self, opts: StoryTellerOptions) -> List[Dict]:
        scenes = self._generate_script(opts)
        return [{"text": sc.text, "keyword": sc.keyword} for sc in scenes]
