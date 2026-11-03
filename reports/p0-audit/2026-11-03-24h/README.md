# Evidência auditável — auditoria P0 24h (#107)

| Ficheiro | Conteúdo |
|---|---|
| `RAW_AUDITOR_REPORT.md` | Relatório integral produzido pelo auditor V4, inalterado (veredito bruto) |
| `auditor-output.json` | JSON integral produzido pelo auditor |
| `auditor-stdout.log` | Saída do auditor |
| `MANUAL_REVIEW.md` | Revisão manual (veredito revisto, falso positivo Telegram, incidentes) |
| `telegram_ledger_check.py` / `.out` | Verificação independente dos ledgers Telegram baseline→fecho |
| `incident-log-excerpts.txt` | Excertos dos logs dos 4 runs com incidente |
| `SHA256SUMS` | Somas de verificação |

Ferramenta: commit `db2d40685e787b0f5af0febb0b51e69ebf39971b`, `tools/p0_stability_audit.py`
sha256 `46f0fafe9bf817c3375c9c49aeac274684eac57e5a449f97c19ba01959b5eb51`.
Comando: `python p0_audit.py --label 24h --start 2026-11-02T09:58:45Z --hours 24` (exit 0; 674 GET, 1 erro = Pages 403, 0 s de espera).
