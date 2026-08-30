# syntax=docker/dockerfile:1

# workspace-standard deviation: CUDA base + system python (GPU inference: faster-whisper STT)
FROM nvidia/cuda:12.6.0-runtime-ubuntu24.04 AS base
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/bin/python3.12 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    WHISPER_DOWNLOAD_ROOT=/models/whisper \
    HF_HOME=/models/hf
WORKDIR /app

# workspace-standard deviation: CUDA base + system python (ffmpeg for edge-tts / whisper decoding)
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.12 \
      python3.12-dev \
      ffmpeg \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/

FROM base AS deps
# layer caches on deps only
COPY pyproject.toml uv.lock ./
COPY platform_core/pyproject.toml platform_core/README.md ./platform_core/
COPY platform_core/platform_core/__init__.py ./platform_core/platform_core/__init__.py
RUN uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY . .
RUN uv sync --frozen --no-dev
CMD ["sh", "-c", "uvicorn main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8005}"]
