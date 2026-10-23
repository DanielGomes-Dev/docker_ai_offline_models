"""Contrato HTTP que o ai_inference OFERECE (POST /tts, /transcribe, /image).

Testa o app real (`create_app()` + RouteRegister do platform_core) com o
`TestClient` do FastAPI; só os serviços de modelo são trocados por fakes (nada de
GPU, modelo ou rede). Os payloads de entrada são os que os clientes reais mandam:

  * video_automation  `src/infra/clients/ai_inference_client.py`  (/tts, /transcribe)
  * video_worker      `src/infra/external/whisper/transcribe_service.py` (/transcribe)
  * llm_adapter       `src/infra/external/ai_inference_image/ai_inference_image_provider.py` (/image)

Envelope (schemas.py): sucesso sem `status`; validação -> HTTP 200
`{"status": "invalid_request", "message"}`; erro interno -> HTTP 200
`{"status": "error", "message"}`.
"""

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config
from src.app import create_app
from src.application.services.media.image import image_service as image_module
from src.application.services.media.tts import tts_service as tts_module
from src.domain.ports.image_provider import ImageResult
from src.domain.ports.tts_provider import TtsResult
from src.infra.external.whisper import transcribe_service as whisper_module

_TRANSCRIBE_OK = {
    "words": [{"word": "olá", "start": 0.0, "end": 0.4}],
    "word_srt": "1\n00:00:00,000 --> 00:00:00,400\nolá\n",
    "sentence_srt": "1\n00:00:00,000 --> 00:00:00,400\nolá\n",
    "duration_s": 0.4,
    "language": "pt",
}


class FakeTtsService:
    def __init__(self):
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def synthesize(self, text, *, voice=None, lang=None):
        self.calls.append((text, voice, lang))
        if self.error:
            raise self.error
        return TtsResult(b"ID3-mp3", "audio/mpeg")


class FakeImageService:
    def __init__(self):
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def generate(self, prompt, *, style=None, aspect_ratio=None, seed=None):
        self.calls.append((prompt, style, aspect_ratio, seed))
        if self.error:
            raise self.error
        return ImageResult(b"\x89PNG-bytes", "image/png")


class FakeTranscribeService:
    """Síncrono, como o TranscribeService real; guarda o conteúdo salvo em disco."""

    def __init__(self):
        self.calls: list[dict] = []
        self.error: Exception | None = None
        self.result: dict = dict(_TRANSCRIBE_OK)

    def transcribe(self, audio_path, language=None):
        self.calls.append(
            {"path": audio_path, "language": language, "content": Path(audio_path).read_bytes()}
        )
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def services(monkeypatch):
    fakes = {
        "tts": FakeTtsService(),
        "image": FakeImageService(),
        "transcribe": FakeTranscribeService(),
    }
    # O controller importa as classes sob demanda; trocar o atributo do módulo
    # basta para nenhum modelo real ser construído.
    monkeypatch.setattr(tts_module, "TtsService", lambda: fakes["tts"])
    monkeypatch.setattr(image_module, "ImageService", lambda: fakes["image"])
    monkeypatch.setattr(whisper_module, "TranscribeService", lambda: fakes["transcribe"])
    return fakes


@pytest.fixture
def client(services, monkeypatch, tmp_path):
    monkeypatch.setattr(config.settings, "role", "all")
    monkeypatch.chdir(tmp_path)  # uploads vão para files/temp/audio_in relativo ao cwd
    return TestClient(create_app())


def _upload(client, content=b"RIFF-wav", filename="narracao.wav", payload=None):
    data = {} if payload is None else {"payload": payload}
    return client.post(
        "/transcribe", data=data, files={"upload": (filename, content, "audio/wav")}
    )


# --------------------------------------------------------------------- /tts


class TestTtsContract:
    def test_sucesso_devolve_so_mime_e_data_b64_sem_status(self, client):
        resp = client.post("/tts", json={"text": "Olá mundo", "voice": None, "lang": "pt-BR"})

        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"mime", "data_b64"}
        assert body["mime"] == "audio/mpeg"
        assert base64.b64decode(body["data_b64"]) == b"ID3-mp3"

    def test_aceita_o_payload_do_video_automation_com_voice_e_lang_nulos(self, client, services):
        resp = client.post("/tts", json={"text": "oi", "voice": None, "lang": None})

        assert resp.status_code == 200
        assert services["tts"].calls == [("oi", None, None)]

    def test_repassa_voice_e_lang_ao_servico(self, client, services):
        client.post("/tts", json={"text": "oi", "voice": "pt-BR-AntonioNeural", "lang": "pt-BR"})

        assert services["tts"].calls == [("oi", "pt-BR-AntonioNeural", "pt-BR")]

    def test_campos_desconhecidos_sao_ignorados(self, client, services):
        resp = client.post("/tts", json={"text": "oi", "speed": 2})

        assert resp.status_code == 200
        assert services["tts"].calls == [("oi", None, None)]

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            ({}, "text: Field required"),
            ({"text": ""}, "text: String should have at least 1 character"),
            ({"text": "   "}, "text: Value error, não pode ser vazio"),
            ({"text": 123}, "text: Input should be a valid string"),
            ({"text": None}, "text: Input should be a valid string"),
            ([], "Input should be a valid dictionary or instance of TtsRequest"),
        ],
    )
    def test_payload_invalido_vira_invalid_request_com_http_200(
        self, client, services, payload, message
    ):
        resp = client.post("/tts", json=payload)

        assert resp.status_code == 200
        assert resp.json() == {"status": "invalid_request", "message": message}
        assert services["tts"].calls == []

    def test_so_o_primeiro_erro_de_validacao_vai_na_mensagem(self, client):
        resp = client.post("/tts", json={"voice": 1, "lang": 2})

        assert resp.json() == {"status": "invalid_request", "message": "text: Field required"}

    def test_falha_do_servico_vira_status_error_com_http_200(self, client, services):
        services["tts"].error = RuntimeError("edge-tts falhou: sem conexão")

        resp = client.post("/tts", json={"text": "oi"})

        assert resp.status_code == 200
        assert resp.json() == {"status": "error", "message": "edge-tts falhou: sem conexão"}

    def test_value_error_do_servico_tambem_vira_status_error(self, client, services):
        services["tts"].error = ValueError("Texto vazio para TTS.")

        resp = client.post("/tts", json={"text": "oi"})

        assert resp.json() == {"status": "error", "message": "Texto vazio para TTS."}

    def test_corpo_que_nao_e_json_estoura_http_500_com_detail(self, client, services):
        # Ver DIV no relatório: aqui NÃO há envelope {status,message}.
        resp = client.post(
            "/tts", content=b"isto nao e json", headers={"content-type": "application/json"}
        )

        assert resp.status_code == 500
        assert set(resp.json()) == {"detail"}
        assert services["tts"].calls == []

    def test_get_nao_e_rota_valida(self, client):
        assert client.get("/tts").status_code == 405


# ------------------------------------------------------------------- /image


class TestImageContract:
    def test_sucesso_devolve_png_em_base64_sem_status(self, client):
        resp = client.post("/image", json={"prompt": "um farol"})

        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"mime", "data_b64"}
        assert body["mime"] == "image/png"
        assert base64.b64decode(body["data_b64"]) == b"\x89PNG-bytes"

    def test_aceita_exatamente_o_payload_do_llm_adapter(self, client, services):
        payload = {
            "prompt": "um farol",
            "style": "cinematic",
            "aspect_ratio": "IMAGE_ASPECT_RATIO_SQUARE",
            "seed": 42,
        }

        resp = client.post("/image", json=payload)

        assert resp.status_code == 200
        assert services["image"].calls == [
            ("um farol", "cinematic", "IMAGE_ASPECT_RATIO_SQUARE", 42)
        ]

    def test_campos_opcionais_nulos_sao_aceitos(self, client, services):
        client.post(
            "/image", json={"prompt": "x", "style": None, "aspect_ratio": None, "seed": None}
        )

        assert services["image"].calls == [("x", None, None, None)]

    def test_seed_numerico_em_string_e_convertido_para_int(self, client, services):
        client.post("/image", json={"prompt": "x", "seed": "42"})

        assert services["image"].calls == [("x", None, None, 42)]

    def test_aspect_ratio_fora_do_enum_passa_sem_validacao(self, client, services):
        resp = client.post("/image", json={"prompt": "x", "aspect_ratio": "16:9"})

        assert resp.status_code == 200
        assert services["image"].calls == [("x", None, "16:9", None)]

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            ({}, "prompt: Field required"),
            ({"prompt": ""}, "prompt: String should have at least 1 character"),
            ({"prompt": " \n "}, "prompt: Value error, não pode ser vazio"),
            (
                {"prompt": "x", "seed": "abc"},
                "seed: Input should be a valid integer, unable to parse string as an integer",
            ),
            (
                {"prompt": "x", "seed": 1.5},
                "seed: Input should be a valid integer, got a number with a fractional part",
            ),
        ],
    )
    def test_payload_invalido_vira_invalid_request_com_http_200(
        self, client, services, payload, message
    ):
        resp = client.post("/image", json=payload)

        assert resp.status_code == 200
        assert resp.json() == {"status": "invalid_request", "message": message}
        assert services["image"].calls == []

    def test_falha_do_modelo_vira_status_error_com_http_200(self, client, services):
        services["image"].error = RuntimeError("CUDA out of memory")

        resp = client.post("/image", json={"prompt": "x"})

        assert resp.status_code == 200
        assert resp.json() == {"status": "error", "message": "CUDA out of memory"}


# -------------------------------------------------------------- /transcribe


class TestTranscribeContract:
    def test_sucesso_devolve_a_transcribe_response_completa(self, client):
        resp = _upload(client, payload=json.dumps({}))

        assert resp.status_code == 200
        assert resp.json() == _TRANSCRIBE_OK

    def test_upload_no_campo_upload_e_salvo_e_repassado_ao_servico(self, client, services, tmp_path):
        _upload(client, content=b"RIFF-123", filename="narracao.wav", payload="{}")

        call = services["transcribe"].calls[0]
        saved = Path(call["path"])
        assert call["content"] == b"RIFF-123"
        assert saved.parent.resolve() == (tmp_path / "files" / "temp" / "audio_in").resolve()
        prefix, _, name = saved.name.partition("_")
        assert prefix.isdigit() and name == "narracao.wav"

    def test_arquivo_salvo_e_apagado_depois_da_transcricao(self, client, services):
        resp = _upload(client, payload="{}")

        assert resp.json() == _TRANSCRIBE_OK
        assert not Path(services["transcribe"].calls[0]["path"]).exists()

    def test_arquivo_salvo_e_apagado_quando_a_transcricao_falha(self, client, services):
        services["transcribe"].error = RuntimeError("whisper sem GPU")

        resp = _upload(client, payload="{}")

        assert resp.json() == {"status": "error", "message": "whisper sem GPU"}
        assert not Path(services["transcribe"].calls[0]["path"]).exists()

    def test_nome_do_arquivo_do_cliente_perde_os_diretorios(self, client, services):
        _upload(client, filename="../../segredo.wav", payload="{}")

        saved = Path(services["transcribe"].calls[0]["path"])
        assert saved.name.endswith("_segredo.wav")
        assert saved.parent.name == "audio_in"

    def test_payload_do_video_worker_repassa_o_language(self, client, services):
        _upload(client, payload=json.dumps({"language": "pt"}))

        assert services["transcribe"].calls[0]["language"] == "pt"

    def test_sem_campo_payload_o_language_e_none(self, client, services):
        resp = _upload(client)

        assert resp.status_code == 200
        assert services["transcribe"].calls[0]["language"] is None

    def test_payload_json_null_e_tratado_como_vazio(self, client, services):
        resp = _upload(client, payload="null")

        assert resp.status_code == 200
        assert services["transcribe"].calls[0]["language"] is None

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            ({"language": 5}, "language: Input should be a valid string"),
            ([1], "Input should be a valid dictionary or instance of TranscribeRequest"),
        ],
    )
    def test_payload_invalido_vira_invalid_request_sem_chamar_o_modelo(
        self, client, services, tmp_path, payload, message
    ):
        resp = _upload(client, payload=json.dumps(payload))

        assert resp.status_code == 200
        assert resp.json() == {"status": "invalid_request", "message": message}
        assert services["transcribe"].calls == []
        assert not (tmp_path / "files").exists()  # nem salva o upload

    def test_language_ausente_na_resposta_do_servico_vira_null(self, client, services):
        services["transcribe"].result = {k: v for k, v in _TRANSCRIBE_OK.items() if k != "language"}

        resp = _upload(client, payload="{}")

        assert resp.json()["language"] is None

    def test_chaves_extras_do_servico_nao_vazam_na_resposta(self, client, services):
        services["transcribe"].result = {**_TRANSCRIBE_OK, "debug": "interno"}

        resp = _upload(client, payload="{}")

        assert set(resp.json()) == set(_TRANSCRIBE_OK)

    def test_resposta_do_servico_fora_do_schema_vira_status_error(self, client, services):
        services["transcribe"].result = {"words": []}

        resp = _upload(client, payload="{}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "TranscribeResponse" in body["message"]

    def test_falha_do_modelo_vira_status_error_com_http_200(self, client, services):
        services["transcribe"].error = RuntimeError("whisper sem GPU")

        resp = _upload(client, payload="{}")

        assert resp.status_code == 200
        assert resp.json() == {"status": "error", "message": "whisper sem GPU"}

    def test_sem_o_campo_upload_o_fastapi_responde_422(self, client, services):
        # Ver DIV no relatório: o envelope {status,message} não cobre este caso.
        resp = client.post("/transcribe", data={"payload": "{}"})

        assert resp.status_code == 422
        assert "detail" in resp.json()
        assert services["transcribe"].calls == []

    def test_payload_que_nao_e_json_estoura_http_500(self, client, services):
        resp = _upload(client, payload="{nao e json")

        assert resp.status_code == 500
        assert set(resp.json()) == {"detail"}
        assert services["transcribe"].calls == []

    def test_upload_em_json_puro_nao_e_aceito(self, client, services):
        resp = client.post("/transcribe", json={"language": "pt"})

        assert resp.status_code == 422
        assert services["transcribe"].calls == []
