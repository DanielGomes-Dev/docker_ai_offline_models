"""Serviço de TTS: escolhe o provider a partir do `config.json` e delega.

O provider pode ser injetado (testes) ou resolvido pelo config (produção).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.application.services.media.tts.edge_tts_provider import EdgeTtsProvider
from src.application.services.media.tts.gemini_tts_provider import GeminiTtsProvider
from src.application.services.media.tts.tts_provider import TtsProvider, TtsResult

_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

_PROVIDERS = {
    "edge_tts": EdgeTtsProvider,
    "gemini": GeminiTtsProvider,
}


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"provider": "edge_tts"}


class TtsService:
    def __init__(self, provider: TtsProvider | None = None, config: dict | None = None):
        self.config = config or _load_config()
        if provider is not None:
            self.provider = provider
        else:
            name = self.config.get("provider", "edge_tts")
            provider_cls = _PROVIDERS.get(name)
            if provider_cls is None:
                raise ValueError(f"Provider de TTS desconhecido: {name!r}")
            self.provider = provider_cls(self.config.get(name, {}))

    async def synthesize(
        self, text: str, *, voice: str | None = None, lang: str | None = None
    ) -> TtsResult:
        return await self.provider.synthesize(text, voice=voice, lang=lang)
