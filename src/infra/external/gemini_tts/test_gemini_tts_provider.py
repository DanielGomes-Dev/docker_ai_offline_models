import base64
import io
import unittest
import wave
from unittest.mock import patch

import httpx

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


class _NetworkErrorThen(FakeAsyncClient):
    """Levanta erro de rede nas primeiras N chamadas e depois devolve as respostas."""

    def __init__(self, failures, responses):
        super().__init__(responses=responses)
        self.failures = failures

    async def post(self, url, **kwargs):
        if self.failures:
            self.failures -= 1
            self.calls.append(("POST", url, kwargs))
            raise httpx.ConnectError("conexão recusada")
        return await super().post(url, **kwargs)


class TestGeminiTtsRequestAndErrors(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        keys_patch = patch.object(mod, "available_api_keys", return_value=["k1", "k2"])
        keys_patch.start()
        self.addCleanup(keys_patch.stop)

    async def _run(self, fake, config=None, **kwargs):
        with patch.object(mod.httpx, "AsyncClient", return_value=fake):
            return await GeminiTtsProvider(config or {"overloaded_backoff_s": 0}).synthesize(
                "olá", **kwargs
            )

    async def test_should_call_generate_content_of_the_model_with_the_key(self):
        fake = FakeAsyncClient(single=_audio_response())
        await self._run(fake, {"model": "modelo-tts", "overloaded_backoff_s": 0})
        self.assertEqual(
            fake.calls[0][1],
            "https://generativelanguage.googleapis.com/v1beta/models/modelo-tts:generateContent?key=k1",
        )

    async def test_should_ask_for_audio_with_the_default_voice(self):
        fake = FakeAsyncClient(single=_audio_response())
        await self._run(fake)
        payload = fake.calls[0][2]["json"]
        self.assertEqual(payload["contents"], [{"parts": [{"text": "olá"}]}])
        self.assertEqual(payload["generationConfig"]["responseModalities"], ["AUDIO"])
        voice = payload["generationConfig"]["speechConfig"]["voiceConfig"]
        self.assertEqual(voice, {"prebuiltVoiceConfig": {"voiceName": "Kore"}})

    async def test_explicit_voice_wins_and_lang_is_ignored(self):
        fake = FakeAsyncClient(single=_audio_response())
        await self._run(fake, voice="Puck", lang="en-US")
        payload = fake.calls[0][2]["json"]
        voice = payload["generationConfig"]["speechConfig"]["voiceConfig"]
        self.assertEqual(voice["prebuiltVoiceConfig"]["voiceName"], "Puck")
        self.assertNotIn("en-US", str(payload))

    async def test_network_error_retries_the_same_key(self):
        fake = _NetworkErrorThen(1, [_audio_response()])
        result = await self._run(fake)
        self.assertEqual(result.mime, "audio/wav")
        self.assertEqual([c[1].endswith("key=k1") for c in fake.calls], [True, True])

    async def test_network_errors_on_every_attempt_end_in_runtime_error(self):
        fake = _NetworkErrorThen(4, [])
        with self.assertRaisesRegex(RuntimeError, "erro de rede"):
            await self._run(fake, {"overloaded_backoff_s": 0, "overloaded_retries": 2})
        self.assertEqual(len(fake.calls), 4)  # 2 chaves × 2 tentativas

    async def test_quota_marker_in_body_skips_to_next_key_even_without_429(self):
        fake = FakeAsyncClient(
            responses=[FakeResponse(400, text="RESOURCE_EXHAUSTED: quota"), _audio_response()]
        )
        await self._run(fake)
        self.assertTrue(fake.calls[1][1].endswith("key=k2"))

    async def test_internal_marker_is_treated_as_overloaded(self):
        fake = FakeAsyncClient(responses=[FakeResponse(400, text="INTERNAL"), _audio_response()])
        await self._run(fake)
        self.assertEqual([c[1].endswith("key=k1") for c in fake.calls], [True, True])

    async def test_definitive_error_raises_http_status_error_without_trying_other_keys(self):
        fake = FakeAsyncClient(single=FakeResponse(400, text="INVALID_ARGUMENT"))
        with self.assertRaises(httpx.HTTPStatusError):
            await self._run(fake)
        self.assertEqual(len(fake.calls), 1)

    async def test_last_error_is_in_the_final_message(self):
        fake = FakeAsyncClient(single=FakeResponse(429, text="cota estourada"))
        with self.assertRaisesRegex(RuntimeError, "HTTP 429: cota estourada"):
            await self._run(fake)

    async def test_unexpected_200_body_raises_runtime_error(self):
        fake = FakeAsyncClient(single=FakeResponse(200, {"candidates": []}))
        with self.assertRaisesRegex(RuntimeError, "Resposta de TTS inesperada"):
            await self._run(fake)

    async def test_missing_rate_in_mime_uses_the_configured_sample_rate(self):
        response = _audio_response()
        response._json["candidates"][0]["content"]["parts"][0]["inlineData"]["mimeType"] = "audio/L16"
        fake = FakeAsyncClient(single=response)
        result = await self._run(fake, {"sample_rate": 22050, "overloaded_backoff_s": 0})
        with wave.open(io.BytesIO(result.audio), "rb") as w:
            self.assertEqual(w.getframerate(), 22050)
            self.assertEqual(w.readframes(w.getnframes()), _PCM)


if __name__ == "__main__":
    unittest.main()
