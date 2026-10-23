"""Testes de MediaController (src/interfaces/http/media/media_controller.py)."""

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.interfaces.http.media.media_controller import MediaController


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


class _Img:
    def __init__(self, image, mime):
        self.image = image
        self.mime = mime


@pytest.fixture
def controller():
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=_Res(b"ID3mp3", "audio/mpeg"))
    transcribe = MagicMock()
    transcribe.transcribe = MagicMock(
        return_value={"words": [], "word_srt": "", "sentence_srt": "", "duration_s": 3.0}
    )
    image = AsyncMock()
    image.generate = AsyncMock(return_value=_Img(b"\x89PNGdata", "image/png"))
    return MediaController(
        tts_service=tts, transcribe_service=transcribe, image_service=image
    )


class TestTts:
    async def test_devolve_audio_base64(self, controller):
        out = (await controller.tts({"text": "olá", "lang": "pt-BR"})).model_dump()
        assert out["mime"] == "audio/mpeg"
        assert base64.b64decode(out["data_b64"]) == b"ID3mp3"
        controller.tts_service.synthesize.assert_awaited_once_with(
            "olá", voice=None, lang="pt-BR"
        )

    async def test_text_ausente_vira_invalid_request(self, controller):
        out = await controller.tts({})
        assert out["status"] == "invalid_request"

    async def test_value_error_do_provider_vira_erro(self, controller):
        controller.tts_service.synthesize = AsyncMock(side_effect=ValueError("vazio"))
        out = await controller.tts({"text": "x"})
        assert out["status"] == "error"


class TestImage:
    async def test_devolve_imagem_base64(self, controller):
        out = (
            await controller.image({"prompt": "um gato", "style": "anime"})
        ).model_dump()
        assert out["mime"] == "image/png"
        assert base64.b64decode(out["data_b64"]) == b"\x89PNGdata"
        controller.image_service.generate.assert_awaited_once_with(
            "um gato", style="anime", aspect_ratio=None, seed=None
        )

    async def test_prompt_ausente_vira_invalid_request(self, controller):
        out = await controller.image({})
        assert out["status"] == "invalid_request"

    async def test_erro_do_provider_vira_dict_de_erro(self, controller):
        controller.image_service.generate = AsyncMock(side_effect=RuntimeError("boom"))
        out = await controller.image({"prompt": "x"})
        assert out["status"] == "error"
        assert "boom" in out["message"]


class TestTranscribe:
    async def test_salva_upload_e_devolve_o_resultado(self, controller, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = (
            await controller.transcribe(
                {"file": _FakeUpload(b"RIFFwav"), "body": {"language": "pt"}}
            )
        ).model_dump()
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


# ---------------------------------------------------------------------------
# Carregamento sob demanda dos serviços (modelo carregado 1x por processo)
# ---------------------------------------------------------------------------


class _CountingFactory:
    """Substitui a classe do serviço: conta construções; pode falhar nas primeiras N."""

    def __init__(self, instance, fail_times=0, error=None):
        self.instance = instance
        self.fail_times = fail_times
        self.error = error or RuntimeError("falha ao carregar")
        self.created = 0

    def __call__(self):
        self.created += 1
        if self.created <= self.fail_times:
            raise self.error
        return self.instance


@pytest.fixture
def factories(monkeypatch):
    from src.application.services.media.image import image_service as image_module
    from src.application.services.media.tts import tts_service as tts_module
    from src.infra.external.whisper import transcribe_service as whisper_module

    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=_Res(b"mp3", "audio/mpeg"))
    image = AsyncMock()
    image.generate = AsyncMock(return_value=_Img(b"png", "image/png"))
    transcribe = MagicMock()
    transcribe.transcribe = MagicMock(
        return_value={"words": [], "word_srt": "", "sentence_srt": "", "duration_s": 0.0}
    )
    f = {
        "tts": _CountingFactory(tts),
        "image": _CountingFactory(image),
        "transcribe": _CountingFactory(transcribe),
    }
    monkeypatch.setattr(tts_module, "TtsService", f["tts"])
    monkeypatch.setattr(image_module, "ImageService", f["image"])
    monkeypatch.setattr(whisper_module, "TranscribeService", f["transcribe"])
    return f


class TestCarregamentoSobDemanda:
    def test_construir_o_controller_nao_carrega_nenhum_servico(self, factories):
        MediaController()
        assert [f.created for f in factories.values()] == [0, 0, 0]

    async def test_tts_cria_o_servico_na_primeira_chamada_e_reusa(self, factories):
        controller = MediaController()
        await controller.tts({"text": "a"})
        await controller.tts({"text": "b"})
        assert factories["tts"].created == 1
        assert factories["image"].created == 0
        assert factories["transcribe"].created == 0

    async def test_image_cria_o_servico_na_primeira_chamada_e_reusa(self, factories):
        controller = MediaController()
        await controller.image({"prompt": "a"})
        await controller.image({"prompt": "b"})
        assert factories["image"].created == 1

    async def test_transcribe_carrega_o_modelo_uma_vez_so(self, factories, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        controller = MediaController()
        await controller.transcribe({"file": _FakeUpload(b"1"), "body": {}})
        await controller.transcribe({"file": _FakeUpload(b"2"), "body": {}})
        assert factories["transcribe"].created == 1

    async def test_request_invalida_nao_carrega_o_servico(self, factories):
        controller = MediaController()
        await controller.tts({})
        await controller.image({})
        assert factories["tts"].created == 0
        assert factories["image"].created == 0

    async def test_falha_ao_carregar_o_whisper_vira_erro_e_a_proxima_chamada_tenta_de_novo(
        self, factories, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        factories["transcribe"].fail_times = 1
        controller = MediaController()

        first = await controller.transcribe({"file": _FakeUpload(b"1"), "body": {}})
        second = await controller.transcribe({"file": _FakeUpload(b"2"), "body": {}})

        assert first == {"status": "error", "message": "falha ao carregar"}
        assert second.duration_s == 0.0
        assert factories["transcribe"].created == 2

    async def test_provider_de_tts_desconhecido_vira_status_error(self, factories):
        factories["tts"].fail_times = 1
        factories["tts"].error = ValueError("Provider de TTS desconhecido: 'nope'")

        out = await MediaController().tts({"text": "oi"})

        assert out == {"status": "error", "message": "Provider de TTS desconhecido: 'nope'"}


class TestErrosDoController:
    async def test_value_error_na_imagem_vira_status_error(self, controller):
        controller.image_service.generate = AsyncMock(side_effect=ValueError("Prompt vazio"))
        out = await controller.image({"prompt": "x"})
        assert out == {"status": "error", "message": "Prompt vazio"}

    async def test_body_invalido_no_transcribe_vira_invalid_request(self, controller):
        out = await controller.transcribe({"file": _FakeUpload(b"x"), "body": {"language": 1}})
        assert out == {"status": "invalid_request", "message": "language: Input should be a valid string"}
        controller.transcribe_service.transcribe.assert_not_called()

    async def test_body_none_no_transcribe_vale_como_vazio(self, controller, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        await controller.transcribe({"file": _FakeUpload(b"x"), "body": None})
        args, _ = controller.transcribe_service.transcribe.call_args
        assert args[1] is None

    async def test_upload_sem_nome_e_salvo_como_audio_wav(self, controller, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        await controller.transcribe({"file": _FakeUpload(b"x", filename=None), "body": {}})
        args, _ = controller.transcribe_service.transcribe.call_args
        assert args[0].endswith("_audio.wav")

    async def test_sem_arquivo_na_request_vira_status_error(self, controller, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = await controller.transcribe({"body": {}})
        assert out == {"status": "error", "message": "'file'"}
