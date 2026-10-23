"""Caracterização de src/config.py: defaults do Settings, leitura de env e
o leitor derivado `google_api_keys` (ordem 00..09 e por fim GOOGLE_API_KEY).

Todo Settings aqui é criado com `_env_file=None` para não depender do `.env`
local do desenvolvedor; as env vars relevantes são limpas via monkeypatch.
"""

import pytest

from src.config import Settings

_SETTINGS_ENV_VARS = [
    "APP_ROLE",
    "ROLE",
    "APP_TITLE",
    "APP_DESCRIPTION",
    "APP_VERSION",
    "WHISPER_DOWNLOAD_ROOT",
    "WHISPER_MODEL_SIZE",
    "WHISPER_DEVICE",
    "WHISPER_COMPUTE_TYPE",
]
_GOOGLE_KEY_VARS = [f"GOOGLE_API_KEY_{i:02d}" for i in range(10)] + ["GOOGLE_API_KEY"]


@pytest.fixture
def clean_env(monkeypatch):
    for name in _SETTINGS_ENV_VARS + _GOOGLE_KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _settings() -> Settings:
    return Settings(_env_file=None)


class TestDefaults:
    def test_should_default_role_to_all(self, clean_env):
        assert _settings().role == "all"

    def test_should_default_fastapi_metadata(self, clean_env):
        s = _settings()
        assert s.app_title == "AI Inference API"
        assert s.app_version == "1.0.0"
        assert s.app_description.startswith("Modelos de IA locais do workspace")

    def test_description_lists_the_three_routes_and_the_real_callers(self, clean_env):
        # DIV-5: citava só TTS/transcrição e o antigo "video_orchestrator".
        d = _settings().app_description
        assert "imagem" in d
        for caller in ("video_automation", "video_worker", "llm_adapter"):
            assert caller in d
        assert "video_orchestrator" not in d

    def test_should_default_whisper_to_large_v3_on_cuda_float16(self, clean_env):
        s = _settings()
        assert s.whisper_model_size == "large-v3"
        assert s.whisper_device == "cuda"
        assert s.whisper_compute_type == "float16"
        assert s.whisper_download_root == "./models"


class TestEnvOverrides:
    def test_should_read_role_from_app_role(self, clean_env):
        clean_env.setenv("APP_ROLE", "image")
        assert _settings().role == "image"

    def test_should_ignore_plain_role_env_var(self, clean_env):
        # validation_alias="APP_ROLE": o nome do campo (ROLE) não é lido.
        clean_env.setenv("ROLE", "media")
        assert _settings().role == "all"

    def test_should_read_whisper_settings_from_env(self, clean_env):
        clean_env.setenv("WHISPER_MODEL_SIZE", "small")
        clean_env.setenv("WHISPER_DEVICE", "cpu")
        clean_env.setenv("WHISPER_COMPUTE_TYPE", "int8")
        clean_env.setenv("WHISPER_DOWNLOAD_ROOT", "/models/whisper")
        s = _settings()
        assert (s.whisper_model_size, s.whisper_device, s.whisper_compute_type, s.whisper_download_root) == (
            "small",
            "cpu",
            "int8",
            "/models/whisper",
        )

    def test_should_ignore_unknown_env_file_entries(self, clean_env, tmp_path):
        # extra="ignore": chaves desconhecidas no .env (ex.: APP_AI_INFERENCE_PORT) não quebram.
        env_file = tmp_path / ".env"
        env_file.write_text("APP_AI_INFERENCE_PORT=8005\nWHISPER_DEVICE=cpu\n", encoding="utf-8")
        s = Settings(_env_file=str(env_file))
        assert s.whisper_device == "cpu"
        assert not hasattr(s, "app_ai_inference_port")


class TestGoogleApiKeys:
    def test_should_return_empty_list_when_no_key_is_set(self, clean_env):
        assert _settings().google_api_keys == []

    def test_should_return_numbered_keys_in_order_then_the_fallback(self, clean_env):
        clean_env.setenv("GOOGLE_API_KEY", "fallback")
        clean_env.setenv("GOOGLE_API_KEY_09", "k09")
        clean_env.setenv("GOOGLE_API_KEY_00", "k00")
        clean_env.setenv("GOOGLE_API_KEY_03", "k03")
        assert _settings().google_api_keys == ["k00", "k03", "k09", "fallback"]

    def test_should_skip_empty_values(self, clean_env):
        clean_env.setenv("GOOGLE_API_KEY_00", "")
        clean_env.setenv("GOOGLE_API_KEY_01", "k01")
        clean_env.setenv("GOOGLE_API_KEY", "")
        assert _settings().google_api_keys == ["k01"]

    def test_should_ignore_keys_beyond_09(self, clean_env):
        clean_env.setenv("GOOGLE_API_KEY_10", "k10")
        clean_env.setenv("GOOGLE_API_KEY_0", "k0-sem-zero")
        assert _settings().google_api_keys == []

    def test_should_read_env_at_each_access_not_at_construction(self, clean_env):
        s = _settings()
        assert s.google_api_keys == []
        clean_env.setenv("GOOGLE_API_KEY_00", "late")
        assert s.google_api_keys == ["late"]

    def test_should_keep_duplicated_values(self, clean_env):
        clean_env.setenv("GOOGLE_API_KEY_00", "same")
        clean_env.setenv("GOOGLE_API_KEY", "same")
        assert _settings().google_api_keys == ["same", "same"]
