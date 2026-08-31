"""Serviço de geração de imagem: escolhe o provider pelo `config.json` e delega.

O provider pode ser injetado (testes) ou resolvido pelo config (produção).
Mesmo padrão do TtsService.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.domain.ports.image_provider import ImageProvider, ImageResult
from src.infra.external.z_image.z_image_provider import ZImageProvider

_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

_PROVIDERS = {
    "z_image": ZImageProvider,
}


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"provider": "z_image"}


class ImageService:
    def __init__(self, provider: ImageProvider | None = None, config: dict | None = None):
        self.config = config or _load_config()
        if provider is not None:
            self.provider = provider
        else:
            name = self.config.get("provider", "z_image")
            provider_cls = _PROVIDERS.get(name)
            if provider_cls is None:
                raise ValueError(f"Provider de imagem desconhecido: {name!r}")
            self.provider = provider_cls(self.config.get(name, {}))

    async def generate(
        self,
        prompt: str,
        *,
        style: str | None = None,
        aspect_ratio: str | None = None,
        seed: int | None = None,
    ) -> ImageResult:
        return await self.provider.generate(
            prompt, style=style, aspect_ratio=aspect_ratio, seed=seed
        )
