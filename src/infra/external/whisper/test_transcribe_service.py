"""Testes de TranscribeService (src/infra/external/whisper/transcribe_service.py).

Uma passada de faster-whisper com word_timestamps=True → dois SRTs + palavras +
duração. `faster_whisper` é fake (ver tests_support/fakes.py).
"""

from unittest.mock import MagicMock, patch

import pytest

from src.infra.external.whisper.transcribe_service import TranscribeService


@pytest.fixture
def service():
    with patch(
        "src.infra.external.whisper.transcribe_service.WhisperModel"
    ) as WhisperModelMock:
        svc = TranscribeService()
        svc._model_cls = WhisperModelMock
        return svc


def _word(w, s, e):
    m = MagicMock()
    m.word = w
    m.start = s
    m.end = e
    return m


def _segment(text, start, end, words=None):
    m = MagicMock()
    m.text = text
    m.start = start
    m.end = end
    m.words = words
    return m


class TestInit:
    def test_le_config_do_ambiente(self, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "whisper_model_size", "small")
        monkeypatch.setattr(settings, "whisper_device", "cpu")
        monkeypatch.setattr(settings, "whisper_compute_type", "int8")
        monkeypatch.setattr(settings, "whisper_download_root", "/x/models")
        with patch(
            "src.infra.external.whisper.transcribe_service.WhisperModel"
        ) as WhisperModelMock:
            TranscribeService()
        WhisperModelMock.assert_called_once_with(
            "small", device="cpu", compute_type="int8", download_root="/x/models"
        )

    def test_erro_ao_carregar_e_relancado(self):
        with patch(
            "src.infra.external.whisper.transcribe_service.WhisperModel",
            side_effect=RuntimeError("sem GPU"),
        ):
            with pytest.raises(RuntimeError, match="sem GPU"):
                TranscribeService()


class TestFormatTime:
    def test_padrao_srt(self, service):
        assert service._format_time(3723.456) == "01:02:03,456"


class TestTranscribe:
    def test_audio_inexistente_levanta(self, service, tmp_path):
        with pytest.raises(FileNotFoundError):
            service.transcribe(str(tmp_path / "nao_existe.wav"))

    def test_gera_word_srt_sentence_srt_palavras_e_duracao(self, service, tmp_path):
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")

        seg = _segment(
            " Olá mundo ", 0.0, 1.2,
            words=[_word(" Olá", 0.0, 0.5), _word(" mundo", 0.5, 1.2), _word("  ", 1.2, 1.3)],
        )
        info = MagicMock(duration=1.2, language="pt")
        service.model.transcribe = MagicMock(return_value=(iter([seg]), info))

        out = service.transcribe(str(audio))

        assert out["duration_s"] == 1.2
        assert out["language"] == "pt"
        assert [w["word"] for w in out["words"]] == ["Olá", "mundo"]  # vazio ignorado
        assert "Olá" in out["word_srt"] and "-->" in out["word_srt"]
        assert "Olá mundo" in out["sentence_srt"]
        _, kwargs = service.model.transcribe.call_args
        assert kwargs["word_timestamps"] is True

    def test_duracao_cai_pro_fim_do_ultimo_segmento_sem_info_duration(self, service, tmp_path):
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")
        seg = _segment("frase", 0.0, 3.4, words=[])
        info = MagicMock(spec=[])  # sem atributo duration
        service.model.transcribe = MagicMock(return_value=(iter([seg]), info))

        out = service.transcribe(str(audio))
        assert out["duration_s"] == 3.4
        assert out["words"] == []
