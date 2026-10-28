# UNDER TESTE — mapa de arquitetura (canónico)

**Referência estrutural atualizada: 28/10/2026.** As secções 5 a 7 abaixo mantêm medições históricas de 27/10 como evidência datada, **não são o estado atual**. Para o cérebro V5 consultar [CEREBRO-ODDS.md](CEREBRO-ODDS.md), para navegação consultar [índice](../README.md), e para dados atuais consultar os JSON. H1, V4 e V5 têm funções diferentes e workflows independentes.

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
results.yml (hora a hora, :41) ── H1 ──► BSD + TheSportsDB + lab_promotion (LAB FINAL verificado)
                                         └─► data/results.csv · data/result_audit.json · docs/data.json
lab-ft-results.yml (:12, :42) ── LAB ──► data/lab/ft-ledger.json · docs/lab/ft-results.json
                                         └─► FT para TODOS os jogos, com ou sem H1
                                   └─ V5 (continue-on-error) pattern_engine → docs/lab/pattern-research.json
                                                                           → data/lab/pattern-registry.json (append-only)
```

## 2. Componentes e estado

| Componente | Ficheiros | Classe | Função | Observações |
| --- | --- | --- | --- | --- |
| Recolha + regra H1 | `h1lab/core.py`, `cli.py`, `session.py` | **Operacional (protegido)** | Parse legado, 1.º H1 por jogo, triplas FIFO | Não alterar |
| Notificação | `h1lab/notify.py`, `bot.py` | **Operacional (protegido)** | Envio das triplas | |
| Liquidação H1 | `h1lab/results.py`, `bsd.py`, `results.yml` | **Operacional (protegido)** | FT via BSD + TheSportsDB; ROI | Jogos pendentes não contam no ROI |
| **Ponte FT LAB → H1** | **`h1lab/lab_promotion.py`** | **Operacional** | Importa apenas FT FINAL para sinais H1 com identidade e fonte rigorosas | Nunca altera picks nem resultados H1 já confirmados; integrada no `results.yml` |
| Agendador | `scheduler/**` | **Operacional (protegido)** | Cloudflare Worker `*/5` | README interno desatualizado (ver §5) |
| Dashboard H1 | `docs/index.html`, `docs/data.json` | **Operacional (protegido)** | ROI singles/triplas | |
| Observador de formatos | `h1lab/shadow_formats.py` | Experimental ativo | Classes de linhas, sem texto | 2,2 KB/mensagem |
| Parser V4 | `h1lab/market_v4.py` | Experimental ativo | Total, AH, 1X2, disparo, janela | Fonte `V4_EXPLICIT` |
| Auditor V4 vs H1 | `h1lab/v4_audit.py`, `scripts/lab_v4_audit.py` | Experimental ativo | Cobertura, concordância, gates | Estado PENDING |
| Golden Set | `h1lab/golden.py`, `scripts/lab_golden.py`, `data/lab/golden/**` | Experimental ativo | Revisão humana por mensagem | NOT_CERTIFIED |
| Prioridades Golden | `h1lab/golden_priority.py` | Experimental ativo | Escolhe mensagens a rever | Não valida valores |
| Cronologia por jogo | `h1lab/timeline.py` | Experimental (nova) | Mensagem → snapshot → movimento → jogo | ver `TIMELINE.md` |
| Identidade FT `CORE_NAME` | `h1lab/lab_identity.py` | Experimental ativo | Nomes iguais após designadores/exónimos; fail-closed | ESPN + lista diária BSD |
| **Cérebro de investigação V5** | `h1lab/pattern_features.py`, `pattern_engine.py`, `market_math.py`, `similarity.py`, `lab_stats.py`, `scripts/lab_pattern_research.py` | **Experimental ativo; sem apostas** | 49 padrões, combinações de Total/1X2/AH, FT, Over 2,5/BTTS, validação temporal fora da amostra e jogos semelhantes | [Guia](CEREBRO-ODDS.md), [método](PATTERN-ENGINE.md), `docs/lab-research.html` |
| Qualidade V2 | `h1lab/market_v2.py`, `scripts/lab_quality.py`, `lab-quality.yml`, `docs/lab-quality.html` | **Desatualizado** | Agregado sobre o registo H1 | Só manual; `quality.json` de 16:11 UTC |
| Market Intelligence V1 | `h1lab/intelligence.py`, `docs/market-intelligence.html` | **Obsoleto** | Protótipo | Página pede `market-intelligence.json`, que não existe; só `tests/test_intelligence.py` o importa |
| Smoke BSD/Bot | `bsd-smoke.yml`, `bsd-coverage.yml`, `bot-smoke.yml` | Diagnóstico manual | Testes de credenciais | Não escrevem no repo |
| Auditoria BSD Europa 30 | `tools/bsd_europa_audit.py`, `config/oruseye_europe30.json`, `reports/` | Histórico + execução **manual** | Cobertura de 30 ligas ORUSEYE com 26 verificadas na amostra (27/10) | Não é sincronização de odds H1; confirmar consumo API antes de executar |

## 3. Responsabilidades sobrepostas

| Pergunta | V2 (`market_v2`) | V4 (`market_v4` + `v4_audit`) | Golden | Cronologia | Decisão |
| --- | --- | --- | --- | --- | --- |
| Que formatos chegam? | `quality.json` (formatos, % OTHER) | `format_eligible` | — | — | V2 fica como histórico; cobertura de formatos passa a vir do auditor V4 |
| Valores das tabelas | Projeção do registo H1 | Extração independente | Transcrição humana | Usa V4, senão H1 com rótulo | V4 é a fonte LAB; H1 nunca conta como validação |
| Jogos repetidos | `unique_games` | `same_match_repeated` (prioridade) | — | Trajetória completa | Cronologia é a fonte canónica |
| Exatidão | — | Concordância entre parsers | Única fonte de exatidão | — | Separado em `QUALITY-DIMENSIONS.md` |

## 4. Relatórios e frescura

| Artefacto | Produtor | Frequência | Situação e leitura |
| --- | --- | --- | --- |
| `docs/data.json` | collect / results | recolha ~5 min / FT ~1 h | **Dinâmico**; 84 singles / 27 triplas no instantâneo de 28/10 11:46 UTC |
| `docs/lab/v4-audit.json` | lab-v4-audit | após cada recolha | atual (20:36 UTC) |
| `docs/lab/golden-*.json` | lab-v4-audit | após cada recolha | atual |
| `docs/lab/match-trajectories.json` | lab-v4-audit (após PR) | após cada recolha | novo |
| `docs/lab/pattern-research.json` | lab-ft-results (V5) | :12 e :42 UTC, pode falhar sem bloquear FT | **800 hipóteses EXPLORATORIO; zero candidatas/validadas** no instantâneo 28/10 11:16 UTC |
| `docs/lab/quality.json` | lab-quality (manual) | manual | **histórico** (16:11 UTC, commit `8e0e541`); não representa o estado atual |
| `market-intelligence.json` | nenhum | — | **inexistente** |

## 5. Agendamento — evidência histórica de 27/10 (não substituir por estado atual)

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

## 6. Workflows — conflitos e riscos (diagnóstico histórico; verificar código atual)

| Risco | Detalhe | Estado |
| --- | --- | --- |
| Concorrência de escrita | `collect` e `results` partilham `asianodds-h1-write`; o LAB usa `asianodds-lab-v4-audit` e escreve ficheiros disjuntos | OK |
| `lab-quality.yml` no grupo H1 | Execução manual pode atrasar uma recolha | Baixo; manter manual ou mover para grupo LAB |
| Rebase do LAB | `fetch → rebase → push`, 5 tentativas | OK; falha só afeta o LAB |
| Builds do Pages | ~12 commits/h da recolha + ~12/h do LAB > limite suave de 10 builds/h | **Médio**: possíveis atrasos de publicação |
| Churn sem dados novos | o coletor relê a última mensagem a cada poll; V4 regravava o registo com novo `parser_commit` (24 de 73 commits sem alteração de `state.json`) e `docs/data.json` muda `generated_at` | V4 corrigido na PR `lab/v4-store-preserve-provenance`; `docs/data.json` é H1 e fica |

## 7. Crescimento (projeções datadas de 27/10, não métricas atuais)

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
| `docs/lab/ARCHITECTURE.md` | este mapa, com notas históricas separadas |
| `docs/lab/CLAUDE-HANDOFF-2026-10-27.md` | regras absolutas e pendências (instantâneo) |
| `docs/lab/TIMELINE.md` | modelo de dados da cronologia |
| `docs/lab/CEREBRO-ODDS.md` | **guia operacional e conceptual do cérebro** e cruzamento de apostas/odds |
| `docs/lab/PATTERN-ENGINE.md` | motor V5: padrões, hipóteses, estados, validação |
| `docs/lab/QUALITY-DIMENSIONS.md` | dimensões de qualidade e critérios estatísticos |
| `docs/lab/GOLDEN-REVIEW.md` | procedimento Golden e estado das revisões |
| `docs/MARKET-INTELLIGENCE.md` | **histórico** (protótipos V1/V2) |
| `README.md` | visão geral H1 + V4 + V5 + ponte LAB para resultados H1 |
| `docs/README.md` | índice documental, canónico vs histórico |
| `reports/README.md` | auditoria BSD Europa 30 (26/30 na amostra; só manual) |

## 9. Atualização operacional: FT universal → liquidação H1 e cérebro V5

**Correção integrada na PR #53 (28/10):** o H1 deixou de depender exclusivamente do seu processo de procura FT. O workflow [results.yml](../../.github/workflows/results.yml) executa a reconciliação direta e depois [lab_promotion.py](../../h1lab/lab_promotion.py), que **importa apenas resultados LAB FINAL verificáveis** do [ledger](../../data/lab/ft-ledger.json) para `data/results.csv`. Compara chave, equipas, kickoff, marcador e proveniência, respeita a janela temporal e **não regrava resultados H1 anteriores**. Foi isto que permitiu passar de 4 para 18 singles H1 liquidadas e liquidar a primeira tripla no instantâneo observado; não foram criados picks novos pelo LAB.

**Pesquisa V5:** o processo [lab-ft-results.yml](../../.github/workflows/lab-ft-results.yml) investiga *todos* os jogos observados, calcula features pré-início e testa combinações nas saídas [pattern-research.json](pattern-research.json) e [pattern-registry.json](../../data/lab/pattern-registry.json). Exige amostra fora do período de descoberta antes de validar. O snapshot de 28/10 11:16 UTC registava **263 jogos elegíveis, 60 FT, 800 hipóteses exploratórias e nenhuma validada**. A página `docs/lab-research.html` é o painel do cérebro.

**Não misturar camadas:** o H1 mede ROI simulado dos sinais originalmente criados; o V5 avalia associação estatística de padrões pré-jogo com Over 2,5 e BTTS sem cálculo de rentabilidade. O Golden Set continua `NOT_CERTIFIED`; a auditoria V4 continua `PENDING`. A frescura e as quotas são verificadas nos artefactos e workflows reais, não pelos números de 27/10 das secções históricas.
