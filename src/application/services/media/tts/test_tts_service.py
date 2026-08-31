import unittest
from unittest.mock import AsyncMock

from src.domain.ports.tts_provider import TtsProvider, TtsResult
from src.application.services.media.tts.tts_service import TtsService


class _FakeProvider(TtsProvider):
    name = "fake"

    def __init__(self):
        self.mock = AsyncMock(return_value=TtsResult(b"wavbytes", "audio/wav"))

    async def synthesize(self, text, *, voice=None, lang=None):
        return await self.mock(text, voice=voice, lang=lang)


class TestTtsService(unittest.IsolatedAsyncioTestCase):
    async def test_should_delegate_to_the_injected_provider(self):
        provider = _FakeProvider()
        service = TtsService(provider=provider)

        result = await service.synthesize("texto", voice="Kore", lang="pt-BR")

        self.assertEqual(result.audio, b"wavbytes")
        provider.mock.assert_awaited_once_with("texto", voice="Kore", lang="pt-BR")

    def test_should_default_to_gemini_provider_from_config(self):
        service = TtsService(config={"provider": "gemini", "gemini": {}})
        self.assertEqual(service.provider.name, "gemini")

    def test_should_build_edge_tts_provider_from_config(self):
        service = TtsService(config={"provider": "edge_tts", "edge_tts": {}})
        self.assertEqual(service.provider.name, "edge_tts")

    def test_should_raise_on_unknown_provider(self):
        with self.assertRaises(ValueError):
            TtsService(config={"provider": "nope"})


if __name__ == "__main__":
    unittest.main()
