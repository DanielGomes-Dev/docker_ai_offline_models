"""Configuração central (pydantic-settings).

Lê de variáveis de ambiente / `.env`. Sem efeito colateral além da leitura de env.
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Metadados do FastAPI (ver create_app()).
    app_title: str = "AI Inference API"
    app_description: str = (
        "Modelos de IA locais do workspace: TTS (edge-tts) e transcrição (faster-whisper). "
        "100% HTTP, síncrono. Chamado pelo video_orchestrator via filas ai-tts / ai-transcribe."
    )
    app_version: str = "1.0.0"

    # faster-whisper (TranscribeService).
    whisper_download_root: str = "./models"
    whisper_model_size: str = "large-v3"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"

    @property
    def google_api_keys(self) -> list[str]:
        """Chaves do Google usáveis pelo TTS Gemini, na ordem de tentativa.

        Os nomes são dinâmicos (`GOOGLE_API_KEY_00`..`GOOGLE_API_KEY_09` e, por
        fim, `GOOGLE_API_KEY`), então não dá pra modelá-los como campos fixos —
        são lidos de `os.environ` a cada acesso. pydantic-settings continua sendo
        a fonte única de config: este é só um leitor derivado.
        """
        keys: list[str] = []
        for i in range(10):
            value = os.environ.get(f"GOOGLE_API_KEY_{i:02d}")
            if value:
                keys.append(value)
        fallback = os.environ.get("GOOGLE_API_KEY")
        if fallback:
            keys.append(fallback)
        return keys


settings = Settings()
