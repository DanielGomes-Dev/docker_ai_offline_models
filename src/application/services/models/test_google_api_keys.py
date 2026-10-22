"""Caracterização de `available_api_keys()`: lista de chaves utilizáveis, na
ordem do `apis.json`, pulando `is_down`; sem nenhuma chave válida no JSON, cai
para `settings.google_api_keys` (GOOGLE_API_KEY_00..09 e GOOGLE_API_KEY).

O caminho do JSON é a constante de módulo `_APIS_JSON`; cada teste aponta ela
para um arquivo em `tmp_path` (o repositório não versiona `apis.json`).
"""

import json

import pytest

from src.application.services.models import google_api_keys as mod
from src.application.services.models.google_api_keys import available_api_keys

_GOOGLE_KEY_VARS = [f"GOOGLE_API_KEY_{i:02d}" for i in range(10)] + ["GOOGLE_API_KEY"]


@pytest.fixture
def env(monkeypatch):
    for name in _GOOGLE_KEY_VARS + ["GEMINI_A", "GEMINI_B", "GEMINI_C"]:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def apis_json(env, tmp_path):
    """Escreve o conteúdo dado (lista/objeto/texto cru) e aponta `_APIS_JSON` para ele."""
    path = tmp_path / "apis.json"

    def _write(content):
        text = content if isinstance(content, str) else json.dumps(content)
        path.write_text(text, encoding="utf-8")
        env.setattr(mod, "_APIS_JSON", path)
        return path

    return _write


class TestFromApisJson:
    def test_should_return_env_values_in_json_order(self, env, apis_json):
        apis_json([{"name": "GEMINI_B"}, {"name": "GEMINI_A"}])
        env.setenv("GEMINI_A", "value-a")
        env.setenv("GEMINI_B", "value-b")
        assert available_api_keys() == ["value-b", "value-a"]

    def test_should_skip_entries_marked_is_down(self, env, apis_json):
        apis_json([{"name": "GEMINI_A", "is_down": True}, {"name": "GEMINI_B", "is_down": False}])
        env.setenv("GEMINI_A", "value-a")
        env.setenv("GEMINI_B", "value-b")
        assert available_api_keys() == ["value-b"]

    def test_should_skip_entries_without_name(self, env, apis_json):
        apis_json([{"is_down": False}, {"name": ""}, {"name": "GEMINI_A"}])
        env.setenv("GEMINI_A", "value-a")
        assert available_api_keys() == ["value-a"]

    def test_should_skip_entries_whose_env_var_is_missing_or_empty(self, env, apis_json):
        apis_json([{"name": "GEMINI_A"}, {"name": "GEMINI_B"}, {"name": "GEMINI_C"}])
        env.setenv("GEMINI_B", "")
        env.setenv("GEMINI_C", "value-c")
        assert available_api_keys() == ["value-c"]

    def test_should_not_add_settings_keys_when_json_yields_at_least_one_key(self, env, apis_json):
        apis_json([{"name": "GEMINI_A"}])
        env.setenv("GEMINI_A", "value-a")
        env.setenv("GOOGLE_API_KEY_00", "k00")
        env.setenv("GOOGLE_API_KEY", "fallback")
        assert available_api_keys() == ["value-a"]

    def test_should_not_rewrite_the_json(self, env, apis_json):
        path = apis_json([{"name": "GEMINI_A", "is_down": True}, {"name": "GEMINI_B"}])
        before = path.read_text(encoding="utf-8")
        env.setenv("GEMINI_B", "value-b")
        available_api_keys()
        assert path.read_text(encoding="utf-8") == before


class TestFallbackToSettings:
    def test_should_use_settings_keys_when_json_is_missing(self, env, tmp_path):
        env.setattr(mod, "_APIS_JSON", tmp_path / "nao-existe.json")
        env.setenv("GOOGLE_API_KEY_01", "k01")
        env.setenv("GOOGLE_API_KEY", "fallback")
        assert available_api_keys() == ["k01", "fallback"]

    def test_should_use_settings_keys_when_json_is_invalid(self, env, apis_json):
        apis_json("{ isto nao e json")
        env.setenv("GOOGLE_API_KEY_00", "k00")
        assert available_api_keys() == ["k00"]

    def test_should_use_settings_keys_when_json_is_not_a_list(self, env, apis_json):
        apis_json({"name": "GEMINI_A"})
        env.setenv("GEMINI_A", "value-a")
        env.setenv("GOOGLE_API_KEY_00", "k00")
        assert available_api_keys() == ["k00"]

    def test_should_use_settings_keys_when_every_json_entry_is_down(self, env, apis_json):
        apis_json([{"name": "GEMINI_A", "is_down": True}])
        env.setenv("GEMINI_A", "value-a")
        env.setenv("GOOGLE_API_KEY_00", "k00")
        assert available_api_keys() == ["k00"]

    def test_should_return_empty_list_when_there_is_no_key_anywhere(self, env, apis_json):
        apis_json([])
        assert available_api_keys() == []

    def test_should_return_a_new_list_on_each_call(self, env, apis_json):
        apis_json([])
        env.setenv("GOOGLE_API_KEY_00", "k00")
        first = available_api_keys()
        first.append("mutated")
        assert available_api_keys() == ["k00"]
