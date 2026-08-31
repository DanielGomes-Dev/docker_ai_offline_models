"""Parser mínimo de SRT → lista de {word/text, start, end} em segundos.

Usado para devolver os timestamps por palavra do áudio gerado (fase 2b do
pipeline 100% IA). Sem dependência externa (o video_worker não tem pysrt).
"""

from __future__ import annotations

import re

_TS = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(text: str) -> list[dict]:
    entries: list[dict] = []
    if not text:
        return entries
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        ts_line_idx = 0 if _TS.search(lines[0]) else (1 if len(lines) > 1 and _TS.search(lines[1]) else None)
        if ts_line_idx is None:
            continue
        match = _TS.search(lines[ts_line_idx])
        start = _to_seconds(*match.group(1, 2, 3, 4))
        end = _to_seconds(*match.group(5, 6, 7, 8))
        word = " ".join(lines[ts_line_idx + 1 :]).strip()
        if not word:
            continue
        entries.append({"word": word, "start": round(start, 3), "end": round(end, 3)})
    return entries


def srt_duration(text: str) -> float:
    """Fim do último bloco do SRT (0.0 se vazio)."""
    entries = parse_srt(text)
    return entries[-1]["end"] if entries else 0.0
