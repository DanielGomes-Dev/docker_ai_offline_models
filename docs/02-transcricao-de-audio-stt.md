# Fluxo — Transcrição de áudio (STT)

## O que é / quando acontece

Converte áudio em texto, com **timestamp por palavra** — não é só "o que foi dito", é "cada
palavra começou e terminou em que segundo". É o que permite gerar legenda sincronizada
automaticamente (SRT palavra-a-palavra ou frase-a-frase).

Dois chamadores diferentes, dois usos diferentes:

- **`video_automation`**, fila `ai-transcribe` — parte do pipeline "vídeo 100% IA" e de outros
  fluxos que geram legenda automaticamente.
- **`video_worker`**, direto por HTTP (sem fila) — usado no fluxo de "corte" de vídeos existentes,
  onde o `video_worker` já tem o vídeo fonte, extrai o áudio localmente com `ffmpeg` e manda só o
  `.wav` (pequeno) para cá, em vez de mandar o vídeo inteiro.

Roda no processo `APP_ROLE=media` (container `ai-inference`, porta `8005`), junto com o TTS. Ver a
separação de processos (por que a geração de imagem roda num container à parte) em
[`00-visao-geral.md`](./00-visao-geral.md).

## Passo a passo

1. **Rota**: `POST /transcribe`, registrada com `method="POST_FILE"` (upload multipart, não JSON
   puro) em `src/interfaces/http/media/media_routes.py` →
   `MediaController.transcribe`.
2. **Request**: upload multipart com o arquivo de áudio + um campo `payload` opcional (JSON) com
   `{"language": "pt"}` (ou omitido para auto-detecção). Validado por `TranscribeRequest`
   (`src/interfaces/http/media/schemas.py`), que só tem o campo `language: str | None`.
3. O controller:
   - Salva o upload em `files/temp/audio_in/<timestamp_ms>_<nome_original>` (lendo em chunks de
     1 MB via `await file.read(1024*1024)`, sem carregar tudo na memória de uma vez).
   - Chama `TranscribeService.transcribe(caminho, language)`
     (`src/infra/external/whisper/transcribe_service.py`) dentro de
     `asyncio.to_thread(...)` — **importante**: essa chamada é **síncrona e bloqueante** (é
     trabalho de GPU), então rodar numa thread separada evita travar o event loop do FastAPI
     enquanto o whisper processa.
4. **`TranscribeService`**:
   - No `__init__`, em ambiente Windows/venv, injeta os diretórios de DLL do
     `nvidia-cublas`/`nvidia-cudnn` (`os.add_dll_directory` + `PATH`) antes de carregar o modelo —
     no-op em Linux/container, onde essas libs já estão no `LD_LIBRARY_PATH` padrão.
   - Carrega **um único** `faster_whisper.WhisperModel` no construtor (fica em memória para
     todas as chamadas seguintes, não recarrega por request), com:
     - `model_size` = `settings.whisper_model_size` (default **`large-v3`**)
     - `device` = `settings.whisper_device` (default **`cuda`**)
     - `compute_type` = `settings.whisper_compute_type` (default **`float16`**)
     - `download_root` = `settings.whisper_download_root` (`/models/whisper` no container, aponta
       para o volume `ai-models`)
   - `transcribe(audio_path, language)` faz **uma única passada** de
     `self.model.transcribe(..., beam_size=5, task="transcribe", word_timestamps=True)`. Como
     `word_timestamps=True`, cada segmento retornado já traz tanto `.text` (frase inteira) quanto
     `.words` (lista de palavras com `start`/`end`) — não precisa rodar o modelo duas vezes para
     ter os dois níveis de granularidade.
   - Monta dois arquivos **SRT** a partir dos mesmos segmentos: `_build_word_srt` (uma legenda por
     palavra) e `_build_sentence_srt` (uma legenda por frase/segmento), formatando timestamps como
     `HH:MM:SS,mmm` (vírgula, padrão SRT).
   - Duração (`duration_s`) vem de `info.duration` (metadado que o próprio faster-whisper extrai do
     áudio); se ausente, cai no fim do último segmento.
5. **Response** (`TranscribeResponse`):
   ```json
   {
     "words": [{"word": "...", "start": 0.12, "end": 0.34}, "..."],
     "word_srt": "1\n00:00:00,120 --> 00:00:00,340\n...\n",
     "sentence_srt": "1\n00:00:00,000 --> 00:00:03,500\n...\n",
     "duration_s": 12.345,
     "language": "pt"
   }
   ```
   `language` vem de `info.language` — é o idioma detectado pelo whisper quando `language` não foi
   passado na request (ou o próprio idioma passado, ecoado de volta).
6. **Cliente do `video_worker`** — vale registrar como esse fluxo é consumido do outro lado:
   `_shared/video_worker/src/infra/external/whisper/transcribe_service.py` mantém a **mesma
   assinatura pública** que existia quando o whisper rodava local no `video_worker` (para não mudar
   o use case chamador), mas por dentro virou um cliente HTTP puro: extrai o áudio com `ffmpeg`
   (`.wav` 16 kHz mono), sobe pro campo `upload` do `POST /transcribe` (contrato do `POST_FILE`),
   escolhe `word_srt` ou `sentence_srt` conforme o `mode` pedido, e grava o `.srt` ao lado do vídeo.

## Tecnologias envolvidas

- **faster-whisper** — reimplementação do Whisper (OpenAI) sobre **CTranslate2**, mais rápida e
  mais leve em VRAM que o Whisper original em PyTorch. Ver
  [glossário — faster-whisper](../../../docs/03-glossario-de-tecnologias.md#ia--modelos).
- **nvidia-cublas-cu12 / nvidia-cudnn-cu12** — libs CUDA que o CTranslate2 carrega em runtime;
  não passam por `torch`, por isso convivem no mesmo processo do container `media` sem o conflito
  que existe com o `diffusers`.
- **Pydantic** — validação de request/response
  (ver [glossário — Pydantic](../../../docs/03-glossario-de-tecnologias.md#web--api)).
- **ffmpeg** — usado pelo lado chamador (`video_worker`) para extrair o áudio do vídeo antes de
  enviar; ver
  [glossário — FFmpeg](../../../docs/01-mapa-de-dependencias.md) e a doc própria do `video_worker`.

## Pontos de atenção

- **Chamada bloqueante de GPU** — mesmo isolada numa thread (`asyncio.to_thread`), a transcrição
  ocupa a GPU inteira enquanto roda; é por isso que a fila `ai-transcribe` do `video_automation`
  roda com `concurrency` baixo — não adianta paralelizar chamadas, a GPU processa uma por vez de
  qualquer forma.
- **Uma passada só, dois granularidades** — a decisão de usar `word_timestamps=True` numa única
  chamada (em vez de transcrever duas vezes) é uma otimização deliberada de custo de GPU; ao mexer
  nesse código, evite reintroduzir uma segunda passada "para simplificar".
- **`large-v3`** é o modelo maior/mais preciso da família Whisper — mais lento e mais pesado em
  VRAM que `medium`/`small`. Trocar o tamanho é só variável de ambiente
  (`WHISPER_MODEL_SIZE`), sem mudar código.
- **Modelo carregado uma vez por processo** — o `WhisperModel` é instanciado no construtor do
  `TranscribeService`, que por sua vez só é criado sob demanda (lazy property no controller) na
  primeira chamada a `/transcribe`. Isso significa que a **primeira** chamada depois de o container
  subir é mais lenta (carrega o modelo + eventualmente baixa os pesos para `/models/whisper` se
  ainda não estiverem no volume); chamadas seguintes reusam o modelo já em memória.
- **Contrato de upload é `POST_FILE`**, não JSON puro — o campo do arquivo se chama `upload` e o
  JSON de opções vai num campo de formulário `payload` (ver o cliente do `video_worker` para o
  formato exato ao integrar um novo chamador).

## Referências para aprofundar

- [faster-whisper (GitHub)](https://github.com/SYSTRAN/faster-whisper)
- [CTranslate2 (motor de inferência usado por baixo)](https://github.com/OpenNMT/CTranslate2)
- [Whisper — paper/modelo original (OpenAI)](https://github.com/openai/whisper)
- [Formato de legenda SRT (SubRip)](https://en.wikipedia.org/wiki/SubRip)
