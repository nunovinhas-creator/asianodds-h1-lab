<!-- MASTER_BRAIN_P0_AUDIT:24h -->
## MASTER BRAIN — AUDITORIA P0 24h (leitura apenas)
Período (semiaberto): **[2026-11-02T09:58:45Z, 2026-11-03T09:58:45Z)** · janela completa · fecho `6e305f5406b1`
Estado científico #63: INCONCLUSIVO (não alterado por esta auditoria). Workflow verde ≠ publicação confirmada: só o recibo conta, datado pela linha do recibo (não pelo início nem pela conclusão do run).

### 1. Publicadores
| Publicador | Execuções | Publicações efetivas | 1.ª tentativa | após CAS | após 408 | recuperado (408/equivalente) | superadas | recusas integridade | falhas não recuperadas | nada a publicar (recibo / passos skipped) | sem evidência | taxa sucesso* | publicadas após a janela |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Coletor | 288 | 286 | 286 | 0 | 0 | 0 | 0 | 0 | 1 | 1 / 0 | 0 | 99.7% | 0 |
| LAB V4 | 288 | 268 | 267 | 0 | 1 | 0 | 19 | 1 | 0 | 0 / 0 | 0 | 99.6% | 0 |
| FT | 43 | 41 | 41 | 0 | 0 | 0 | 0 | 0 | 2 | 0 / 0 | 0 | 95.3% | 0 |
| H1 | 24 | 21 | 19 | 2 | 0 | 0 | 0 | 0 | 0 | 0 / 3 | 0 | 100.0% | 0 |
\* publicações efetivas ÷ (efetivas + recusas + falhas); supersessões, 'nada a publicar' e runs sem evidência excluídos do denominador. 'Sem evidência' = verde sem recibo, logs indisponíveis, erro da API, recibo ilegível, cancelado sem recibo ou em curso no fecho.
Consultas repetidas a fornecedores comprovadas nos recibos: **0**.

### 2. Falhas e recuperações (todas visíveis): 7
| Publicador | Run | Criado | Publicado | Workflow | Recibo | Categoria | Tent. | CAS | 408 | Entrada | Commit | Motivo | Bundle |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Coletor | 41479757276 | 2026-11-02T16:15:52Z | 2026-11-02T16:16:19Z | failure | PUSH_REFUSED | UNRECOVERED_FAILURE | 1 | 0 | 0 | `cb401e29` | `` | PUSH_REFUSED | sim |
| LAB V4 | 41507672240 | 2026-11-02T19:11:46Z | 2026-11-02T19:12:57Z | failure | REFUSED | INTEGRITY_REFUSAL | 1 | 0 | 0 | `92cf013b` | `` | INCOMPATIBLE_PROGRAM | sim |
| LAB V4 | 41518456236 | 2026-11-02T20:21:23Z | 2026-11-02T20:22:06Z | success | PUBLISHED | AFTER_TRANSPORT | 2 | 0 | 1 | `75c53ef3` | `d663b45a` |  |  |
| FT | 41476501130 | 2026-11-02T15:56:18Z |  | failure | None | NO_RECEIPT_WORKFLOW_FAILURE | None | 0 | 0 | `` | `` |  |  |
| FT | 41502044305 | 2026-11-02T18:35:35Z |  | failure | None | NO_RECEIPT_WORKFLOW_FAILURE | None | 0 | 0 | `` | `` |  |  |
| H1 | 41475675906 | 2026-11-02T15:51:18Z | 2026-11-02T15:52:03Z | success | PUBLISHED | AFTER_CAS | 2 | 0 | 0 | `f3bdcd8f` | `e28f4089` |  |  |
| H1 | 41572694424 | 2026-11-03T03:31:21Z | 2026-11-03T03:32:08Z | success | PUBLISHED | AFTER_CAS | 2 | 0 | 0 | `0d482d8f` | `e1cdffa0` |  |  |

### 3. Lacunas de evidência: 4
Lacunas de observabilidade — **não** são incidentes de corrupção nem provas de publicação. As bloqueantes impedem uma conclusão de estabilidade (INCONCLUSIVO_OPERACIONAL); as informativas ficam registadas.
| Tipo | Bloqueante | Workflow | Run | Detalhe |
|---|---|---|---|---|
| GREEN_NO_RECEIPT_PUBLISH_STEPS_SKIPPED | não | results.yml | 41438630423 | verde, sem recibo; API confirma passos de publicação/recibo todos skipped (sem tentativa de publicação) |
| GREEN_NO_RECEIPT_PUBLISH_STEPS_SKIPPED | não | results.yml | 41523381521 | verde, sem recibo; API confirma passos de publicação/recibo todos skipped (sem tentativa de publicação) |
| GREEN_NO_RECEIPT_PUBLISH_STEPS_SKIPPED | não | results.yml | 41569910538 | verde, sem recibo; API confirma passos de publicação/recibo todos skipped (sem tentativa de publicação) |
| PAGES_NOT_VERIFIED | não | - | — | bytes servidos não obtidos (informativo; não bloqueia o veredito dos publicadores) |

### 4. Supersessão / starvation LAB V4
Ciclos: **288** · publicações efetivas: **268** · superados: **19** · sem evidência: **0** · taxa: **6.6%** · maior sequência consecutiva: **1** · tempo máximo sem publicação: **13.3 min** (('2026-11-02T19:14:14Z', '2026-11-02T19:27:33Z')) · recuperação após supersessão: n=19, máx 6.6 min, média 5.4 min · sequência aberta no fim: 0.
Sem gatilhos de alerta (3 consecutivas / >30 min / >25% com n≥8).

### 5. Integridade
- Baseline `b8bc46cab955` (main no início da janela, 2026-11-02T09:58:45Z): FT {'FINAL': 446, 'EXPIRED_UNVERIFIED': 423, 'PENDING': 308, 'IDENTITY_CONFLICT': 1}, H1 116, Telegram 13 `sent` — **FALHOU a verificação**: telegram_sent: 0 ≠ esperado 13
- **Fotografia A — fecho da janela** (`6e305f5406b1`, último push < fim): H1 certificados **126** (+10 novos); FT {'EXPIRED_UNVERIFIED': 605, 'FINAL': 475, 'PENDING': 238}.
- Journals append-only verificados (baseline→fecho): 19.
- Verificação histórica commit a commit (baseline→fecho; atribuição pela hora de push registada pelo GitHub, não pela data do commit): 710 commits, 130 transições de estado FT/H1/Telegram verificadas; violações transitórias: **0**.
- Leitores de produção: V4 eventos=1924, projeção=True; `docs/data.json` coerente=True; arquivo V6: ver secção 9; estado científico=INCONCLUSIVO.
- Commits publicados na main no período (pela hora de push): 710 (merges 8); multi-dono: 26; programa: 0; caminho desconhecido: 0; commits com recibo PUBLISHED ausentes da main: 0.
  - multi-dono (revisão manual; H1 re-renderiza `docs/data.json`): `f5672576` ['COLLECTOR', 'H1_RESULTS'], `47cb7348` ['COLLECTOR', 'H1_RESULTS'], `59a6c27e` ['COLLECTOR', 'LEGACY_FROZEN'], `922df9cc` ['COLLECTOR', 'H1_RESULTS'], `8e25f2eb` ['COLLECTOR', 'H1_RESULTS'], `44c379a0` ['COLLECTOR', 'LEGACY_FROZEN'], `24a70084` ['COLLECTOR', 'H1_RESULTS'], `aba23c27` ['COLLECTOR', 'LEGACY_FROZEN']
- **Violações de integridade: 0**

### 6. Telegram
- Modos efetivos nos logs do coletor: {'TG_DURABLE_INTENT=0': 206, 'TG_IGNORE_AUTH_BLOCK=0': 206}
- `data/e5-over25-notifications.json`: 0 → 74 {'sent': 74} novos=74
- Commits a `data/telegram-delivery-block.json` no período: 0 (persistência de bloqueio não exercitada).
- Sinais 429/401/403 nos logs: 0
- Exactly-once **não** é afirmado (AT-LEAST-ONCE com modo durável desligado).

### 7. Pages
- {'bytes': 'NOT VERIFIED', 'build_error': 'gh api repos/nunovinhas-creator/asianodds-h1-lab/pages/builds/latest: HTTP 403: {"message":"Access to this GitHub API path is not permitted through this proxy.","documentation_url":"https://docs.anthr', 'bytes_error': 'curl: (22) The requested URL returned error: 403\n'}

### 8. Fronteira temporal — fotografias A e B
- Fecho: `6e305f5406b1` = último push com hora de servidor < 2026-11-03T09:58:45Z (push às 2026-11-03T09:57:02Z); primeiro push ≥ fecho: 2026-11-03T10:01:15Z. Cadeia de 729 pushes contínua desde a baseline (A: 710, B: 19). Fonte: registo de atividade do GitHub (não a data dos commits).
- **Fotografia B — main na auditoria** (`b6002e6861e2`): 19 commits publicados após o fecho; violações posteriores ao fecho: **0** — fora dos indicadores e do veredito desta janela.
- Estado na auditoria: H1 126; FT {'EXPIRED_UNVERIFIED': 605, 'FINAL': 476, 'PENDING': 239}; projeção V4 True; `docs/data.json` coerente True.

### 9. Arquivo V6 (índice selado ≠ relatório derivado)
- Estado: **INDICE_SELADO_INTEGRO** — índice selado em sincronia; relatório de saúde atual
- Frescura do relatório de saúde na janela (limite superior via Git): 127 regenerações; 125 episódios desatualizados; mediana 1.0 min; máximo 19.4 min ('2026-11-02T23:52:39Z', '2026-11-03T00:12:00Z') (4 ciclos LAB); aberto no fecho: None min; limite de alerta 90 min.

### 10. Cobertura e orçamento da API
| Publicador | Segmentos completos | Esperados (API) | Obtidos | Terminados antes do início (lookback, metadados) | Na janela | Com recibo | Sem evidência completa |
|---|---|---|---|---|---|---|---|
| Coletor | 3/3 | 324 | 324 | 36 | 288 | 288 | 0 |
| LAB V4 | 3/3 | 324 | 324 | 36 | 288 | 288 | 0 |
| FT | 3/3 | 48 | 48 | 5 | 43 | 41 | 0 |
| H1 | 3/3 | 28 | 28 | 4 | 24 | 21 | 0 |
- Cobertura integral demonstrada (total_count = obtidos em todos os segmentos).
- API: 674 pedidos, 1 erros, limite 15000/h, mínimo restante 14362, espera por limites 0 s; ritmo máx. 8.0 pedidos/s. Início: {'limit': 15000, 'used': 53, 'remaining': 14947, 'reset': 1793704855}.
- Head auditada `b6002e6861e2` = main remota.

### 11. Bloqueios P0 e classificação
- Classificação operacional: **DEGRADADO — incidentes operacionais a investigar + INCONCLUSIVO_OPERACIONAL (lacunas de evidência)** (falhas não recuperadas=1, falhas sem recibo=2, recusas=1, alertas LAB=0, violações=0, arquivo V6=INDICE_SELADO_INTEGRO, alertas de atualização=0, lacunas de evidência bloqueantes=1, informativas=4).
- Bloqueios P0 conhecidos mantidos: Telegram AT-LEAST-ONCE (modo durável desligado; crash entre envio e publicação sem diagnóstico); recusas FT conhecidas sobre nova geração do índice de arquivo/partições.
- CI verde não é usado como prova de estabilidade. #107 permanece **OPEN**; o fecho exige avaliação explícita. #204 isolada; #63 INCONCLUSIVO.

