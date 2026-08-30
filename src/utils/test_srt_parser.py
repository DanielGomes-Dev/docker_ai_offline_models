"""Testes de src/utils/srt_parser.py — parser mínimo de SRT."""

from src.utils.srt_parser import parse_srt, srt_duration

_WORD_SRT = """1
00:00:00,000 --> 00:00:00,480
Você

2
00:00:00,480 --> 00:00:00,900
sabia

3
00:00:00,900 --> 00:00:01,500
disso
"""


class TestParseSrt:
    def test_extrai_palavra_start_e_end_em_segundos(self):
        entries = parse_srt(_WORD_SRT)
        assert len(entries) == 3
        assert entries[0] == {"word": "Você", "start": 0.0, "end": 0.48}
        assert entries[2]["end"] == 1.5

    def test_string_vazia_devolve_lista_vazia(self):
        assert parse_srt("") == []
        assert parse_srt("   \n\n  ") == []

    def test_aceita_ponto_no_lugar_de_virgula_nos_milissegundos(self):
        entries = parse_srt("1\n00:00:01.000 --> 00:00:02.000\noi\n")
        assert entries == [{"word": "oi", "start": 1.0, "end": 2.0}]

    def test_ignora_blocos_sem_timestamp(self):
        entries = parse_srt("lixo\nsem tempo aqui\n\n1\n00:00:00,000 --> 00:00:01,000\nok\n")
        assert entries == [{"word": "ok", "start": 0.0, "end": 1.0}]

    def test_junta_multiplas_linhas_de_texto(self):
        entries = parse_srt("1\n00:00:00,000 --> 00:00:02,000\nprimeira\nsegunda\n")
        assert entries[0]["word"] == "primeira segunda"


class TestSrtDuration:
    def test_devolve_o_fim_do_ultimo_bloco(self):
        assert srt_duration(_WORD_SRT) == 1.5

    def test_zero_quando_vazio(self):
        assert srt_duration("") == 0.0
