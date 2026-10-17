# Revisão Design Patterns — docker_ai_offline_models (verificação final)
Stack: Python (FastAPI via `platform_core`, pydantic, pytest) · Tipo: aplicação com camadas (domain/application/infra/interfaces) · Alcance: projeto inteiro (sem venv/, docs/, .vscode/, revisao/) · ~25 arquivos de código relidos nos pontos afetados (testes por amostragem)
Curso: não é projeto de estudo · Carimbo: 2026-10-16_12-53-17

## Resumo
O projeto segue com Strategy/Adapter via ports ABC, Registry + Factory por nome e fábricas injetadas nos adapters (`pipeline_factory`, `model_factory`, `communicate_factory`). Desde a revisão anterior, o adapter do whisper foi renomeado (DP-4) e ganhou `model_factory` com default isolado (SOLID-6), então o Z-Image é agora o único adapter que constrói a dependência pesada inline (DP-6). O ponto mais importante continua igual: o `MediaController` faz de Service Locator (DP-1), e os services finos seguem sem regra (DP-2). Nada de novo apareceu e nada regrediu.

Evolução vs. `2026-10-16_13-24-46-revisao-design-patterns.md`: **resolvido** DP-4 (commit 9d28b10; adapter agora é `FasterWhisperTranscriptProvider`, `transcript_provider_factory.py:13`, `transcribe_service.py:48`). **Mantidos, mesmos IDs:** DP-1, DP-2, DP-3, DP-5, DP-6, DP-7, DP-8, DP-9, DP-10. **Novo:** nenhum. Menor mudança de contexto: DP-6 ficou mais evidente porque o whisper agora usa `_default_model_factory` (`transcribe_service.py:40,58`). Resquício do DP-4: o módulo ainda se chama `transcribe_service.py` (nome de arquivo, fora do tema; ver DDD).

## Padrões em uso
| Padrão | Categoria | Onde | O que resolve aqui | Vale a pena? | Custo |
|---|---|---|---|---|---|
| Strategy (via port ABC) | GoF comportamental | `domain/ports/{tts,image,transcript}_provider.py` | Troca edge-tts/Gemini/Z-Image/whisper sem mexer em quem usa | ✅ TTS (2 impls); ⚠️ imagem e transcrição (1 impl, mas o port serve de mock e a troca de engine é objetivo declarado) | Baixo |
| Adapter | GoF estrutural | `infra/external/*` (Edge, Gemini, ZImage, `FasterWhisperTranscriptProvider`) | Isola SDKs/REST atrás do contrato do domínio | ✅ (nomes agora consistentes) | Baixo |
| Registry + Factory (por nome) | Arquitetura | `infra/providers/provider_registry.py`, `tts/image *_provider_factory.py` | Escolhe a implementação pelo `config.json` | ✅ | Baixo |
| Factory simples (função) | Arquitetura | `transcript_provider_factory.py:13-22` | Monta o único adapter a partir de `settings` | ✅ (sem registry, YAGNI correto com 1 engine) | Mínimo |
| Dependency Injection (construtor) | Arquitetura | `TtsService(provider)`, `ImageService(provider)`, adapters com `*_factory` | Testabilidade com fakes | ✅ nos services/adapters; ❌ no caminho de produção do controller (DP-1) | — |
| Service Locator disfarçado | anti-padrão | `media_controller.py:41-69` | Cria dependências sob demanda | ❌ | Esconde dependências, acopla interface à infra |
| Use Case / Application Service (delegador) | Arquitetura | `application/services/media/{tts,image}/*_service.py` | Em tese, orquestrar | ⚠️ só repassa a chamada (DP-2) | 2 arquivos + 2 testes sem regra |
| Value Object / DTO | DDD | `ImageResult`, `TtsResult`, `TranscriptResult`, `WordTiming`, `schemas.py` | Contratos imutáveis entre camadas e na borda | ✅ | Baixo |
| Lazy Initialization | Idioma | `ZImageProvider._load_pipe`, factory de transcrição, edge_tts | Evita carregar torch/whisper no container errado | ✅ | Imports espalhados, justificados por `APP_ROLE` |
| Singleton (instância de módulo) | GoF criacional (idiomático) | `config.py` `settings` | Config única | ✅ (DP-3 sobre as chaves Google) | Baixo |
| Facade de rotas | Estrutural | `interfaces/http/routes.py`, `media_routes.py` | Agrega registro de rotas por `APP_ROLE` | ✅ | Baixo |
| Re-export de compatibilidade | — | `route_register_fast_api.py` | Mantém import antigo | ⚠️ shim (DP-9) | Mínimo |
| Template Method / Decorator GoF | — | não encontrados (`@dataclass`, `@abstractmethod` são de linguagem) | — | — | — |

## Achados detalhados

### 🟠 DP-1 [mal aplicado] Dependency Injection / Service Locator — `src/interfaces/http/media/media_controller.py:31-69`, `media_routes.py:10`
**O quê:** `MediaRoutes` faz `MediaController()` sem argumentos e o controller resolve `tts_service`, `transcribe_service` e `image_service` por `property` com lazy-import da application e das factories da infra (comentário nas linhas 38-40 admite ser provisório). `transcribe_service` guarda um `TranscriptProvider` direto, então os três têm formas diferentes.
**Por quê:** DI é receber as dependências prontas; aqui a interface *busca* o que precisa (Service Locator).
**E daí:** a dependência concreta some da assinatura, o controller importa a infra e o lazy-import por `APP_ROLE` fica espalhado.
**Como resolver:** composition root (`build_media_controller(role)` em `src/app.py` ou `composition.py`) que monta só os services do role e os injeta; o controller recebe tudo no `__init__`, sem properties.
```python
def build_media_controller(role: str) -> MediaController:
    tts = TtsService(build_tts_provider()) if role in ("media", "all") else None
    return MediaController(tts_service=tts, ...)
```
**Esforço:** M (depende do DDD-3, ainda pendente)
**📚** `13 - Tecnologia/02. Code Design …/02. Design Patterns (GoF)/Design Patterns/Dependency Injection.md`

### 🟡 DP-2 [prematuro] Use Case / Application Service — `tts_service.py:13-20`, `image_service.py:13-27`
**O quê:** `synthesize` e `generate` só repassam ao provider; enquanto isso o controller guarda lógica de caso de uso (gravar upload, `to_thread`, `media_controller.py:121-136`).
**Por quê:** camada só se paga quando concentra regra (YAGNI).
**E daí:** indireção sem ganho; lógica de caso de uso na borda HTTP.
**Como resolver:** (a) mover para os services o que é caso de uso e criar o de transcrição, ou (b) injetar o provider direto até haver regra. Recomendo (a), junto com DP-1.
**Esforço:** P
**📚** sem anotação sobre Use Case/Interactor; skill `tec-arquitetura`.

### 🟡 DP-3 [mal aplicado] Estado global escondido — `src/config.py`, `google_api_keys.py`, `gemini_tts_provider.py:25,53`
**O quê:** `google_api_keys` lê `os.environ`/`apis.json` a cada `synthesize` e o adapter (infra) importa da application (`gemini_tts_provider.py:25`), sentido invertido.
**Por quê:** Singleton saudável é leitura imutável; aqui a dependência de chaves é implícita.
**E daí:** teste do provider exige monkeypatch de env/JSON; dois leitores de chaves com regras sobrepostas.
**Como resolver:** `api_keys_provider: Callable[[], list[str]]` no construtor (função injetada = Strategy idiomático), default montado pela factory; mover `google_api_keys.py` para a infra.
**Esforço:** P
**📚** `…/Design Patterns/Creational Patterns/Singleton/Singleton.md`

### 🟡 DP-5 [oportunidade] Strategy (função) — retry do Gemini — `gemini_tts_provider.py:69-106`
**O quê:** `synthesize` mistura payload, rotação de chaves, retry/backoff, classificação de erro e `print` em dois `for` aninhados.
**Por quê:** cada regra nova de erro entra no meio do loop.
**E daí:** difícil testar cada decisão isolada.
**Como resolver:** extrair `_classify(resp)` e `_post_with_retry(...)`; só criar `RetryPolicy` injetável se surgir segundo provider com a mesma política.
**Esforço:** P · **Ganho:** testes pequenos por classe de erro.
**📚** `…/03. Comportamentais …/Teoria 01 - Strategy - trocando o algoritmo em tempo de execução.md`

### 🟡 DP-6 [oportunidade] Factory (função) — pipeline do Z-Image — `z_image_provider.py:55-100`
**O quê:** `_load_pipe` constrói inline o pipeline real (quantização, dtype, offload em 3 modos), e `pipeline_factory` só cobre o teste. O whisper agora tem `_default_model_factory` (`transcribe_service.py:40`), então o Z-Image ficou como exceção.
**Por quê:** um só jeito de criar dependência pesada nos adapters.
**E daí:** `_load_pipe` mistura cache, lock e construção.
**Como resolver:** extrair `_default_pipeline_factory(config)` e usar `self._pipeline_factory or _default_pipeline_factory`. Builder desnecessário. Cuidado: caminho de GPU não é coberto por testes aqui; validar em ambiente com GPU.
**Esforço:** P
**📚** `…/01. Criacionais …/Teoria 01 - Factory Method ….md`

### 🟡 DP-7 [oportunidade] Decorator (de função) — erros no controller — `media_controller.py:72-140`
**O quê:** `tts`, `image` e `transcribe` repetem validar, `try`, converter exceção em `{"status": "error"}` + `print`; base64 também repete. Já há divergência: `transcribe` não trata `ValueError` à parte.
**Por quê:** mesma regra de borda 3 vezes.
**E daí:** mudar o contrato de erro exige 3 edições.
**Como resolver:** wrapper `@handle_errors("tts")` (aqui o `@` aplica o Decorator GoF numa função). Não é Notification Pattern.
**Esforço:** P · Fazer depois do DP-1.
**📚** `…/02. Estruturais …/Teoria 02 - Decorator - adicionando comportamento sem herança.md`

## Outros achados
| ID | Tipo | Padrão | Gravidade | Arquivo |
|---|---|---|---|---|
| DP-8 | mal aplicado (código morto) | `FilesUtils` nunca usado; controller duplica upload em chunks | ⚪ | `src/utils/files.py:4`, `media_controller.py:123-132` |
| DP-9 | prematuro | `route_register_fast_api.py` é só re-export | ⚪ | `src/interfaces/http/route_register_fast_api.py` |
| DP-10 | observação | `srt_parser.py` só usado por testes; confirmar se é código morto | ⚪ | `src/infra/external/whisper/srt_parser.py` |

Contagem: 🔴 0 · 🟠 1 · 🟡 6 · ⚪ 3 (resolvido desde a anterior: DP-4).

## Glossário rápido dos padrões citados
| Padrão | Problema que resolve (1 frase) | 📚 anotação |
|---|---|---|
| Strategy | Trocar a implementação de um algoritmo sem mudar quem usa (em Python pode ser função) | `…/03. Comportamentais …/Teoria 01 - Strategy ….md` |
| Adapter | Fazer uma API externa caber na interface que o domínio espera | `…/02. Estruturais …/Teoria 01 - Adapter ….md` |
| Factory Method / Factory | Centralizar a decisão de qual classe instanciar | `…/01. Criacionais …/Teoria 01 - Factory Method ….md` |
| Registry | Mapa nome → classe para escolher implementação por configuração | sem anotação |
| Dependency Injection | Receber as dependências prontas em vez de buscá-las | `…/Design Patterns/Dependency Injection.md` |
| Service Locator | (anti-padrão) buscar dependências de dentro da classe | sem anotação |
| Singleton | Instância única; em Python o módulo já faz isso | `…/Creational Patterns/Singleton/Singleton.md` |
| Decorator (GoF) | Adicionar comportamento em volta de um objeto/função sem herança | `…/02. Estruturais …/Teoria 02 - Decorator ….md` |
| Value Object / DTO | Objeto imutável por valor / objeto só para transportar dados | ver `tec-ddd` |

## Próximos passos (ordem sugerida)
1. DP-6 — padronizar criação de dependência pesada (barato; validar com GPU).
2. DP-3 — injetar a fonte de chaves no Gemini (resolve inversão infra → application).
3. DP-1 — composition root por `APP_ROLE` (é o DDD-3 pendente).
4. DP-2 — decidir o futuro dos services finos junto com o DP-1.
5. DP-7 — wrapper de erro no controller (depois do DP-1).
6. DP-5 — enxugar o retry do Gemini ao mexer no arquivo.
Para aplicar: peça ao refatorador de design patterns "aplicar DP-6 e DP-3".

## Anotações a criar
- Registry (nome → classe) como padrão de escolha por configuração.
- Service Locator e por que é o oposto da DI.
- Composition Root.
- Strategy/Decorator como função em Python (formas idiomáticas).
- Use Case/Interactor e quando uma camada fina é YAGNI.
