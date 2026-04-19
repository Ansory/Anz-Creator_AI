"""
Short Maker — Konversi video panjang jadi short/clip pendek dengan AI.

Alur utama:
  1. Download video (yt-dlp) atau pakai file upload
  2. AI analisis → cari momen viral / generate metadata
  3. Potong sesuai timestamp
  4. Transform aspect ratio (blur/bars/crop)
  5. Tambah subtitle kalau diminta
  6. Return metadata + path output
"""
from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import ffmpeg_utils as ff
from .api_rotator import APIKeyRotator
from .gemini_client import GeminiClient


# Karakter yang ilegal sebagai nama file di Windows.
_WINDOWS_BAD = r'<>:"/\|?*'


def _safe_filename(name: str, max_len: int = 50, fallback: str = "clip") -> str:
    """Sanitasi nama file untuk Windows & Linux."""
    cleaned = "".join("_" if c in _WINDOWS_BAD else c for c in name)
    cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    cleaned = cleaned[:max_len].rstrip("._ ")
    return cleaned or fallback


# -------------------------------------------------------------- Topik config
TOPICS = {
    "free": "Bebas, topik apa saja yang menarik dan punya potensi viral",
    "business": "Bisnis, keuangan, investasi, kewirausahaan",
    "motivation": "Motivasi, mindset, pengembangan diri, produktivitas",
    "romance": "Asmara, hubungan, percintaan, relationship advice",
    "entertainment": "Hiburan, komedi, momen lucu, reaksi spontan",
    "education": "Edukasi, fakta menarik, sains, pengetahuan umum",
}

DURATION_PRESETS = {
    "auto": (15, 90),
    "short": (15, 30),
    "medium": (30, 60),
    "long": (45, 90),
}


# -------------------------------------------------------------- Data classes
@dataclass
class ShortMakerOptions:
    source: str                  # URL atau path lokal
    source_type: str = "url"     # "url" | "file"
    transform_mode: str = "blur"
    aspect: str = "9:16"
    quality: str = "1080p"
    caption_ai: bool = True
    topic: str = "free"
    duration_preset: str = "auto"  # auto|short|medium|long|custom|manual
    custom_start: float = 0.0
    custom_end: float = 0.0
    encoding: str = "balanced"
    use_gpu: bool = False
    bypass_copyright: bool = False
    language: str = "id"


@dataclass
class ShortMakerResult:
    output_path: str
    thumbnail_path: str
    title: str
    description: str
    tags: List[str] = field(default_factory=list)
    pinned_comment: str = ""
    duration: float = 0.0
    start_seconds: float = 0.0
    end_seconds: float = 0.0


# -------------------------------------------------------------- Main class
class ShortMaker:
    def __init__(self, rotator: APIKeyRotator, output_dir: str | Path = "outputs"):
        self.rotator = rotator
        self.gemini = GeminiClient(rotator)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir = self.output_dir / ".work"
        self.work_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------- Download
    def _download_youtube(self, url: str, progress_cb=None) -> Path:
        """Download video pakai yt-dlp. Return path file."""
        try:
            import yt_dlp
        except ImportError as e:
            raise RuntimeError("yt-dlp tidak terinstall. Jalankan: pip install yt-dlp") from e

        job_id = uuid.uuid4().hex[:8]
        out_template = str(self.work_dir / f"yt_{job_id}.%(ext)s")

        def hook(d):
            if progress_cb and d.get("status") == "downloading":
                pct = d.get("_percent_str", "").strip()
                progress_cb(f"Download: {pct}")

        ydl_opts = {
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "merge_output_format": "mp4",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook] if progress_cb else [],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            p = Path(filename)
            if not p.exists():
                # coba ganti ekstensi
                for ext in (".mp4", ".mkv", ".webm"):
                    alt = p.with_suffix(ext)
                    if alt.exists():
                        return alt
                raise RuntimeError("yt-dlp tidak menghasilkan file output yang valid.")
            return p

    # ------------------------------------------------------- AI analysis
    def _prompt_analyze(self, duration: float, topic: str, dur_preset: str,
                        language: str) -> str:
        topic_desc = TOPICS.get(topic, TOPICS["free"])
        dur_range = DURATION_PRESETS.get(dur_preset, DURATION_PRESETS["auto"])
        lang_label = "Bahasa Indonesia" if language == "id" else "English"

        return f"""Kamu adalah ahli content strategy viral untuk YouTube Shorts, TikTok, dan Instagram Reels.

Video berdurasi {duration:.1f} detik. Topik fokus: {topic_desc}.
Pilih 1 momen paling menarik / punya potensi viral tertinggi.
Durasi clip target: {dur_range[0]}–{dur_range[1]} detik.

Output JSON strict dalam {lang_label} dengan schema:
{{
  "start_seconds": <angka detik mulai>,
  "end_seconds": <angka detik selesai>,
  "title": "<judul click-bait 5-9 kata>",
  "description": "<deskripsi 2-3 kalimat + 5 hashtag relevan di akhir>",
  "tags": ["tag1", "tag2", ...] (minimal 8 tags, semua lowercase, tanpa #),
  "pinned_comment": "<komentar ajak tonton video panjang>",
  "reason": "<alasan kenapa momen ini viral>"
}}

PENTING:
- start_seconds & end_seconds harus dalam rentang [0, {duration:.1f}]
- (end_seconds - start_seconds) harus dalam [{dur_range[0]}, {dur_range[1]}]
- Output HANYA JSON, tanpa prefix/suffix lain.
"""

    def _generate_metadata(self, duration: float, opts: ShortMakerOptions) -> Dict:
        prompt = self._prompt_analyze(duration, opts.topic, opts.duration_preset, opts.language)
        try:
            data = self.gemini.generate_json(prompt)
            # validasi
            s = float(data.get("start_seconds", 0))
            e = float(data.get("end_seconds", min(30, duration)))
            s = max(0.0, min(s, duration - 5))
            e = max(s + 5, min(e, duration))
            data["start_seconds"] = s
            data["end_seconds"] = e
            return data
        except Exception as e:  # noqa: BLE001
            # fallback: ambil 30 detik dari awal
            end = min(30.0, duration)
            return {
                "start_seconds": 0.0,
                "end_seconds": end,
                "title": "Momen Menarik dari Video",
                "description": "Potongan video yang wajib kamu tonton! #shorts #viral #fyp #trending #reels",
                "tags": ["shorts", "viral", "fyp", "trending", "reels", "short", "video", "clip"],
                "pinned_comment": "Tonton versi lengkapnya di video aslinya ya! 🔥",
                "reason": f"AI fallback karena error: {e}",
            }

    # ------------------------------------------------------- Subtitle
    def _generate_srt(self, video_path: Path, srt_path: Path, duration: float) -> None:
        """
        Generate SRT placeholder sederhana.
        Note: untuk transkripsi akurat, idealnya pakai Whisper/Gemini Audio.
        """
        # coba pakai Whisper kalau ada
        try:
            import whisper  # type: ignore
            model = whisper.load_model("base")
            result = model.transcribe(str(video_path))
            self._write_srt_from_whisper(result, srt_path)
            return
        except Exception:
            pass

        # Fallback: satu baris captions
        h = int(duration // 3600)
        m = int((duration % 3600) // 60)
        s = duration % 60
        end_ts = f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(
                "1\n"
                f"00:00:00,000 --> {end_ts}\n"
                "[ Aktifkan subtitle via transkripsi Whisper untuk hasil terbaik ]\n\n"
            )

    def _write_srt_from_whisper(self, result: dict, srt_path: Path) -> None:
        def ts(t: float) -> str:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = t % 60
            return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(result.get("segments", []), 1):
                f.write(f"{i}\n{ts(seg['start'])} --> {ts(seg['end'])}\n{seg['text'].strip()}\n\n")

    # ------------------------------------------------------- Process
    def process(self, opts: ShortMakerOptions, progress_cb=None) -> ShortMakerResult:
        def log(msg):
            if progress_cb:
                progress_cb(msg)

        # 1. Dapatkan source video
        log("Mempersiapkan video source...")
        if opts.source_type == "url":
            log("Downloading dari YouTube...")
            src_path = self._download_youtube(opts.source, progress_cb=progress_cb)
        else:
            src_path = Path(opts.source)
            if not src_path.exists():
                raise FileNotFoundError(f"File tidak ditemukan: {src_path}")

        duration = ff.get_duration(src_path)
        log(f"Durasi video: {duration:.1f} detik")

        # 2. Tentukan segment
        if opts.duration_preset == "manual" or opts.duration_preset == "custom":
            start = max(0.0, opts.custom_start)
            end = min(duration, opts.custom_end) if opts.custom_end > 0 else min(start + 60, duration)
            metadata = {
                "start_seconds": start,
                "end_seconds": end,
                "title": "Video Clip",
                "description": "#shorts #viral #fyp #trending #reels",
                "tags": ["shorts", "viral", "fyp", "trending", "reels"],
                "pinned_comment": "",
            }
            log("Menggunakan timestamp manual")
        else:
            log("AI menganalisis momen viral...")
            metadata = self._generate_metadata(duration, opts)
            start = metadata["start_seconds"]
            end = metadata["end_seconds"]

        # Validasi durasi
        if end - start < 1.0:
            end = min(start + 5, duration)
        log(f"Clip: {start:.1f}s → {end:.1f}s")

        # 3. Cut
        job_id = uuid.uuid4().hex[:8]
        cut_path = self.work_dir / f"cut_{job_id}.mp4"
        log("Memotong segmen video...")
        ff.cut_video(src_path, cut_path, start, end)

        # 4. Transform aspect
        transformed_path = self.work_dir / f"trans_{job_id}.mp4"
        log(f"Transform aspect ({opts.transform_mode}, {opts.aspect})...")
        ff.transform_aspect(
            cut_path, transformed_path,
            mode=opts.transform_mode,
            aspect=opts.aspect,
            quality=opts.quality,
            use_gpu=opts.use_gpu,
            encoding=opts.encoding,
            bypass_copyright=opts.bypass_copyright,
        )

        # 5. Subtitle (opsional)
        if opts.caption_ai:
            log("Generate subtitle...")
            srt_path = self.work_dir / f"sub_{job_id}.srt"
            self._generate_srt(transformed_path, srt_path, ff.get_duration(transformed_path))
            captioned_path = self.work_dir / f"cap_{job_id}.mp4"
            try:
                ff.burn_subtitles(transformed_path, captioned_path, srt_path,
                                  use_gpu=opts.use_gpu, encoding=opts.encoding)
                final_src = captioned_path
            except Exception as e:  # noqa: BLE001
                log(f"Subtitle gagal, lanjut tanpa subtitle: {e}")
                final_src = transformed_path
        else:
            final_src = transformed_path

        # 6. Pindah ke output dir
        safe_title = _safe_filename(metadata.get("title", "clip"))
        final_name = f"{safe_title}_{job_id}.mp4"
        final_path = self.output_dir / final_name
        if final_path.exists():
            final_path.unlink()
        shutil.move(str(final_src), str(final_path))

        # 7. Thumbnail
        thumb_path: Optional[Path] = self.output_dir / f"{final_path.stem}_thumb.jpg"
        try:
            ff.extract_frame(final_path, thumb_path, at=0.5)
        except Exception:
            thumb_path = None

        # cleanup work files
        for p in self.work_dir.glob(f"*_{job_id}.*"):
            p.unlink(missing_ok=True)

        return ShortMakerResult(
            output_path=str(final_path),
            thumbnail_path=str(thumb_path) if thumb_path and thumb_path.exists() else "",
            title=metadata.get("title", "Untitled"),
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            pinned_comment=metadata.get("pinned_comment", ""),
            duration=end - start,
            start_seconds=start,
            end_seconds=end,
        )

    # ------------------------------------------------------- AI Find Viral
    def find_viral_moments(self, source: str, source_type: str, topic: str,
                           language: str = "id") -> Dict:
        """
        Scan video tanpa render, return daftar momen viral terbaik.
        """
        if source_type == "url":
            src_path = self._download_youtube(source)
        else:
            src_path = Path(source)

        duration = ff.get_duration(src_path)
        topic_desc = TOPICS.get(topic, TOPICS["free"])
        lang_label = "Bahasa Indonesia" if language == "id" else "English"

        prompt = f"""Kamu adalah viral moment detector.
Video berdurasi {duration:.1f} detik. Topik fokus: {topic_desc}.

Berikan 3 kandidat momen viral terbaik.

Output JSON strict ({lang_label}):
{{
  "moments": [
    {{
      "start_seconds": <num>,
      "end_seconds": <num>,
      "title": "<judul 5-9 kata>",
      "hook": "<1 kalimat hook>",
      "score": <1-10>
    }}
  ]
}}

HANYA JSON, tanpa teks lain."""
        return self.gemini.generate_json(prompt)
