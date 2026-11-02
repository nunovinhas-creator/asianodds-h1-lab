# P0 — Publicação do coletor e do LAB V4 (2026-11-02)

Issue: #107 (DEGRADED). Estado científico #63: **INCONCLUSIVO** (inalterado).

## 1. Causa-raiz (coletor)

`collect.yml` publicava com:

```
git add data/state.json docs/data.json <ledgers> <bloqueio> data/lab
git commit ; git pull --rebase origin main ; git push origin main
```

Esta sequência corre **depois** de `three_moves_notify` e `two_up_notify` terem
enviado mensagens. Com `TG_DURABLE_INTENT=0` o único registo do envio é o ledger
local. Qualquer falha a partir daqui descarta, na mesma operação, os recibos
Telegram, o bloqueio de cooldown, o checkpoint `last_id` e as observações V4:

| Evento reproduzido (Git bare)                         | Fluxo antigo                                   | Consequência                                      |
|------------------------------------------------------|------------------------------------------------|---------------------------------------------------|
| LAB V4/FT/H1 publica entre `pull --rebase` e `push`  | push rejeitado (`cannot lock ref`/non-ff), job falha | recibo `sent` perdido → próximo ciclo pode reenviar |
| Outro coletor altera `data/state.json`               | conflito no rebase, job falha                  | recibo e observações perdidos                     |
| Outro coletor altera um ledger                       | conflito; o duplicado não é reportado          | dois envios do mesmo alerta, sem diagnóstico      |
| H1 re-renderiza outro campo de `docs/data.json`      | merge textual silencioso                       | publica uma vista que ninguém renderizou          |
| HTTP 408 antes da aceitação                          | job falha                                      | igual ao primeiro caso                            |
| HTTP 408 depois da aceitação                         | job vermelho, watchdogs saltados               | sinal operacional errado; nenhum recibo           |
| `git add data/lab`                                   | publica ficheiros que não são do coletor       | p.ex. pode apagar FINAL do `ft-ledger.json`       |
| Crash após envio e antes da publicação               | —                                              | risco residual, ver §4                            |

Testes: `tests/test_collect_publish_safe.py::LegacyCollectorFlowRisks` (6 cenários).

## 2. Matriz de propriedade (código: `scripts/publication_ownership.py`)

`data/lab/**` **não** pertence a um único produtor.

| Ficheiro / padrão | Dono (único escritor) | Tipo | Lido por | Conflito concorrente |
|---|---|---|---|---|
| `data/state.json` | COLETOR | estado (observações monotónicas) | notificadores, H1, LAB V4, FT | outro escritor → **recusa** |
| `docs/data.json` | COLETOR (H1 re-renderiza) | vista derivada de state+results | Pages | re-render offline |
| `data/three-total-moves-notifications.json`, `data/two-up-total-notifications.json` | COLETOR | recibos Telegram (nunca removidos; terminais imutáveis) | notificadores, LAB V4 (elegibilidade) | outro escritor → **recusa** |
| `data/telegram-delivery-block.json` | COLETOR | cooldown 429/401/403 (nunca encurtado) | notificadores | outro escritor → **recusa** |
| `data/lab/markets-YYYY-MM[-partNNNN].jsonl` | COLETOR | vista mutável (nunca perde eventos) | notificadores, LAB V4, FT | outro escritor → **recusa** |
| `data/lab/formats-…jsonl` | COLETOR | vista mutável | LAB V4 | outro escritor → **recusa** |
| `data/lab/v4-revisions-…jsonl` | COLETOR | journal append-only (cadeia SHA) | LAB V4 | outro escritor → **recusa** |
| `data/results.csv`, `data/result_audit.json`, `data/health/h1-results.json` | H1 | resultados certificados | coletor (render), LAB V4 | mantido; `results.csv` → re-render |
| `data/lab/ft-*.json`, `pattern-*`, `discovery-*`, `v6-ft-events-*`, `docs/lab/ft-*` … | FT | ledger FINAL, journals | H1, LAB V4 | mantido (não é entrada do coletor) |
| `docs/lab/{v4-audit,golden-*,v6-*,telegram-eligibility,…}.json`, `data/lab/v6-forecasts-*`, `v6-memory-*`, `v6-hypotheses`, `v6-weekly-snapshots`, `v4-runchecks`, `v6-archive-index.json` | LAB V4 | relatórios + journals append-only | FT (alguns), Pages | mantido |
| `docs/lab/llm-*`, `llm-statistics*`, `quality.json` | LLM / estatística / qualidade | relatórios | Pages | mantido |
| `data/pattern-notifications.json`, `e4-`, `strategy-`, `t05-` | LEGADO congelado | ledgers de notificadores desativados | — | alteração → **recusa** |
| `h1lab/`, `scripts/`, `.github/`, `config/`, requirements | PROGRAMA | código | todos | **recusa** (INCOMPATIBLE_PROGRAM) |
| `tests/`, `*.md`, `docs/*.html|js|css`, `data/lab/golden/**`, `reports/**` | documentação / site / revisão manual | não-runtime para o coletor | — | mantido |
| qualquer outro | desconhecido | — | — | **recusa** (UNKNOWN_PATH) |

`tests/test_publication_ownership.py` prova que todos os ficheiros rastreados têm
dono e que cada `git add` de cada workflow só toca ficheiros do respetivo dono.

## 3. Correção do coletor

* `scripts/git_selective_publish.py`: motor comum (generaliza #202/#203). Commit
  sobre o `base` fixado; índice Git isolado; os blobs do produtor são
  transplantados sobre a `main` remota atual e **todos** os outros blobs remotos
  ficam byte-a-byte; comparação com os blobs remotos para idempotência
  (`ALREADY_PUBLISHED_EQUIVALENT`); classificação de push via
  `git_publish_outcome` (CAS → nova tentativa revalidada; 408/5xx → leitura do
  remoto antes de qualquer nova tentativa; AUTH → paragem); tentativas limitadas
  (6, transporte ≤3); nunca `--force`, nunca rebase.
* `scripts/collect_publish_safe.py`: política do coletor.
  * `stage`: só os caminhos do coletor (nunca `data/lab` inteiro); outros
    alterados localmente → `::warning` e não publicados.
  * guardas base→fonte: `last_id` nunca recua; alertas/sinais/tickets nunca
    removidos; identidade de jogos estável; recibos nunca removidos e terminais
    imutáveis; bloqueio nunca encurtado/removido enquanto ativo; journal V4
    append-only; vistas V4 nunca perdem eventos (repartição permitida).
  * recibo `COLLECT_PUBLISH_RECEIPT` com SHA, `path`
    (FIRST_ATTEMPT / AFTER_CAS / AFTER_TRANSPORT / CONFIRMED_AFTER_TRANSPORT_ERROR /
    EQUIVALENT_ALREADY_ON_REMOTE), `cas_retries`, `transport_failures`,
    `telegram_requests: 0`, `provider_requeries: 0`.
  * falha: `REFUSED` (PERSISTENT_INCOMPATIBILITY) / `RETRY_EXHAUSTED`
    (TRANSIENT_CONTENTION) / `OUTCOME_UNRESOLVED` / `PUSH_REFUSED`, com bundle do
    commit não publicado e anotações `::error` `COLLECT_PUBLICATION_FAILED`,
    `TELEGRAM_RECEIPTS_NOT_ON_MAIN` (chave, estado, `telegram_message_id`) e
    `TELEGRAM_RESEND_RISK`.
* Elegibilidade dos alertas, notificadores, quotas e cooldowns: **inalterados**.

### 3.1 Imutabilidade das observações (revisão crítica, 2.ª iteração)

A primeira versão só verificava a permanência dos identificadores. Agora a
publicação reexecuta os leitores de produção (`h1lab.v4_revisions.read_events`,
`verify_projection`, `h1lab.core.public_data`) sobre a árvore de origem **e** sobre
a árvore candidata exata.

| Dado | Imutável | Pode mudar legitimamente | Prova exigida |
|---|---|---|---|
| `state.json` `alerts[]` (por `event_id`) | registo inteiro | — (`core.incorporate` só acrescenta) | igualdade campo-a-campo |
| `state.json` `signals[]` / `tickets[]` | registo inteiro | — | igualdade campo-a-campo |
| `state.json` `last_id` | nunca recua | cresce | monotonia |
| `state.json` `diagnostics`, `collector` | — | estado operacional | — |
| `markets-*` (vista V4) | `event_id`, `observed_at` (hora original Telegram) | odds, linha, mercado, identidade — **só** via nova revisão | revisão `EDIT_DATE_CHANGED`/`CONTENT_CHANGED_EDIT_UNPROVEN` nova no journal, encadeada à anterior, cujo `snapshot_sha256` é exatamente a linha nova (`verify_projection`) |
| `formats-*` | `event_id`, `observed_at` | assinatura, só para eventos revistos no mesmo commit | revisão V4 do mesmo evento |
| `v4-revisions-*` | prefixo inteiro (cadeia SHA) | só append | `read_events`: `sha256`, `previous_sha256`, `previous_event_revision_id`, `snapshot_sha256`, `known_at` |
| `docs/data.json` | — | derivado | igual **exatamente** a `public_data(state, results.csv, generated_at)` da mesma árvore |

O journal guarda, para cada revisão: evento (`event_id`), conteúdo anterior
(revisão anterior ligada por `previous_event_revision_id`), conteúdo novo
(`snapshot`), momento (`known_at`, `telegram_edit_at`) e proveniência
(`parser_commit`, `parser_source_sha256` no snapshot). Uma revisão para evento
inexistente, um hash ou elo de cadeia inválido, uma alteração não registada ou
uma reescrita da hora original são recusados (`tests/test_collect_publish_safe.py::
HistoricalObservationImmutability`, casos 1–8). Reprodução sobre a `main` real:
os 39 commits do coletor disponíveis no histórico raso são todos aceites pelas
novas guardas (sem falsos positivos) e o `docs/data.json` atual é coerente.

Outras correções desta iteração: `stage` remove do índice ficheiros estrangeiros
staged por passos anteriores e, com `--park`, guarda num patch e restaura ficheiros
estrangeiros modificados (antes deixariam o checkout "sujo" e a publicação inteira
seria recusada); o caminho `ALREADY_PUBLISHED_EQUIVALENT` só é aceite se o
`docs/data.json` remoto for coerente — caso contrário a vista é reparada e publicada.

Limite conhecido: se `market_v4.store` falhar a meio (é não-fatal no coletor), os
ficheiros V4 incoerentes fazem a publicação inteira do ciclo ser recusada, com
recibo, bundle e `TELEGRAM_RESEND_RISK`. Preferiu-se recusa explícita a publicação
parcial.

## 4. Telegram — risco residual honesto

`TG_DURABLE_INTENT=0` (confirmado nos logs) ⇒ **AT-LEAST-ONCE**. Janela: do
`sendMessage` aceite até `main` conter o ledger. Esta PR fecha a parte Git da
janela (corridas, 408, conflitos com outros produtores), mas **não** fecha:

1. crash/cancelamento do runner entre o envio e a publicação;
2. recusa persistente (segundo coletor, alteração de programa a meio do ciclo);
3. remoto ilegível após 408 (`OUTCOME_UNRESOLVED`).

Nos casos 2 e 3 o job falha com o recibo listando os alertas em risco de
reenvio e o bundle. O caso 1 não deixa diagnóstico no repositório (só o log do
job interrompido). O modo durável não foi ativado. Exactly-once não é prometido.

## 5. LAB V4 (`lab-v4-audit.yml`)

O `publication_guard` (outcomes de todos os produtores + selo dos bytes) já
impedia publicações parciais e alterações dos ficheiros selados durante o
rebase. O risco está no que o selo **não** cobre: as **entradas** dos relatórios.

| Pergunta | Loop antigo (fetch/rebase/verify/push ×5) | Evidência |
|---|---|---|
| Pode perder alterações? | Não (rebase preserva commits remotos); conflitos fazem o job falhar sem recibo | `test_concurrent_journal_append_conflicts` |
| Sobrescrever resultados independentes? | Não diretamente (só ficheiros staged) | — |
| Duplicar entradas append-only? | Não observado: rebase em conflito falha; 408-depois-de-aceite é absorvido pelo rebase no-op | — |
| Publicar relatórios sobre entradas incompatíveis? | **Sim** | `test_closed_month_append_publishes_an_index_that_contradicts_main`, `test_rewritten_ft_final_is_not_noticed`, `test_report_contradicting_rolled_back_receipt_is_published` |
| Destruir um selo válido no rebase? | Não: o selo detecta (ou o rebase entra em conflito) | `test_same_artifact_by_another_lab_run_conflicts_or_is_caught_by_the_seal` |
| Confundir rejeitada com aceite? | Não perde dados, mas não classifica nem emite recibo; AUTH é repetido 5× | — |

O caso mais grave: um append FT a um mês fechado que o novo
`v6-archive-index.json` acabou de selar faz rebase limpo, passa o selo e é
publicado; a `main` passa a ter um índice que contradiz os ficheiros, e todos os
builds seguintes falham com `SEALED_MONTH_MUTATED_OR_MISSING`.

### Correção: `scripts/lab_v4_publish_safe.py`

Mesmo motor comum; `publication_guard outcomes` e `seal` mantidos no workflow;
`publication_guard.verify` reexecutado sobre a árvore candidata exata.

Política de dependências por caminho remoto: artefacto LAB V4 alterado por outro
→ recusa (`CONCURRENT_OWNER_WRITE`, inclui journals e nova geração do arquivo);
identidade de jogos, recibos Telegram, bloqueio e journal V4 do coletor validados;
`results.csv` certificado retido; FINAL do `ft-ledger.json` inalterados; journals
FT append-only; rótulos Golden (`data/lab/golden/**`) → recusa; programa/legado/
desconhecido → recusa. Verificações sobre o candidato: selo, cada entrada selada
do índice de arquivo contra os blobs do candidato, cada recibo terminal citado em
`telegram-eligibility.json` contra os ledgers do candidato, journals append-only.
Recusa explícita, nunca publicação parcial. Recibo `LAB_V4_PUBLISH_RECEIPT`.

### 5.1 Relatórios sobre entradas obsoletas (revisão crítica, 2.ª iteração)

A primeira versão mantinha alterações concorrentes **válidas** às entradas
(estado/observações do coletor, recibos, `results.csv`, ledger FT) e publicava os
relatórios selados por cima delas: um relatório calculado sobre a base aparecia na
`main` ao lado de entradas mais recentes, sem o indicar.

Regra atual (`scripts/lab_v4_publish_safe.py`):

* violação de integridade → `REFUSED` (falha): FINAL alterado, linha certificada
  alterada, recibo revertido, journal reescrito, identidade de jogos reescrita,
  mês fechado selado pelo índice alterado, rótulos Golden, programa, desconhecido;
* alteração **válida** de uma entrada material → `SUPERSEDED_BY_NEWER_INPUTS`:
  nada publicado, nenhum relatório obsoleto apresentado como atual; o job termina
  com `::notice` (exit 0) e a execução seguinte do LAB — disparada pela conclusão
  seguinte do coletor (≤ 5 min) — recalcula sobre a nova `main`;
* não-material (nenhum produtor LAB os lê): `docs/data.json`, bloqueio Telegram,
  LLM, estatística, qualidade, site, documentação → mantidos.

Proveniência: cada commit LAB transporta `LAB-Input-Commit: <sha>`; antes do push
prova-se que nenhum caminho material difere entre esse commit e o pai do commit
publicado. Um trailer que nomeie outro commit é recusado. Custo: as entradas
append-only do LAB de um ciclo superado (p.ex. forecasts com `known_at`) não são
publicadas; o ciclo seguinte regista o seu próprio instante de processamento.

## 6. Simulação conjunta dos quatro escritores

`tests/test_four_writer_concurrency.py` usa os publicadores reais (coletor e LAB
V4 no motor comum; FT #202 e H1 #203 inalterados). Os quatro preparam o ciclo a
partir da mesma base e publicam nas **24 ordens possíveis**, com faltas fixas:
2.º publicador CAS (commit LLM independente), 3.º HTTP 408 antes da aceitação,
4.º HTTP 408 depois da aceitação seguido de outro commit. Invariantes: todos os
commits presentes, cada mensagem uma única vez, recibos Telegram intactos, FINAL
FT e H1 retidos, journals com prefixo da base, sem duplicados, `docs/data.json`
consistente com as entradas finais. Contenção persistente → `RETRY_EXHAUSTED`
após exatamente 6 tentativas (limite não aumentado) e publicação posterior sem
novo trabalho; incompatibilidade persistente → `REFUSED` sem nada parcial.

Segunda iteração: o fixture usa os escritores de produção (`market_v4.store`,
`shadow_formats.store`, `public_data`); o LAB é superado em exatamente 18 das 24
ordens (sempre que um escritor material publica antes) e recalcula sobre a nova
`main`; no fim de cada ordem a `main` é reproduzida desde a base com os leitores
de produção (alertas imutáveis, cadeia V4, projeção, vistas) e o `docs/data.json`
é igual ao render exato. Alterações incompatíveis são recusadas antes de qualquer
push pelos quatro publicadores reais.

Recusas conhecidas do publicador FT (não alteradas aqui, seguras): nova geração
de `v6-archive-index.json` e partições `markets-…-partNNNN` bloqueiam esse ciclo
FT (`KnownCrossProducerRefusals`).
