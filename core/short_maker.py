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
import urllib.request
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
    source: str                       # URL atau path lokal
    source_type: str = "url"          # "url" | "file"
    transform_mode: str = "blur"      # blur|bars|crop|smart|original
    aspect: str = "9:16"              # 9:16|1:1|4:5
    quality: str = "1080p"            # 4K|2K|1080p|720p|480p|360p
    caption_ai: bool = True
    caption_style: str = "classic_white"   # 14 gaya subtitle
    caption_language: str = "original"    # original|id|en
    animate_text: bool = False             # word-by-word highlight
    word_density: int = 2                  # 1-5 kata per layar
    topic: str = "free"
    duration_preset: str = "auto"     # auto|short|medium|long|custom
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
    caption_applied: bool = True


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
    def _yt_dlp(self):
        try:
            import yt_dlp
            return yt_dlp
        except ImportError as e:
            raise RuntimeError("yt-dlp tidak terinstall. Jalankan: pip install yt-dlp") from e

    def _get_yt_info(self, url: str) -> dict:
        """Ambil metadata video tanpa download (untuk dapat durasi, judul, dll)."""
        yt_dlp = self._yt_dlp()
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 20,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False) or {}

    def _get_yt_transcript(self, info: dict) -> str:
        """
        Ambil transcript/subtitle YouTube dari info dict (tanpa download video).
        Prioritas: subtitle manual (id/en) → auto-caption (id/en).
        Return teks bersih, max ~8000 karakter.
        """
        def _parse_vtt(url: str) -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    raw = r.read().decode("utf-8", errors="ignore")
                seen: list[str] = []
                for line in raw.splitlines():
                    line = line.strip()
                    if not line or line.startswith("WEBVTT") or "-->" in line:
                        continue
                    # skip VTT metadata tags like <00:00:01.000>
                    line = re.sub(r"<[^>]+>", "", line).strip()
                    if line and (not seen or line != seen[-1]):
                        seen.append(line)
                return " ".join(seen)[:8000]
            except Exception:
                return ""

        for pool_key in ("subtitles", "automatic_captions"):
            pool = info.get(pool_key) or {}
            for lang in ("id", "en", "en-US", "en-GB"):
                tracks = pool.get(lang, [])
                vtt_url = next((t["url"] for t in tracks if t.get("ext") == "vtt"), None)
                if vtt_url:
                    text = _parse_vtt(vtt_url)
                    if text:
                        return text
        return ""

    def _build_video_context(self, source: str, source_type: str,
                              yt_info: dict | None = None) -> str:
        """
        Bangun teks konteks dari metadata video.
        Untuk URL YouTube: judul + deskripsi + chapters + transcript.
        Untuk file lokal: kosong (Whisper akan digunakan di _generate_srt).
        """
        if source_type != "url":
            return ""

        info = yt_info or self._get_yt_info(source)
        parts: list[str] = []

        title = info.get("title", "")
        if title:
            parts.append(f"Judul video: {title}")

        uploader = info.get("uploader") or info.get("channel", "")
        if uploader:
            parts.append(f"Channel: {uploader}")

        desc = (info.get("description") or "").strip()
        if desc:
            parts.append(f"Deskripsi:\n{desc[:600]}")

        chapters = info.get("chapters") or []
        if chapters:
            ch_lines = "\n".join(
                f"  [{c.get('start_time', 0):.0f}s] {c.get('title', '?')}"
                for c in chapters[:25]
            )
            parts.append(f"Chapters:\n{ch_lines}")

        transcript = self._get_yt_transcript(info)
        if transcript:
            parts.append(f"Transcript:\n{transcript}")

        return "\n\n".join(parts)

    def _download_youtube(self, url: str, quality: str = "1080p", progress_cb=None) -> Path:
        """Download video pakai yt-dlp dengan retry & timeout. Return path file."""
        yt_dlp = self._yt_dlp()

        quality_heights = {
            "4K": 2160, "2K": 1440, "1080p": 1080,
            "720p": 720, "480p": 480, "360p": 360,
        }
        max_h = quality_heights.get(quality, 1080)

        job_id = uuid.uuid4().hex[:8]
        out_template = str(self.work_dir / f"yt_{job_id}.%(ext)s")

        ffmpeg_path = ff.ffmpeg_bin()
        ffmpeg_dir = str(Path(ffmpeg_path).parent)

        def hook(d):
            if progress_cb and d.get("status") == "downloading":
                pct = d.get("_percent_str", "").strip()
                speed = d.get("_speed_str", "").strip()
                progress_cb(f"Download: {pct} · {speed}")

        ydl_opts = {
            "format": f"bestvideo[height<={max_h}]+bestaudio/best[height<={max_h}]/best",
            "merge_output_format": "mp4",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook] if progress_cb else [],
            "ffmpeg_location": ffmpeg_dir,
            # Timeout & retry settings
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,
            "file_access_retries": 3,
            "extractor_retries": 3,
            "throttledratelimit": 100,       # retry kalau speed < 100 B/s
            "http_chunk_size": 10_485_760,   # 10 MB chunks
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            p = Path(filename)
            if not p.exists():
                for ext in (".mp4", ".mkv", ".webm"):
                    alt = p.with_suffix(ext)
                    if alt.exists():
                        return alt
                raise RuntimeError("yt-dlp tidak menghasilkan file output yang valid.")
            return p

    # ------------------------------------------------------- AI analysis
    def _prompt_analyze(self, duration: float, topic: str, dur_preset: str,
                        language: str, context: str = "") -> str:
        topic_desc = TOPICS.get(topic, TOPICS["free"])
        dur_range = DURATION_PRESETS.get(dur_preset, DURATION_PRESETS["auto"])
        lang_label = "Bahasa Indonesia" if language == "id" else "English"

        context_block = f"\n\n--- KONTEN VIDEO ---\n{context}\n--- AKHIR KONTEN ---" if context else ""

        return f"""Kamu adalah ahli content strategy viral untuk YouTube Shorts, TikTok, dan Instagram Reels.

Video berdurasi {duration:.1f} detik. Topik fokus: {topic_desc}.{context_block}

Berdasarkan konten video di atas, pilih 1 momen paling menarik / punya potensi viral tertinggi.
Durasi clip target: {dur_range[0]}–{dur_range[1]} detik.

Output JSON strict dalam {lang_label} dengan schema:
{{
  "start_seconds": <angka detik mulai>,
  "end_seconds": <angka detik selesai>,
  "title": "<judul click-bait 5-9 kata SESUAI ISI VIDEO>",
  "description": "<deskripsi 2-3 kalimat SESUAI ISI VIDEO + 5 hashtag relevan>",
  "tags": ["tag1", "tag2", ...] (minimal 8 tags, semua lowercase, tanpa #, RELEVAN KONTEN),
  "pinned_comment": "<komentar ajak tonton video panjang>",
  "reason": "<alasan momen ini viral>"
}}

PENTING:
- Judul & deskripsi HARUS mencerminkan isi video yang sebenarnya, bukan generik
- start_seconds & end_seconds harus dalam rentang [0, {duration:.1f}]
- (end_seconds - start_seconds) harus dalam [{dur_range[0]}, {dur_range[1]}]
- Output HANYA JSON, tanpa prefix/suffix lain.
"""

    def _generate_metadata(self, duration: float, opts: ShortMakerOptions,
                            context: str = "") -> Dict:
        prompt = self._prompt_analyze(duration, opts.topic, opts.duration_preset,
                                       opts.language, context)
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
    def _vtt_to_srt_clipped(self, yt_info: dict, clip_start: float, clip_end: float) -> str:
        """
        Ambil VTT dari YouTube, filter ke window clip, offset timestamp, return SRT.
        """
        def fetch_vtt(url: str) -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.read().decode("utf-8", errors="ignore")
            except Exception:
                return ""

        def ts_to_sec(ts: str) -> float:
            parts = ts.strip().split(":")
            try:
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
            except Exception:
                pass
            return 0.0

        def sec_to_srt_ts(sec: float) -> str:
            sec = max(0.0, sec)
            h = int(sec // 3600)
            m = int((sec % 3600) // 60)
            s = sec % 60
            return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s % 1) * 1000)):03d}"

        # Cari URL VTT
        vtt_url = None
        for pool_key in ("subtitles", "automatic_captions"):
            pool = yt_info.get(pool_key) or {}
            for lang in ("id", "en", "en-US", "en-GB"):
                tracks = pool.get(lang, [])
                vtt_url = next((t["url"] for t in tracks if t.get("ext") == "vtt"), None)
                if vtt_url:
                    break
            if vtt_url:
                break
        if not vtt_url:
            return ""

        raw = fetch_vtt(vtt_url)
        if not raw:
            return ""

        # Parse VTT entries
        raw_entries: list[tuple[float, float, str]] = []
        lines = raw.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if "-->" in line:
                parts = line.split("-->")
                if len(parts) == 2:
                    t_s = ts_to_sec(parts[0].strip())
                    t_e = ts_to_sec(parts[1].strip().split()[0])
                    text_parts: list[str] = []
                    i += 1
                    while i < len(lines) and lines[i].strip() and "-->" not in lines[i]:
                        cleaned = re.sub(r"<[^>]+>", "", lines[i]).strip()
                        if cleaned:
                            text_parts.append(cleaned)
                        i += 1
                    text = " ".join(text_parts)
                    if text:
                        raw_entries.append((t_s, t_e, text))
                    continue
            i += 1

        # Filter ke window clip, offset, deduplicate
        srt_entries: list[tuple[float, float, str]] = []
        prev_text = ""
        for t_s, t_e, text in raw_entries:
            if t_e <= clip_start or t_s >= clip_end:
                continue
            new_s = max(0.0, t_s - clip_start)
            new_e = min(clip_end - clip_start, t_e - clip_start)
            if new_e <= new_s or text == prev_text:
                continue
            srt_entries.append((new_s, new_e, text))
            prev_text = text

        if not srt_entries:
            return ""

        return "\n".join(
            f"{n}\n{sec_to_srt_ts(s)} --> {sec_to_srt_ts(e)}\n{t}\n"
            for n, (s, e, t) in enumerate(srt_entries, 1)
        )

    def _generate_srt(self, video_path: Path, srt_path: Path, duration: float,
                      yt_info: dict | None = None, clip_start: float = 0.0) -> bool:
        """
        Generate SRT file. Return True jika ada konten subtitle nyata.
        Priority: Whisper → YouTube captions (clipped+offset) → skip (file kosong).
        """
        # 1. Coba Whisper
        try:
            import whisper  # type: ignore
            model = whisper.load_model("base")
            result = model.transcribe(str(video_path))
            self._write_srt_from_whisper(result, srt_path)
            return True
        except Exception:
            pass

        # 2. Coba YouTube captions (sudah ada dari yt_info, tidak perlu download ulang)
        if yt_info is not None:
            try:
                srt_text = self._vtt_to_srt_clipped(yt_info, clip_start, clip_start + duration)
                if srt_text.strip():
                    srt_path.write_text(srt_text, encoding="utf-8")
                    return True
            except Exception:
                pass

        # 3. Tidak ada subtitle — tulis file kosong, jangan burn
        srt_path.write_text("", encoding="utf-8")
        return False

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
        yt_info: dict | None = None
        if opts.source_type == "url":
            log("Mengambil info video dari YouTube...")
            try:
                yt_info = self._get_yt_info(opts.source)
            except Exception as e:
                log(f"[WARN] Gagal ambil info YouTube: {e}")
            log("Downloading dari YouTube...")
            src_path = self._download_youtube(opts.source, quality=opts.quality, progress_cb=progress_cb)
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
            # Masih generate metadata AI (judul/deskripsi) meski pakai custom time
            context = self._build_video_context(opts.source, opts.source_type, yt_info)
            log("Menggunakan timestamp manual — AI generate judul & metadata...")
            meta_opts_copy = ShortMakerOptions(
                source=opts.source, source_type=opts.source_type,
                topic=opts.topic, duration_preset="auto",
                language=opts.language,
            )
            try:
                meta_opts_copy.custom_start = start
                meta_opts_copy.custom_end = end
                metadata = self._generate_metadata(duration, meta_opts_copy, context)
                metadata["start_seconds"] = start
                metadata["end_seconds"] = end
            except Exception:
                metadata = {
                    "start_seconds": start,
                    "end_seconds": end,
                    "title": "Video Clip",
                    "description": "#shorts #viral #fyp #trending #reels",
                    "tags": ["shorts", "viral", "fyp", "trending", "reels"],
                    "pinned_comment": "",
                }
        else:
            log("AI menganalisis konten video...")
            context = self._build_video_context(opts.source, opts.source_type, yt_info)
            if context:
                log("✓ Konteks video berhasil diambil — metadata akan sesuai isi video")
            metadata = self._generate_metadata(duration, opts, context)
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
        if opts.transform_mode == "original":
            log("Mode original — pertahankan aspect ratio asli...")
            transformed_path = self.work_dir / f"trans_{job_id}.mp4"
            ff.transform_aspect(
                cut_path, transformed_path,
                mode="original",
                aspect=opts.aspect,
                quality=opts.quality,
                use_gpu=opts.use_gpu,
                encoding=opts.encoding,
                bypass_copyright=opts.bypass_copyright,
            )
        else:
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
        caption_applied = False
        if opts.caption_ai:
            log("Generate subtitle...")
            srt_path = self.work_dir / f"sub_{job_id}.srt"
            has_srt = self._generate_srt(
                transformed_path, srt_path,
                duration=ff.get_duration(transformed_path),
                yt_info=yt_info,
                clip_start=start,
            )
            if has_srt:
                captioned_path = self.work_dir / f"cap_{job_id}.mp4"
                try:
                    ff.burn_subtitles(transformed_path, captioned_path, srt_path,
                                      style_name=opts.caption_style,
                                      use_gpu=opts.use_gpu, encoding=opts.encoding)
                    final_src = captioned_path
                    caption_applied = True
                    log("✓ Subtitle berhasil diburn")
                except Exception as e:  # noqa: BLE001
                    log(f"[WARN] Subtitle gagal diburn: {e}")
                    final_src = transformed_path
            else:
                log("[INFO] Tidak ada subtitle tersedia — caption dilewati")
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
            caption_applied=caption_applied,
        )

    # ------------------------------------------------------- AI Find Viral
    def find_viral_moments(self, source: str, source_type: str, topic: str,
                           language: str = "id") -> Dict:
        """
        Scan video, return daftar momen viral terbaik.
        Untuk URL: ambil durasi + transcript dari metadata (tanpa download video).
        """
        if source_type == "url":
            info = self._get_yt_info(source)
            duration = float(info.get("duration") or 0)
            if duration <= 0:
                raise RuntimeError("Tidak bisa mendapatkan durasi video dari URL tersebut.")
            context = self._build_video_context(source, source_type, info)
        else:
            src_path = Path(source)
            duration = ff.get_duration(src_path)
            context = ""

        topic_desc = TOPICS.get(topic, TOPICS["free"])
        lang_label = "Bahasa Indonesia" if language == "id" else "English"
        context_block = f"\n\n--- KONTEN VIDEO ---\n{context}\n--- AKHIR KONTEN ---" if context else ""

        prompt = f"""Kamu adalah viral moment detector ahli untuk YouTube Shorts, TikTok, dan Instagram Reels.
Video berdurasi {duration:.1f} detik. Topik fokus: {topic_desc}.{context_block}

Berdasarkan konten video di atas, berikan hingga 10 kandidat momen viral terbaik.

Output JSON strict dalam {lang_label}:
{{
  "moments": [
    {{
      "start_seconds": <num>,
      "end_seconds": <num>,
      "title": "<judul click-bait 5-9 kata SESUAI ISI VIDEO>",
      "hook": "<1 kalimat hook dari isi video yang paling menarik>",
      "hook_quote": "<kutipan LANGSUNG dari transcript yang kuat untuk thumbnail/caption>",
      "score": <1-10>,
      "score_label": "<HOOK KUAT|PLOT TWIST|FAKTA MENGEJUTKAN|MOMEN EMOSIONAL|PUNCHLINE|VIRAL QUOTE|KONTROVERSI|TUTORIAL KEY|REVEAL|INSPIRASI>",
      "description": "<2 kalimat kenapa momen ini viral, berdasarkan isi video>",
      "caption_suggestion": "<caption siap-upload dengan emoji & hashtag, 2-4 kalimat, bahasa {lang_label}, SESUAI ISI VIDEO>"
    }}
  ]
}}

Aturan:
- start_seconds & end_seconds dalam rentang [0, {duration:.1f}]
- Durasi tiap clip 30–90 detik
- Judul, hook_quote, caption HARUS mencerminkan isi video nyata, bukan generik
- score_label harus salah satu dari daftar yang tersedia
- HANYA JSON, tanpa teks lain."""
        try:
            return self.gemini.generate_json(prompt)
        except Exception as e:  # noqa: BLE001
            return {"moments": [], "error": str(e)}
