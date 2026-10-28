# UNDER TESTE — mapa de arquitetura (canónico)

**Base auditada:** `main` @ `4bbd70e` (27/10/2026, ~20:40 UTC). Este documento substitui, como referência de estrutura, as descrições espalhadas em `docs/MARKET-INTELLIGENCE.md` e no README. Nada foi apagado.

## 1. Fluxo

```
Cloudflare Cron (*/5) ──workflow_dispatch──┐
GitHub schedule (2-57/5, best effort) ─────┤
                                           ▼
                         collect.yml  ── H1 (produção, intocável) ─────────────► state.json · docs/data.json · Telegram bot
                           │  └─ ganchos sombra try/except (não bloqueiam H1)
                           │       shadow_formats → data/lab/formats-AAAA-MM.jsonl
                           │       market_v4      → data/lab/markets-AAAA-MM.jsonl
                           ▼ workflow_run (completed, main)
                         lab-v4-audit.yml  ── LAB (grupo de concorrência próprio)
                               v4_audit      → docs/lab/v4-audit.json + data/lab/v4-runchecks.jsonl
                               golden        → docs/lab/golden-candidates.json · golden-report.json
                               golden_priority → docs/lab/golden-priority.json
                               timeline      → docs/lab/match-trajectories.json   (PR lab/match-timeline)
results.yml (hora a hora, :41) ── H1 ──► data/results.csv · data/result_audit.json · docs/data.json
lab-ft-results.yml (:12, :42) ── LAB ──► data/lab/ft-ledger.json · docs/lab/ft-results.json
                                   └─ V5 (continue-on-error) pattern_engine → docs/lab/pattern-research.json
                                                                           → data/lab/pattern-registry.json (append-only)
```

## 2. Componentes e estado

| Componente | Ficheiros | Classe | Função | Observações |
| --- | --- | --- | --- | --- |
| Recolha + regra H1 | `h1lab/core.py`, `cli.py`, `session.py` | **Operacional (protegido)** | Parse legado, 1.º H1 por jogo, triplas FIFO | Não alterar |
| Notificação | `h1lab/notify.py`, `bot.py` | **Operacional (protegido)** | Envio das triplas | |
| Liquidação | `h1lab/results.py`, `bsd.py`, `results.yml` | **Operacional (protegido)** | FT via BSD + TheSportsDB | |
| Agendador | `scheduler/**` | **Operacional (protegido)** | Cloudflare Worker `*/5` | README interno desatualizado (ver §5) |
| Dashboard H1 | `docs/index.html`, `docs/data.json` | **Operacional (protegido)** | ROI singles/triplas | |
| Observador de formatos | `h1lab/shadow_formats.py` | Experimental ativo | Classes de linhas, sem texto | 2,2 KB/mensagem |
| Parser V4 | `h1lab/market_v4.py` | Experimental ativo | Total, AH, 1X2, disparo, janela | Fonte `V4_EXPLICIT` |
| Auditor V4 vs H1 | `h1lab/v4_audit.py`, `scripts/lab_v4_audit.py` | Experimental ativo | Cobertura, concordância, gates | Estado PENDING |
| Golden Set | `h1lab/golden.py`, `scripts/lab_golden.py`, `data/lab/golden/**` | Experimental ativo | Revisão humana por mensagem | NOT_CERTIFIED |
| Prioridades Golden | `h1lab/golden_priority.py` | Experimental ativo | Escolhe mensagens a rever | Não valida valores |
| Cronologia por jogo | `h1lab/timeline.py` | Experimental (nova) | Mensagem → snapshot → movimento → jogo | ver `TIMELINE.md` |
| Identidade FT `CORE_NAME` | `h1lab/lab_identity.py` | Experimental ativo | Nomes iguais após designadores/exónimos; fail-closed | ESPN + lista diária BSD |
| Motor de investigação V5 | `h1lab/pattern_features.py`, `pattern_engine.py`, `market_math.py`, `similarity.py`, `lab_stats.py`, `scripts/lab_pattern_research.py` | Experimental ativo | Padrões, combinações, FT, validação fora da amostra, jogos semelhantes | ver `PATTERN-ENGINE.md`; página `docs/lab-research.html` |
| Qualidade V2 | `h1lab/market_v2.py`, `scripts/lab_quality.py`, `lab-quality.yml`, `docs/lab-quality.html` | **Desatualizado** | Agregado sobre o registo H1 | Só manual; `quality.json` de 16:11 UTC |
| Market Intelligence V1 | `h1lab/intelligence.py`, `docs/market-intelligence.html` | **Obsoleto** | Protótipo | Página pede `market-intelligence.json`, que não existe; só `tests/test_intelligence.py` o importa |
| Smoke BSD/Bot | `bsd-smoke.yml`, `bsd-coverage.yml`, `bot-smoke.yml` | Diagnóstico manual | Testes de credenciais | Não escrevem no repo |

## 3. Responsabilidades sobrepostas

| Pergunta | V2 (`market_v2`) | V4 (`market_v4` + `v4_audit`) | Golden | Cronologia | Decisão |
| --- | --- | --- | --- | --- | --- |
| Que formatos chegam? | `quality.json` (formatos, % OTHER) | `format_eligible` | — | — | V2 fica como histórico; cobertura de formatos passa a vir do auditor V4 |
| Valores das tabelas | Projeção do registo H1 | Extração independente | Transcrição humana | Usa V4, senão H1 com rótulo | V4 é a fonte LAB; H1 nunca conta como validação |
| Jogos repetidos | `unique_games` | `same_match_repeated` (prioridade) | — | Trajetória completa | Cronologia é a fonte canónica |
| Exatidão | — | Concordância entre parsers | Única fonte de exatidão | — | Separado em `QUALITY-DIMENSIONS.md` |

## 4. Relatórios e frescura

| Artefacto | Produtor | Frequência | Estado em `4bbd70e` |
| --- | --- | --- | --- |
| `docs/data.json` | collect / results | 5 min / 1 h | atual |
| `docs/lab/v4-audit.json` | lab-v4-audit | após cada recolha | atual (20:36 UTC) |
| `docs/lab/golden-*.json` | lab-v4-audit | após cada recolha | atual |
| `docs/lab/match-trajectories.json` | lab-v4-audit (após PR) | após cada recolha | novo |
| `docs/lab/pattern-research.json` | lab-ft-results (V5) | 30 min, só se mudar | novo |
| `docs/lab/quality.json` | lab-quality (manual) | manual | **histórico** (16:11 UTC, commit `8e0e541`); não representa o estado atual |
| `market-intelligence.json` | nenhum | — | **inexistente** |

## 5. Agendamento — evidência verificável no histórico git

`data/state.json → collector.trigger_source` em cada commit da `main` (27/10/2026):

- 14:36:07 → 20:31:07 UTC: **48 commits com `cloudflare-cron`** e **1 com `github-schedule`** (18:12:13 UTC). Ou seja, o cron nativo do GitHub também disparou pelo menos uma vez.
- 73 commits `data: collect and notify H1` desde as 14:30 UTC; 68 intervalos de 5 min, 1 de 1, 3, 7 e 9 min.
- Limitação: só há commit quando algo muda; a ausência de commit não prova uma execução falhada. Os logs das Actions (ex.: run `40578712731`) não foram consultáveis a partir desta sessão.
- Conclusão: o Cloudflare Cron **está ativo e a disparar** a recolha. O README raiz foi corrigido nesta PR. `scheduler/README.md` ainda diz que não houve `event=schedule`; é ficheiro protegido e fica para PR autorizada.

Reproduzir:
```bash
for c in $(git log main --format=%h --since='2026-10-27T14:00' -- data/state.json); do
  git show $c:data/state.json | python3 -c "import json,sys;c=json.load(sys.stdin)['collector'];print(c.get('trigger_source'),c.get('last_poll_at'))"
done | sort | uniq -c -w 15
```

## 6. Workflows — conflitos e riscos

| Risco | Detalhe | Estado |
| --- | --- | --- |
| Concorrência de escrita | `collect` e `results` partilham `asianodds-h1-write`; o LAB usa `asianodds-lab-v4-audit` e escreve ficheiros disjuntos | OK |
| `lab-quality.yml` no grupo H1 | Execução manual pode atrasar uma recolha | Baixo; manter manual ou mover para grupo LAB |
| Rebase do LAB | `fetch → rebase → push`, 5 tentativas | OK; falha só afeta o LAB |
| Builds do Pages | ~12 commits/h da recolha + ~12/h do LAB > limite suave de 10 builds/h | **Médio**: possíveis atrasos de publicação |
| Churn sem dados novos | o coletor relê a última mensagem a cada poll; V4 regravava o registo com novo `parser_commit` (24 de 73 commits sem alteração de `state.json`) e `docs/data.json` muda `generated_at` | V4 corrigido na PR `lab/v4-store-preserve-provenance`; `docs/data.json` é H1 e fica |

## 7. Crescimento

Medido a 27/10 (137 alertas em 8,6 h ≈ 380/dia):

| Ficheiro | Por mensagem | Por mês | Limite 100 MB do GitHub |
| --- | --- | --- | --- |
| `data/state.json` (ficheiro único, H1) | ~0,96 KB | ~11 MB | **~9 meses** — risco real, decisão H1 |
| `data/lab/formats-AAAA-MM.jsonl` | ~2,2 KB | ~25 MB | partição mensal, OK |
| `data/lab/markets-AAAA-MM.jsonl` | ~0,95 KB | ~11 MB | partição mensal, OK |
| `docs/lab/v4-audit.json` | janela fixa | ~70 KB | reescrito a cada recolha → histórico git cresce |
| `docs/lab/match-trajectories.json` | ≤ 400 jogos | < 2 MB | limitado por desenho |

Duplicação de observações: `event_id` é chave única em todos os armazenamentos; mensagens repetidas do mesmo movimento são **anotadas** pela cronologia, nunca removidas.

## 8. Documentação canónica

| Documento | Conteúdo |
| --- | --- |
| `docs/lab/ARCHITECTURE.md` | este mapa |
| `docs/lab/CLAUDE-HANDOFF-2026-10-27.md` | regras absolutas e pendências (instantâneo) |
| `docs/lab/TIMELINE.md` | modelo de dados da cronologia |
| `docs/lab/PATTERN-ENGINE.md` | motor V5: padrões, hipóteses, estados, validação |
| `docs/lab/QUALITY-DIMENSIONS.md` | dimensões de qualidade e critérios estatísticos |
| `docs/lab/GOLDEN-REVIEW.md` | procedimento Golden e estado das revisões |
| `docs/MARKET-INTELLIGENCE.md` | **histórico** (protótipos V1/V2) |
| `README.md` | operação H1 |
