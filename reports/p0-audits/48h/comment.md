<!-- MASTER_BRAIN_P0_AUDIT:48h -->
## MASTER BRAIN — AUDITORIA P0 48h (leitura apenas · auditor V5)
Período (semiaberto): **[2026-11-02T09:58:45Z, 2026-11-04T09:58:45Z)** · janela completa · fecho `78f94366b9d7`
Estado científico #63: INCONCLUSIVO (não alterado por esta auditoria). Workflow verde ≠ publicação confirmada: só o recibo conta, datado pela linha do recibo (não pelo início nem pela conclusão do run).

### 1. Publicadores
| Publicador | Execuções | Publicações efetivas | 1.ª tentativa | após CAS | após 408 | recuperado (408/equivalente) | superadas | recusas integridade | falhas não recuperadas | nada a publicar (recibo / passos skipped) | sem evidência | taxa sucesso* | publicadas após a janela |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Coletor | 575 | 572 | 570 | 0 | 2 | 0 | 0 | 0 | 2 | 1 / 0 | 0 | 99.7% | 0 |
| LAB V4 | 575 | 543 | 541 | 0 | 2 | 0 | 31 | 1 | 0 | 0 / 0 | 0 | 99.8% | 0 |
| FT | 87 | 84 | 84 | 0 | 0 | 0 | 0 | 0 | 3 | 0 / 0 | 0 | 96.6% | 0 |
| H1 | 47 | 42 | 40 | 2 | 0 | 0 | 0 | 0 | 0 | 0 / 5 | 0 | 100.0% | 0 |
\* publicações efetivas ÷ (efetivas + recusas + falhas); supersessões, 'nada a publicar' e runs sem evidência excluídos do denominador. 'Sem evidência' = verde sem recibo, logs indisponíveis, erro da API, recibo ilegível, cancelado sem recibo ou em curso no fecho.
Consultas repetidas a fornecedores comprovadas nos recibos: **0**.

### 2. Falhas e recuperações (todas visíveis): 12
| Publicador | Run | Criado | Publicado | Workflow | Recibo | Categoria | Tent. | CAS | 408 | Entrada | Commit | Motivo | Bundle |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Coletor | 41479757276 | 2026-11-02T16:15:52Z | 2026-11-02T16:16:19Z | failure | PUSH_REFUSED | UNRECOVERED_FAILURE | 1 | 0 | 0 | `cb401e29` | `` | PUSH_REFUSED | sim |
| Coletor | 41808825267 | 2026-11-04T09:35:55Z | 2026-11-04T09:36:22Z | failure | PUSH_REFUSED | UNRECOVERED_FAILURE | 1 | 0 | 0 | `48815784` | `` | PUSH_REFUSED | sim |
| Coletor | 41809284355 | 2026-11-04T09:40:53Z | 2026-11-04T09:42:08Z | failure | PUBLISHED | AFTER_TRANSPORT | 4 | 0 | 3 | `70ea4173` | `4db79bb3` |  |  |
| Coletor | 41810807256 | 2026-11-04T09:55:52Z | 2026-11-04T09:56:42Z | success | PUBLISHED | AFTER_TRANSPORT | 2 | 0 | 1 | `8d9dbbc4` | `c44d3639` |  |  |
| LAB V4 | 41507672240 | 2026-11-02T19:11:46Z | 2026-11-02T19:12:57Z | failure | REFUSED | INTEGRITY_REFUSAL | 1 | 0 | 0 | `92cf013b` | `` | INCOMPATIBLE_PROGRAM | sim |
| LAB V4 | 41518456236 | 2026-11-02T20:21:23Z | 2026-11-02T20:22:06Z | success | PUBLISHED | AFTER_TRANSPORT | 2 | 0 | 1 | `75c53ef3` | `d663b45a` |  |  |
| LAB V4 | 41809441442 | 2026-11-04T09:42:42Z | 2026-11-04T09:43:36Z | success | PUBLISHED | AFTER_TRANSPORT | 3 | 0 | 2 | `4db79bb3` | `cd5f1e18` |  |  |
| FT | 41476501130 | 2026-11-02T15:56:18Z |  | failure | None | NO_RECEIPT_WORKFLOW_FAILURE | None | 0 | 0 | `` | `` |  |  |
| FT | 41502044305 | 2026-11-02T18:35:35Z |  | failure | None | NO_RECEIPT_WORKFLOW_FAILURE | None | 0 | 0 | `` | `` |  |  |
| FT | 41796944393 | 2026-11-04T08:06:18Z |  | failure | None | NO_RECEIPT_WORKFLOW_FAILURE | None | 0 | 0 | `` | `` |  |  |
| H1 | 41475675906 | 2026-11-02T15:51:18Z | 2026-11-02T15:52:03Z | success | PUBLISHED | AFTER_CAS | 2 | 0 | 0 | `f3bdcd8f` | `e28f4089` |  |  |
| H1 | 41572694424 | 2026-11-03T03:31:21Z | 2026-11-03T03:32:08Z | success | PUBLISHED | AFTER_CAS | 2 | 0 | 0 | `0d482d8f` | `e1cdffa0` |  |  |

### 3. Lacunas de evidência: 6
Lacunas de observabilidade — **não** são incidentes de corrupção nem provas de publicação. As bloqueantes impedem uma conclusão de estabilidade (INCONCLUSIVO_OPERACIONAL); as informativas ficam registadas.
| Tipo | Bloqueante | Workflow | Run | Detalhe |
|---|---|---|---|---|
| GREEN_NO_RECEIPT_PUBLISH_STEPS_SKIPPED | não | results.yml | 41438630423 | verde, sem recibo; API confirma passos de publicação/recibo todos skipped (sem tentativa de publicação) |
| GREEN_NO_RECEIPT_PUBLISH_STEPS_SKIPPED | não | results.yml | 41523381521 | verde, sem recibo; API confirma passos de publicação/recibo todos skipped (sem tentativa de publicação) |
| GREEN_NO_RECEIPT_PUBLISH_STEPS_SKIPPED | não | results.yml | 41569910538 | verde, sem recibo; API confirma passos de publicação/recibo todos skipped (sem tentativa de publicação) |
| GREEN_NO_RECEIPT_PUBLISH_STEPS_SKIPPED | não | results.yml | 41695798133 | verde, sem recibo; API confirma passos de publicação/recibo todos skipped (sem tentativa de publicação) |
| GREEN_NO_RECEIPT_PUBLISH_STEPS_SKIPPED | não | results.yml | 41788973268 | verde, sem recibo; API confirma passos de publicação/recibo todos skipped (sem tentativa de publicação) |
| PAGES_NOT_VERIFIED | não | - | — | bytes servidos não obtidos (informativo; não bloqueia o veredito dos publicadores) |

### 4. Supersessão / starvation LAB V4
Ciclos: **575** · publicações efetivas: **543** · superados: **31** · sem evidência: **0** · taxa: **5.4%** · maior sequência consecutiva: **2** · tempo máximo sem publicação: **15.1 min** (('2026-11-03T15:47:14Z', '2026-11-03T16:02:22Z')) · recuperação após supersessão: n=30, máx 10.6 min, média 5.7 min · sequência aberta no fim: 0.
Sem gatilhos de alerta (3 consecutivas / >30 min / >25% com n≥8).

### 5. Integridade
- Baseline `b8bc46cab955` (main no início da janela, 2026-11-02T09:58:45Z): FT {'FINAL': 446, 'EXPIRED_UNVERIFIED': 423, 'PENDING': 308, 'IDENTITY_CONFLICT': 1}, H1 116, Telegram 13 `sent` — **verificada** contra o objeto Git.
- **Fotografia A — fecho da janela** (`78f94366b9d7`, último push < fim): H1 certificados **131** (+15 novos); FT {'EXPIRED_UNVERIFIED': 676, 'FINAL': 506, 'PENDING': 289}.
- Journals append-only verificados (baseline→fecho): 19.
- Verificação histórica commit a commit (baseline→fecho; atribuição pela hora de push registada pelo GitHub, não pela data do commit): 1427 commits, 262 transições de estado FT/H1/Telegram verificadas; violações transitórias: **2**.
- Leitores de produção: V4 eventos=2163, projeção=True; `docs/data.json` coerente=True; arquivo V6: ver secção 9; estado científico=INCONCLUSIVO.
- Commits publicados na main no período (pela hora de push): 1427 (merges 12); multi-dono: 47; programa: 0; caminho desconhecido: 0; commits com recibo PUBLISHED ausentes da main: 0.
  - multi-dono (revisão manual; H1 re-renderiza `docs/data.json`): `f5672576` ['COLLECTOR', 'H1_RESULTS'], `47cb7348` ['COLLECTOR', 'H1_RESULTS'], `59a6c27e` ['COLLECTOR', 'LEGACY_FROZEN'], `922df9cc` ['COLLECTOR', 'H1_RESULTS'], `8e25f2eb` ['COLLECTOR', 'H1_RESULTS'], `44c379a0` ['COLLECTOR', 'LEGACY_FROZEN'], `24a70084` ['COLLECTOR', 'H1_RESULTS'], `aba23c27` ['COLLECTOR', 'LEGACY_FROZEN']
- **Violações de integridade: 2**
  - FT expirado reaberto: 2026-11-01,1009,964 -> IDENTITY_CONFLICT @ d06b6394ee91 (push 2026-11-03T20:38:23Z)
  - FT expirado reaberto: 2026-11-01,1009,964 -> IDENTITY_CONFLICT @ a1374a9d322c (push 2026-11-04T01:32:49Z)

### 6. Telegram
- Modos efetivos nos logs do coletor: {'TG_DURABLE_INTENT=0': 206, 'TG_IGNORE_AUTH_BLOCK=0': 206}
- `data/three-total-moves-notifications.json`: 6 → 8 {'sent': 8} novos=2
- `data/two-up-total-notifications.json`: 7 → 10 {'sent': 10} novos=3
- `data/e5-over25-notifications.json`: 0 → 118 {'sent': 118} novos=118
- Commits a `data/telegram-delivery-block.json` no período: 0 (persistência de bloqueio não exercitada).
- Sinais 429/401/403 nos logs: 0
- Exactly-once **não** é afirmado (AT-LEAST-ONCE com modo durável desligado).

### 7. Pages
- {'bytes': 'NOT VERIFIED', 'build_error': 'gh api repos/nunovinhas-creator/asianodds-h1-lab/pages/builds/latest: HTTP 403: {"message":"Access to this GitHub API path is not permitted through this proxy.","documentation_url":"https://docs.anthr', 'bytes_error': 'curl: (22) The requested URL returned error: 403\n'}

### 8. Fronteira temporal — fotografias A e B
- Fecho: `78f94366b9d7` = último push com hora de servidor < 2026-11-04T09:58:45Z (push às 2026-11-04T09:57:38Z); primeiro push ≥ fecho: 2026-11-04T10:01:40Z. Cadeia de 1437 pushes contínua desde a baseline (A: 1427, B: 10). Fonte: registo de atividade do GitHub (não a data dos commits).
- **Fotografia B — main na auditoria** (`26ef6de4178b`): 10 commits publicados após o fecho; violações posteriores ao fecho: **0** — fora dos indicadores e do veredito desta janela.
- Estado na auditoria: H1 131; FT {'EXPIRED_UNVERIFIED': 676, 'FINAL': 506, 'PENDING': 289}; projeção V4 True; `docs/data.json` coerente True.

### 9. Arquivo V6 (índice selado ≠ relatório derivado)
- Estado: **INDICE_SELADO_INTEGRO** — índice selado em sincronia; relatório de saúde atual
- Frescura do relatório de saúde na janela (limite superior via Git): 257 regenerações; 253 episódios desatualizados; mediana 1.1 min; máximo 19.4 min ('2026-11-02T23:52:39Z', '2026-11-03T00:12:00Z') (4 ciclos LAB); aberto no fecho: None min; limite de alerta 90 min.

### 10. Cobertura e orçamento da API
| Publicador | Segmentos completos | Esperados (API) | Obtidos | Terminados antes do início (lookback, metadados) | Na janela | Com recibo | Sem evidência completa |
|---|---|---|---|---|---|---|---|
| Coletor | 5/5 | 611 | 611 | 36 | 575 | 575 | 0 |
| LAB V4 | 5/5 | 611 | 611 | 36 | 575 | 575 | 0 |
| FT | 5/5 | 92 | 92 | 5 | 87 | 84 | 0 |
| H1 | 5/5 | 51 | 51 | 4 | 47 | 42 | 0 |
- Cobertura integral demonstrada (total_count = obtidos em todos os segmentos).
- API: 1337 pedidos, 1 erros, limite 15000/h, mínimo restante 13710, espera por limites 0 s; ritmo máx. 8.0 pedidos/s. Início: {'limit': 15000, 'used': 12, 'remaining': 14988, 'reset': 1793790647}.
- Head auditada `26ef6de4178b` = main remota.

### 11. Bloqueios P0 e classificação
- Classificação operacional: **CRÍTICO — violação de integridade verificada** (falhas não recuperadas=2, falhas sem recibo=3, recusas=1, alertas LAB=0, violações=2, arquivo V6=INDICE_SELADO_INTEGRO, alertas de atualização=0, lacunas de evidência bloqueantes=0, informativas=6).
- Bloqueios P0 conhecidos mantidos: Telegram AT-LEAST-ONCE (modo durável desligado; crash entre envio e publicação sem diagnóstico); recusas FT conhecidas sobre nova geração do índice de arquivo/partições.
- CI verde não é usado como prova de estabilidade. #107 permanece **OPEN**; o fecho exige avaliação explícita. #204 isolada; #63 INCONCLUSIVO.

---
### 12. Revisão manual fundamentada (MASTER BRAIN) — veredito revisto: **DEGRADED**
**(a) Veredito bruto do auditor (não editado, acima):** CRÍTICO — violação de integridade verificada (2 violações). **(b) Revisão manual:** `DEGRADED` — a "violação" é transitória, auto-corrigida e não é corrupção; ver abaixo. Não há lacunas bloqueantes e a cobertura é integral, logo não é INCONCLUSIVO_OPERACIONAL.

**Preflight/proveniência:** API OK (push/admin, 14 999/15 000), logs de jobs lidos (>0 bytes; o job em curso devolve BlobNotFound, normal). Auditor V5 `ff9c54c5…` é ancestral de origin/main (verificado após `fetch --unshallow`; o clone raso inicial dava falso negativo), sha256 `97abba9edbe46f70093c7574994eb7c55b6f17c893cf4ef86aad8b6b7efe215b` coincide. Guardas anti-escrita ativas (push falhou como esperado).

**As 2 violações (mesmo jogo `2026-11-01,1009,964`, CD Cobresal vs CD Everton de Viña del Mar):**
- `d06b6394ee91` (push 2026-11-03T20:38:23Z) e `a1374a9d322c` (push 2026-11-04T01:32:49Z), ambos "publish verified FT snapshot": EXPIRED_UNVERIFIED → IDENTITY_CONFLICT (`conflicting_observed_identity`, fontes H1_ALERT+V4, 2 alertas observados). A baseline já continha 1 IDENTITY_CONFLICT.
- Em ambos os casos a publicação FT seguinte repôs EXPIRED_UNVERIFIED (verificado em `033700998`, `08531d59c`, no fecho `78f94366b9d7` e na main atual). Fecho: 0 IDENTITY_CONFLICT; nenhum FINAL perdido, H1 131 (+15), journals append-only verificados (19), `JOURNAL_SELADO_ALTERADO` ausente, arquivo V6 INDICE_SELADO_INTEGRO. Trata-se de oscilação de estado (flapping) entre quarentena de identidade e expiração — incidente a investigar (porque é que o conflito de identidade é reavaliado e revertido), não corrupção. Fotografia B: 0 violações.

**Falhas (causa exata nos logs):**
- Coletor 41479757276 (02/11 16:16Z): GitHub `500 Internal Server Error` no push (`remote rejected … Internal Server Error`); Coletor 41808825267 (04/11 09:36Z): `remote: fatal error in commit_refs` / `remote rejected (failure)`. Ambas infraestrutura GitHub, bundle guardado, PUSH_REFUSED sem recuperação automática (2 falhas; a segunda é nova face à 24h).
- LAB V4 41507672240 (02/11 19:12Z): `INCOMPATIBLE_PROGRAM Incompatible program change: h1lab/e5_notify.py` — recusa de integridade esperada por mudança de programa concorrente (já na 24h).
- FT 41476501130: `UnsafeFTPublication: Unknown concurrent path: data/lab/v6-memory-evidence-2026-11.jsonl`; FT 41502044305: `UnsafeFTPublication: H1 notification receipt invalid: data/e5-over25-notifications.json` (ambas já na 24h, anteriores à correção); **FT 41796944393 (04/11 08:06Z, nova):** `LAB_PATTERN_REPORT_TOO_LARGE 350074` e `ValueError: Publication blocked; producers not successful: research, discovery` — guarda de publicação bloqueou corretamente; sem recibo, sem dado corrompido. Padrão a corrigir: relatório de padrões LAB excede o limite.
- Recuperações por 408/CAS (5 coletor/LAB, 2 H1) concluídas com PUBLISHED. 5 `results.yml` verdes sem recibo com passos de publicação todos skipped (informativo). Pages: 403 do proxy (limitação, PAGES_NOT_VERIFIED).

**Supersessão LAB:** 31/575 (5,4%; 24h: 6,6%), maior sequência 2, máx. 15,1 min sem publicação, sem alertas. **Arquivo:** íntegro; relatório de saúde desatualizado máx. 19,4 min (<90). **Cobertura:** integral (4 publicadores, 5/5 segmentos; Coletor/LAB 611=611, FT 92=92, H1 51=51); head auditada = main remota; fecho determinado pela hora de push do servidor.
**Multi-dono:** 47 commits COLLECTOR+H1_RESULTS/COLLECTOR+LEGACY_FROZEN (esperados; lista parcial no relatório; os LEGACY_FROZEN após #209 devem ser reavaliados). Merges de programa: 12 merges na janela, 0 classificados "programa" pela ferramenta (não verificados individualmente nesta revisão).
**Telegram:** TG_DURABLE_INTENT=0 e TG_IGNORE_AUTH_BLOCK=0 em 206 runs; 0 sinais 429/401/403; baseline 13 `sent` verificada (V5 já sem falso BASELINE_INVALID); ledgers: three-total 6→8, two-up 7→10, e5-over25 0→118 (todos `sent`; o ledger E5 não existia na baseline). Bloqueio persistente não exercitado. Exactly-once NÃO afirmado (at-least-once).

**Evolução vs 24h (DEGRADED):** falhas não recuperadas 1→2; sem recibo 2→3; recusas 1→1; violações 0→2 (transitórias, mesmo jogo); lacunas bloqueantes 1→0 (resolvidas); supersessão 6,6%→5,4%; cobertura integral em ambas; arquivo íntegro em ambas; H1 126→131, FT FINAL 475→506. Veredito: DEGRADED mantém-se (sem melhoria nem corrupção). #107 permanece OPEN; #63 INCONCLUSIVO; #204 não tocada.

**Ferramenta:** `tools/p0_stability_audit_v5.py` @ `ff9c54c5db2b04e8964a8094ba225f4a2e45fba6`, sha256 `97abba9edbe46f70093c7574994eb7c55b6f17c893cf4ef86aad8b6b7efe215b`. Orçamento API: 1 337 pedidos (1 erro), mínimo restante 13 710/15 000, sem esperas.

_Generated by [Claude Code](https://claude.ai/code)_


---
_Generated by [Claude Code](https://claude.ai/code)_