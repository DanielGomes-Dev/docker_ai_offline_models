"""Leitura das chaves de API do Google a partir do mesmo `apis.json` usado pelo
`GeminiModelService`.

O `GeminiModelService` já faz rotação de chave (marca `is_down` em quota estourada)
para o fluxo de texto. Os provedores de mídia (TTS / imagem) precisam só de uma
lista de chaves utilizáveis para tentar em ordem — sem reescrever o estado do
JSON. Este helper entrega exatamente isso, sem tocar no `GeminiModelService`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.config import settings

_APIS_JSON = Path(__file__).resolve().parent / "apis.json"


def _load_entries() -> list[dict]:
    try:
        with open(_APIS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def available_api_keys() -> list[str]:
    """Valores das chaves (não os nomes) das entradas não marcadas como `is_down`
    e que têm a variável de ambiente correspondente definida, na ordem do JSON.

    Se o `apis.json` estiver vazio/ausente, cai para as env vars
    ``GOOGLE_API_KEY_00``..``GOOGLE_API_KEY_09`` e por fim ``GOOGLE_API_KEY``.
    """
    keys: list[str] = []
    for entry in _load_entries():
        if entry.get("is_down"):
            continue
        env_name = entry.get("name")
        if not env_name:
            continue
        value = os.environ.get(env_name)
        if value:
            keys.append(value)

    if not keys:
        keys.extend(settings.google_api_keys)

    return keys
