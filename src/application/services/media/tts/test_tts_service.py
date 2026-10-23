import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.application.services.media.tts import tts_service as tts_module
from src.infra.external.edge_tts.edge_tts_provider import EdgeTtsProvider
from src.infra.external.gemini_tts.gemini_tts_provider import GeminiTtsProvider
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


class TestTtsServiceProviderSelection(unittest.TestCase):
    """Seleção do provider pelo `config.json` (trocar de engine = editar o JSON)."""

    def _with_config_file(self, content):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.json"
        if content is not None:
            path.write_text(content, encoding="utf-8")
        p = patch.object(tts_module, "_CONFIG_PATH", path)
        p.start()
        self.addCleanup(p.stop)

    def test_should_use_edge_tts_from_the_versioned_config_json(self):
        service = TtsService()
        self.assertEqual(service.config["provider"], "edge_tts")
        self.assertIsInstance(service.provider, EdgeTtsProvider)
        self.assertEqual(service.provider.default_voice, "pt-BR-FranciscaNeural")

    def test_should_read_the_config_file_when_given_an_empty_dict(self):
        # `config or _load_config()`: {} é falsy, então o JSON do disco vale.
        self._with_config_file(json.dumps({"provider": "gemini", "gemini": {"voice": "Puck"}}))
        service = TtsService(config={})
        self.assertIsInstance(service.provider, GeminiTtsProvider)
        self.assertEqual(service.provider.default_voice, "Puck")

    def test_should_fall_back_to_edge_tts_when_the_config_file_is_missing(self):
        self._with_config_file(None)
        service = TtsService()
        self.assertEqual(service.config, {"provider": "edge_tts"})
        self.assertIsInstance(service.provider, EdgeTtsProvider)

    def test_should_fall_back_to_edge_tts_when_the_config_file_is_invalid_json(self):
        self._with_config_file("{ nao e json")
        self.assertIsInstance(TtsService().provider, EdgeTtsProvider)

    def test_should_default_to_edge_tts_when_provider_key_is_absent(self):
        service = TtsService(config={"gemini": {}})
        self.assertIsInstance(service.provider, EdgeTtsProvider)

    def test_should_pass_only_the_provider_section_to_the_provider(self):
        service = TtsService(
            config={
                "provider": "gemini",
                "gemini": {"model": "modelo-x", "voice": "Puck", "sample_rate": 16000},
                "edge_tts": {"voice": "ignorada"},
            }
        )
        self.assertEqual(service.provider.model, "modelo-x")
        self.assertEqual(service.provider.default_voice, "Puck")
        self.assertEqual(service.provider.default_sample_rate, 16000)

    def test_should_build_the_provider_with_defaults_when_its_section_is_absent(self):
        service = TtsService(config={"provider": "edge_tts"})
        self.assertEqual(service.provider.default_voice, "pt-BR-FranciscaNeural")
        self.assertEqual(
            (service.provider.rate, service.provider.pitch, service.provider.volume),
            ("+0%", "+0Hz", "+0%"),
        )

    def test_should_name_the_unknown_provider_in_the_error(self):
        with self.assertRaisesRegex(ValueError, "Provider de TTS desconhecido: 'kokoro'"):
            TtsService(config={"provider": "kokoro"})

    def test_should_not_read_the_config_file_when_a_provider_is_injected(self):
        self._with_config_file('{"provider": "nope"}')
        provider = _FakeProvider()
        service = TtsService(provider=provider)
        self.assertIs(service.provider, provider)
        self.assertEqual(service.config, {"provider": "nope"})


if __name__ == "__main__":
    unittest.main()
