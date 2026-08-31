"""Contrato de um provedor de geração de imagem (texto → imagem).

Trocar de modelo (Z-Image, SDXL, FLUX, ...) é só implementar esta interface e
apontar o `config.json` para o novo provider — mesmo padrão do TTS.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ImageResult:
    def __init__(self, image: bytes, mime: str):
        self.image = image
        self.mime = mime


class ImageProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        style: str | None = None,
        aspect_ratio: str | None = None,
        seed: int | None = None,
    ) -> ImageResult:
        raise NotImplementedError
