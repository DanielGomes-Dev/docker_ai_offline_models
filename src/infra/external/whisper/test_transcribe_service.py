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


# ---------------------------------------------------------------------------
# Carga do modelo e formato exato da saída
# ---------------------------------------------------------------------------


def _audio(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    return str(audio)


class TestCargaDoModelo:
    def test_argumentos_explicitos_tem_prioridade_sobre_o_settings(self, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "whisper_download_root", "/models/whisper")
        with patch(
            "src.infra.external.whisper.transcribe_service.WhisperModel"
        ) as WhisperModelMock:
            TranscribeService(model_size="tiny", device="cpu", compute_type="int8")
        WhisperModelMock.assert_called_once_with(
            "tiny", device="cpu", compute_type="int8", download_root="/models/whisper"
        )

    def test_carrega_o_modelo_uma_vez_e_reusa_entre_transcricoes(self, tmp_path):
        with patch(
            "src.infra.external.whisper.transcribe_service.WhisperModel"
        ) as WhisperModelMock:
            WhisperModelMock.return_value.transcribe.side_effect = lambda *a, **k: (
                iter([]),
                MagicMock(duration=1.0, language="pt"),
            )
            svc = TranscribeService()
            svc.transcribe(_audio(tmp_path))
            svc.transcribe(_audio(tmp_path))
        assert WhisperModelMock.call_count == 1
        assert svc.model.transcribe.call_count == 2

    def test_injeta_as_dlls_cuda_do_venv_quando_existem(self, monkeypatch, tmp_path):
        cublas = tmp_path / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin"
        cublas.mkdir(parents=True)  # cudnn ausente: só o cublas entra
        added = []
        monkeypatch.setattr("sys.prefix", str(tmp_path))
        monkeypatch.setattr("os.add_dll_directory", added.append, raising=False)
        monkeypatch.setenv("PATH", "ORIGINAL")
        with patch("src.infra.external.whisper.transcribe_service.WhisperModel"):
            TranscribeService()
        import os

        assert added == [str(cublas)]
        assert os.environ["PATH"] == str(cublas) + os.pathsep + "ORIGINAL"

    def test_sem_dlls_no_venv_nao_mexe_no_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr("sys.prefix", str(tmp_path))
        monkeypatch.setenv("PATH", "ORIGINAL")
        with patch("src.infra.external.whisper.transcribe_service.WhisperModel"):
            TranscribeService()
        import os

        assert os.environ["PATH"] == "ORIGINAL"


class TestSaidaDaTranscricao:
    def test_chama_o_modelo_numa_passada_com_beam_5_e_o_language(self, service, tmp_path):
        service.model.transcribe = MagicMock(return_value=(iter([]), MagicMock(duration=1.0)))
        path = _audio(tmp_path)

        service.transcribe(path, "en")

        service.model.transcribe.assert_called_once_with(
            path, beam_size=5, language="en", task="transcribe", word_timestamps=True
        )

    def test_word_srt_e_sentence_srt_no_formato_exato(self, service, tmp_path):
        segs = [
            _segment(" Olá mundo.", 0.0, 1.5, words=[_word(" Olá", 0.0, 0.5), _word(" mundo.", 0.5, 1.5)]),
            _segment(" Tchau ", 61.25, 3725.0, words=[_word(" Tchau", 61.25, 3725.0)]),
        ]
        service.model.transcribe = MagicMock(
            return_value=(iter(segs), MagicMock(duration=3725.0, language="pt"))
        )

        out = service.transcribe(_audio(tmp_path))

        assert out["word_srt"] == (
            "1\n00:00:00,000 --> 00:00:00,500\nOlá\n\n"
            "2\n00:00:00,500 --> 00:00:01,500\nmundo.\n\n"
            "3\n00:01:01,250 --> 01:02:05,000\nTchau\n\n"
        )
        assert out["sentence_srt"] == (
            "1\n00:00:00,000 --> 00:00:01,500\nOlá mundo.\n\n"
            "2\n00:01:01,250 --> 01:02:05,000\nTchau\n\n"
        )

    def test_palavras_e_duracao_sao_arredondadas_em_3_casas(self, service, tmp_path):
        seg = _segment("x", 0.0, 1.0, words=[_word("x", 0.12345, 0.98765)])
        service.model.transcribe = MagicMock(
            return_value=(iter([seg]), MagicMock(duration=12.34567, language="pt"))
        )

        out = service.transcribe(_audio(tmp_path))

        assert out["words"] == [{"word": "x", "start": 0.123, "end": 0.988}]
        assert out["duration_s"] == 12.346

    def test_sem_segmentos_devolve_srts_vazios_e_duracao_zero(self, service, tmp_path):
        service.model.transcribe = MagicMock(
            return_value=(iter([]), MagicMock(duration=0, language=None))
        )

        out = service.transcribe(_audio(tmp_path))

        assert out == {
            "words": [],
            "word_srt": "",
            "sentence_srt": "",
            "duration_s": 0.0,
            "language": None,
        }

    def test_duracao_zero_no_info_cai_pro_fim_do_ultimo_segmento(self, service, tmp_path):
        segs = [_segment("a", 0.0, 1.0, words=None), _segment("b", 1.0, 2.5, words=None)]
        service.model.transcribe = MagicMock(
            return_value=(iter(segs), MagicMock(duration=0, language="pt"))
        )

        out = service.transcribe(_audio(tmp_path))

        assert out["duration_s"] == 2.5
        assert out["word_srt"] == ""  # segmentos sem .words não geram legenda por palavra

    def test_devolve_o_idioma_detectado_pelo_modelo(self, service, tmp_path):
        service.model.transcribe = MagicMock(
            return_value=(iter([]), MagicMock(duration=1.0, language="es"))
        )

        assert service.transcribe(_audio(tmp_path), None)["language"] == "es"
