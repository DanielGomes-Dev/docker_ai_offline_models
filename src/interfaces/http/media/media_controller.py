"""Controller do ai_inference: TTS (texto → áudio) e transcrição (áudio →
timestamps por palavra). Ambos rodam modelos locais.

Padrão do repo: devolve dict simples; em erro interno devolve
``{"status": "error", "message": ...}`` (HTTP 200). O chamador
(`video_automation` via fila) levanta ao ver isso.
"""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path

from pydantic import ValidationError

from src.interfaces.http.media.schemas import (
    ImageRequest,
    ImageResponse,
    TranscribeRequest,
    TranscribeResponse,
    TtsRequest,
    TtsResponse,
    invalid_request,
)


class MediaController:
    def __init__(self, tts_service=None, transcribe_service=None, image_service=None):
        self._tts_service = tts_service
        self._transcribe_service = transcribe_service
        self._image_service = image_service
        self.upload_dir = Path("files/temp/audio_in")

    # ---- serviços carregados sob demanda (whisper baixa modelo na 1ª vez) ----
    @property
    def tts_service(self):
        if self._tts_service is None:
            from src.application.services.media.tts.tts_service import TtsService

            self._tts_service = TtsService()
        return self._tts_service

    @property
    def transcribe_service(self):
        if self._transcribe_service is None:
            from src.infra.external.whisper.transcribe_service import (
                TranscribeService,
            )

            self._transcribe_service = TranscribeService()
        return self._transcribe_service

    @property
    def image_service(self):
        if self._image_service is None:
            from src.application.services.media.image.image_service import ImageService

            self._image_service = ImageService()
        return self._image_service

    # ------------------------------------------------------------------
    async def tts(self, body: dict):
        try:
            req = TtsRequest.model_validate(body)
        except ValidationError as e:
            return invalid_request(e)

        try:
            result = await self.tts_service.synthesize(
                req.text, voice=req.voice, lang=req.lang
            )
            return TtsResponse(
                mime=result.mime,
                data_b64=base64.b64encode(result.audio).decode("ascii"),
            )
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:  # noqa: BLE001
            print(f"[tts] ❌ {type(e).__name__}: {e}")
            return {"status": "error", "message": str(e)}

    async def image(self, body: dict):
        try:
            req = ImageRequest.model_validate(body)
        except ValidationError as e:
            return invalid_request(e)

        try:
            result = await self.image_service.generate(
                req.prompt,
                style=req.style,
                aspect_ratio=req.aspect_ratio,
                seed=req.seed,
            )
            return ImageResponse(
                mime=result.mime,
                data_b64=base64.b64encode(result.image).decode("ascii"),
            )
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:  # noqa: BLE001
            print(f"[image] ❌ {type(e).__name__}: {e}")
            return {"status": "error", "message": str(e)}

    async def transcribe(self, request: dict):
        try:
            req = TranscribeRequest.model_validate(request.get("body") or {})
        except ValidationError as e:
            return invalid_request(e)

        dest: Path | None = None
        try:
            file = request["file"]
            self.upload_dir.mkdir(parents=True, exist_ok=True)
            name = Path(file.filename or "audio.wav").name
            dest = self.upload_dir / f"{int(time.time() * 1000)}_{name}"

            with dest.open("wb") as f:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)

            result = await asyncio.to_thread(
                self.transcribe_service.transcribe, str(dest), req.language
            )
            return TranscribeResponse.model_validate(result)
        except Exception as e:  # noqa: BLE001
            print(f"[transcribe] ❌ {type(e).__name__}: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            # o upload só existe para o whisper ler: apaga sempre (sucesso ou
            # erro). Falha ao apagar não pode mudar a resposta.
            if dest is not None:
                try:
                    dest.unlink(missing_ok=True)
                except OSError as e:
                    print(f"[transcribe] ⚠️ não apagou {dest}: {e}")
