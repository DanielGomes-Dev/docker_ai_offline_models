"""Testes de MediaController (src/interfaces/api/media/media_controller.py)."""

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.interfaces.api.media.media_controller import MediaController


class _Res:
    def __init__(self, audio, mime):
        self.audio = audio
        self.mime = mime


class _FakeUpload:
    def __init__(self, data: bytes, filename="a.wav"):
        self._data = data
        self.filename = filename
        self._sent = False

    async def read(self, _n=-1):
        if self._sent:
            return b""
        self._sent = True
        return self._data


@pytest.fixture
def controller():
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=_Res(b"ID3mp3", "audio/mpeg"))
    transcribe = MagicMock()
    transcribe.transcribe = MagicMock(
        return_value={"words": [], "word_srt": "", "sentence_srt": "", "duration_s": 3.0}
    )
    return MediaController(tts_service=tts, transcribe_service=transcribe)


class TestTts:
    async def test_devolve_audio_base64(self, controller):
        out = await controller.tts({"text": "olá", "lang": "pt-BR"})
        assert out["mime"] == "audio/mpeg"
        assert base64.b64decode(out["data_b64"]) == b"ID3mp3"
        controller.tts_service.synthesize.assert_awaited_once_with(
            "olá", voice=None, lang="pt-BR"
        )

    async def test_text_ausente_vira_erro(self, controller):
        out = await controller.tts({})
        assert out["status"] == "error"

    async def test_value_error_do_provider_vira_erro(self, controller):
        controller.tts_service.synthesize = AsyncMock(side_effect=ValueError("vazio"))
        out = await controller.tts({"text": "x"})
        assert out["status"] == "error"


class TestTranscribe:
    async def test_salva_upload_e_devolve_o_resultado(self, controller, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = await controller.transcribe(
            {"file": _FakeUpload(b"RIFFwav"), "body": {"language": "pt"}}
        )
        assert out["duration_s"] == 3.0
        args, _ = controller.transcribe_service.transcribe.call_args
        assert args[1] == "pt"  # language repassado
        assert (tmp_path / "files" / "temp" / "audio_in").exists()

    async def test_erro_na_transcricao_vira_dict_de_erro(self, controller, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        controller.transcribe_service.transcribe = MagicMock(side_effect=RuntimeError("boom"))
        out = await controller.transcribe({"file": _FakeUpload(b"x"), "body": {}})
        assert out["status"] == "error"
        assert "boom" in out["message"]
