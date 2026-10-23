"""Testes de MediaRoutes (src/interfaces/http/media/media_routes.py).

`APP_ROLE` decide quais rotas o processo monta: `media` (/tts + /transcribe),
`image` (/image) ou `all` (as três, só dev). Um RouteRegister fake registra as
chamadas, sem FastAPI.
"""

import pytest

from src import config
from src.interfaces.http.media.media_routes import MediaRoutes


class FakeRouteRegister:
    def __init__(self):
        self.calls: list[dict] = []

    def execute(self, prefix, route, method, callback, compress=False, file=False):
        self.calls.append({"prefix": prefix, "route": route, "method": method, "callback": callback})


def _register(monkeypatch, role):
    monkeypatch.setattr(config.settings, "role", role)
    register = FakeRouteRegister()
    routes = MediaRoutes(routes_register=register)
    routes.register()
    return routes, register


class TestRoutesByRole:
    def test_role_media_monta_tts_e_transcribe(self, monkeypatch):
        _, register = _register(monkeypatch, "media")
        assert [(c["route"], c["method"]) for c in register.calls] == [
            ("/tts", "POST"),
            ("/transcribe", "POST_FILE"),
        ]

    def test_role_image_monta_so_image(self, monkeypatch):
        _, register = _register(monkeypatch, "image")
        assert [(c["route"], c["method"]) for c in register.calls] == [("/image", "POST")]

    def test_role_all_monta_as_tres_rotas(self, monkeypatch):
        _, register = _register(monkeypatch, "all")
        assert [c["route"] for c in register.calls] == ["/tts", "/transcribe", "/image"]

    @pytest.mark.parametrize("role", ["", "MEDIA", "gpu", "media,image"])
    def test_role_desconhecido_nao_monta_nenhuma_rota(self, monkeypatch, role):
        _, register = _register(monkeypatch, role)
        assert register.calls == []

    def test_rotas_ficam_na_raiz_sem_prefixo(self, monkeypatch):
        _, register = _register(monkeypatch, "all")
        assert {c["prefix"] for c in register.calls} == {""}

    def test_callbacks_sao_os_metodos_do_mesmo_controller(self, monkeypatch):
        routes, register = _register(monkeypatch, "all")
        callbacks = {c["route"]: c["callback"] for c in register.calls}
        assert callbacks["/tts"] == routes.controller.tts
        assert callbacks["/transcribe"] == routes.controller.transcribe
        assert callbacks["/image"] == routes.controller.image

    def test_role_e_lido_na_hora_do_register_nao_no_construtor(self, monkeypatch):
        monkeypatch.setattr(config.settings, "role", "media")
        register = FakeRouteRegister()
        routes = MediaRoutes(routes_register=register)
        monkeypatch.setattr(config.settings, "role", "image")
        routes.register()
        assert [c["route"] for c in register.calls] == ["/image"]
