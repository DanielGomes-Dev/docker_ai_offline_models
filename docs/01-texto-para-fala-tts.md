# Fluxo — Texto para fala (TTS)

## O que é / quando acontece

Converte um texto em áudio falado. É usado sempre que o pipeline de vídeo (`video_automation`)
precisa de uma narração/voz para um roteiro gerado por IA — o fluxo mais comum é o
"vídeo 100% IA" (`ai-video-generation`), que gera roteiro → chama este endpoint para virar áudio →
manda o áudio para o `video_worker` montar o vídeo.

Roda no processo `APP_ROLE=media` (container `ai-inference`, porta `8005`), junto com a
transcrição — os dois dividem o mesmo processo porque nenhum dos dois usa `torch`/CUDA via
PyTorch (só o CTranslate2 do whisper usa GPU aqui). Ver a separação de processos em
[`00-visao-geral.md`](./00-visao-geral.md).

## Passo a passo

1. **Rota**: `POST /tts`, registrada em
   `src/interfaces/http/media/media_routes.py` → `MediaController.tts`
   (`src/interfaces/http/media/media_controller.py`).
2. **Request** validado por `TtsRequest`
   (`src/interfaces/http/media/schemas.py`):
   ```json
   { "text": "string (obrigatório, não pode ser vazio)", "voice": "string opcional", "lang": "string opcional" }
   ```
   Erro de validação → `{"status": "invalid_request", "message": "..."}` (HTTP 200 — o padrão do
   repo é nunca estourar HTTP 4xx para erro de payload, o chamador é quem decide o que fazer com o
   `status`).
3. O controller chama `TtsService.synthesize(text, voice=voice, lang=lang)`
   (`src/application/services/media/tts/tts_service.py`). O `TtsService` só faz uma coisa: ler
   `src/application/services/media/tts/config.json` para decidir **qual provider** usar e delegar.
   Hoje o config traz:
   ```json
   { "provider": "edge_tts", "edge_tts": {...}, "gemini": {...} }
   ```
   Ou seja, **`edge_tts` é o provider padrão**; trocar para Gemini é editar esse JSON (campo
   `"provider": "gemini"`), sem precisar mexer em código.
4. **Provider padrão — `EdgeTtsProvider`**
   (`src/infra/external/edge_tts/edge_tts_provider.py`):
   - Importa `edge_tts` de forma lazy (só na hora de sintetizar), para o módulo carregar mesmo sem
     o pacote instalado (facilita teste com fake injetado via `communicate_factory`).
   - Escolhe a voz: se `voice` veio explícito na request, usa ela; senão mapeia `lang` (minúsculo)
     para uma voz default por idioma (`_VOICE_BY_LANG`), ex.: `pt-br`/`pt` →
     `pt-BR-FranciscaNeural`, `en`/`en-us` → `en-US-AriaNeural`, `es`/`es-es` →
     `es-ES-ElviraNeural`; se nem `voice` nem `lang` vieram, cai no `default_voice` do config
     (`pt-BR-FranciscaNeural`).
   - Chama `edge_tts.Communicate(text, voz, rate=, volume=, pitch=).stream()` e acumula os chunks
     de áudio (`chunk["type"] == "audio"`) num buffer de bytes.
   - Devolve `TtsResult(audio=bytes, mime="audio/mpeg")` — **sempre MP3**.
5. **Provider alternativo — `GeminiTtsProvider`**
   (`src/infra/external/gemini_tts/gemini_tts_provider.py`), selecionável por config, não é o
   default:
   - Chama a REST API do Google Generative Language direto via `httpx` (não usa
     `langchain-google-genai`, porque essa lib não expõe saída de áudio), modelo
     `gemini-2.5-flash-preview-tts` por padrão.
   - Precisa de credencial: lê `GOOGLE_API_KEY_00`..`GOOGLE_API_KEY_09` e/ou `GOOGLE_API_KEY` (via
     `available_api_keys()`), tentando as chaves em ordem — a mesma estratégia de rotação de chaves
     usada no resto do workspace para contornar limite de requisições por minuto.
   - Resiliência específica de modelo preview: em `429`/`RESOURCE_EXHAUSTED` pula direto para a
     próxima chave (cota estourou); em `500`/`503`/`UNAVAILABLE`/`OVERLOADED` espera um backoff e
     **tenta de novo na mesma chave** (trocar de chave não ajuda quando o modelo em si está
     sobrecarregado).
   - A resposta vem como PCM 16-bit mono em base64; o provider embrulha isso num container WAV
     antes de devolver (`TtsResult(audio=wav, mime="audio/wav")`).
6. **Response** (`TtsResponse`): `{"mime": "audio/mpeg", "data_b64": "<base64>"}` — o controller
   faz `base64.b64encode` do áudio bruto devolvido pelo provider. Erro de síntese (`ValueError` ou
   qualquer outra exceção) vira `{"status": "error", "message": "..."}`, sem estourar HTTP 500.

## Tecnologias envolvidas

- **edge-tts** — biblioteca Python que fala com o endpoint de síntese de voz do Microsoft Edge.
  Ver [glossário — edge-tts](../../../docs/03-glossario-de-tecnologias.md#edge-tts).
- **Google Gemini (TTS)** — mesmo provedor de LLM usado no resto do workspace, aqui numa variante
  de saída de áudio. Ver
  [glossário — Google Gemini](../../../docs/03-glossario-de-tecnologias.md#ia--modelos).
- **httpx** — cliente HTTP assíncrono, usado pelo provider Gemini para chamar a REST API
  diretamente (sem SDK).
- **Pydantic** — validação de request/response
  (ver [glossário — Pydantic](../../../docs/03-glossario-de-tecnologias.md#web--api)).

## Pontos de atenção

- **`edge-tts` não é 100% offline**, apesar de morar dentro de um repositório chamado
  `docker_ai_offline_models` e de uma pasta `edge_tts/`. Ele depende de rede: fala com o endpoint
  gratuito de voz da Microsoft a cada chamada. Se a rede cair ou a Microsoft mudar/bloquear o
  endpoint, o TTS para de funcionar mesmo com o container rodando perfeitamente. É uma
  característica conhecida e aceita (qualidade pt-BR compensa), não um bug.
- **Nenhum dos dois providers usa GPU** — TTS aqui é 100% chamada de rede (edge-tts) ou REST API
  (Gemini). Quem usa GPU neste processo é só a transcrição (faster-whisper).
- **Trocar de provider é edição de config, não de código** — `config.json` decide tudo; útil saber
  isso ao debugar "por que a voz mudou" ou "por que ficou lento" (Gemini tem muito mais latência e
  rate limit que o edge-tts).
- **Gemini TTS depende de chave válida** (`GOOGLE_API_KEY_*`); sem nenhuma chave configurada, o
  provider levanta erro imediatamente ao tentar sintetizar — só importa se o config for trocado
  para `"gemini"`.
- Formato de saída **difere por provider**: edge-tts devolve MP3, Gemini devolve WAV. Quem consome
  a resposta (ex.: `video_worker`/`moviepy`/`ffmpeg`) precisa lidar com os dois mimes possíveis.

## Referências para aprofundar

- [edge-tts (GitHub)](https://github.com/rany2/edge-tts)
- [Gemini API — geração de áudio (TTS)](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Documentação oficial FastAPI](https://fastapi.tiangolo.com/)
- [Pydantic docs](https://docs.pydantic.dev/latest/)
