# Visão geral — `docker_ai_offline_models` (serviço `ai-inference`)

> Nome do repo/pasta é `docker_ai_offline_models`; o slug canônico do serviço (Swagger, docs do
> workspace) é `ai-inference`. Os dois nomes aparecem nesta documentação — são o mesmo serviço.

## O que o serviço faz

É o serviço que roda **modelos de IA localmente, na GPU**, para os três fluxos que não fazem
sentido pagar por API externa a cada chamada (ou que precisam rodar 100% offline / self-hosted):

1. **Texto → áudio** (TTS) — ver [`01-texto-para-fala-tts.md`](./01-texto-para-fala-tts.md)
2. **Áudio → texto com timestamp por palavra** (STT/transcrição) — ver
   [`02-transcricao-de-audio-stt.md`](./02-transcricao-de-audio-stt.md)
3. **Texto → imagem** — ver [`03-geracao-de-imagem.md`](./03-geracao-de-imagem.md)

FastAPI + uvicorn, "100% HTTP, síncrono" (mesmo estilo dos outros microserviços do workspace):
recebe request, processa (bloqueando a thread numa chamada de GPU), devolve resposta. Sem fila
própria — quem enfileira é o `video_automation`.

## Por que **dois processos separados** (`APP_ROLE`)

Este é o ponto mais importante para entender a arquitetura do serviço, e o motivo de ele não ser
"um container FastAPI normal com três rotas".

O código roda em **um único container image** (mesma imagem Docker, mesmo `main.py`), mas é
**subido duas vezes**, cada vez com uma variável de ambiente `APP_ROLE` diferente que decide quais
rotas aquele processo registra (`src/interfaces/http/media/media_routes.py`):

| `APP_ROLE` | Container (compose) | Rotas montadas | Porta |
|---|---|---|---|
| `media` | `ai-inference` | `POST /tts`, `POST /transcribe` | `8005` |
| `image` | `ai-image` | `POST /image` | `8007` |
| `all` | (nenhum no compose — só uso manual/dev) | as três rotas no mesmo processo | — |

**O motivo é conflito de driver de GPU dentro do mesmo processo Python**, não escala ou
organização de código:

- A transcrição usa **faster-whisper**, que por baixo roda em **CTranslate2** (um runtime de
  inferência em C++ próprio, não é PyTorch).
- A geração de imagem usa **`torch` + `diffusers`** (CUDA via PyTorch).
- Carregar CTranslate2 e PyTorch/CUDA **no mesmo processo** colide na inicialização do cuDNN e
  derruba o processo com segfault, ou com um erro `"meta tensor"` do lado do `diffusers` quando ele
  tenta mover o pipeline para a GPU. Isso já foi reproduzido durante o desenvolvimento — não é
  teórico.
- A solução foi isolar em **dois processos do SO**, cada um só carregando a lib que usa. Como os
  dois processos ainda competem pela mesma GPU física, o container `ai-image` **depende** do
  `ai-inference` no compose (`depends_on`) e cada provider serializa o acesso à própria GPU com um
  lock (detalhe no fluxo de imagem).

`APP_ROLE=all` existe só para rodar os três endpoints num processo só em dev local (por exemplo,
para não precisar subir dois containers para testar rapidamente). **Não é usado em produção** e
tende a quebrar assim que a GPU é exercitada de verdade (mesmo problema de colisão acima).

## Onde se encaixa no ecossistema

Quem chama este serviço:

- **`video_automation`** — via duas filas BullMQ dedicadas, uma por endpoint de modelo:
  `ai-tts` (`POST /tts`) e `ai-transcribe` (`POST /transcribe`). Ver
  `_shared/video_automation/src/infra/queue/queue_names.py` (constantes `AI_TTS`/`AI_TRANSCRIBE`) e
  os workers `src/workers/ai_tts_worker.py` / `ai_transcribe_worker.py`. Cada fila roda com
  `concurrency` baixo de propósito: 1 worker = 1 chamador daquele endpoint, serializando o uso da
  GPU e dando visibilidade/retry/DLQ por chamada de modelo no Bull Board.
- **`video_worker`** — chama `POST /transcribe` **diretamente por HTTP** (sem fila), em
  `src/infra/external/whisper/transcribe_service.py`. Ele extrai o áudio do vídeo com `ffmpeg`
  localmente e manda só o `.wav` para o `ai_inference`; o faster-whisper em si saiu do
  `video_worker` junto com as libs CUDA-python.
- **`llm_adapter`** — para geração de imagem, tem um provider (`AiInferenceImageProvider`, em
  `src/infra/external/ai_inference_image/ai_inference_image_provider.py`) que chama
  `POST /image` diretamente por HTTP, como alternativa local ao Google Image FX.

Mapa completo de dependências entre todos os serviços do workspace:
[`../../../docs/01-mapa-de-dependencias.md`](../../../docs/01-mapa-de-dependencias.md) (nó
`AiInference` / `docker_ai_offline_models`).

## Stack tecnológica

- **FastAPI + uvicorn** — servidor HTTP. Ver
  [glossário — FastAPI](../../../docs/03-glossario-de-tecnologias.md#web--api).
- **faster-whisper** (CTranslate2) — STT. Precisa de `nvidia-cublas-cu12` / `nvidia-cudnn-cu12`
  (as libs CUDA que o CTranslate2 usa em runtime, sem depender do `torch`).
- **edge-tts** — TTS via endpoint gratuito da Microsoft (provider padrão); **Gemini TTS** existe
  como provider alternativo configurável, não é o default.
- **torch** (índice CUDA 12.8) + **diffusers** (fixado no HEAD do repositório git, não numa
  release — o suporte a Z-Image no `diffusers` é recente demais para ter release estável) +
  **transformers**, **accelerate**, **safetensors**, **bitsandbytes** (quantização 4-bit) — geração
  de imagem.

### Requisito de GPU específico

O `Dockerfile` usa `nvidia/cuda:12.8.0-runtime-ubuntu24.04` **de propósito**: é a versão de CUDA
compatível com o wheel `torch` exigido por GPUs **Blackwell** (ex.: **RTX 5060 Ti**, arquitetura
`sm_120`). Uma imagem CUDA mais antiga não teria o driver runtime necessário para essa geração de
placa. Base Ubuntu 24.04 + Python 3.12 do sistema (não a imagem `python:3.12` oficial) + `ffmpeg`
(decodificação de áudio) + `git` (porque o `diffusers` é instalado direto do repositório git, não
do PyPI).

Volume Docker nomeado **`ai-models`** (externo, compartilhado entre os dois containers) montado em
`/models`:
- `/models/whisper` — pesos baixados do Whisper (`WHISPER_DOWNLOAD_ROOT`).
- `/models/hf` — cache do Hugging Face (`HF_HOME`), usado pelos modelos de imagem (Z-Image, text
  encoder, etc.).

## Como rodar localmente

Faz parte do pipeline geral de conteúdo — ver o script/skill de subida do workspace
(`content.py` / `video_automation.py`, dependendo de qual script de orquestração local está em uso
no momento). **Precisa de GPU NVIDIA** com driver instalado no host (o compose usa
`deploy.resources.reservations.devices` com `driver: nvidia`); sem GPU, os dois containers sobem
mas falham ao carregar os modelos.

```bash
cd _shared/docker_ai_offline_models
docker compose up --build
```

Isso sobe os dois containers definidos em `docker-compose.yml`:
- `ai-inference` (porta `8005`, `APP_ROLE=media`)
- `ai-image` (porta `8007`, `APP_ROLE=image`, depende do anterior)

Ambos exigem a rede externa `app-network-ai` e o volume externo `ai-models` já criados
previamente (o script de orquestração do workspace cuida disso).

## Índice dos fluxos

| Fluxo | Rota | Processo (`APP_ROLE`) | Documento |
|---|---|---|---|
| Texto → áudio (TTS) | `POST /tts` | `media` | [01-texto-para-fala-tts.md](./01-texto-para-fala-tts.md) |
| Áudio → texto (STT) | `POST /transcribe` | `media` | [02-transcricao-de-audio-stt.md](./02-transcricao-de-audio-stt.md) |
| Texto → imagem | `POST /image` | `image` | [03-geracao-de-imagem.md](./03-geracao-de-imagem.md) |
