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

## 5. LAB V4

Ver secção acrescentada pela PR do LAB V4.
