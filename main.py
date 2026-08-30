from fastapi import FastAPI

from src.interfaces.api.routes import Routes

app = FastAPI(
    title="AI Inference API",
    description=(
        "Modelos de IA locais do workspace: TTS (edge-tts) e transcrição "
        "(faster-whisper). 100% HTTP, síncrono. Chamado pelo video_automation "
        "via filas `ai-tts` / `ai-transcribe`."
    ),
    version="1.0.0",
)


def main():
    routes = Routes()
    routes.execute()
    app.include_router(routes.router)


main()
