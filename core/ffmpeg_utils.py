"""
FFmpeg helper utilities — wrapper di atas subprocess ffmpeg.
Semua fungsi di sini menerima path file & return path hasil.
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple


# -------------------------------------------------------------- Binary lookup
def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError(
            "FFmpeg tidak ditemukan di PATH. Install FFmpeg dari https://ffmpeg.org/download.html "
            "atau bundle bersama .exe di folder /bin."
        )
    return path


def ffprobe_bin() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise RuntimeError("ffprobe tidak ditemukan di PATH.")
    return path


# -------------------------------------------------------------- Low-level runners
def run_ffmpeg(args: list[str], *, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg gagal: {e.stderr or e.stdout}") from e


def probe(path: str | Path) -> dict:
    """Return JSON info dari ffprobe."""
    cmd = [
        ffprobe_bin(), "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
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
def _target_res(aspect: str, quality: str) -> Tuple[int, int]:
    """Map aspect + quality ke (W, H)."""
    heights = {"1080p": 1080, "720p": 720, "480p": 480}
    h = heights.get(quality, 1080)
    if aspect == "9:16":
        return int(h * 9 / 16), h
    if aspect == "16:9":
        return int(h * 16 / 9), h
    if aspect == "1:1":
        return h, h
    return int(h * 9 / 16), h


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
    mode: str = "blur",             # blur | bars | crop | smart
    aspect: str = "9:16",
    quality: str = "1080p",
    use_gpu: bool = False,
    encoding: str = "balanced",
    bypass_copyright: bool = False,
) -> str:
    """
    Transform video ke aspect target dengan salah satu mode.
      - blur  : sisi kiri/kanan di-blur (background), video di-fit di tengah
      - bars  : sisi kiri/kanan black bars
      - crop  : center crop ke aspect target
      - smart : sama dengan crop untuk sekarang (placeholder untuk AI scene detection)
    """
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
        af_parts.append("asetrate=44100*1.02,aresample=44100,atempo=1/1.02*1.02")

    args = ["-i", str(src), "-vf", vf]
    if af_parts:
        args += ["-af", ",".join(af_parts)]
    args += _encoder_flags(use_gpu, encoding)
    args += ["-c:a", "aac", "-movflags", "+faststart", str(dst)]

    run_ffmpeg(args)
    return str(dst)


# -------------------------------------------------------------- Subtitle burn
def burn_subtitles(src: str | Path, dst: str | Path, srt_path: str | Path,
                   use_gpu: bool = False, encoding: str = "balanced") -> str:
    """Burn SRT subtitle ke video. Path SRT perlu di-escape untuk filter graph."""
    srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")
    vf = f"subtitles='{srt_escaped}':force_style='FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=2,Shadow=0,Alignment=2'"
    args = ["-i", str(src), "-vf", vf]
    args += _encoder_flags(use_gpu, encoding)
    args += ["-c:a", "copy", str(dst)]
    run_ffmpeg(args)
    return str(dst)


# -------------------------------------------------------------- Concat
def concat_videos(inputs: list[str | Path], dst: str | Path) -> str:
    """Concat videos dengan re-encode (aman untuk codec campuran)."""
    if not inputs:
        raise ValueError("Daftar video kosong")

    listfile = Path(dst).with_suffix(".concat.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for p in inputs:
            p_abs = str(Path(p).resolve()).replace("\\", "/")
            f.write(f"file '{p_abs}'\n")

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
    Bagus untuk footage statis di story teller.
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
