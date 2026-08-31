import unittest

from src.infra.external.edge_tts.edge_tts_provider import EdgeTtsProvider


class _FakeCommunicate:
    """Imita edge_tts.Communicate: guarda os args e streama chunks."""

    instances: list = []

    def __init__(self, text, voice, *, rate="+0%", volume="+0%", pitch="+0Hz"):
        self.text = text
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch
        self.chunks = [
            {"type": "audio", "data": b"ID3"},
            {"type": "WordBoundary", "text": "oi", "offset": 0},
            {"type": "audio", "data": b"\x00\x01"},
        ]
        _FakeCommunicate.instances.append(self)

    async def stream(self):
        for c in self.chunks:
            yield c


class _EmptyCommunicate(_FakeCommunicate):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.chunks = [{"type": "WordBoundary", "text": "oi"}]


class _RaisingCommunicate(_FakeCommunicate):
    async def stream(self):
        raise RuntimeError("NoAudioReceived")
        yield  # pragma: no cover


class TestEdgeTtsProvider(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _FakeCommunicate.instances = []

    async def test_concatena_os_chunks_de_audio_e_devolve_mp3(self):
        provider = EdgeTtsProvider(communicate_factory=_FakeCommunicate)
        result = await provider.synthesize("olá mundo", lang="pt-BR")

        assert result.mime == "audio/mpeg"
        assert result.audio == b"ID3\x00\x01"
        assert _FakeCommunicate.instances[0].voice == "pt-BR-FranciscaNeural"

    async def test_voz_explicita_tem_prioridade_sobre_o_lang(self):
        provider = EdgeTtsProvider(
            {"voice": "pt-BR-AntonioNeural"}, communicate_factory=_FakeCommunicate
        )
        await provider.synthesize("oi", voice="en-US-AriaNeural", lang="pt-BR")
        assert _FakeCommunicate.instances[0].voice == "en-US-AriaNeural"

    async def test_usa_a_voz_default_do_config_quando_sem_lang(self):
        provider = EdgeTtsProvider(
            {"voice": "pt-BR-ThalitaNeural"}, communicate_factory=_FakeCommunicate
        )
        await provider.synthesize("oi")
        assert _FakeCommunicate.instances[0].voice == "pt-BR-ThalitaNeural"

    async def test_texto_vazio_levanta_value_error(self):
        provider = EdgeTtsProvider(communicate_factory=_FakeCommunicate)
        with self.assertRaises(ValueError):
            await provider.synthesize("   ")

    async def test_sem_audio_recebido_levanta_runtime_error(self):
        provider = EdgeTtsProvider(communicate_factory=_EmptyCommunicate)
        with self.assertRaises(RuntimeError):
            await provider.synthesize("oi")

    async def test_erro_no_stream_vira_runtime_error(self):
        provider = EdgeTtsProvider(communicate_factory=_RaisingCommunicate)
        with self.assertRaises(RuntimeError):
            await provider.synthesize("oi")


if __name__ == "__main__":
    unittest.main()
