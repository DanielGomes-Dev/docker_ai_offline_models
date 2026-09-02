# Arquitetura Padrão — Microserviços Python

> Contrato de arquitetura para os 8 microserviços Python do workspace. Uma cópia deste arquivo
> vive na raiz de cada repo; a fonte de verdade é a da raiz do workspace
> (`Projects_Developer/ARQUITETURA_PADRAO.md`). O `CLAUDE.md` de cada repo aponta para cá.

## Serviços cobertos

| Serviço | pasta | slug canônico | papel |
|---|---|---|---|
| Video Orchestrator | `_shared/video_automation` | `video-orchestrator` | orquestra o pipeline de vídeo; dono do Postgres + filas BullMQ + workers |
| Video Worker | `_shared/video_worker` | `video-worker` | render pesado (ffmpeg/moviepy); 100% HTTP síncrono; GPU |
| Social Media Adapter | `_shared/social_media_adapter` | `social-media-adapter` | YouTube (yt-dlp) + TikTok (Selenium); 100% HTTP |
| Agents | `_shared/agents` | `agents` | flows de IA por domínio (chatbot, cortes, currículo, linkedin, ia_video) |
| LLM Adapter | `_shared/llm_adapter` | `llm-adapter` | gateway Gemini; `POST /agent/v1` |
| Chatbot Adapter | `_shared/chatbot_adapter` | `chatbot-adapter` | ponte WAHA/WhatsApp ↔ filas BullMQ |
| Resume Automation | `curriculo/curriculo_automation` | `curriculo-automation` | geração de currículo LaTeX/ATS |
| AI Inference | `_shared/docker_ai_offline_models` | `ai-inference` | TTS (edge-tts) + STT (faster-whisper) locais; GPU |

Fora deste contrato: `chatbot_orchestrator_kadabra` (NestJS), `chatbot_frontend_alakazam` (Next.js),
e os serviços de infra (`docker_redis`, `docker_postgresql`, `docker_bullboard`, `docker_waha`, `nginx`).

---

## 1. Estrutura de pastas padrão

```
<service>/
├─ pyproject.toml            # config ÚNICA: deps, dev-group, pytest, ruff, build-system, [tool.uv.sources]
├─ uv.lock                   # commitado
├─ Dockerfile                # multi-stage; SEM sufixo (.<name>)
├─ docker-compose.yml  .dockerignore  .gitignore  .env.example
├─ alembic/  alembic.ini     # SÓ serviços com ORM (hoje: só video_orchestrator)
├─ main.py                   # 2 linhas — ver §4
├─ platform_core/            # SUBMÓDULO git → biblioteca compartilhada; importa como `platform_core`
└─ src/
   ├─ app.py                 # create_app() factory. SEM efeito colateral no import.
   ├─ config.py              # pydantic-settings: env vars, URLs, dirs, timeouts, chaves
   ├─ interfaces/http/
   │  ├─ router.py           # build_routers(): lista EXPLÍCITA de feature-routers, sem entradas comentadas
   │  └─ <feature>/
   │     ├─ <feature>_controller.py   # request → usecase → schema Pydantic. FINO.
   │     ├─ <feature>_routes.py       # tabela de rotas (platform_core.http.RouteRegisterFastApi)
   │     ├─ schemas.py                # Request/Response Pydantic
   │     └─ test_<feature>_controller.py …
   ├─ application/usecases/<feature>/
   │  ├─ <verb>_<noun>.py             # 1 classe por fluxo; sufixo UseCase
   │  ├─ steps/                       # passos internos multi-step (era facades/ + components/)
   │  └─ test_*.py
   ├─ domain/                # Python PURO — sem I/O, sem ORM, sem FastAPI, sem httpx, sem bullmq
   │  ├─ <feature>/  entities.py  enums.py  value_objects.py  errors.py  services.py
   │  └─ ports/              # ABCs que a application depende (BaseAgent, BaseModel, TranscriptProvider, TtsProvider, …)
   ├─ infra/
   │  ├─ clients/  <service>_client.py    # HTTP client de saída; sufixo Client
   │  ├─ db/       base.py session.py models.py repositories.py   # re-export de platform_core.db + models locais
   │  ├─ queue/    queue_names.py          # re-export de platform_core.queue + nomes de fila e job-opts LOCAIS
   │  ├─ external/ ffmpeg/ moviepy/ whisper/ selenium/ gemini/ edge_tts/ yt_dlp/ waha/   # adapters de SDK/lib
   │  └─ storage/  <feature>_paths.py      # política de layout de FS local
   └─ workers/<queue>/
      ├─ worker.py           # build_worker() + process(); importa application+infra, NUNCA src/app.py
      └─ __main__.py         # entrypoint fino (era worker_<queue>.py na raiz)
```

### Decisões (uma por questão)

| Questão | Decisão | Motivo |
|---|---|---|
| `interfaces/api` vs `interfaces/http` | **`src/interfaces/http/`** | "api" colide com `infra/clients` (saída); "http" = adapter de entrada, sem ambiguidade |
| `infra/api` vs `infra/clients` | **`src/infra/clients/`**, classe sufixo `Client` | são clientes HTTP de saída p/ outros serviços |
| `facades/` | **fundir em `usecases/`**; passos internos → `usecases/<feature>/steps/` | "facade" aqui = use case multi-passo |
| `services/` pass-through (repassa 1 chamada HTTP, sem lógica) | **deletado** — o use case chama `infra/clients/` direto | |
| `services/` adapter de SDK/lib (ffmpeg, moviepy, whisper, selenium, gemini, edge-tts, yt-dlp, waha) | **`src/infra/external/<tool>/<name>_service.py`**, sufixo `Service` | é o `services/` legítimo |
| `contracts/` | **remover a pasta**. ABC de domínio → `src/domain/ports/`; `RouteRegisterInterface` → `platform_core.http` | |
| layer-first vs feature-first | **híbrido**: layer no topo, feature dentro de cada camada | |
| testes co-locados vs `tests/` espelhado | **co-locado `test_<name>.py`** irmão do fonte + `--import-mode=importlib` + `consider_namespace_packages=true` | `importlib` mode elimina a colisão de basename do pytest — os testes viram irmãos simples |
| worker entrypoints | `worker_<queue>.py` da raiz → `src/workers/<queue>/__main__.py` | |
| nome do pacote importável | **continua `src`** (todos já usam `from src.…`) | |

### Regras invioláveis

- `domain/` **nunca** importa `infra/`, `interfaces/`, FastAPI, SQLAlchemy, httpx, bullmq.
- Models ORM ficam em `infra/db/models.py` mas importam enums de `domain/<feature>/enums.py`.
- Controller retorna **schema Pydantic** (`XxxResponse`), nunca dict montado de linha ORM.
- `import src.app` (sem chamar `create_app()`), `import main`, `import src.*` — **não** registram
  rota, não abrem Redis/Postgres, não leem estado de arquivo, não fazem `print`.
- Workers têm `__main__` próprio e **nunca** importam `src/app.py`.

---

## 2. Biblioteca compartilhada — `platform_core`

**Consumo:** submódulo git (`github.com/DanielGomes-Dev/platform_core`) em `./platform_core/` dentro
de cada repo, instalado editable via `[tool.uv.sources]`. Import name = **`platform_core`**
(`platform` sozinho sombreia o módulo stdlib). Cada repo pina um SHA do submódulo = a "versão".
`platform_core.__version__` semver + `CHANGELOG.md`. Breaking change = bump minor + entrada no
CHANGELOG + PR em cada repo consumidor atualiza o SHA.

Fica dentro do build context do Docker (`context: .`) — `.dockerignore` **não** exclui `platform_core/`.
O `script_open_project` clona com `--recurse-submodules` e roda `git submodule update --init` no pull.

### Layout

```
platform_core/                      # raiz do repo/submódulo
├─ pyproject.toml                    # name="platform-core"
├─ CHANGELOG.md
└─ platform_core/
   ├─ __init__.py                    # __version__ = "x.y.z"
   ├─ http/       route_register.py  responses.py  app_factory.py
   ├─ files/      files_utils.py  markdown.py
   ├─ youtube/    errors.py  url.py
   ├─ db/         base.py  session.py
   ├─ queue/      bull_queue.py  dlq.py  run_job.py
   ├─ config/     env.py
   └─ testing/    fakes.py  db.py
```

### Módulos e API pública

| módulo | API | notas |
|---|---|---|
| `http/route_register.py` | `RouteRegisterFastApi`, `RouteRegisterInterface` | base = versão do `agents` (`_register_post/_get/_post_form/_post_file` + `_handle_response` + `_handle_route_exception`) **com `except HTTPException: raise` re-adicionado** + `POST_FILES` do `video_worker`; `execute(prefix, route, method, callback, *, compress=False, file=False)` + `operation_id`/`name` explícitos derivados de `method+full_route` |
| `http/responses.py` | `zip_and_download(path, filename)`, `file_response(path, media_type)` | `_compress` do video_orchestrator (RFC 5987 `filename*`, sanitização `re.sub`); **sem `time.sleep`** — zip via `anyio.to_thread.run_sync` |
| `http/app_factory.py` | `create_app(*, title, description, version, routers, lifespan=None)` | ver §4 |
| `files/files_utils.py` | `FilesUtils` | superset do video_orchestrator (168L); `save_upload_file(upload_file, output_dir, *, file_name=None, overwrite=False)`; retorno `{"status","path","name"}` |
| `files/markdown.py` | `save_object_as_md(obj, out_dir, filename=None, *, layout="flat")` | |
| `youtube/errors.py` | `YoutubeBlockedError`, `is_block_message`, `BLOCK_SIGNATURES` | |
| `youtube/url.py` | `extract_video_id(url)` | |
| `db/base.py` + `db/session.py` | `Base`, `get_engine/get_sessionmaker/session_scope/reset_engine/create_all/get_database_url` | do video_orchestrator verbatim |
| `queue/bull_queue.py` | `get_queue/make_worker/close_queues/get_redis_url/get_queue_prefix` | |
| `queue/dlq.py` | `push_to_dlq(*, stage, original, error, reason_code="max_attempts")` | os `STAGE_*` ficam **por-serviço** |
| `queue/run_job.py` | `run_job(queue_name, name, payload, job_opts=None, *, poll_interval=3.0, timeout=1800.0)` | |
| `config/env.py` | `env_str/env_int/env_float/env_bool` | |
| `testing/fakes.py` | `install_fakes(mapping)` | generaliza `video_worker/tests_support/fakes.py` |
| `testing/db.py` | fixtures `db_session`, `db_sessionmaker` | reuso via `pytest_plugins = ["platform_core.testing.db"]` |

### Fica FORA (sempre por-serviço)

Nomes de fila + job-opts (`src/infra/queue/queue_names.py`); `config.py`/settings; domínio;
controllers; use cases; models ORM; workers; `Dockerfile`; `docker-compose.yml`; `.env`;
Alembic (só video_orchestrator).

---

## 3. `pyproject.toml` como config única

`pytest.ini` é **deletado** no mesmo commit que adiciona `[tool.pytest.ini_options]` (o `pytest.ini`
ganha silenciosamente do pyproject). `conftest.py` só para fixtures / `pytest_plugins`.

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "<slug-canônico>"              # video-orchestrator, video-worker, social-media-adapter, ...
version = "0.1.0"
requires-python = ">=3.12,<3.13"      # toda imagem Docker é 3.12
dependencies = [ "platform-core", ... ]

[tool.hatch.build.targets.wheel]
packages = ["src"]

[dependency-groups]
dev = ["pytest", "pytest-asyncio", "pytest-cov", "ruff", "aiosqlite"]

[tool.pytest.ini_options]
addopts = "-ra -q --import-mode=importlib"
testpaths = ["src"]
python_files = ["test_*.py"]
asyncio_mode = "auto"
pythonpath = ["."]
consider_namespace_packages = true

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "platform_core"]
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "PL", "RUF"]
ignore = ["PLR0913"]
[tool.ruff.lint.isort]
known-first-party = ["src", "platform_core"]
[tool.ruff.format]
quote-style = "double"

[tool.uv.sources]
platform_core = { path = "platform_core", editable = true }
```

**Lock:** `uv` + `uv.lock` commitado. Dockerfile: `uv sync --frozen --no-dev`.
`requirements.txt` **removido do git + gitignore** em todos. Python padronizado em **3.12**.

---

## 4. `main.py` / `create_app()` / config

- `src/app.py`:
  ```python
  from platform_core.http import create_app as _base
  from src.interfaces.http.router import build_routers
  from src.config import settings

  def create_app():
      return _base(
          title=settings.app_title,
          description=settings.app_description,
          version=settings.app_version,
          routers=build_routers(),
          lifespan=...,   # fecha filas + engine.dispose() quando o serviço declara
      )
  ```
- `main.py` (2 linhas EXATAS em todos):
  ```python
  from src.app import create_app
  app = create_app()
  ```
- **Nenhum `main()` no nível de módulo.** Importar `main`/`src.*` não registra rota nem toca Redis/Postgres.
- `src/config.py` — `pydantic-settings`. Absorve validação de env obrigatória (falta de env →
  `ValidationError` no `create_app()`, **não** `sys.exit(1)` no import), chaves de API, cookies,
  timeouts, diretórios. Nada de segredo hardcoded em código.
- Workers têm `src/workers/<queue>/__main__.py`, nunca importam `src/app.py`.

### Títulos Swagger (por serviço)

`Video Orchestrator API` · `Video Worker API` · `Social Media Adapter API` · `Agents API` ·
`LLM Adapter API` · `Chatbot Adapter API` · `Resume Automation API` · `AI Inference API`.
Todos com `description` e `version` reais.

---

## 5. Docker

Um `Dockerfile` por repo (sem sufixo). Multi-stage `base` → `deps` → `runtime`; `deps` chaveado só
em `pyproject.toml` + `uv.lock` + `platform_core/`; `uv sync --frozen --no-dev`; sem
`pip-tools`/`pip-compile` no build. `CMD` de produção **sem `--reload`** (dev = `command:` override
no compose).

`.dockerignore` padrão:
```
.git .venv venv __pycache__ *.pyc .pytest_cache .ruff_cache files/ videos/ *.mp4 *.webm *.mkv *.mp3 *.wav .env *.md tests/
```

2 desvios legítimos, confinados ao stage `base`, marcados `# workspace-standard deviation: <motivo>`:
- **`video-worker` + `ai-inference` (CUDA):** base `nvidia/cuda:...` via build-arg + `apt` python3.12 + FFmpeg.
- **`social-media-adapter` (ffmpeg):** `apt-get install -y ffmpeg ca-certificates`.

---

## 6. Convenções de nome

| Tipo | Regra | Exemplo |
|---|---|---|
| Módulo | `snake_case.py`, inglês, **sem underscore inicial** | `cut_creator.py` |
| Classe | `PascalCase`, nunca `snake_Case` nem `Prefixo_Palavra` | `CreateAgentUseCase` (não `Create_Agent_UseCase`) |
| HTTP entrada | `<feature>_controller.py`, `<feature>_routes.py`, `schemas.py` | |
| Use case | arquivo `<verb>_<noun>.py` (sem sufixo `_usecase`); classe sufixo `UseCase` | `create_batch.py` → `CreateBatchUseCase` |
| Passo interno multi-step | `usecases/<feature>/steps/<verb>_<noun>.py` | (era `facades/.../components/`) |
| Domínio | `entities.py`, `enums.py`, `errors.py`, `value_objects.py`, `services.py` | |
| Port (ABC) | `src/domain/ports/<name>.py`; classe prefixo `Base` | `BaseModel`, `BaseAgent` |
| Cliente HTTP de saída | `<service>_client.py`; classe sufixo `Client` | `nginx_client.py` → `NginxClient` |
| Adapter de SDK/lib | `src/infra/external/<tool>/<name>_service.py`; sufixo `Service` | `FfmpegService` |
| Repositório | `<feature>_repository.py`; sufixo `Repository` | `TranscriptBatchRepository` |
| Worker | `src/workers/<queue>/worker.py`; sufixo `Worker` | |
| Pydantic | `XxxRequest` / `XxxResponse` em `schemas.py` | |
| Teste | `test_<module>.py` co-locado | |
| Arquivo de classe | `snake_case` mesmo quando é 1 classe só | `base_agent.py` (não `BaseAgentFacade.py`) |
| Rede Docker | `app-network-<slug>` (exceções legadas toleradas: `app-network-llm`, `app-network-ai`, `app-network-video-orchestrator`) | |
| Env var de serviço | `APP_<SLUG_MAIÚSCULO>_{HOST,PORT,URL}` | `APP_AGENTS_URL`, `APP_LLM_ADAPTER_URL` |
| Dockerfile | `Dockerfile` (sem sufixo) | |

### Traduções PT→EN (piores casos)

| Atual | Alvo |
|---|---|
| `social_midia_manager` / `social-midia-manager` / `automacoes-social-midia-manager` | `social-media-adapter` (folder/service/image/pyproject/env) |
| `SocialMidiaManagerApi` | `SocialMediaAdapterClient` |
| `Nginx_API` / `nginx_api.py` | `NginxClient` / `nginx_client.py` |
| `ChaBotController` / `chat_bot_controller.py` | `ChatBotController` / `chatbot_controller.py` |
| `Create_Agent_UseCase` | `CreateAgentUseCase` |
| `GerarCurriculoLaterAts` / `gerar_curriculo_latex_ats` | `GenerateLatexAtsResume` / `generate_latex_ats_resume.py` |
| `AgentAutoAprimoravelFacade` | (código morto — deletar) |
| `criador_de_cortes` / `CriadorDeCorte` / `criador_de_cortes_para_videos_curtos_facade` | `usecases/cut_creator/create_cuts.py` / `CreateCutsUseCase` |
| `dividir_transcricao` / `extrair_cuts` | `steps/split_transcript.py` / `steps/extract_cuts.py` |
| `criador_curriculo` / `adaptar_info_vaga` | `usecases/resume_builder/build_resume.py` / `steps/adapt_job_info.py` |
| `criar_conteudo_linkedin` / `gerar_conteudo_linkedin` | `create_linkedin_content.py` / `steps/generate_linkedin_content.py` |
| `atendimento_chatbot` / `responder_mensagem` | `usecases/support_chatbot/reply_message.py` |
| `gerar_insight` / `analisar_conversa` | `usecases/insights/generate_insight.py` / `steps/analyze_conversation.py` |
| `gerar_roteiro` / `gerar_prompts_imagens` | `usecases/ai_video/generate_script.py` / `generate_image_prompts.py` |
| `analista_conteudo` / `analise_pratica` | (código morto — deletar) |
| `BaseAgentFacade.py` | `base_agent.py` / `BaseAgent` |
| `src/utils/_dict_to_md.py … _zip_folder.py` (7, agents) | `platform_core.files` / `platform_core.http.responses` |
| `salvar_objeto_como_md` / `verificar_variaveis_obrigatorias` | `save_object_as_md` / dissolvido em `config.py` |
| `AgenteController` / `AgenteRoutes` (curriculo) | `AgentController` / `AgentRoutes` |
| `usecase` / `usecases` / `agente` / `agentes` misto | dir sempre `usecases/` e `agents/`; classe sufixo `UseCase` |
| `FileUsecase` | `FileUseCase` |
| params `pipeVideo`, `titulo`, `fonte`, `canal`, `transcricao_txt`, `descricao`, `horarios`, `url_canal`, `url_video`, `nome_arquivo`, `vaga`, `mensagem`, `historico`, `contexto_adicional`, `pergunta`, `tema`, `roteiro`, `duracao_alvo_s`, `idioma`, `segundos_por_imagem`, `estilo` | `video_pipeline`, `title`, `source`, `channel`, `transcript_txt`, `description`, `schedule_times`, `channel_url`, `video_url`, `file_name`, `job_posting`, `message`, `history`, `extra_context`, `question`, `topic`, `script`, `target_duration_s`, `language`, `seconds_per_image`, `style` |
| colunas ORM PT (`tema`, `idioma`, `duracao_alvo_s`, `roteiro_text`, `estilo`, `segundos_por_imagem`) | inglês + migration Alembic |
| `ClassVideo` / `class_video.py` / `videos_youtube.json` | `youtube_channel.py` / `youtube_channels.json` (migrado p/ `config.py`/`.env`) |
| `title="Exemplo Classe Controller"` | título real por serviço (§4) |
| `Dockerfile.<name>` | `Dockerfile` |

### Rotas HTTP (contrato — renomeadas em bloco com kadabra + frontend)

| Antes | Depois |
|---|---|
| `POST /agente/chatbot/responder` | `POST /agent/chatbot/reply` |
| `POST /agente/chatbot/insight` | `POST /agent/chatbot/insight` |
| `POST /agente/gerador/curriculo` | `POST /agent/generator/resume` |
| `POST /agente/gerador/cortes` | `POST /agent/generator/cuts` |
| `POST /agente/gerador/conteudo/linkedin` | `POST /agent/generator/content/linkedin` |
| `POST /agente/ia-video/roteiro` | `POST /agent/ai-video/script` |
| `POST /agente/ia-video/prompts-imagens` | `POST /agent/ai-video/image-prompts` |
| `GET /youtube/metadados` (SMA) | `GET /youtube/metadata` |
| `POST /video-generator/cortes` (video-worker) | `POST /video-generator/cuts` |
| `POST /curriculo/vaga` (curriculo) | `POST /resume/job` |

Docstrings/comentários em PT podem ficar; traduz oportunisticamente quando o arquivo é tocado.
**Identificadores, nomes de arquivo e rotas = inglês.**

---

## 7. Testes

- Runner único: **pytest** (`unittest` sai de `agents`, `llm-adapter`, `chatbot-adapter`).
- Co-locado `test_<module>.py` irmão do fonte. `tests/` espelhado é dissolvido.
- `--import-mode=importlib` + `consider_namespace_packages=true` → sem colisão de basename;
  não precisa mais de `test_x/test_x.py`.
- Fixtures de DB: `pytest_plugins = ["platform_core.testing.db"]`.
- Fakes de deps pesadas (moviepy, faster-whisper, edge-tts): `platform_core.testing.fakes.install_fakes`.
- **Baseline antes de qualquer refactor por repo:** salvar `pytest --co -q` + resumo pass/fail fora
  do repo. Refactor não reduz PASS nem aumenta FAIL.

---

## 8. Ordem de migração

`platform_core` (repo novo + submódulo + `script_open_project`) → mini-rodadas de rename cross-repo
→ **video_orchestrator** (referência) → video-worker → social-media-adapter → llm-adapter →
**agents** (+ rename de rotas coordenado) → chatbot-adapter → curriculo-automation → ai-inference.

Ver `~/.claude/plans/vamos-voltar-ao-plano-declarative-piglet.md` para o detalhe de cada rodada.
