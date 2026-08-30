"""Application factory. Importing this module has no side effect until create_app() runs."""

from platform_core.http import create_app as _base

from src.interfaces.http.routes import Routes

_TITLE = "AI Inference API"
_DESCRIPTION = (
    "Modelos de IA locais do workspace: TTS (edge-tts) e transcrição (faster-whisper). "
    "100% HTTP, síncrono. Chamado pelo video_orchestrator via filas ai-tts / ai-transcribe."
)
_VERSION = "1.0.0"


def create_app():
    routes = Routes()
    routes.execute()
    return _base(title=_TITLE, description=_DESCRIPTION, version=_VERSION, routers=[routes.router])
