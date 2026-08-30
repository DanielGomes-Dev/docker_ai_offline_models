FROM nvidia/cuda:12.6.0-runtime-ubuntu24.04

ARG APP_DIR=/ai-inference
ENV APP_DIR=${APP_DIR}
ENV PYTHONUNBUFFERED=1
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# pesos dos modelos (whisper) fora da imagem — volume `ai-models`
ENV WHISPER_DOWNLOAD_ROOT=/models/whisper
ENV HF_HOME=/models/hf

WORKDIR ${APP_DIR}

# 1. Deps de sistema (mudam quase nunca)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3-pip \
    python-is-python3 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pip-tools

# 2. SÓ o arquivo de deps — cache do pip só quebra se as deps mudarem
COPY pyproject.toml ./
RUN pip-compile pyproject.toml && pip install --no-cache-dir -r ./requirements.txt

# 3. Código por último — editar código não refaz o pip install
COPY . .

CMD ["sh", "-c", "uvicorn main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8005} --reload"]
