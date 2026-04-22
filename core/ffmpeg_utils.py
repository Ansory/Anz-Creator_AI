"""
FFmpeg helper utilities — wrapper di atas subprocess ffmpeg.
Semua fungsi di sini menerima path file & return path hasil.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple


# -------------------------------------------------------------- Binary lookup
def _is_windows() -> bool:
    return os.name == "nt"


def _candidates(name: str) -> list[Path]:
    """
    Kumpulkan kandidat path untuk binary ffmpeg/ffprobe.
    Urutan: env var → sebelah .exe → PyInstaller bundle (_MEIPASS) →
            folder bin/ di project → PATH.
    """
    exe = f"{name}.exe" if _is_windows() else name
    out: list[Path] = []

    # 1. env var (FFMPEG_BIN / FFPROBE_BIN)
    env_key = f"{name.upper()}_BIN"
    ev = os.getenv(env_key)
    if ev:
        out.append(Path(ev))

    # 2. Sebelah .exe (frozen mode)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        out.append(exe_dir / exe)
        out.append(exe_dir / "bin" / exe)

    # 3. PyInstaller bundle dir (_MEIPASS)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.append(Path(meipass) / exe)
        out.append(Path(meipass) / "bin" / exe)

    # 4. Folder bin/ di project root
    project_root = Path(__file__).resolve().parent.parent
    out.append(project_root / "bin" / exe)
    out.append(project_root / exe)

    return out


def _resolve_binary(name: str) -> str:
    # Cek kandidat di atas dulu
    for p in _candidates(name):
        try:
            if p and p.is_file():
                return str(p)
        except OSError:
            continue
    # Fallback ke PATH
    which = shutil.which(name)
    if which:
        return which
    raise RuntimeError(
        f"{name} tidak ditemukan. Install FFmpeg dari https://ffmpeg.org/download.html, "
        f"taruh di folder `bin/`, atau set env var {name.upper()}_BIN di .env."
    )


def ffmpeg_bin() -> str:
    return _resolve_binary("ffmpeg")


def ffprobe_bin() -> str:
    return _resolve_binary("ffprobe")


def _no_console_flags() -> dict:
    """Di Windows, sembunyikan console popup saat spawn subprocess."""
    if _is_windows():
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


# -------------------------------------------------------------- Low-level runners
def run_ffmpeg(args: list[str], *, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error"] + args
    try:
        return subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            **_no_console_flags(),
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg gagal: {e.stderr or e.stdout}") from e


def probe(path: str | Path) -> dict:
    """Return JSON info dari ffprobe."""
    cmd = [
        ffprobe_bin(), "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    out = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_no_console_flags(),
    )
    return json.loads(out.stdout)


def get_duration(path: str | Path) -> float:
    """Return durasi file media dalam detik."""
    info = probe(path)
    try:
        return float(info["format"]["duration"])
    except (KeyError, ValueError):
        for s in info.get("streams", []):
            if "duration" in s:
                return float(s["duration"])
    return 0.0


def get_video_size(path: str | Path) -> Tuple[int, int]:
    info = probe(path)
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            return int(s["width"]), int(s["height"])
    return 0, 0


# -------------------------------------------------------------- Operasi dasar
def cut_video(src: str | Path, dst: str | Path, start: float, end: float) -> str:
    """Potong video dari start (detik) sampai end (detik)."""
    duration = max(0.1, end - start)
    run_ffmpeg([
        "-ss", f"{start:.3f}",
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        "-movflags", "+faststart",
        str(dst),
    ])
    return str(dst)


def extract_frame(src: str | Path, dst: str | Path, at: float = 1.0) -> str:
    run_ffmpeg([
        "-ss", f"{at:.2f}",
        "-i", str(src),
        "-frames:v", "1",
        "-q:v", "2",
        str(dst),
    ])
    return str(dst)


# -------------------------------------------------------------- Aspect transforms
_QUALITY_HEIGHTS: dict[str, int] = {
    "4K": 2160, "2K": 1440, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360,
}


def _target_res(aspect: str, quality: str) -> Tuple[int, int]:
    """Map aspect + quality ke (W, H) — selalu genap."""
    h = _QUALITY_HEIGHTS.get(quality, 1080)
    if aspect == "9:16":
        w = int(h * 9 / 16)
    elif aspect == "16:9":
        w = int(h * 16 / 9)
    elif aspect == "1:1":
        w = h
    elif aspect == "4:5":
        w = int(h * 4 / 5)
    else:
        w = int(h * 9 / 16)
    w = w // 2 * 2
    h = h // 2 * 2
    return w, h


def _encoder_flags(use_gpu: bool, encoding: str) -> list[str]:
    """encoding: 'quality' (libx264 slow) | 'balanced' (libx264 fast). GPU pakai h264_nvenc."""
    if use_gpu:
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4" if encoding == "balanced" else "p6",
            "-rc", "vbr", "-cq", "23",
        ]
    return [
        "-c:v", "libx264",
        "-preset", "fast" if encoding == "balanced" else "slow",
        "-crf", "20" if encoding == "quality" else "23",
    ]


def transform_aspect(
    src: str | Path,
    dst: str | Path,
    *,
    mode: str = "blur",             # blur | bars | crop | smart | original
    aspect: str = "9:16",
    quality: str = "1080p",
    use_gpu: bool = False,
    encoding: str = "balanced",
    bypass_copyright: bool = False,
) -> str:
    """
    Transform video ke aspect target dengan salah satu mode.
      - blur     : sisi kiri/kanan di-blur (background), video di-fit di tengah
      - bars     : sisi kiri/kanan black bars
      - crop     : center crop ke aspect target
      - smart    : sama dengan crop (placeholder AI scene detection)
      - original : scale ke target quality height, pertahankan aspect ratio asli
    """
    if mode == "original":
        h_target = (_QUALITY_HEIGHTS.get(quality, 1080) // 2) * 2
        vf = f"scale=-2:{h_target}"
        af_parts = []
        if bypass_copyright:
            vf = f"{vf},eq=contrast=1.03:saturation=1.05:brightness=0.02,setpts=PTS/1.02"
            af_parts.append("asetrate=44100*1.02,aresample=44100,atempo=0.9804")
        args = ["-i", str(src), "-vf", vf]
        if af_parts:
            args += ["-af", ",".join(af_parts)]
        args += _encoder_flags(use_gpu, encoding)
        args += ["-c:a", "aac", "-movflags", "+faststart", str(dst)]
        run_ffmpeg(args)
        return str(dst)

    W, H = _target_res(aspect, quality)

    if mode == "blur":
        vf = (
            f"split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},boxblur=luma_radius=30:luma_power=1[bgblur];"
            f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[fgscaled];"
            f"[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2"
        )
    elif mode == "bars":
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    else:  # crop / smart
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}"
        )

    # Bypass copyright meta: pitch-shift audio dikit + color grade + speed 1.02x
    af_parts = []
    if bypass_copyright:
        vf = f"{vf},eq=contrast=1.03:saturation=1.05:brightness=0.02,setpts=PTS/1.02"
        af_parts.append("asetrate=44100*1.02,aresample=44100,atempo=0.9804")

    args = ["-i", str(src), "-vf", vf]
    if af_parts:
        args += ["-af", ",".join(af_parts)]
    args += _encoder_flags(use_gpu, encoding)
    args += ["-c:a", "aac", "-movflags", "+faststart", str(dst)]

    run_ffmpeg(args)
    return str(dst)


# -------------------------------------------------------------- Subtitle burn
# Warna FFmpeg ASS format: &HAABBGGRR (AA=alpha 00=opaque, BB blue, GG green, RR red)
# Alignment=2 = bottom-center (standard subtitle position)
# WrapStyle=0 = smart wrap (potong kata tidak di tengah kata)
_CAPTION_STYLES: dict[str, str] = {
    "classic_white":    "FontName=Arial,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,WrapStyle=0",
    "hormozi_bold":     "FontName=Impact,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,BorderStyle=1,Outline=4,Shadow=0,Alignment=2,WrapStyle=0",
    "mrbeast":          "FontName=Arial Black,Bold=1,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BackColour=&H00000000,BorderStyle=1,Outline=5,Shadow=1,Alignment=2,WrapStyle=0",
    "ali_abdaal":       "FontName=Arial,Bold=0,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H60000000,BorderStyle=1,Outline=1,Shadow=1,Alignment=2,WrapStyle=0",
    "iman_gadzhi":      "FontName=Arial,Bold=1,Italic=1,PrimaryColour=&H00F0F0F0,OutlineColour=&H00111111,BackColour=&H00000000,BorderStyle=1,Outline=1,Shadow=0,Alignment=2,WrapStyle=0",
    "cyberpunk":        "FontName=Courier New,Bold=1,PrimaryColour=&H00FFFF00,OutlineColour=&H00FF00FF,BackColour=&H00000000,BorderStyle=1,Outline=2,Shadow=2,Alignment=2,WrapStyle=0",
    "aesthetic_retro":  "FontName=Arial,Bold=0,Italic=1,PrimaryColour=&H00FF80C0,OutlineColour=&H00800040,BackColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,WrapStyle=0",
    "movie_subtitle":   "FontName=Arial,Bold=0,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,WrapStyle=0",
    "hacker_terminal":  "FontName=Courier New,Bold=1,PrimaryColour=&H0000FF00,OutlineColour=&H00000000,BackColour=&HAA000000,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,WrapStyle=0",
    "comic_pop":        "FontName=Arial,Bold=1,PrimaryColour=&H00FF0000,OutlineColour=&H0000FFFF,BackColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,Alignment=2,WrapStyle=0",
    "fire_red":         "FontName=Impact,Bold=1,PrimaryColour=&H000000FF,OutlineColour=&H000060FF,BackColour=&H00000000,BorderStyle=1,Outline=3,Shadow=2,Alignment=2,WrapStyle=0",
    "box_kotak":        "FontName=Arial,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&HCC000000,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,WrapStyle=0",
    "neon_glow":        "FontName=Arial,Bold=1,PrimaryColour=&H00FFFF00,OutlineColour=&H00FFFF00,BackColour=&H00000000,BorderStyle=1,Outline=4,Shadow=3,Alignment=2,WrapStyle=0",
    "karaoke_green":    "FontName=Arial,Bold=1,PrimaryColour=&H0000FF00,SecondaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,WrapStyle=0",
}

# Font size sebagai rasio tinggi video — dikalibrasi untuk Shorts/Reels 9:16
_STYLE_SIZE_RATIOS: dict[str, float] = {
    "hormozi_bold":  0.048,   # Bold besar — word-by-word impact
    "mrbeast":       0.050,   # Kuning besar
    "fire_red":      0.046,   # Impact merah
    "comic_pop":     0.042,   # Tebal berwarna
    "ali_abdaal":    0.032,   # Elegan tipis
    "iman_gadzhi":   0.030,   # Italic halus
    "movie_subtitle":0.030,   # Subtitle bioskop kecil
    "hacker_terminal":0.032,  # Monospace kecil
    # default untuk style lainnya: 0.038
}

def _escape_ffmpeg_filter_path(p: str | Path) -> str:
    """
    Escape path untuk digunakan dalam filter FFmpeg (contoh: subtitles).
    - Ubah backslash ke forward slash
    - Escape colon (drive letter) dan backslash
    - Escape single quote
    """
    s = str(p).replace("\\", "/")
    # Escape colon hanya jika itu adalah drive letter (contoh: C:/)
    if _is_windows() and len(s) > 1 and s[1] == ":":
        s = s[0] + "\\:" + s[2:]
    s = s.replace("'", "'\\''")  # escape single quote
    return s


def burn_subtitles(src: str | Path, dst: str | Path, srt_path: str | Path,
                   style_name: str = "classic_white",
                   use_gpu: bool = False, encoding: str = "balanced") -> str:
    """Burn SRT subtitle ke video dengan caption style yang dipilih."""
    srt_escaped = _escape_ffmpeg_filter_path(srt_path)
    w, h = get_video_size(src)
    h = h or 1080
    w = w or 608

    size_ratio = _STYLE_SIZE_RATIOS.get(style_name, 0.038)
    font_size = max(14, int(h * size_ratio))

    # MarginV: 4% dari tinggi — mepet bawah seperti subtitle film/Shorts
    margin_v = max(20, int(h * 0.04))
    # MarginL/R: 5% dari lebar — teks tidak mepet tepi kiri/kanan
    margin_lr = max(20, int(w * 0.05))

    style_base = _CAPTION_STYLES.get(style_name, _CAPTION_STYLES["classic_white"])
    vf = (
        f"subtitles='{srt_escaped}':force_style='"
        f"{style_base},FontSize={font_size},"
        f"MarginV={margin_v},MarginL={margin_lr},MarginR={margin_lr}'"
    )
    args = ["-i", str(src), "-vf", vf]
    args += _encoder_flags(use_gpu, encoding)
    args += ["-c:a", "copy", str(dst)]
    run_ffmpeg(args)
    return str(dst)


# -------------------------------------------------------------- Concat
def _escape_concat_list_path(p: str | Path) -> str:
    """Escape path untuk file list concat demuxer (format: file '...')."""
    s = str(p).replace("\\", "/")
    # Escape single quote
    s = s.replace("'", "'\\''")
    return s


def concat_videos(inputs: list[str | Path], dst: str | Path) -> str:
    """Concat videos dengan re-encode (aman untuk codec campuran)."""
    if not inputs:
        raise ValueError("Daftar video kosong")

    listfile = Path(dst).with_suffix(".concat.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for p in inputs:
            escaped = _escape_concat_list_path(p)
            f.write(f"file '{escaped}'\n")

    try:
        run_ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", str(listfile),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(dst),
        ])
    finally:
        listfile.unlink(missing_ok=True)
    return str(dst)


# -------------------------------------------------------------- Audio mix
def mix_audio(video: str | Path, narration: str | Path, dst: str | Path,
              bgm: Optional[str | Path] = None,
              narration_volume: float = 1.0,
              bgm_volume: float = 0.15) -> str:
    """
    Gabung video + narasi + (opsional) BGM.
    Audio video asli di-mute.
    """
    args: list[str] = ["-i", str(video), "-i", str(narration)]
    if bgm:
        args += ["-i", str(bgm)]
        filter_complex = (
            f"[1:a]volume={narration_volume}[narr];"
            f"[2:a]volume={bgm_volume},aloop=loop=-1:size=2e9[bg];"
            f"[narr][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        args += ["-filter_complex", filter_complex, "-map", "0:v", "-map", "[aout]"]
    else:
        args += ["-map", "0:v", "-map", "1:a"]

    args += [
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        str(dst),
    ]
    run_ffmpeg(args)
    return str(dst)


# -------------------------------------------------------------- Ken Burns
def apply_ken_burns(src: str | Path, dst: str | Path, duration: float,
                    size: Tuple[int, int] = (1080, 1920)) -> str:
    """
    Terapkan efek slow zoom-in (Ken Burns) ke video/image.
    """
    W, H = size
    fps = 30
    total_frames = int(duration * fps)
    # zoom dari 1.0 ke 1.15 secara linear
    zoom_expr = f"min(zoom+0.0008,1.15)"
    vf = (
        f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
        f"crop={W*2}:{H*2},"
        f"zoompan=z='{zoom_expr}':d={total_frames}:s={W}x{H}:fps={fps}"
    )
    run_ffmpeg([
        "-i", str(src),
        "-vf", vf,
        "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        str(dst),
    ])
    return str(dst)
