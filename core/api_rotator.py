"""
API Key Rotator — Kelola rotasi ratusan Gemini API key otomatis.
Mendukung mode Round Robin & Smart.
Thread-safe, persistent ke keys.json.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any


def _resolve_storage_path(given: str | Path) -> Path:
    """
    Selalu simpan keys.json di sebelah .exe (app_root),
    bukan di current working directory.
    """
    p = Path(given)
    # Kalau path sudah absolut, pakai apa adanya
    if p.is_absolute():
        return p
    # Kalau frozen (PyInstaller .exe), simpan di sebelah .exe
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / p.name
    # Dev mode: simpan di sebelah script yang memanggil
    return Path(__file__).resolve().parent.parent / p.name


class KeyStatus(str, Enum):
    ACTIVE = "active"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID = "invalid"


@dataclass
class APIKey:
    key: str
    status: str = KeyStatus.ACTIVE.value
    last_used: float = 0.0
    error_count: int = 0
    quota_reset_at: float = 0.0
    usage_count: int = 0
    label: str = ""

    def masked(self) -> str:
        if len(self.key) <= 8:
            return "****"
        return self.key[:4] + "..." + self.key[-4:]

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "masked": self.masked(),
            "status": self.status,
            "last_used": self.last_used,
            "error_count": self.error_count,
            "quota_reset_at": self.quota_reset_at,
            "usage_count": self.usage_count,
            "label": self.label,
        }


class AllKeysExhaustedError(Exception):
    """Raised saat semua API key habis kuota / invalid."""


class APIKeyRotator:
    QUOTA_COOLDOWN = 60 * 60  # 1 jam
    VALID_MODES = ("round_robin", "smart")

    def __init__(self, storage_path: str | Path = "keys.json"):
        self.storage_path = _resolve_storage_path(storage_path)
        self._keys: List[APIKey] = []
        self._current = 0
        self._mode = "round_robin"
        self._lock = threading.Lock()
        self.load_from_file()

    # ---------------------------------------------------------------- CRUD
    def add_keys(self, keys_list: List[str], label_prefix: str = "") -> int:
        added = 0
        with self._lock:
            existing = {k.key for k in self._keys}
            for raw in keys_list:
                k = raw.strip()
                if not k or k in existing:
                    continue
                label = f"{label_prefix}{len(self._keys) + 1}" if label_prefix else ""
                self._keys.append(APIKey(key=k, label=label))
                existing.add(k)
                added += 1
        if added:
            self.save_to_file()
        return added

    def remove_key(self, masked_or_key: str) -> bool:
        with self._lock:
            before = len(self._keys)
            self._keys = [
                k for k in self._keys
                if k.key != masked_or_key and k.masked() != masked_or_key
            ]
            changed = len(self._keys) != before
            if self._current >= len(self._keys):
                self._current = 0
        if changed:
            self.save_to_file()
        return changed

    def clear_all(self) -> int:
        with self._lock:
            count = len(self._keys)
            self._keys = []
            self._current = 0
        self.save_to_file()
        return count

    # ---------------------------------------------------------------- Selection
    def set_mode(self, mode: str) -> None:
        if mode not in self.VALID_MODES:
            raise ValueError(f"Mode harus salah satu dari {self.VALID_MODES}")
        with self._lock:
            self._mode = mode
        self.save_to_file()

    def get_mode(self) -> str:
        return self._mode

    def _refresh_quota_status(self) -> None:
        now = time.time()
        for k in self._keys:
            if k.status == KeyStatus.QUOTA_EXCEEDED.value and k.quota_reset_at and now >= k.quota_reset_at:
                k.status = KeyStatus.ACTIVE.value
                k.quota_reset_at = 0.0

    def get_next_key(self) -> str:
        with self._lock:
            if not self._keys:
                raise AllKeysExhaustedError("Tidak ada API key tersedia. Tambahkan via API Key Manager.")

            self._refresh_quota_status()

            active = [i for i, k in enumerate(self._keys) if k.status == KeyStatus.ACTIVE.value]
            if not active:
                raise AllKeysExhaustedError(
                    "Semua API key habis kuota / invalid. Tambah key baru atau tunggu reset kuota."
                )

            if self._mode == "round_robin":
                ordered = sorted(active, key=lambda i: (i - self._current) % len(self._keys))
                idx = ordered[0]
                self._current = (idx + 1) % len(self._keys)
            else:
                idx = min(active, key=lambda i: self._keys[i].usage_count)

            k = self._keys[idx]
            k.last_used = time.time()
            k.usage_count += 1
            chosen_key = k.key

        self.save_to_file()
        return chosen_key

    # ---------------------------------------------------------------- Status updates
    def mark_quota_exceeded(self, key: str) -> None:
        with self._lock:
            for k in self._keys:
                if k.key == key:
                    k.status = KeyStatus.QUOTA_EXCEEDED.value
                    k.quota_reset_at = time.time() + self.QUOTA_COOLDOWN
                    break
        self.save_to_file()

    def mark_invalid(self, key: str) -> None:
        with self._lock:
            for k in self._keys:
                if k.key == key:
                    k.status = KeyStatus.INVALID.value
                    k.error_count += 1
                    break
        self.save_to_file()

    def mark_success(self, key: str) -> None:
        with self._lock:
            for k in self._keys:
                if k.key == key:
                    if k.status != KeyStatus.ACTIVE.value:
                        k.status = KeyStatus.ACTIVE.value
                    k.error_count = 0
                    break

    # ---------------------------------------------------------------- Stats
    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            self._refresh_quota_status()
            total = len(self._keys)
            active = sum(1 for k in self._keys if k.status == KeyStatus.ACTIVE.value)
            exhausted = sum(1 for k in self._keys if k.status == KeyStatus.QUOTA_EXCEEDED.value)
            invalid = sum(1 for k in self._keys if k.status == KeyStatus.INVALID.value)
        return {
            "total": total,
            "active": active,
            "quota_exceeded": exhausted,
            "invalid": invalid,
        }

    def list_keys_public(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._refresh_quota_status()
            return [k.to_public_dict() for k in self._keys]

    # ---------------------------------------------------------------- Persistence
    def save_to_file(self) -> None:
        try:
            data = {
                "mode": self._mode,
                "current": self._current,
                "keys": [asdict(k) for k in self._keys],
            }
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.storage_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(self.storage_path)
        except Exception as e:
            print(f"[APIKeyRotator] save error: {e}")

    def load_from_file(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._mode = data.get("mode", "round_robin")
            if self._mode not in self.VALID_MODES:
                self._mode = "round_robin"
            self._current = int(data.get("current", 0))
            self._keys = [APIKey(**k) for k in data.get("keys", [])]
        except Exception as e:
            print(f"[APIKeyRotator] load error: {e}")
            self._keys = []
            self._current = 0


# Singleton
rotator_singleton: Optional[APIKeyRotator] = None


def get_rotator() -> APIKeyRotator:
    global rotator_singleton
    if rotator_singleton is None:
        rotator_singleton = APIKeyRotator()
    return rotator_singleton
