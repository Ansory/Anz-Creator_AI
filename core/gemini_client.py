"""
Gemini API client dengan auto-rotation key.
Setiap call akan otomatis ambil key dari APIKeyRotator,
dan kalau dapat error 429 (quota) → mark & retry dengan key berikutnya.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import google.generativeai as genai

from .api_rotator import APIKeyRotator, AllKeysExhaustedError


class GeminiClient:
    # Gunakan model yang tersedia di free tier Gemini.
    MODEL_TEXT = "gemini-1.5-flash"
    MAX_RETRIES_PER_CALL = 10  # max swap key sebelum menyerah
    MAX_OUTPUT_TOKENS = 8192

    def __init__(self, rotator: APIKeyRotator):
        self.rotator = rotator

    def generate(self, prompt: str, *, json_mode: bool = False,
                 temperature: float = 0.7) -> str:
        """
        Generate text pakai Gemini. Auto retry dengan key lain kalau quota.
        Return: raw text response.
        """
        last_err: Optional[Exception] = None
        for _ in range(self.MAX_RETRIES_PER_CALL):
            try:
                key = self.rotator.get_next_key()
            except AllKeysExhaustedError:
                raise

            try:
                genai.configure(api_key=key)
                gen_config: Dict[str, Any] = {
                    "temperature": temperature,
                    "max_output_tokens": self.MAX_OUTPUT_TOKENS,
                }
                if json_mode:
                    gen_config["response_mime_type"] = "application/json"

                model = genai.GenerativeModel(
                    model_name=self.MODEL_TEXT,
                    generation_config=gen_config,
                )
                resp = model.generate_content(prompt)
                text = ""
                try:
                    text = (resp.text or "").strip()
                except Exception:
                    # Kalau .text raise (mis. safety block), gabung dari candidates
                    for c in getattr(resp, "candidates", []) or []:
                        for part in getattr(getattr(c, "content", None), "parts", []) or []:
                            t = getattr(part, "text", None)
                            if t:
                                text += t
                    text = text.strip()
                if not text:
                    raise RuntimeError("Gemini mengembalikan response kosong.")
                self.rotator.mark_success(key)
                return text
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = str(e).lower()
                if "quota" in msg or "429" in msg or "rate" in msg or "exhaust" in msg:
                    self.rotator.mark_quota_exceeded(key)
                    continue
                if "api key" in msg or "invalid" in msg or "permission" in msg or "401" in msg or "403" in msg:
                    self.rotator.mark_invalid(key)
                    continue
                # error lain: retry pakai key berikutnya
                continue

        raise RuntimeError(f"Gemini gagal setelah retry. Error terakhir: {last_err}")

    def generate_json(self, prompt: str, *, temperature: float = 0.7) -> Any:
        """Generate & parse JSON. Return dict/list."""
        raw = self.generate(prompt, json_mode=True, temperature=temperature)
        # pembersihan: ada kasus model membungkus dengan ``` fences
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # coba ekstrak JSON object/array dari text
            match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            raise
