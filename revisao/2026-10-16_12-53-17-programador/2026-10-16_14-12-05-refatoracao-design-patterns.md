# Refatoração design-patterns — docker_ai_offline_models — 2026-10-16_12-53-17
Relatório da revisão: `revisao/2026-10-16_12-53-17-programador/2026-10-16_13-24-46-revisao-design-patterns.md` · Commit base: 2ce822f · Stack: Python/pytest · Itens pedidos: DP-4 · Testes antes: 115 ✅ / 0 ❌ → depois: 115 ✅ / 0 ❌ · Tipos/lint: não há checagem configurada

## Aplicados
### DP-4 Adapter com nome de application service ✅
**O problema:** o adapter do faster-whisper (infra) se chamava `TranscribeService`, nome de camada application, mas implementa o port `TranscriptProvider`. Quem lê procura o service na application e o acha na infra; o nome também destoa de `EdgeTtsProvider`, `GeminiTtsProvider`, `ZImageProvider`.

**Código anterior** — `src/infra/external/whisper/transcribe_service.py:48` e `src/infra/providers/transcript/transcript_provider_factory.py:20-22`
```python
class TranscribeService(TranscriptProvider):
    ...
    from src.infra.external.whisper.transcribe_service import TranscribeService
    return TranscribeService(config)
```

**Código depois** — mesmos arquivos
```python
class FasterWhisperTranscriptProvider(TranscriptProvider):
    ...
    from src.infra.external.whisper.transcribe_service import FasterWhisperTranscriptProvider
    return FasterWhisperTranscriptProvider(config)
```
Também atualizados: comentário em `src/config.py:33` e os testes `test_transcribe_service.py` e `test_transcript_provider_factory.py` (inclusive o path do `patch`).

**Por que esta é a melhor forma:** Adapter nomeado pelo papel/tecnologia (`<Engine>TranscriptProvider`), igual aos outros providers. Problema que resolve: confusão de camada ao ler. Custo: nenhum em runtime; só o nome do módulo `transcribe_service.py` ainda destoa. Não renomeei o arquivo para manter o diff mínimo e o patch dos testes estável (decisão sua: `git mv` para `faster_whisper_transcript_provider.py`). Passar a factory pelo registry (`TRANSCRIPT_PROVIDERS`) foi descartado: só há uma engine (YAGNI, como a própria revisão diz). `name = "faster_whisper"` e o import lazy dentro da função foram preservados, então `faster_whisper` continua fora do topo de módulos carregados pelo container de imagem. Sem mudança de comportamento.
**Testes:** os testes existentes foram adaptados ao novo nome; suíte completa 115 ✅.
📚 Factory Method / Adapter (`02. Design Patterns (GoF)/02. Estruturais …/Teoria 01 - Adapter …`)

## Não aplicados
| ID | Motivo / decisão necessária |
|---|---|
| DP-6 | Caminho de GPU/lock do Z-Image não testável aqui; pendente de decisão/validação sua em ambiente com GPU. |
| DP-3 | Depende da decisão DDD-2/DDD-3 (onde fica `google_api_keys`). |
| DP-1 | Depende do DDD-3 (composition root por APP_ROLE). |
| DP-2 | Decidir junto com o DP-1 (manter services finos ou injetar provider direto). |
| DP-5, DP-7 | Adiados para depois do DP-1 (evitar editar duas vezes). |
| DP-8, DP-9, DP-10 | ⚪ opcionais, não pedidos. |

## Arquivos movidos / criados / configs alteradas
| Ação | Caminho |
|---|---|
| Alterado | src/config.py (só comentário) |
| Alterado | src/infra/external/whisper/transcribe_service.py |
| Alterado | src/infra/external/whisper/test_transcribe_service.py |
| Alterado | src/infra/providers/transcript/transcript_provider_factory.py |
| Alterado | src/infra/providers/transcript/test_transcript_provider_factory.py |

## Fora do meu tema
- Nome do módulo `transcribe_service.py` e do teste `test_transcribe_service.py` ainda usam "service" (renomear arquivo é mover/estrutura: `refatorador-ddd`, se quiser).

## Para você revisar
- Commits (sem push):
  | Commit | ID | Mensagem |
  |---|---|---|
  | 9d28b10 | DP-4 | refactor(design-patterns): DP-4 renomeia adapter para FasterWhisperTranscriptProvider |
- `git log --oneline 2ce822f..HEAD`; `git show 9d28b10`; `git revert 9d28b10` desfaz.
- Pontos para estudar: nomear adapters pelo papel; YAGNI em Registry com uma só implementação.
