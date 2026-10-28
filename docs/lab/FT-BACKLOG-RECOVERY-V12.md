# MASTER BRAIN — FT backlog: diagnóstico e recuperação controlada V12
**Data de auditoria:** 28/10/2026, 17:25 UTC. **Estado:** operativo em sombra; nenhum FT inferido.

## Fotografia base (antes da recuperação)

- Ledger LAB: 338 jogos observados, **75 FINAL**, 263 ainda PENDING.
- Dos não liquidados: **178 FUTURE**, **20 dentro das três horas pós-KO**, e **65 efetivamente passados há mais de três horas sem prova FT** (fotografia do relatório oficial).
- Ao atualizar o relógio de observação cerca das 17:25 UTC, havia pelo menos **71 jogos** anteriores a KO+3h, incluindo 6 ainda sem `checked_at`. A contagem varia com o relógio e os novos jogos; consultar sempre `docs/lab/ft-backlog.json`.
- Duas datas UTC dominavam os atrasados: **27/10 e 28/10**. Os últimos motivos de consulta indicavam sobretudo `monte_no_exact_archive_match`, `espn_unsupported_competition`, `sportscore_no_exact_match`, `goal_identity_no_core_match` e `openfoot_identity_no_core_match`. Tais motivos não permitem inventar pontuações.
- O ficheiro `data/lab/ft-api-audit.json` conservava uma operação autenticada em 28/10 às 14h30 UTC com **GOAL ativa** (1 dia, 4 verificações), **OpenFoot ativa** (1 dia, zero verificações) e **API-Football desligada**. A amostra mais recente `ft-results.json` veio de um evento `push`, em que, por política de segurança de quotas, GOAL/OpenFoot/API-Football **não são ativadas normalmente**.
- Ao consultar as 100 execuções GitHub mais recentes, as únicas reconciliações FT visíveis eram dois `push`, às 16h38 e 16h53 UTC. Não há nessa amostra comprovação de que o cron `12,42 * * * *` tenha disparado recentemente. **Não atribuir automaticamente isto a segredo inválido**: as credenciais só são testadas quando a chamada correspondente acontece.

## Correções deste passo

1. Um único `push` de integração expressamente identificado pelo marcador `[ft-recovery-v12-once]` ativa a recuperação de **até 30 jogos**, mesmo com cooldown normal de 4h, sem tocar nos FINAL.
2. Guardas cumulativas: `LAB_FT_BACKLOG_ONCE_20261028=true`, workflow GitHub exato `Lab - Reconcile FT for all observed matches`, evento `push` e branch `refs/heads/main`. Um `push` normal mantém as três APIs reservadas ao `schedule`.
3. Na recuperação, os adaptadores ativos têm **máximo de 3 datas API-Football, 2 GOAL e 2 OpenFoot**, dentro dos seus limites existentes. Outros limites, como 30 jogos/ciclo, BSD, SportScore e TSDB, continuam aplicáveis; sem aumentar a periodicidade de execução.
4. Ficheiro `docs/lab/ft-backlog.json` atualizado no workflow de reconciliação; é uma vista derivada, não altera `ft-ledger.json` nem o registo de provas. Apresenta contagens mutuamente exclusivas e o diagnóstico do último lote de pedidos. A CI compara as contagens da vista com o ledger e `ft-results.json`.
5. Os resultados são inscritos apenas após identidade exata ou `CORE_NAME` já validado, KO compatível, marcador regulamentar 90m e inexistência de fontes contraditórias. Pontuações de prolongamento e penáltis não substituem o FT. Jogos ambíguos ficam em revisão.

## O que ainda tem de ser provado

- Confirmar uma execução `push` FT pós-merge com `LAB_FT_API_AUDIT one_time_backlog_recovery_v12`, os números reais de pedidos GOAL/OpenFoot/API-Football, `LAB_FT_PUBLISHED` e novo `ft-results.json`.
- Quantificar **novos** FT confirmados por fonte e os remanescentes que as APIs não conseguem identificar.
- Corrigir autonomamente o agendamento GitHub se as execuções `schedule` continuarem ausentes. O cron GitHub é *best effort*; este merge não substitui o agendamento nem demonstra que ficou estável. Uma solução Cloudflare pode exigir publicação adicional do Worker.
- Realizar pesquisa guiada de correspondências individuais para os restantes jogos, usando prova pública de equipas/horários e **sem aliases fuzzy automáticos**.
- Corrigir a captura pré-KO em caso de aviso com apenas 25 segundos de antecedência, se for requisito conseguir esses sinais: o intervalo H1 de 5 min não é suficiente para uma garantia de 99% de todos os avisos imediatos, independentemente das APIs de resultados.

**Não confundir:** a taxa de FT históricos do LAB não é a taxa de FT prospetivos do V6. Prospective V6 exige `known_at` verdadeiro, registo formal anterior, FT posterior temporalmente comprovado, SHA da previsão e gates de cobertura. Não promover modelos, ROI ou sinais de apostas com este trabalho.

## Links de controlo

- [Resultados LAB](ft-results.json)
- [Fila FT atrasada](ft-backlog.json)
- [Auditoria de chamadas autenticadas](../../data/lab/ft-api-audit.json)
- [Issue de acompanhamento V6](https://github.com/nunovinhas-creator/asianodds-h1-lab/issues/63)
- [Workflow FT e quotas](../../.github/workflows/lab-ft-results.yml)
