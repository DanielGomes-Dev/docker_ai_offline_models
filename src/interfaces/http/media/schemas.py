"""Schemas HTTP das rotas de mídia: ``POST /tts``, ``POST /transcribe`` e ``POST /image``.

Convenções do repo (mantidas):
- sucesso ``/tts`` e ``/image``: ``{"mime": ..., "data_b64": ...}``
- sucesso ``/transcribe``: ``{"words": [...], "word_srt": ..., "sentence_srt": ...,
  "duration_s": ..., "language": ...}``
- erro de validação da request: ``{"status": "invalid_request", "message": ...}`` (HTTP 200)
- erro interno:                 ``{"status": "error", "message": ...}``            (HTTP 200)

O controller valida a request com ``model_validate`` e devolve o response model
(o RouteRegister/FastAPI serializa). O corpo do happy-path é idêntico ao anterior.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError, field_validator


def invalid_request(exc: ValidationError) -> dict:
    first = exc.errors()[0]
    loc = ".".join(str(p) for p in first.get("loc", ()))
    msg = f"{loc}: {first.get('msg')}" if loc else first.get("msg", "payload inválido")
    return {"status": "invalid_request", "message": msg}


# --------------------------------------------------------------------- /tts


class TtsRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str | None = None
    lang: str | None = None

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("não pode ser vazio")
        return v


class TtsResponse(BaseModel):
    mime: str
    data_b64: str


# ------------------------------------------------------------------- /image


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1)
    style: str | None = None
    aspect_ratio: str | None = None
    seed: int | None = None

    @field_validator("prompt")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("não pode ser vazio")
        return v


class ImageResponse(BaseModel):
    mime: str
    data_b64: str


# -------------------------------------------------------------- /transcribe


class TranscribeRequest(BaseModel):
    language: str | None = None


class TranscribeWord(BaseModel):
    word: str
    start: float
    end: float


class TranscribeResponse(BaseModel):
    words: list[TranscribeWord]
    word_srt: str
    sentence_srt: str
    duration_s: float
    language: str | None = None
