"""Provedor de TTS via **edge-tts** (vozes neurais da Microsoft Edge).

Não é 100% offline — usa o endpoint de TTS do Edge (sem chave, sem custo) — mas
a qualidade pt-BR é melhor que a da maioria dos modelos open self-hosted e não
tem o 429/503 do Gemini preview.

Saída: MP3 (`audio/mpeg`). ffmpeg / faster-whisper / moviepy lidam com mp3.

`edge_tts` é importado só na hora de sintetizar (lazy) — assim o módulo carrega
mesmo sem o pacote instalado, e os testes injetam um fake via
`communicate_factory`.
"""

from __future__ import annotations

from src.domain.ports.tts_provider import TtsProvider, TtsResult

# lang (lower) → voz default
_VOICE_BY_LANG = {
    "pt-br": "pt-BR-FranciscaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "en": "en-US-AriaNeural",
    "en-us": "en-US-AriaNeural",
    "es": "es-ES-ElviraNeural",
    "es-es": "es-ES-ElviraNeural",
}


class EdgeTtsProvider(TtsProvider):
    name = "edge_tts"

    def __init__(self, config: dict | None = None, *, communicate_factory=None):
        config = config or {}
        self.default_voice = config.get("voice", "pt-BR-FranciscaNeural")
        self.rate = config.get("rate", "+0%")
        self.pitch = config.get("pitch", "+0Hz")
        self.volume = config.get("volume", "+0%")
        self._communicate_factory = communicate_factory

    def _factory(self):
        if self._communicate_factory is not None:
            return self._communicate_factory
        import edge_tts  # lazy

        return edge_tts.Communicate

    def _pick_voice(self, voice: str | None, lang: str | None) -> str:
        if voice:
            return voice
        if lang:
            mapped = _VOICE_BY_LANG.get(lang.lower())
            if mapped:
                return mapped
        return self.default_voice

    async def synthesize(
        self, text: str, *, voice: str | None = None, lang: str | None = None
    ) -> TtsResult:
        if not text or not text.strip():
            raise ValueError("Texto vazio para TTS.")

        Communicate = self._factory()
        communicate = Communicate(
            text,
            self._pick_voice(voice, lang),
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
        )

        buffer = bytearray()
        try:
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    buffer.extend(chunk["data"])
        except Exception as e:  # NoAudioReceived, rede, etc.
            raise RuntimeError(f"edge-tts falhou: {e!r}") from e

        if not buffer:
            raise RuntimeError(
                "edge-tts não retornou áudio (voz inválida ou sem conexão com o endpoint da Microsoft)."
            )

        return TtsResult(audio=bytes(buffer), mime="audio/mpeg")
