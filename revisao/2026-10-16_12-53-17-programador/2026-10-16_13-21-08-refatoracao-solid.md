# Refatoração solid — docker_ai_offline_models — 2026-10-16_12-53-17
Relatório da revisão: `revisao/2026-10-16_12-53-17-programador/2026-10-16_13-17-46-revisao-solid.md` · Commit base: 2ce822f (já com 4 commits do DDD) · Stack: Python 3.12, FastAPI, pydantic, pytest · Itens pedidos: SOLID-5, SOLID-6 · Testes antes: 109 ✅ / 0 ❌ → depois: 115 ✅ / 0 ❌ (rodados com `venv/Scripts/python.exe -m pytest`; `uv` e ruff indisponíveis) · Tipos/lint: não há type checker/ruff instalado no ambiente.

## Aplicados

### SOLID-5 Contrato de transcrição tipado (TranscriptResult) ✅
**Commit:** c9348db

**O problema:** `TranscriptProvider.transcribe` devolvia um `dict` cujas chaves só existiam no docstring. TTS e imagem já devolvem Value Objects frozen. Se um segundo adapter errasse uma chave, só se descobria em runtime no `model_validate` do controller (pós-condição do contrato LSP não verificável).

**Código anterior** — `src/domain/ports/transcript_provider.py:13-23`, `transcribe_service.py:75-106`
```python
def transcribe(self, audio_path: str, language: str | None = None) -> dict:
    """... Devolve ``{"words", "word_srt", "sentence_srt", "duration_s", "language"}``."""
...
words = [{"word": w.word.strip(), "start": ..., "end": ...} for ...]
return {"words": words, "word_srt": ..., "sentence_srt": ..., "duration_s": ..., "language": ...}
```
controller: `return TranscribeResponse.model_validate(result)`

**Código depois** — `transcript_provider.py`
```python
@dataclass(frozen=True)
class WordTiming:
    word: str; start: float; end: float

@dataclass(frozen=True)
class TranscriptResult:
    words: tuple[WordTiming, ...]
    word_srt: str; sentence_srt: str; duration_s: float
    language: str | None = None
```
adapter devolve `TranscriptResult(words=tuple(WordTiming(...)...), ...)`; controller: `TranscribeResponse.model_validate(asdict(result))`.

**Por que esta é a melhor forma:** mesmo molde de `TtsResult`/`ImageResult`: o tipo vira a pós-condição (LSP verificável e checável por type checker/IDE), imutável e comparável por valor. `asdict` na borda HTTP mantém o JSON idêntico (tupla vira lista). Alternativa descartada: TypedDict (não é imutável nem VO). Renomear `TranscribeService` para `...Provider` (sugestão da revisão) não foi feito: não era necessário e aumentaria o diff (YAGNI). Custo: uma conversão `asdict` no controller. Princípio: LSP/ISP ❌ → ✅ (contrato explícito).

**Testes:** adaptados `test_transcribe_service.py`, `test_transcript_provider.py`, `test_media_controller.py` (fake agora devolve `TranscriptResult`, e a resposta HTTP é checada incluindo `words`); novos: `TestResultadoTipado` (imutável, words em tupla) e `TestTranscriptResult` (VO). 111 ✅.

### SOLID-6 Adapter whisper com config injetada, model_factory e import lazy ✅
**Commit:** b3da808

**O problema:** o adapter lia `settings` globais, importava `faster_whisper` no topo do módulo (quebra em containers sem a lib) e injetava DLLs CUDA no `__init__`. Era o único adapter sem costura de teste (os outros têm `pipeline_factory`/`communicate_factory`); os testes patchavam o símbolo `WhisperModel` do módulo.

**Código anterior** — `transcribe_service.py:14-52`
```python
from faster_whisper import WhisperModel
from src.config import settings
...
def __init__(self, model_size=None, device=None, compute_type=None):
    self._inject_cuda_libraries()
    model_size = model_size or settings.whisper_model_size
    ...
    self.model = WhisperModel(model_size, device=device, compute_type=compute_type,
                              download_root=settings.whisper_download_root)
```
controller: `from ...whisper.transcribe_service import TranscribeService; TranscribeService()`

**Código depois**
```python
def __init__(self, config: dict | None = None, *, model_factory=None):
    config = config or {}
    ...
    factory = model_factory or _default_model_factory
    self.model = factory(model_size, device=device, compute_type=compute_type,
                         download_root=config.get("download_root", "./models"))

def _default_model_factory(model_size, **kwargs):
    _inject_cuda_libraries()
    from faster_whisper import WhisperModel   # lazy
    return WhisperModel(model_size, **kwargs)
```
Novo `src/infra/providers/transcript/transcript_provider_factory.py`: `build_transcript_provider(config=None)` monta o config dos `settings` e importa o adapter de forma lazy. O controller chama essa factory (também lazy), como já faz com TTS e imagem.

**Por que esta é a melhor forma:** DIP/consistência: o adapter só conhece o `config` recebido, e `settings` fica na factory (borda de composição). `faster_whisper` continua só sendo importado quando o modelo real é carregado, e o módulo do adapter não o importa no topo (há teste AST). Comportamento HTTP idêntico. ⚠️ Mudança sutil: `_inject_cuda_libraries` (agora função de módulo) só roda ao carregar o modelo real, não quando se injeta um `model_factory` (irrelevante em produção). A assinatura do construtor mudou (`model_size/device/compute_type` → `config`); o único chamador era o controller, atualizado. Não criei `config.json` para transcrição (YAGNI; os valores vêm de `settings`/env). Custo: mais um arquivo de factory.

**Testes:** reescritos `TestInit` e a fixture `service` (usam `model_factory` fake em vez de patch); novos: teste AST de que o módulo não importa `faster_whisper` no topo, `test_transcript_provider_factory.py` (2 testes) e `test_transcribe_service_vem_da_factory` no controller. 115 ✅.

## Não aplicados
| ID | Motivo / decisão necessária |
|---|---|
| SOLID-1 | Sobrepõe DDD-3 (composition root/use cases), pendente do usuário. Decidir DDD-3 primeiro. |
| SOLID-2 | Sobrepõe DDD-2 (mover `google_api_keys`), pendente do usuário. |
| SOLID-3 | `ZImageProvider`: caminho de GPU/lock não testável aqui e alterado recentemente; risco alto. Decisão: o usuário aprova e valida em máquina com GPU. |
| SOLID-4 | Depende de SOLID-1 (mesmo controller). |
| SOLID-7 a SOLID-10 | Opcionais (⚪), não pedidos. |

## Arquivos movidos / criados / configs alteradas
| Ação | Caminho |
|---|---|
| Criado | `src/infra/providers/transcript/transcript_provider_factory.py` |
| Criado | `src/infra/providers/transcript/test_transcript_provider_factory.py` |
| Alterado | `src/domain/ports/transcript_provider.py`, `src/domain/ports/test_transcript_provider.py` |
| Alterado | `src/infra/external/whisper/transcribe_service.py`, `src/infra/external/whisper/test_transcribe_service.py` |
| Alterado | `src/interfaces/http/media/media_controller.py`, `src/interfaces/http/media/test_media_controller.py` |
| Configs | nenhuma |

## Fora do meu tema
- Comentário em `src/config.py:33` ainda cita `TranscribeService` (cosmético, inalterado).
- Controller ainda é composition root provisório (DDD-3, `refatorador-ddd`); `google_api_keys` na application (DDD-2).
- Os `print` de erro no controller e uploads nunca removidos (SOLID-4, pendente).
- Não há `src/infra/providers/transcript/__init__.py` (o projeto usa namespace packages, como as outras pastas de providers).

## Para você revisar
- `git diff --stat 2ce822f..HEAD` para ver o tamanho; `git show <hash>` mostra um item; `git revert <hash>` desfaz um item (quem roda é você).
- Commits desta etapa (nenhum push):
  | Commit | ID | Mensagem |
  |---|---|---|
  | c9348db | SOLID-5 | refactor(solid): SOLID-5 TranscriptResult tipado no port de transcricao |
  | b3da808 | SOLID-6 | refactor(solid): SOLID-6 adapter whisper recebe config e model_factory |
- Pontos para estudar: contrato tipado como pós-condição (LSP + VO); config injetada e factory como costura de teste (DIP); import lazy de dependência pesada.
