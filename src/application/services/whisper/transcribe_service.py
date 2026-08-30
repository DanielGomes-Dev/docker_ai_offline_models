"""Transcrição de áudio via faster-whisper (GPU).

Uma passada só com `word_timestamps=True` já entrega palavra-a-palavra E
frase-a-frase (cada segmento tem `.words` e `.text`). Devolve um dict com os
dois SRTs + a lista de palavras + a duração.

`transcribe()` é síncrono (bloqueia CPU/GPU) — o controller chama via
`asyncio.to_thread`.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


def _download_root() -> str:
    return os.environ.get("WHISPER_DOWNLOAD_ROOT", "./models")


class TranscribeService:
    def __init__(self, model_size=None, device=None, compute_type=None):
        self._inject_cuda_libraries()

        model_size = model_size or os.environ.get("WHISPER_MODEL_SIZE", "large-v3")
        device = device or os.environ.get("WHISPER_DEVICE", "cuda")
        compute_type = compute_type or os.environ.get("WHISPER_COMPUTE_TYPE", "float16")

        logger.info(f"Carregando WhisperModel ({model_size}) em {device}...")
        try:
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=_download_root(),
            )
        except Exception as e:
            logger.error(f"Falha ao carregar modelo: {e}")
            raise

    def _inject_cuda_libraries(self):
        """Injeção de DLLs para ambientes Windows/VENV (no-op no Linux)."""
        base = sys.prefix
        for path in (
            os.path.join(base, "Lib", "site-packages", "nvidia", "cublas", "bin"),
            os.path.join(base, "Lib", "site-packages", "nvidia", "cudnn", "bin"),
        ):
            if os.path.exists(path):
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(path)
                os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")

    # ------------------------------------------------------------------
    @staticmethod
    def _format_time(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:06.3f}".replace(".", ",")

    def _build_word_srt(self, segments) -> str:
        lines: list[str] = []
        idx = 1
        for seg in segments:
            for word in getattr(seg, "words", None) or []:
                text = word.word.strip()
                if not text:
                    continue
                lines.append(
                    f"{idx}\n{self._format_time(word.start)} --> "
                    f"{self._format_time(word.end)}\n{text}\n"
                )
                idx += 1
        return "\n".join(lines) + ("\n" if lines else "")

    def _build_sentence_srt(self, segments) -> str:
        lines: list[str] = []
        for idx, seg in enumerate(segments, start=1):
            lines.append(
                f"{idx}\n{self._format_time(seg.start)} --> "
                f"{self._format_time(seg.end)}\n{seg.text.strip()}\n"
            )
        return "\n".join(lines) + ("\n" if lines else "")

    # ------------------------------------------------------------------
    def transcribe(self, audio_path: str, language: str | None = None) -> dict:
        audio = Path(audio_path)
        if not audio.exists():
            raise FileNotFoundError(f"Áudio não encontrado: {audio_path}")

        segments_gen, info = self.model.transcribe(
            str(audio),
            beam_size=5,
            language=language,
            task="transcribe",
            word_timestamps=True,
        )
        segments = list(segments_gen)  # consome o gerador uma vez

        words = [
            {
                "word": w.word.strip(),
                "start": round(float(w.start), 3),
                "end": round(float(w.end), 3),
            }
            for seg in segments
            for w in (getattr(seg, "words", None) or [])
            if w.word.strip()
        ]

        duration = getattr(info, "duration", None)
        if not duration:
            duration = segments[-1].end if segments else 0.0

        return {
            "words": words,
            "word_srt": self._build_word_srt(segments),
            "sentence_srt": self._build_sentence_srt(segments),
            "duration_s": round(float(duration), 3),
            "language": getattr(info, "language", None),
        }
