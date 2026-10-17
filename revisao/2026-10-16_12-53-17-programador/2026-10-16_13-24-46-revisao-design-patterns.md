# Revisão Design Patterns — docker_ai_offline_models
Stack: Python (FastAPI via `platform_core`, pydantic, pytest) · Tipo: aplicação com camadas (domain/application/infra/interfaces) · Alcance: projeto inteiro (sem venv/, docs/, .vscode/, revisao/) · ~30 arquivos lidos (testes por amostragem)
Curso: não é projeto de estudo · Carimbo: 2026-10-16_12-53-17

## Resumo
O projeto usa bem os padrões que importam: Strategy/Adapter via ports ABC, Registry + Factory por nome vindo do `config.json`, Value Objects imutáveis e fábricas injetadas nos adapters (`pipeline_factory`, `model_factory`, `communicate_factory`) para testar sem GPU. O ponto fraco é a Dependency Injection incompleta: o `MediaController` faz de composition root e busca dependências por lazy-import (Service Locator disfarçado). Os services `TtsService`/`ImageService` são camadas finas sem comportamento próprio. Há oportunidades pequenas e concretas (retry do Gemini, erro repetido no controller).
Evolução: não há relatório de design patterns anterior. O DDD-5 (registry/factories em `infra/providers`) já trouxe o Registry/Factory atual; o DDD-3 (composition root por APP_ROLE) continua pendente e aparece aqui como DP-1.

## Padrões em uso
| Padrão | Categoria | Onde | O que resolve aqui | Vale a pena? | Custo |
|---|---|---|---|---|---|
| Strategy (via port ABC) | GoF comportamental | `domain/ports/{tts,image,transcript}_provider.py` | Troca edge-tts/Gemini/Z-Image/whisper sem mexer em quem usa | ✅ TTS (2 impls reais); ⚠️ imagem e transcrição (1 impl cada, mas a troca de engine é o objetivo declarado e o port serve de mock) | 1 arquivo por port, baixo |
| Adapter | GoF estrutural | `infra/external/*` (Edge, Gemini, ZImage, `TranscribeService`) | Isola SDKs/REST externos atrás do contrato do domínio | ✅ | Baixo; `TranscribeService` é adapter com nome de service (DP-4) |
| Registry + Factory (por nome) | Arquitetura | `infra/providers/provider_registry.py`, `*/*_provider_factory.py` | Escolhe a implementação pelo `config.json`; novo provider = classe + 1 linha | ✅ | Baixo; factory de transcrição não usa o registry (DP-4) |
| Dependency Injection (construtor) | Arquitetura | `TtsService(provider)`, `ImageService(provider)`, `MediaController(tts_service=...)` | Testabilidade com fakes | ✅ nos services; ❌ no caminho de produção do controller (DP-1) | — |
| Service Locator disfarçado | anti-padrão | `media_controller.py:41-69` | Cria dependências sob demanda | ❌ | Esconde dependências, acopla interface à infra |
| Use Case / Application Service (delegador) | Arquitetura | `application/services/media/{tts,image}/*_service.py` | Em tese, orquestrar o caso de uso | ⚠️ só repassa a chamada (DP-2) | 2 arquivos + 2 testes sem regra |
| Value Object / DTO | DDD | `ImageResult`, `TtsResult`, `TranscriptResult`, `WordTiming`, `schemas.py` | Contratos imutáveis entre camadas e na borda HTTP | ✅ | Baixo |
| Lazy Initialization | Idioma | `ZImageProvider._load_pipe`, `edge_tts` lazy, factory de transcrição | Evita carregar torch/whisper no container errado | ✅ | Imports espalhados, justificado por `config.py:21-22` |
| Singleton (instância de módulo) | GoF criacional (idiomático) | `config.py:59 settings` | Config única lida do env | ✅ para a config; ver DP-3 (leitura de env a cada acesso) | Baixo |
| Facade de rotas | Estrutural | `interfaces/http/routes.py`, `media_routes.py` | Agrega registro de rotas por `APP_ROLE` | ✅ | Baixo |
| Re-export de compatibilidade | — | `route_register_fast_api.py` | Mantém import antigo | ⚠️ não é padrão; shim de 1 linha | Mínimo |
| Template Method / Decorator GoF | — | não encontrados (`@dataclass` e `@abstractmethod` são de linguagem, não Decorator GoF) | — | — | — |

## Achados detalhados

### 🟠 DP-1 [mal aplicado] Dependency Injection / Service Locator — `src/interfaces/http/media/media_controller.py:31-69`, `media_routes.py:10`
**O quê:** `MediaRoutes` faz `MediaController()` sem argumentos, e o controller resolve `tts_service`, `transcribe_service` e `image_service` por `property` com lazy-import da application e das factories da infra. O comentário (linhas 38-40) já admite que é provisório. Além disso, `transcribe_service` guarda um `TranscriptProvider` direto (sem service), então os três "services" têm formas diferentes.
**Por quê:** DI é receber as dependências prontas; aqui a camada de interface *busca* o que precisa (Service Locator), conhece a infra e decide a construção. O construtor aceita injeção (tem o nome), mas o caminho real de produção não injeta nada.
**E daí:** a dependência concreta fica invisível na assinatura, o controller importa a infra, e o lazy-import por `APP_ROLE` fica espalhado em vez de num lugar só.
**Como resolver:** criar um composition root (`build_media_controller(role)` em `src/app.py` ou `composition.py`) que, conforme `settings.role`, monta só os services necessários e os injeta. O controller recebe tudo no `__init__`, sem properties. Os lazy-imports vão para dentro do root.
```python
def build_media_controller(role: str) -> MediaController:
    tts = TtsService(build_tts_provider()) if role in ("media", "all") else None
    ...
    return MediaController(tts_service=tts, transcribe_service=..., image_service=...)
```
**Esforço:** M (é o DDD-3 já pendente)
**📚** `13 - Tecnologia/02. Code Design …/02. Design Patterns (GoF)/Design Patterns/Dependency Injection.md`

### 🟡 DP-2 [prematuro] Use Case / Application Service — `application/services/media/tts/tts_service.py:13-20`, `image/image_service.py:13-27`
**O quê:** `TtsService.synthesize` e `ImageService.generate` só repassam a chamada ao provider com os mesmos argumentos. Não há regra, orquestração nem tradução de erro.
**Por quê:** uma camada só se paga quando concentra algo (validação, retry, métrica, composição). Hoje é indireção sem ganho (YAGNI), um Proxy sem comportamento.
**E daí:** 2 arquivos + 2 testes que testam o "repasse", um nível a mais de leitura; enquanto isso o controller ainda contém lógica que seria de um use case (upload, `to_thread` da transcrição).
**Como resolver:** escolher uma saída. (a) Manter por consistência com a arquitetura e mover para dentro deles o que é de caso de uso (validação de texto vazio hoje duplicada nos providers, gravação do upload, `to_thread`), criando também o `TranscribeService` de application. (b) Injetar o provider direto no controller e remover os services até haver regra real. Recomendo (a), alinhada ao DP-1/DDD-3.
**Esforço:** P
**📚** sem anotação específica sobre Use Case/Interactor; ver skill `tec-arquitetura` (Clean Architecture).

### 🟡 DP-3 [mal aplicado] Singleton/estado global escondido — `src/config.py:39-56`, `application/services/models/google_api_keys.py:16-51`, `gemini_tts_provider.py:25,53`
**O quê:** `settings` é instância de módulo (Singleton idiomático, bom), mas `google_api_keys` lê `os.environ` a cada acesso (estado global lido por fora do objeto). `available_api_keys()` ainda lê `apis.json` do disco a cada `synthesize`, e o `GeminiTtsProvider` (infra) importa essa função da *application* (infra → application, sentido invertido).
**Por quê:** Singleton é saudável como leitura imutável; aqui a dependência de chaves é implícita no adapter e só se troca em teste com monkeypatch.
**E daí:** teste do provider precisa mexer em env/JSON; dois leitores de chave (`settings.google_api_keys` e `apis.json`) com regras sobrepostas.
**Como resolver:** o provider recebe `api_keys_provider: Callable[[], list[str]]` no construtor (função injetada = Strategy idiomático), com default montado pela factory. Mover `google_api_keys.py` para a infra (ex.: `infra/external/gemini_tts/`).
**Esforço:** P
**📚** `…/Design Patterns/Creational Patterns/Singleton/Singleton.md`

### 🟡 DP-4 [mal aplicado] Factory/Adapter inconsistentes — `infra/providers/transcript/transcript_provider_factory.py:13-22`, `infra/external/whisper/transcribe_service.py:182`
**O quê:** `build_transcript_provider` não usa o registry (instancia o único adapter direto) e monta o `config` a partir de `settings`, enquanto TTS e imagem leem `config.json`. A classe adapter se chama `TranscribeService` (nome de application service) mas implementa `TranscriptProvider`.
**Por quê:** o Registry/Factory já existe e é bom; a transcrição tem só metade dele, e o nome do adapter confunde com a camada application.
**E daí:** quem lê procura `TranscribeService` na application e acha na infra; trocar de engine exige mexer num formato diferente dos outros.
**Como resolver:** renomear para `FasterWhisperTranscriptProvider` (mantendo `name`) e, só se entrar uma segunda engine, passar pelo `build_provider` com um `TRANSCRIPT_PROVIDERS`. Enquanto houver uma, o `if` simples está ok (YAGNI); basta o rename.
**Esforço:** P
**📚** `…/01. Criacionais - Factory Method, Abstract Factory, Builder/Teoria - passo a passo/Teoria 01 - Factory Method ….md`

### 🟡 DP-5 [oportunidade] Strategy (função) — retry do Gemini — `gemini_tts_provider.py:69-106`
**O quê:** `synthesize` mistura montagem do payload, rotação de chaves, retry com backoff, classificação de erro (cota/sobrecarga/definitivo) e `print`, em dois `for` aninhados com `break`/`continue`.
**Por quê:** a dor é real (cerca de 40 linhas com 3 níveis de decisão): cada nova regra de erro entra no meio do loop.
**E daí:** difícil testar cada decisão isolada; `print` no meio da política de retry.
**Como resolver:** sem hierarquia. Extrair `_classify(resp) -> "ok"|"quota"|"overloaded"|"fatal"` e `_post_with_retry(client, url, payload)`, deixando `synthesize` só com `for key in keys`. Se surgir um segundo provider com a mesma política, aí extrair uma `RetryPolicy` como função injetada.
**Esforço:** P · **Ganho:** testes pequenos por classe de erro, leitura linear.
**📚** `…/03. Comportamentais …/Teoria 01 - Strategy - trocando o algoritmo em tempo de execução.md`

### 🟡 DP-6 [oportunidade] Factory (função) — carga do pipeline do Z-Image — `infra/external/z_image/z_image_provider.py:55-100`
**O quê:** `_load_pipe` constrói inline o pipeline real (quantização, dtype, offload em 3 modos); `pipeline_factory` só é usado no caminho de teste. O whisper faz o contrário e melhor: `_default_model_factory` isolada (`transcribe_service.py:174`).
**Por quê:** ter um só jeito de criar dependência pesada nos adapters.
**E daí:** `_load_pipe` mistura cache, lock e construção.
**Como resolver:** extrair `_default_pipeline_factory(config)` e usar `self._pipeline_factory or _default_pipeline_factory`. Builder não é necessário: são parâmetros simples.
**Esforço:** P
**📚** `…/Teoria 01 - Factory Method ….md`

### 🟡 DP-7 [oportunidade] Decorator (de função) — erros no controller — `media_controller.py:72-140`
**O quê:** `tts`, `image` e `transcribe` repetem o esqueleto: validar com pydantic, `try`, converter exceção em `{"status": "error", ...}` + `print`. A conversão para base64 também se repete.
**Por quê:** mesma regra de borda repetida 3 vezes; o ponto central seria um wrapper/middleware de erro.
**E daí:** mudar o contrato de erro (usar logging, status HTTP) exige 3 edições, e já há divergência (`transcribe` não trata `ValueError` à parte).
**Como resolver:** um wrapper `@handle_errors("tts")` que captura e devolve o dict; o controller fica só com validação e chamada. Aqui o `@` é sintaxe de linguagem aplicando o Decorator GoF (comportamento em volta de uma função). Não é Notification Pattern: não há acúmulo de erros de validação.
**Esforço:** P
**📚** `…/02. Estruturais - Adapter, Decorator, Facade, Composite, Proxy/Teoria - passo a passo/Teoria 02 - Decorator - adicionando comportamento sem herança.md`

## Outros achados
| ID | Tipo | Padrão | Gravidade | Arquivo |
|---|---|---|---|---|
| DP-8 | mal aplicado (código morto) | `FilesUtils` nunca usado; o controller duplica o upload em chunks | ⚪ | `src/utils/files.py:4`, `media_controller.py:123-132` |
| DP-9 | prematuro | `route_register_fast_api.py` é só re-export; ok como shim, remover quando os imports forem atualizados | ⚪ | `src/interfaces/http/route_register_fast_api.py` |
| DP-10 | observação | `srt_parser.py` só é usado por testes; confirmar se é código morto | ⚪ | `src/infra/external/whisper/srt_parser.py` |

## Glossário rápido dos padrões citados
| Padrão | Problema que resolve (1 frase) | 📚 anotação |
|---|---|---|
| Strategy | Trocar a implementação de um algoritmo sem mudar quem usa (aqui os providers atrás dos ports; em Python pode ser uma função) | `…/03. Comportamentais …/Teoria 01 - Strategy ….md` |
| Adapter | Fazer uma API externa caber na interface que o domínio espera | `…/02. Estruturais …/Teoria 01 - Adapter ….md` |
| Factory Method / Factory | Centralizar a decisão de qual classe instanciar | `…/01. Criacionais …/Teoria 01 - Factory Method ….md` |
| Registry | Mapa nome → classe para escolher implementação por configuração | sem anotação |
| Dependency Injection | Receber as dependências prontas em vez de buscá-las ou criá-las | `…/Design Patterns/Dependency Injection.md` |
| Service Locator | (anti-padrão) buscar dependências de dentro da classe, escondendo o acoplamento | sem anotação |
| Singleton | Instância única; em Python o módulo já faz isso | `…/Creational Patterns/Singleton/Singleton.md` |
| Decorator (GoF) | Adicionar comportamento em volta de um objeto/função sem herança | `…/02. Estruturais …/Teoria 02 - Decorator ….md` |
| Value Object / DTO | Objeto imutável comparado por valor / objeto só para transportar dados | ver `tec-ddd` |

## Próximos passos (ordem sugerida)
1. DP-4 e DP-6 — renomear o adapter e padronizar a criação de dependência pesada (baratos, tiram inconsistência).
2. DP-3 — injetar a fonte de chaves no Gemini (resolve a inversão infra → application).
3. DP-1 — composition root por `APP_ROLE` (é o DDD-3 pendente; simplifica o resto).
4. DP-2 — decidir o futuro dos services finos junto com o DP-1.
5. DP-7 — wrapper de erro no controller (depois do DP-1 para não editar duas vezes).
6. DP-5 — enxugar o retry do Gemini quando for mexer no arquivo.
Para aplicar: peça ao refatorador de design patterns "aplicar DP-4 e DP-6".

## Anotações a criar
- Registry (nome → classe) como padrão de escolha por configuração.
- Service Locator e por que é o oposto da DI.
- Composition Root.
- Strategy/Decorator como função em Python (formas idiomáticas).
- Use Case/Interactor e quando uma camada fina é YAGNI.
