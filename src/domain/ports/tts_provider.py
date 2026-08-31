"""Contrato de um provedor de Text-To-Speech.

Trocar de engine (edge-tts, Kokoro, Gemini, XTTS...) é só implementar esta
interface e apontar o `config.json` para o novo provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TtsResult:
    def __init__(self, audio: bytes, mime: str):
        self.audio = audio
        self.mime = mime


class TtsProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def synthesize(
        self, text: str, *, voice: str | None = None, lang: str | None = None
    ) -> TtsResult:
        raise NotImplementedError
