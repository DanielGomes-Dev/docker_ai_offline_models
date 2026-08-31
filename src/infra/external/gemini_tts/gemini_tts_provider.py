"""Provedor de TTS via Gemini (`gemini-2.5-flash-preview-tts` por padrão).

Usa a REST API do Google Generative Language direto (httpx) — o
`langchain-google-genai` não expõe saída de áudio. A resposta vem como PCM
16-bit mono base64; embrulhamos num container WAV antes de devolver.

Resiliência:
  * 429 / RESOURCE_EXHAUSTED  → cota da chave estourou: pula para a próxima chave.
  * 503 / 500 / UNAVAILABLE   → o modelo (preview) está sobrecarregado: espera um
    backoff e tenta de novo NA MESMA chave (trocar de chave não ajuda); só depois
    passa para a próxima.
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
import struct
import wave

import httpx

from src.application.services.models.google_api_keys import available_api_keys
from src.application.services.media.tts.tts_provider import TtsProvider, TtsResult

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_QUOTA_MARKERS = ("RESOURCE_EXHAUSTED",)
_OVERLOADED_MARKERS = ("UNAVAILABLE", "OVERLOADED", "INTERNAL")
_OVERLOADED_STATUS = {500, 503}


class GeminiTtsProvider(TtsProvider):
    name = "gemini"

    def __init__(self, config: dict | None = None, *, timeout: float = 120.0):
        config = config or {}
        self.model = config.get("model", "gemini-2.5-flash-preview-tts")
        self.default_voice = config.get("voice", "Kore")
        self.default_sample_rate = int(config.get("sample_rate", 24000))
        self.timeout = timeout
        # nº de tentativas por chave quando o modelo está sobrecarregado (503)
        self.overloaded_retries = int(config.get("overloaded_retries", 4))
        self.overloaded_backoff_s = float(config.get("overloaded_backoff_s", 5.0))

    async def synthesize(
        self, text: str, *, voice: str | None = None, lang: str | None = None
    ) -> TtsResult:
        if not text or not text.strip():
            raise ValueError("Texto vazio para TTS.")

        keys = available_api_keys()
        if not keys:
            raise RuntimeError("Nenhuma chave GOOGLE_API_KEY disponível para o TTS.")

        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice or self.default_voice}
                    }
                },
            },
        }

        last_error: str = "sem detalhes"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for key in keys:
                url = f"{_BASE_URL}/{self.model}:generateContent?key={key}"

                for attempt in range(self.overloaded_retries):
                    try:
                        resp = await client.post(url, json=payload)
                    except httpx.HTTPError as e:  # rede/timeout
                        last_error = f"erro de rede: {e!r}"
                        await asyncio.sleep(self.overloaded_backoff_s)
                        continue

                    if resp.status_code == 200:
                        return self._parse(resp.json())

                    body = resp.text.upper()
                    last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"

                    if resp.status_code == 429 or any(m in body for m in _QUOTA_MARKERS):
                        break  # cota estourou → próxima chave

                    if resp.status_code in _OVERLOADED_STATUS or any(
                        m in body for m in _OVERLOADED_MARKERS
                    ):
                        wait = self.overloaded_backoff_s * (attempt + 1)
                        print(
                            f"[gemini-tts] modelo sobrecarregado ({resp.status_code}), "
                            f"tentativa {attempt + 1}/{self.overloaded_retries}, "
                            f"aguardando {wait:.0f}s..."
                        )
                        await asyncio.sleep(wait)
                        continue

                    # erro definitivo (400, 404, safety, ...) → propaga
                    resp.raise_for_status()

        raise RuntimeError(f"TTS Gemini falhou após todas as tentativas: {last_error}")

    def _parse(self, data: dict) -> TtsResult:
        try:
            part = data["candidates"][0]["content"]["parts"][0]
            inline = part["inlineData"]
            pcm = base64.b64decode(inline["data"])
            mime = inline.get("mimeType", "")
        except (KeyError, IndexError, TypeError, struct.error) as e:
            raise RuntimeError(f"Resposta de TTS inesperada do Gemini: {data!r}") from e

        rate = _rate_from_mime(mime, self.default_sample_rate)
        wav = _pcm_to_wav(pcm, sample_rate=rate)
        return TtsResult(audio=wav, mime="audio/wav")


def _pcm_to_wav(pcm: bytes, *, sample_rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _rate_from_mime(mime: str, default: int) -> int:
    match = re.search(r"rate=(\d+)", mime or "")
    return int(match.group(1)) if match else default
