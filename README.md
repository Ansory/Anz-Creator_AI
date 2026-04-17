# ◈ Anz-Creator — AI Content Studio

> **Desktop Content Studio** untuk membuat **YouTube Shorts otomatis** dari video panjang dan **video storytelling sinematik** dari teks — semuanya bertenaga **Google Gemini AI**, berjalan lokal di Windows.

```
╔══════════════════════════════════════════════════════════╗
║  ANZ-CREATOR  //  AI CONTENT STUDIO  //  v1.0.0         ║
║  Short Maker  ·  Text-to-Story  ·  Multi-API Rotator    ║
╚══════════════════════════════════════════════════════════╝
```

---

## 🎯 Fitur Utama

### 1. **Short Maker** — Long Video → Viral Shorts
- Download video YouTube otomatis (yt-dlp)
- AI deteksi momen viral (Gemini menganalisis transkrip)
- Auto-cut + transformasi aspek rasio 9:16 (blur bg / bars / crop / smart)
- Generate judul, deskripsi, hashtag, caption otomatis
- Subtitle burn-in (SRT) + thumbnail
- **Bypass copyright mode** (eq filter + pitch shift + setpts)

### 2. **Text-to-Story** — Teks → Video Sinematik
- AI generate naskah scene-by-scene (Gemini)
- Auto fetch footage dari **Pexels** + **Pixabay** (portrait 9:16)
- TTS narasi via **gTTS** (ID/EN, kecepatan adjustable)
- Ken Burns effect (zoompan) per scene
- Background music (mood-based, optional)
- Preview naskah dulu sebelum render

### 3. **API Key Manager** — Gemini Multi-Key Rotator
- **Round-robin** atau **Smart mode** (skip quota-exceeded)
- Auto-cooldown 1 jam untuk key yang kena quota
- Import bulk, stats real-time
- Persistent storage di `keys.json`

---

## 📋 Prasyarat

| Komponen | Versi | Keterangan |
|----------|-------|------------|
| **Python** | 3.10+ | Wajib |
| **FFmpeg** | 6.0+ | Harus di PATH, atau set `FFMPEG_BIN` di `.env` |
| **Google Chrome** | — | Untuk UI (launcher auto-open) |
| **Windows** | 10/11 | Target utama (Linux/Mac bisa jalan tapi launcher belum dioptimasi) |

### Install FFmpeg di Windows
```powershell
# Via winget (recommended)
winget install Gyan.FFmpeg

# Atau download manual dari: https://www.gyan.dev/ffmpeg/builds/
# Extract ke C:\ffmpeg, lalu add C:\ffmpeg\bin ke System PATH
```

Cek instalasi:
```powershell
ffmpeg -version
ffprobe -version
```

---

## 🚀 Instalasi

### 1. Clone / Extract Project
```bash
cd C:\
# Extract Anz-Creator.zip, atau:
git clone <repo-url> Anz-Creator
cd Anz-Creator
```

### 2. Buat Virtual Environment (Recommended)
```powershell
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

> **Catatan:** `moviepy` dan `yt-dlp` cukup berat. Jika install lambat, gunakan mirror:
> ```powershell
> pip install -r requirements.txt -i https://pypi.org/simple
> ```

### 4. Konfigurasi `.env`
```powershell
copy .env.example .env
notepad .env
```

Isi file `.env`:
```ini
# Gemini API keys (pisahkan dengan koma jika banyak)
GEMINI_API_KEYS=AIzaSy...key1,AIzaSy...key2,AIzaSy...key3

# Pexels API (gratis di https://www.pexels.com/api/)
PEXELS_API_KEY=your_pexels_key_here

# Pixabay API (gratis di https://pixabay.com/api/docs/)
PIXABAY_API_KEY=your_pixabay_key_here

# Server
SERVER_PORT=8080
OUTPUT_DIR=outputs
```

> **Tips API Keys:**
> - Gemini free tier: 15 RPM per key. **Makin banyak key = makin cepat!**
> - Dapatkan di: https://aistudio.google.com/app/apikey
> - Bisa juga input via UI (menu "API Manager") tanpa edit `.env`.

---

## ▶️ Menjalankan Aplikasi

### Mode A: Development (paling mudah)
```powershell
python server.py
```
Lalu buka browser: **http://127.0.0.1:8080**

### Mode B: Launcher (auto-open Chrome)
```powershell
python launcher.py
```

### Mode C: Compiled `.exe` (distribusi ke user akhir)
```powershell
# Compile jadi single-file exe
pyinstaller --onefile --noconsole ^
    --name "Anz-Creator" ^
    --icon=assets/icon.ico ^
    --add-data "static;static" ^
    --add-data "server.py;." ^
    --add-data "core;core" ^
    launcher.py
```

Hasil: `dist/Anz-Creator.exe` — double-click, Chrome otomatis terbuka.

> **⚠️ Penting untuk `.exe`:**
> - FFmpeg **tidak** di-bundle by default. Ada 2 opsi:
>   1. **User install FFmpeg sendiri** (paling ringan, direkomendasi).
>   2. **Bundle FFmpeg** tambahkan flag: `--add-binary "C:\ffmpeg\bin\ffmpeg.exe;."` dan `--add-binary "C:\ffmpeg\bin\ffprobe.exe;."` (ukuran exe akan +100MB).
> - File `.env` harus ada di folder yang sama dengan `.exe` saat runtime.

---

## 📁 Struktur Folder

```
Anz-Creator/
├── server.py              # FastAPI server (endpoint + WebSocket)
├── launcher.py            # PyInstaller entry-point (auto-open Chrome)
├── requirements.txt
├── .env.example
├── .env                   # (tidak di-commit)
├── keys.json              # (auto-generated, tidak di-commit)
│
├── core/
│   ├── __init__.py
│   ├── api_rotator.py     # Gemini multi-key rotator
│   ├── gemini_client.py   # Wrapper Gemini + auto-retry
│   ├── ffmpeg_utils.py    # FFmpeg helpers (cut, transform, burn sub, etc)
│   ├── short_maker.py     # Pipeline: YouTube → Shorts
│   └── story_teller.py    # Pipeline: Text → Story video
│
├── static/                # Frontend (served by FastAPI)
│   ├── index.html
│   ├── css/style.css      # HUD Holographic Aurora theme
│   └── js/app.js          # Vanilla JS, no framework
│
├── assets/
│   ├── bgm/               # (opsional) MP3 per mood: cinematic.mp3, happy.mp3, dll
│   └── icon.ico           # Icon untuk .exe
│
└── outputs/               # File hasil generate (video, srt, thumbnail)
```

---

## 🎨 UI Theme — HUD Holographic Aurora

Desain terinspirasi **sci-fi cockpit display**:
- Background gelap (`#020408`) dengan grid overlay + scanlines
- Accent aurora: cyan `#00f7ff` · purple `#bf00ff` · pink `#ff006e` · green `#00ff88`
- Font: **JetBrains Mono** / Courier (monospace)
- Corner markers di setiap card (seperti HUD viewfinder)
- Gradient animation cycling di logo + tombol hero

---

## 🔧 Arsitektur Singkat

```
┌──────────────────────────────────────────────────────────┐
│                   launcher.py (.exe)                     │
│   └─ spawn server.py subprocess                         │
│   └─ wait /api/health                                    │
│   └─ open Chrome → http://127.0.0.1:8080                │
└──────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────────────────────────────────────┐
│                   server.py (FastAPI)                    │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐         │
│  │  /api/*    │  │  /ws/job/  │  │  /files/   │         │
│  │  endpoints │  │  WebSocket │  │  static    │         │
│  └────────────┘  └────────────┘  └────────────┘         │
└──────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
  ┌──────────┐      ┌──────────┐      ┌──────────┐
  │  Short   │      │  Story   │      │   API    │
  │  Maker   │      │  Teller  │      │ Rotator  │
  └─────┬────┘      └─────┬────┘      └──────────┘
        │                 │
        ▼                 ▼
  ┌──────────────────────────────┐
  │  FFmpeg + yt-dlp + gTTS      │
  │  + Gemini + Pexels + Pixabay │
  └──────────────────────────────┘
```

---

## 🐛 Troubleshooting

### `FFmpeg not found`
Pastikan FFmpeg ada di PATH, atau set eksplisit di `.env`:
```ini
FFMPEG_BIN=C:\ffmpeg\bin\ffmpeg.exe
FFPROBE_BIN=C:\ffmpeg\bin\ffprobe.exe
```

### `yt-dlp: Video unavailable` / `Sign in to confirm`
yt-dlp sering perlu update karena YouTube berubah-ubah:
```powershell
pip install -U yt-dlp
```

### `Gemini quota exceeded` terus-menerus
- Tambahkan lebih banyak API key di menu "API Manager".
- Switch mode dari `round_robin` ke `smart` (otomatis skip key yang kena limit).
- Free tier Gemini: 15 RPM, 1500 request/hari per key.

### Subtitle kosong / placeholder
Short Maker saat ini pakai fallback subtitle placeholder jika **Whisper tidak terinstall**. Untuk transkripsi real:
```powershell
pip install openai-whisper
```
Lalu Short Maker akan otomatis pakai Whisper untuk generate SRT asli.

### BGM tidak ada
Letakkan file MP3 di `assets/bgm/<mood>.mp3`, contoh:
```
assets/bgm/cinematic.mp3
assets/bgm/happy.mp3
assets/bgm/dark.mp3
assets/bgm/motivational.mp3
```
Jika file tidak ada, video akan tetap di-render tanpa BGM (cuma narasi TTS).

### Port 8080 sudah dipakai
Ubah di `.env`:
```ini
SERVER_PORT=9090
```

### `.exe` tidak bisa dibuka (Windows Defender)
PyInstaller compiled binary sering kena false-positive. Solusi:
1. Add folder `dist/` ke exception Windows Defender.
2. Atau sign binary dengan code-signing certificate (untuk distribusi publik).

---

## 📝 Catatan Penting

1. **Server local-only**: Bind ke `127.0.0.1`, tidak expose ke jaringan. Untuk multi-user, perlu setup tambahan (reverse proxy + auth).
2. **Keys.json**: File ini menyimpan API key dalam plaintext. **Jangan commit ke git**, sudah ada di `.gitignore`.
3. **Copyright**: Fitur "bypass copyright" hanya modifikasi teknis (pitch, speed, warna). **Bukan pengganti lisensi yang sah** — gunakan dengan bijak sesuai Term of Service YouTube/platform target.
4. **Gemini model**: Default `gemini-1.5-flash` (gratis, cepat). Bisa diganti ke `gemini-1.5-pro` di `core/gemini_client.py` untuk kualitas lebih tinggi (tapi quota lebih ketat).
5. **GPU encoding**: FFmpeg utils otomatis deteksi NVENC jika GPU NVIDIA tersedia. AMD/Intel user pakai software encoding (lebih lambat tapi tetap jalan).

---

## 🛣️ Roadmap

- [ ] Integrasi Whisper built-in untuk transkripsi akurat
- [ ] Bundle FFmpeg portable di installer
- [ ] Template scene custom untuk Story Teller
- [ ] Export batch (multi-video sekaligus)
- [ ] Theme switcher (dark aurora / light / cyberpunk)
- [ ] Auto-upload ke YouTube (OAuth)
- [ ] Voice cloning (Coqui TTS / ElevenLabs)

---

## 📜 Lisensi

Internal project. Gunakan untuk keperluan pribadi atau bisnis kecil. Tidak untuk redistribusi komersial tanpa izin.

---

## 🙏 Credits

- **Gemini** — Google AI
- **FFmpeg** — The FFmpeg team
- **yt-dlp** — yt-dlp contributors
- **Pexels / Pixabay** — Free stock footage providers
- **gTTS** — Google Text-to-Speech wrapper
- **FastAPI** — Sebastián Ramírez
- **PyInstaller** — PyInstaller team

Built with ⚡ by **Anz** · Trenggalek, East Java 🇮🇩

```
◈ ═══════════════════════════════════════ ◈
       "Make content. Break limits."
◈ ═══════════════════════════════════════ ◈
```
