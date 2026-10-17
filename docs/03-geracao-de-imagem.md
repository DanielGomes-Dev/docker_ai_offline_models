# Fluxo — Geração de imagem

## O que é / quando acontece

Gera uma imagem a partir de um prompt de texto, **rodando o modelo localmente na GPU** (sem
depender de API paga externa). É a alternativa self-hosted ao Google Image FX: o `llm_adapter` tem
um provider de imagem (`AiInferenceImageProvider`) que pode chamar este endpoint em vez de um
serviço de imagem do Google, como fonte de imagens para o pipeline de vídeo/conteúdo.

Roda no processo **`APP_ROLE=image`** — container **separado** (`ai-image`, porta `8007`), nunca
junto com TTS/transcrição no mesmo processo. O motivo (conflito CTranslate2 × torch/CUDA) está
detalhado em [`00-visao-geral.md`](./00-visao-geral.md); este documento foca no que acontece depois
que a request chega no processo certo.

## Passo a passo

1. **Rota**: `POST /image`, registrada em `src/interfaces/http/media/media_routes.py`
   (só quando `APP_ROLE` é `image` ou `all`) → `MediaController.image`.
2. **Request** validado por `ImageRequest` (`src/interfaces/http/media/schemas.py`):
   ```json
   { "prompt": "string (obrigatório, não vazio)", "style": "string opcional", "aspect_ratio": "string opcional", "seed": "int opcional" }
   ```
3. O controller chama `ImageService.generate(prompt, style=, aspect_ratio=, seed=)`
   (`src/application/services/media/image/image_service.py`) — mesmo padrão do `TtsService`: lê
   `config.json` da própria pasta para escolher o provider (hoje só existe `z_image` registrado) e
   delega.
4. **`ZImageProvider`** (`src/infra/external/z_image/z_image_provider.py`), modelo
   `Tongyi-MAI/Z-Image-Turbo` (6B parâmetros, licença Apache-2.0, afinado para realismo) via
   `diffusers.ZImagePipeline`:
   - **Prompt final**: se `style` foi passado, concatena `"{prompt}. {style}"`; senão usa o prompt
     puro.
   - **Resolução por `aspect_ratio`** — mapeamento fixo em `_SIZE_BY_ASPECT` (os valores que o
     `video_automation`/`llm_adapter` mandam são os nomes do enum de aspecto de vídeo):
     | `aspect_ratio` | tamanho (px) |
     |---|---|
     | `IMAGE_ASPECT_RATIO_PORTRAIT` | 768 × 1344 |
     | `IMAGE_ASPECT_RATIO_LANDSCAPE` | 1344 × 768 |
     | `IMAGE_ASPECT_RATIO_SQUARE` | 1024 × 1024 |
     | (qualquer outro valor / ausente) | default do config, `768 × 1344` |
     Todos os tamanhos são múltiplos de 64 (requisito comum de modelos de difusão baseados em
     VAE).
   - **Carregamento do pipeline** (`_load_pipe`, lazy — só na primeira geração, e só uma vez;
     fica em cache na instância): importa `torch`/`diffusers` (import pesado, por isso lazy), e
     se `quantize=True` (**default**) monta um `PipelineQuantizationConfig` com
     `quant_backend="bitsandbytes_4bit"`, `load_in_4bit=True`, `bnb_4bit_quant_type="nf4"`,
     aplicado a `["transformer", "text_encoder"]` — ou seja, **quantiza o transformer de difusão e
     o text encoder Qwen para 4-bit (NF4)**, não o VAE. Isso reduz o modelo de ~30 GB
     (full-precision: DiT + text encoder Qwen + VAE) para ~9 GB de VRAM, o que é o que permite ele
     caber na GPU disponível.
   - Com `offload="none"` (default do config), o pipeline quantizado vai **inteiro para a GPU**
     (`pipe.to("cuda")`) — sem CPU offload. O comentário no código é explícito: isso só cabe porque
     o whisper deste ambiente não está competindo pela mesma VRAM (processos separados, ver
     visão geral), e que `cpu_offload` com pipeline já quantizado quebra com erro de "meta tensor"
     na versão atual do `diffusers` — **não é uma opção viável hoje**, não só uma escolha de
     performance.
   - **Inferência** (`_run_locked`): `pipe(prompt=, width=, height=, num_inference_steps=9,
     guidance_scale=0.0, generator=)`. Os dois parâmetros — 9 passos e `guidance_scale=0.0` — não
     são ajustáveis livremente: são **obrigatórios para modelos "Turbo"/destilados** como este; um
     `guidance_scale` diferente de zero tende a degradar ou quebrar a geração num modelo destilado
     para guidance-free.
   - **`seed`**: se veio na request, cria um `torch.Generator` — em `"cuda"` se `offload == "none"`
     (é o caso hoje), senão em `"cpu"` (mais seguro quando os módulos migram de device via
     offload).
   - Resultado: PNG em memória (`image.save(buf, format="PNG")`), devolvido como
     `ImageResult(image=png_bytes, mime="image/png")`.
5. **Lock de GPU** (`threading.Lock` em `ZImageProvider.__init__`): toda chamada a `generate` passa
   por `_run` → adquire o lock → `_run_locked`. Como é **1 GPU física** para o container `ai-image`,
   isso serializa tanto o carregamento lazy do pipeline (evita corrida se duas requests chegarem
   simultaneamente antes do pipeline existir) quanto a inferência em si (duas gerações
   simultâneas na mesma GPU não são seguras/eficientes de qualquer forma).
6. **`generate()` é assíncrono só na superfície** — a chamada real (`_run`) é síncrona/bloqueante
   (trabalho de GPU), então roda dentro de `asyncio.to_thread(...)`, igual ao padrão usado na
   transcrição.
7. **Response** (`ImageResponse`): `{"mime": "image/png", "data_b64": "<base64>"}`. Erro de
   geração vira `{"status": "error", "message": "..."}` (HTTP 200), mesmo padrão dos outros
   endpoints.
8. **Cliente do `llm_adapter`** —
   `_shared/llm_adapter/src/infra/external/ai_inference_image/ai_inference_image_provider.py`
   (`AiInferenceImageProvider`) chama `POST {ai_inference_url}/image` com o mesmo shape de
   `ImageRequest`; trata `status == "invalid_request"` como `ValueError` e `status == "error"` (ou
   HTTP ≥ 400) como `RuntimeError`, que o `LlmMediaClient` mapeia para `LlmMediaError` — de onde o
   worker do `video_automation` decide retry/DLQ.

## Tecnologias envolvidas

- **Diffusers (Hugging Face) / Z-Image-Turbo** — framework de pipelines de difusão + o modelo em
  si. Ver
  [glossário — Diffusers / Z-Image Turbo](../../../docs/03-glossario-de-tecnologias.md#ia--modelos).
- **torch (build CUDA 12.8)** — runtime de tensor/GPU por baixo do `diffusers`; a versão do índice
  CUDA precisa casar com a versão de CUDA da imagem base do Docker (12.8, ver visão geral) para
  suportar a arquitetura Blackwell da GPU alvo.
- **bitsandbytes** — biblioteca de quantização usada aqui para carregar o transformer e o text
  encoder em 4-bit (NF4).
  [bitsandbytes (GitHub)](https://github.com/bitsandbytes-foundation/bitsandbytes).
- **transformers / accelerate / safetensors** — dependências padrão do ecossistema Hugging Face
  para carregar o text encoder (Qwen) e os pesos com segurança/eficiência.
- **Pydantic** — validação de request/response
  (ver [glossário — Pydantic](../../../docs/03-glossario-de-tecnologias.md#web--api)).

## Pontos de atenção

- **Quantização 4-bit é trade-off qualidade × VRAM, não gratuito** — reduzir o transformer e o
  text encoder para NF4 4-bit é o que faz o modelo caber na GPU disponível, mas tipicamente perde
  um pouco de qualidade/fidelidade frente ao modelo full-precision. Se um dia a qualidade da
  imagem virar suspeita de bug, checar `quantize` no config antes de investigar o prompt.
  `bfloat16` é o dtype de computação por baixo da quantização (`bnb_4bit_compute_dtype`).
  Ver [glossário — quantização](../../../docs/03-glossario-de-tecnologias.md#ia--modelos).
- **Lock serializa toda a GPU** — só uma geração de imagem roda por vez neste container,
  independente de quantas requests chegarem ao mesmo tempo; throughput sob carga é limitado pelo
  tempo de uma geração (9 passos), não pela capacidade de paralelizar requests HTTP.
- **`diffusers` fixado no HEAD do git, não numa release do PyPI** — decisão deliberada porque o
  suporte à classe `ZImagePipeline` é recente demais para ter chegado numa release estável no
  momento em que isso foi escrito. Consequência prática: um `docker compose build` pode trazer
  mudanças de comportamento do `diffusers` sem que o `pyproject.toml`/`uv.lock` do repo tenham
  mudado (o "HEAD" de hoje não é o "HEAD" de amanhã) — se algo quebrar depois de um rebuild sem
  mudança de código local, checar primeiro se o `diffusers` avançou.
- **`guidance_scale=0.0` e `steps=9` não são "valores default ajustáveis à vontade"** — são
  requisitos do modelo Turbo/destilado; mudar isso sem entender a distilação do modelo tende a
  piorar drasticamente a qualidade, não é um dial de "mais qualidade = mais steps" como em modelos
  não destilados.
- **`cpu_offload` não é uma opção válida hoje** com o pipeline quantizado (erro de "meta tensor" no
  `diffusers` atual) — se a VRAM disponível mudar (GPU diferente, ou o whisper voltar a competir
  pela mesma GPU), a solução não é simplesmente ligar offload; é revisitar a estratégia de memória
  como um todo.
- **`aspect_ratio` desconhecido cai silenciosamente no tamanho default** (`768×1344`) — não há
  erro de validação se o chamador mandar um valor fora do enum esperado; útil saber ao debugar
  "por que a imagem saiu no formato errado".

## Referências para aprofundar

- [Hugging Face Diffusers — documentação](https://huggingface.co/docs/diffusers/index)
- [Modelo Z-Image-Turbo (model card, Hugging Face)](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo)
- [bitsandbytes — quantização 4-bit](https://huggingface.co/docs/bitsandbytes/main/en/index)
- [Diffusers — guia de quantização de pipelines](https://huggingface.co/docs/diffusers/main/en/quantization/overview)
