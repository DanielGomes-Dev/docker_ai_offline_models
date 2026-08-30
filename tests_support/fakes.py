"""Fakes leves das dependências pesadas do ai_inference (faster_whisper),
instalados em `sys.modules` ANTES de qualquer módulo do serviço ser importado
pelos testes — só quando o pacote real não está instalado.

Ver o gêmeo em `video_worker/tests_support/fakes.py`.
"""

import importlib.util
import sys
import types
from unittest.mock import MagicMock


def _module(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _really_installed(name: str) -> bool:
    if name in sys.modules:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def install_fake_faster_whisper() -> None:
    if _really_installed("faster_whisper"):
        return
    mod = _module("faster_whisper")
    mod.WhisperModel = MagicMock(name="WhisperModel")


def install_all_fakes() -> None:
    install_fake_faster_whisper()
