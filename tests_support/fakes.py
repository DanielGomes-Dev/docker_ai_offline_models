"""Lightweight fakes for ai_inference's heavy deps (faster_whisper), installed in
``sys.modules`` BEFORE any service module is imported — only when the real package
is not installed.

Primitives come from platform_core; the fake spec is ai_inference-specific.
"""

from unittest.mock import MagicMock

from platform_core.testing.fakes import install_fake


def install_all_fakes() -> None:
    install_fake("faster_whisper", attrs={"WhisperModel": MagicMock(name="WhisperModel")})
