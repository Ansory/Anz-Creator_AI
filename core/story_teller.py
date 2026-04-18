"""
Text to Story Telling — Ubah teks/topik jadi video storytelling cinematic.

Alur:
  1. Gemini generate naskah lengkap (dipecah per scene)
  2. Per scene, Gemini generate keyword footage
  3. Pexels/Pixabay search footage video bergerak
  4. Download & potong footage sesuai durasi scene
  5. Ken Burns / zoom / pan biar tidak statis
  6. gTTS generate narasi audio
  7. FFmpeg concat semua scene + audio narasi + subtitle + BGM
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import requests

from . import ffmpeg_utils as ff
from .api_rotator import APIKeyRotator
from .gemini_client import GeminiClient


GENRES = ["Romance", "Thriller", "Motivasi", "Horor", "Drama", "Edukasi", "Komedi"]
STYLES = ["Formal", "Santai", "Dramatis", "Puitis"]
LENGTH_PRESETS = {
    "short": (60, 6),      # ~1 menit, ~6 scene
    "medium": (180, 15),   # ~3 menit, ~15 scene
    "long": (300, 25),     # ~5 menit, ~25 scene
}


@dataclass
class StoryTellerOptions:
    title: str
    genre: str = "Drama"
    style: str = "Dramatis"
    length: str = "medium"       # short|medium|long
    language: str = "id"
    tts_voice: str = "female"    # gTTS cuma support 1 voice per lang, tapi bisa variasi speed
    tts_speed: str = "normal"    # slow|normal|fast
    bgm_mood: str = "epic"       # epic|sad|calm|upbeat|none
    aspect: str = "9:16"
    quality: str = "1080p"
    use_footage: bool = True     # kalau false, pakai BG solid/gradient


@dataclass
class Scene:
    index: int
    text: str                    # narasi
    keyword: str                 # search term footage
    duration: float = 0.0        # akan diisi setelah TTS
    footage_path: Optional[str] = None
    audio_path: Optional[str] = None
    rendered_path: Optional[str] = None


@dataclass
class StoryResult:
    output_path: str
    thumbnail_path: str
    script: str
    scenes: List[Dict] = field(default_factory=list)
    duration: float = 0.0


class StoryTeller:
    def __init__(self, rotator: APIKeyRotator, output_dir: str | Path = "outputs",
                 pexels_key: str = "", pixabay_key: str = ""):
        self.rotator = rotator
        self.gemini = GeminiClient(rotator)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir = self.output_dir / ".work"
        self.work_dir.mkdir(exist_ok=True)
        self.pexels_key = pexels_key or os.getenv("PEXELS_API_KEY", "PfwZYmwU4CJhd5W84N14mIkfo3ZqN5Q0r68qUFfCVsoyxE57xaew4h1Z")
        self.pixabay_key = pixabay_key or os.getenv("PIXABAY_API_KEY", "43243893-078bf0defe316eaf53d71f550")

    # ------------------------------------------------------- Script gen
    def _generate_script(self, opts: StoryTellerOptions) -> List[Scene]:
        target_dur, n_scenes = LENGTH_PRESETS.get(opts.length, LENGTH_PRESETS["medium"])
        lang_label = "Bahasa Indonesia" if opts.language == "id" else "English"

        prompt = f"""Kamu adalah penulis skenario video storytelling cinematic untuk YouTube / TikTok.

Buat naskah cerita {opts.genre} dengan gaya {opts.style} dalam {lang_label}.
Judul/topik: "{opts.title}"
Target durasi narasi: ~{target_dur} detik ({n_scenes} scene).

Pecah cerita menjadi tepat {n_scenes} scene. Setiap scene:
- text: narasi 1-3 kalimat, mengalir, cocok dibaca TTS
- keyword: 2-4 kata bahasa Inggris untuk cari footage video di Pexels/Pixabay
  (pilih keyword yang VISUAL konkret, contoh: "rainy city street", "sunrise mountain peak",
   "woman crying close up", "busy office workers" — JANGAN abstrak)

Output JSON strict:
{{
  "scenes": [
    {{"text": "...", "keyword": "..."}},
    ...
  ]
}}

HANYA JSON, tanpa teks lain. Jangan pakai emoji di text."""

        data = self.gemini.generate_json(prompt)
        scenes_raw = data.get("scenes", [])
        return [
            Scene(index=i, text=s.get("text", "").strip(), keyword=s.get("keyword", "nature").strip())
            for i, s in enumerate(scenes_raw) if s.get("text")
        ]

    # ------------------------------------------------------- Footage search
    def _search_pexels(self, query: str) -> Optional[str]:
        if not self.pexels_key:
            return None
        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self.pexels_key}
        params = {"query": query, "per_page": 5, "orientation": "portrait"}
        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            for video in data.get("videos", []):
                # ambil file hd
                files = sorted(video.get("video_files", []),
                               key=lambda f: (f.get("quality") == "hd", f.get("width", 0)),
                               reverse=True)
                if files:
                    return files[0].get("link")
        except Exception as e:  # noqa: BLE001
            print(f"[pexels] {e}")
        return None

    def _search_pixabay(self, query: str) -> Optional[str]:
        if not self.pixabay_key:
            return None
        url = "https://pixabay.com/api/videos/"
        params = {"key": self.pixabay_key, "q": query, "per_page": 5, "safesearch": "true"}
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            for hit in data.get("hits", []):
                videos = hit.get("videos", {})
                for quality in ("large", "medium", "small"):
                    if quality in videos and videos[quality].get("url"):
                        return videos[quality]["url"]
        except Exception as e:  # noqa: BLE001
            print(f"[pixabay] {e}")
        return None

    def _get_footage(self, keyword: str, dst: Path) -> Optional[Path]:
        """Coba Pexels dulu, fallback Pixabay. Return path lokal atau None."""
        for fn in (self._search_pexels, self._search_pixabay):
            url = fn(keyword)
            if not url:
                continue
            try:
                with requests.get(url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    with open(dst, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1 << 16):
                            f.write(chunk)
                if dst.stat().st_size > 1024:
                    return dst
            except Exception as e:  # noqa: BLE001
                print(f"[download footage] {e}")
                continue
        return None

    # ------------------------------------------------------- TTS
    def _generate_tts(self, text: str, dst: Path, language: str, speed: str) -> Path:
        try:
            from gtts import gTTS
        except ImportError as e:
            raise RuntimeError("gTTS tidak terinstall. Jalankan: pip install gTTS") from e

        lang = "id" if language == "id" else "en"
        slow = speed == "slow"
        tts = gTTS(text=text, lang=lang, slow=slow)
        tts.save(str(dst))

        # speed up kalau "fast"
        if speed == "fast":
            fast_path = dst.with_name(dst.stem + "_fast.mp3")
            ff.run_ffmpeg(["-i", str(dst), "-filter:a", "atempo=1.25", str(fast_path)])
            fast_path.replace(dst)
        return dst

    # ------------------------------------------------------- Scene render
    def _render_scene(self, scene: Scene, size: tuple[int, int]) -> Path:
        """
        Render satu scene ke video dengan durasi audio narasi.
        Kalau ada footage → pakai footage (loop/trim sesuai durasi narasi).
        Kalau tidak → gradient background.
        """
        W, H = size
        out = self.work_dir / f"scene_{scene.index:03d}_{uuid.uuid4().hex[:6]}.mp4"
        dur = scene.duration

        if scene.footage_path and Path(scene.footage_path).exists():
            # Scale footage ke target size + loop kalau kurang + Ken Burns subtle
            vf = (
                f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},"
                f"zoompan=z='min(zoom+0.0005,1.10)':d=1:s={W}x{H}:fps=30"
            )
            ff.run_ffmpeg([
                "-stream_loop", "-1",
                "-i", str(scene.footage_path),
                "-i", str(scene.audio_path),
                "-t", f"{dur:.2f}",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "aac", "-pix_fmt", "yuv420p",
                "-shortest",
                str(out),
            ])
        else:
            # Gradient background
            ff.run_ffmpeg([
                "-f", "lavfi",
                "-i", f"color=c=0x06080f:s={W}x{H}:d={dur:.2f},"
                      f"drawtext=text='{scene.text[:40]}':fontcolor=white:fontsize=36:"
                      f"x=(w-text_w)/2:y=(h-text_h)/2",
                "-i", str(scene.audio_path),
                "-t", f"{dur:.2f}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "aac", "-pix_fmt", "yuv420p",
                "-shortest",
                str(out),
            ])

        return out

    # ------------------------------------------------------- SRT
    def _write_srt(self, scenes: List[Scene], path: Path) -> None:
        def ts(t: float) -> str:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = t % 60
            return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

        t = 0.0
        with open(path, "w", encoding="utf-8") as f:
            for i, sc in enumerate(scenes, 1):
                start = t
                end = t + sc.duration
                f.write(f"{i}\n{ts(start)} --> {ts(end)}\n{sc.text}\n\n")
                t = end

    # ------------------------------------------------------- Main
    def process(self, opts: StoryTellerOptions, progress_cb=None) -> StoryResult:
        def log(msg):
            if progress_cb:
                progress_cb(msg)

        # 1. Script
        log("AI menulis naskah cerita...")
        scenes = self._generate_script(opts)
        if not scenes:
            raise RuntimeError("Gagal generate naskah.")
        log(f"Naskah selesai: {len(scenes)} scene")

        job_id = uuid.uuid4().hex[:8]

        # 2. TTS per scene
        for i, sc in enumerate(scenes):
            log(f"TTS scene {i+1}/{len(scenes)}...")
            audio_path = self.work_dir / f"aud_{job_id}_{i:03d}.mp3"
            self._generate_tts(sc.text, audio_path, opts.language, opts.tts_speed)
            sc.audio_path = str(audio_path)
            sc.duration = max(2.0, ff.get_duration(audio_path) + 0.3)

        # 3. Footage per scene
        if opts.use_footage:
            for i, sc in enumerate(scenes):
                log(f"Cari footage scene {i+1}/{len(scenes)}: {sc.keyword}")
                dst = self.work_dir / f"foot_{job_id}_{i:03d}.mp4"
                result = self._get_footage(sc.keyword, dst)
                if result:
                    sc.footage_path = str(result)

        # 4. Render per scene
        size = self._resolve_size(opts.aspect, opts.quality)
        scene_paths = []
        for i, sc in enumerate(scenes):
            log(f"Render scene {i+1}/{len(scenes)}...")
            p = self._render_scene(sc, size)
            sc.rendered_path = str(p)
            scene_paths.append(p)

        # 5. Concat
        log("Menggabungkan semua scene...")
        concat_path = self.work_dir / f"concat_{job_id}.mp4"
        ff.concat_videos(scene_paths, concat_path)

        # 6. Subtitle
        log("Menambah subtitle...")
        srt_path = self.work_dir / f"sub_{job_id}.srt"
        self._write_srt(scenes, srt_path)
        with_sub = self.work_dir / f"sub_{job_id}.mp4"
        try:
            ff.burn_subtitles(concat_path, with_sub, srt_path, encoding="balanced")
        except Exception as e:  # noqa: BLE001
            log(f"Subtitle gagal, lanjut tanpa: {e}")
            with_sub = concat_path

        # 7. BGM (opsional — placeholder, butuh library BGM lokal)
        final_path = self.output_dir / f"story_{job_id}.mp4"
        bgm_path = self._find_bgm(opts.bgm_mood)
        if bgm_path:
            log("Mix BGM...")
            try:
                # BGM sudah mixed lewat extract narration track dari video
                tmp = self.work_dir / f"final_{job_id}.mp4"
                # extract audio narration (current audio track)
                narr_audio = self.work_dir / f"narr_{job_id}.aac"
                ff.run_ffmpeg(["-i", str(with_sub), "-vn", "-c:a", "copy", str(narr_audio)])
                ff.mix_audio(with_sub, narr_audio, tmp, bgm=bgm_path)
                tmp.replace(final_path)
            except Exception as e:  # noqa: BLE001
                log(f"BGM mix gagal, skip: {e}")
                shutil.copy(with_sub, final_path)
        else:
            shutil.copy(with_sub, final_path)

        # 8. Thumbnail
        thumb_path = self.output_dir / f"story_{job_id}_thumb.jpg"
        try:
            ff.extract_frame(final_path, thumb_path, at=min(2.0, ff.get_duration(final_path) / 2))
        except Exception:
            thumb_path = Path()

        # cleanup
        for p in self.work_dir.glob(f"*_{job_id}*"):
            p.unlink(missing_ok=True)
        for p in scene_paths:
            Path(p).unlink(missing_ok=True)

        return StoryResult(
            output_path=str(final_path),
            thumbnail_path=str(thumb_path) if thumb_path else "",
            script="\n\n".join(sc.text for sc in scenes),
            scenes=[{"text": sc.text, "keyword": sc.keyword, "duration": sc.duration}
                    for sc in scenes],
            duration=sum(sc.duration for sc in scenes),
        )

    def _resolve_size(self, aspect: str, quality: str) -> tuple[int, int]:
        heights = {"1080p": 1080, "720p": 720, "480p": 480}
        h = heights.get(quality, 1080)
        if aspect == "9:16":
            return int(h * 9 / 16), h
        if aspect == "16:9":
            return int(h * 16 / 9), h
        if aspect == "1:1":
            return h, h
        return int(h * 9 / 16), h

    def _find_bgm(self, mood: str) -> Optional[Path]:
        """Cari file BGM di folder assets/bgm/<mood>.mp3 kalau ada."""
        if mood == "none":
            return None
        # cek folder lokal
        for base in [Path("assets/bgm"), Path(__file__).parent.parent / "assets" / "bgm"]:
            p = base / f"{mood}.mp3"
            if p.exists():
                return p
        return None

    # ------------------------------------------------------- Preview only
    def preview_script(self, opts: StoryTellerOptions) -> List[Dict]:
        """Generate script tanpa render video. Untuk tombol Preview."""
        scenes = self._generate_script(opts)
        return [{"text": sc.text, "keyword": sc.keyword} for sc in scenes]
