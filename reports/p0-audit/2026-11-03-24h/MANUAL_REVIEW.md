# Revisão manual — auditoria P0 24h (MASTER BRAIN, 2026-11-03)

Janela semiaberta `[2026-11-02T09:58:45Z, 2026-11-03T09:58:45Z)`; baseline `b8bc46cab95549a3f43a5b05dd3c5693af723398` (merge #206).
Fecho (registo de atividade da main, hora de servidor): `6e305f5406b1` pushed 2026-11-03T09:57:02Z; push seguinte 10:01:15Z.

## Vereditos (ambos preservados)
- **Veredito bruto do auditor V4:** `DEGRADADO — incidentes operacionais a investigar + INCONCLUSIVO_OPERACIONAL (lacunas de evidência)` (ver `RAW_AUDITOR_REPORT.md`, inalterado).
- **Revisão manual fundamentada:** `DEGRADED`.

## Falso positivo Telegram (`BASELINE_INVALID: telegram_sent 0 ≠ 13`)
Causa: `tools/p0_stability_audit.py` (V4) importa `scripts.publication_ownership.TELEGRAM_LEDGERS` da **árvore de trabalho atual**.
Após a PR #209 (merge 2026-11-02T18:35:31Z, dentro da janela) essa tupla passou a ser `(E5_LEDGER,)`; `data/e5-over25-notifications.json`
só foi criado em 18:35:55Z, logo não existe na baseline → contagem 0.
Na baseline, `TELEGRAM_LEDGERS = (THREE_LEDGER, TWO_LEDGER)`:
- `data/three-total-moves-notifications.json`: 6 `sent`
- `data/two-up-total-notifications.json`: 7 `sent`
- total **13** = valor esperado ✔

Verificação commit a commit (first-parent, baseline→fecho; `telegram_ledger_check.py`, saída em `telegram_ledger_check.out`):
legacy 13→18 (+5, último a 18:31:12Z, antes da #209), E5 0→74; 0 entradas removidas, 0 `sent` alterados, 0 `telegram_message_id` duplicados.
Sem esta lacuna, as lacunas bloqueantes passam a **0**.

Os commits multi-dono `COLLECTOR+LEGACY_FROZEN` (59a6c27e, 44c379a0, aba23c27, …) são anteriores à #209: nessa altura esses ledgers pertenciam ao coletor. Esperado.

## Incidentes (todos fail-closed; 0 violações de integridade) — excertos em `incident-log-excerpts.txt`
| Publicador | Run | Hora | Causa | Recibo |
|---|---|---|---|---|
| Coletor | 41479757276 | 16:16Z | GitHub `500 Internal Server Error` no push; 2 alertas não publicados nesse run; bundle; `telegram_requests=0`, `resend_risk=NONE_KNOWN` | sim (`PUSH_REFUSED`) |
| LAB V4 | 41507672240 | 19:12Z | `INCOMPATIBLE_PROGRAM h1lab/e5_notify.py` — merge #211 37 s antes | sim (`REFUSED`) |
| FT | 41476501130 | 15:56Z | `UnsafeFTPublication: Unknown concurrent path data/lab/v6-memory-evidence-2026-11.jsonl` | **não** |
| FT | 41502044305 | 18:35Z | `UnsafeFTPublication: H1 notification receipt invalid: data/e5-over25-notifications.json` (push do merge #209) | **não** |

## Merges de programa na janela (ferramenta reporta `programa: 0` porque não classifica merges)
#207 (autorizada, 9acde7e6), #208 (23bcec79), #209 (0b4a9591), #210 (61706206), #211 (f33a779a), #212 (b22c5c0b), #214 (9fac5467), #213 (19ccf744) — todas pelo proprietário.

## Limitações de observabilidade
- **Pages não verificadas:** `pages/builds/latest` e bytes servidos → HTTP 403 do proxy da sessão (informativo).
- FT sem recibo nos caminhos `UnsafeFTPublication` (2 runs).
- A execução agendada das 10:10Z (sessão `session_01UsVWBEPvmBonxwNhd1UkDC`) não teve acesso à API do GitHub e não auditou; esta auditoria foi executada manualmente às ~10:35Z na sessão `session_01UsVWBELmkXqByCprnN4EwN`.

## Fundamentação de DEGRADED
Cobertura integral (total_count = obtidos em todos os segmentos), head auditada = main remota, baseline confirmada manualmente, 0 violações;
mas 1 falha não recuperada (coletor), 1 recusa de integridade (LAB) e 2 falhas FT sem recibo ⇒ não ESTÁVEL; não INCONCLUSIVO porque a única lacuna bloqueante foi refutada com prova.
