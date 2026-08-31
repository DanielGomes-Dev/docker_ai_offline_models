import base64
import io
import unittest
import wave
from unittest.mock import patch

from src.infra.external.gemini_tts import gemini_tts_provider as mod
from src.infra.external.gemini_tts.gemini_tts_provider import GeminiTtsProvider
from tests_support.httpx_fake import FakeAsyncClient, FakeResponse

_PCM = b"\x01\x02" * 1000


def _audio_response(rate=24000):
    return FakeResponse(
        200,
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": f"audio/L16;codec=pcm;rate={rate}",
                                    "data": base64.b64encode(_PCM).decode("ascii"),
                                }
                            }
                        ]
                    }
                }
            ]
        },
    )


class TestGeminiTtsProvider(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        keys_patch = patch.object(mod, "available_api_keys", return_value=["k1", "k2"])
        keys_patch.start()
        self.addCleanup(keys_patch.stop)

    async def test_should_wrap_pcm_into_a_valid_wav(self):
        fake = FakeAsyncClient(single=_audio_response(24000))
        with patch.object(mod.httpx, "AsyncClient", return_value=fake):
            result = await GeminiTtsProvider().synthesize("olá mundo")

        self.assertEqual(result.mime, "audio/wav")
        with wave.open(io.BytesIO(result.audio), "rb") as w:
            self.assertEqual(w.getframerate(), 24000)
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)

    async def test_should_use_the_sample_rate_from_the_response_mime(self):
        fake = FakeAsyncClient(single=_audio_response(16000))
        with patch.object(mod.httpx, "AsyncClient", return_value=fake):
            result = await GeminiTtsProvider().synthesize("oi")
        with wave.open(io.BytesIO(result.audio), "rb") as w:
            self.assertEqual(w.getframerate(), 16000)

    async def test_should_fall_back_to_the_next_key_on_429(self):
        fake = FakeAsyncClient(responses=[FakeResponse(429, text="RESOURCE_EXHAUSTED"), _audio_response()])
        with patch.object(mod.httpx, "AsyncClient", return_value=fake):
            result = await GeminiTtsProvider().synthesize("oi")
        self.assertEqual(result.mime, "audio/wav")
        self.assertEqual(len(fake.calls), 2)

    async def test_should_raise_when_all_keys_exhausted(self):
        fake = FakeAsyncClient(responses=[FakeResponse(429, text="429"), FakeResponse(429, text="429")])
        with patch.object(mod.httpx, "AsyncClient", return_value=fake):
            with self.assertRaises(RuntimeError):
                await GeminiTtsProvider().synthesize("oi")

    async def test_should_retry_same_key_on_503_then_succeed(self):
        fake = FakeAsyncClient(
            responses=[FakeResponse(503, text="UNAVAILABLE: model overloaded"), _audio_response()]
        )
        with patch.object(mod.httpx, "AsyncClient", return_value=fake):
            result = await GeminiTtsProvider({"overloaded_backoff_s": 0}).synthesize("oi")
        self.assertEqual(result.mime, "audio/wav")
        self.assertEqual(len(fake.calls), 2)

    async def test_should_give_up_after_exhausting_503_retries_on_all_keys(self):
        fake = FakeAsyncClient(single=FakeResponse(503, text="UNAVAILABLE"))
        with patch.object(mod.httpx, "AsyncClient", return_value=fake):
            with self.assertRaises(RuntimeError):
                await GeminiTtsProvider(
                    {"overloaded_backoff_s": 0, "overloaded_retries": 2}
                ).synthesize("oi")
        # 2 chaves × 2 tentativas
        self.assertEqual(len(fake.calls), 4)

    async def test_should_propagate_definitive_errors_like_400(self):
        fake = FakeAsyncClient(single=FakeResponse(400, text="INVALID_ARGUMENT"))
        with patch.object(mod.httpx, "AsyncClient", return_value=fake):
            with self.assertRaises(Exception):
                await GeminiTtsProvider({"overloaded_backoff_s": 0}).synthesize("oi")

    async def test_should_raise_on_empty_text(self):
        with self.assertRaises(ValueError):
            await GeminiTtsProvider().synthesize("   ")

    async def test_should_raise_when_no_api_keys(self):
        with patch.object(mod, "available_api_keys", return_value=[]):
            with self.assertRaises(RuntimeError):
                await GeminiTtsProvider().synthesize("oi")


if __name__ == "__main__":
    unittest.main()
