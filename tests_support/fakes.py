"""Lightweight fakes for ai_inference's heavy deps (faster_whisper, torch,
diffusers), installed in ``sys.modules`` BEFORE any service module is imported —
only when the real package is not installed.

Primitives come from platform_core; the fake spec is ai_inference-specific.
"""

from unittest.mock import MagicMock

from platform_core.testing.fakes import install_fake


def install_all_fakes() -> None:
    install_fake("faster_whisper", attrs={"WhisperModel": MagicMock(name="WhisperModel")})
    # ZImageProvider só toca torch/diffusers no _load_pipe() real; os testes
    # injetam pipeline_factory. Fakes aqui só evitam ImportError se alguém
    # instanciar o ImageService de verdade sem GPU.
    install_fake("torch", attrs={"bfloat16": "bfloat16", "float16": "float16", "Generator": MagicMock(name="Generator")})
    install_fake("diffusers", attrs={"ZImagePipeline": MagicMock(name="ZImagePipeline")})
