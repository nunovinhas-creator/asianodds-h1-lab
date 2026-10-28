# Auditoria BSD — cobertura de 30 ligas ORUSEYE (27/10/2026)

**Estado:** evidência histórica concluída e preservada, sem integração operacional no H1.

- Data da recolha: 2026-10-27T15:28:34+00:00.
- API: BSD / Bzzoiro, catálogo com 96 ligas devolvidas, paginação completa: sim.
- Ligas ORUSEYE avaliadas: 30; correspondência única: 26; com todos os quatro indicadores na amostra: 26.
- Pedidos reais à BSD: 236. O plano de recolha incluiu janela futura de 21 dias e janela histórica de 14 dias; foram verificados no máximo 3 eventos por liga.
- Ligas ausentes **nesta recolha**: GER3, NED2, UKR1, SRB1.
- Execução: GitHub Actions [40531326688](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40531326688).
- Relatório integral: [bsd-europa-audit.json](./bsd-europa-audit.json); saída textual: [bsd-europa-audit.log](./bsd-europa-audit.log).
- Script de auditoria: [tools/bsd_europa_audit.py](../tools/bsd_europa_audit.py); catálogo de entrada: [config/oruseye_europe30.json](../config/oruseye_europe30.json).

## Mapeamento histórico observado

| ORUSEYE | Liga BSD | ID BSD |
|---|---|---:|
| ENG1 | Premier League | 1 |
| ENG2 | Championship | 12 |
| ENG3 | League One | 86 |
| ESP1 | La Liga | 3 |
| ESP2 | Segunda División | 38 |
| GER1 | Bundesliga | 5 |
| GER2 | 2. Bundesliga | 94 |
| ITA1 | Serie A | 4 |
| ITA2 | Serie B | 100 |
| FRA1 | Ligue 1 | 6 |
| FRA2 | Ligue 2 | 89 |
| POR1 | Liga Portugal Betclic | 2 |
| POR2 | Liga Portugal 2 | 88 |
| NED1 | Eredivisie | 10 |
| BEL1 | Pro League | 14 |
| SCO1 | Scottish Premiership | 13 |
| TUR1 | Trendyol Super Lig | 11 |
| GRE1 | Stoiximan Super League | 24 |
| AUT1 | Austrian Bundesliga | 96 |
| SUI1 | Super League | 15 |
| DEN1 | Danish Superliga | 84 |
| NOR1 | Eliteserien | 54 |
| SWE1 | Allsvenskan | 26 |
| POL1 | Ekstraklasa | 25 |
| CZE1 | Czech First League | 99 |
| ROU1 | Superliga | 23 |

**Sem correspondência única na execução:** GER3, NED2, UKR1, SRB1. Não interpretar esta ausência como prova de que nunca existam dados nessas ligas.

## Interpretação e limitações

A auditoria é **exploratória e apenas de leitura**. Verifica correspondência de país/liga, encontros futuros, eventos concluídos e até três amostras por liga por ID (listagem, detalhe e consulta por equipa). A existência de um jogo na BSD não garante correspondência com IDs de jogos provenientes do AsianOdds. Não autoriza liquidação automática de H1, escolha de apostas nem resultados de jogos particulares.

Os indicadores `ft90_goals` testam marcadores inteiros com `status=finished` nas amostras de liga, mas este ensaio não prova, por si só, a distinção entre tempo regulamentar, prolongamento e penáltis para qualquer competição futura. Essas salvaguardas continuam a pertencer aos validadores específicos do LAB/H1.

O endpoint de época devolveu o objeto `season` aninhado; o script original registou alguns campos de `current_season` ao nível errado (valores nulos). Os dados de esquema completos ficaram no JSON, mas esses nulos não devem ser interpretados como inexistência de época.

## Operação daqui em diante

O workflow [bsd-europa-audit.yml](../.github/workflows/bsd-europa-audit.yml) é **exclusivamente manual**, com confirmação explícita do orçamento de pedidos antes da execução. A execução escreve um artifact temporário (30 dias), não altera `main`, resultados, H1, Telegram, cron ou dados da produção. Não existem triggers `push` ou `schedule`.

Esta documentação preserva os resultados históricos mesmo depois de eliminar a branch experimental `feature/bsd-europa-audit`.
