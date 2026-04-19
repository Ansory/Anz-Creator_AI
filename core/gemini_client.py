"""
Gemini API client dengan auto-rotation key.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import google.generativeai as genai
from .api_rotator import APIKeyRotator, AllKeysExhaustedError

class GeminiClient:
    MODEL_TEXT = "gemini-3.1-flash-lite-preview"
    MAX_RETRIES_PER_CALL = 10
    MAX_OUTPUT_TOKENS = 8192

    def __init__(self, rotator: APIKeyRotator):
        self.rotator = rotator

    def generate(self, prompt: str, *, json_mode: bool = False, temperature: float = 0.7) -> str:
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

                model = genai.GenerativeModel(model_name=self.MODEL_TEXT, generation_config=gen_config)
                resp = model.generate_content(prompt)
                
                text = ""
                try:
                    text = (resp.text or "").strip()
                except Exception:
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
                
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                
                # Evaluasi error handling yang bersih tanpa duplikasi
                if any(k in msg for k in ["quota", "429", "rate", "exhaust"]):
                    self.rotator.mark_quota_exceeded(key)
                elif any(k in msg for k in ["api key", "invalid", "permission", "401", "403"]):
                    self.rotator.mark_invalid(key)
                # Jika error selain dari API key/quota, lanjutkan mencoba key berikutnya
                continue

        raise RuntimeError(f"Gemini gagal setelah retry. Error terakhir: {last_err}")

    def generate_json(self, prompt: str, *, temperature: float = 0.7) -> Any:
        raw = self.generate(prompt, json_mode=True, temperature=temperature)
        cleaned = raw.strip()
        cleaned = re.sub(r"^
http://googleusercontent.com/immersive_entry_chip/0
