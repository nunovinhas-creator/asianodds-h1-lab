# LAB FT V11 — GOAL API + OpenFoot Starter

## Dados de produção e documentação

**GOAL API — diagnóstico autenticado**: execução https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40673147644.
O pedido `/v1/results/date/2026-10-27?limit=100&offset=0` respondeu com **294 resultados**, sem paginação no envelope. Estados: 271 `FINISHED`, 17 `AFTER_PEN`, 6 `AFTER_ET`. Os dados contêm `homeTeamFtScore`, `awayTeamFtScore` separados de `homeTeamScore`, `homeTeamExtraScore` e `homeTeamPenaltyScore`. Um jogo terminado após penáltis tinha FT `1-1`, resultado exposto `2-1`, penáltis `5-3` (exemplo do esquema, não é um jogo AsianOdds).

**OpenFoot Starter — diagnóstico autenticado**: execução https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40672472059.
`/v1/matches?date=2026-10-27&status=finished&limit=100` retornou 63 jogos em 120 competições pesquisadas, lista completa na data, sem `next_cursor`, `total_count=63` e `authenticated=true`. A Taça da Roménia tem quatro resultados nesse dia; dois deles estavam pendentes com nomes AsianOdds divergentes, pelo que não se pode converter por heurística. Para os jogos OpenFoot exige-se expressamente `period=FT`, `status=finished` e marcador inteiro.

## Segurança de correspondências

Nenhuma pontuação é registada sem dois clubes casa/fora na ordem correta, horário UTC ±90 min, par `EXACT` ou `CORE_NAME` e ausência de duplicados/reversos/colisão de clubes no dia. Os jogos não encontrados ou com identidade curta/variante não corroborada ficam pendentes. `AFTER_ET`/`AFTER_PEN` da GOAL API **podem** ser avaliados apenas com as colunas FT expressas; jamais se usam os resultados finais do prolongamento/penáltis. Na OpenFoot, estados que não provem os 90 minutos ficam pendentes.

A GOAL API fornece um identificador próprio consultável em `/v1/fixtures/{apiId}`. A OpenFoot fornece o URL da consulta datada/competição como proveniência (o identificador exato é validado). **Não considerar GOAL, OpenFoot, FotMob e outras fontes como confirmação estatisticamente independente sem auditar os seus feeds subjacentes**: OpenFoot publica alguns resultados derivados de FotMob. Conflitos de marcadores entre fornecedores são postos em `SCORE_CONFLICT` e nenhuma correspondência pode reabrir automaticamente os quatro conflitos históricos `SOURCE_ORDER_CONFLICT`.

## Quotas e credenciais

Os secrets no GitHub são **`GOAL_API_KEY`** e **`OPENFOOT_API_KEY`** (nunca impressos). A GOAL API usa Bearer na URL oficial `https://api.goal-api.com/v1/results/date/YYYY-MM-DD`; OpenFoot usa Bearer em `https://openfootapi.com/v1/matches`. Ambos fazem cache de uma página por data **até duas datas por execução do LAB**. Com 48 execuções agendadas num dia, o limite teórico é 96 pedidos diários por fornecedor: GOAL abaixo dos 1.000/dia anunciados; OpenFoot até 2.976 pedidos em 31 dias, abaixo dos 5.000/mês anunciados. Não há recolhas contínuas em WebSocket; H1, Cloudflare, Telegram e apostas nunca são tocados.

O relatório FT adiciona `goal_search`, `openfoot_search` com `configured`, `poll_enabled`, `requests`, `verified_in_run` e diagnósticos. `lookup_source_version=11` aplica-se só quando uma destas duas fontes está realmente ligada; permite reconsultar de imediato os pendentes sem regravar FT previamente confirmados. Mantém-se 30 jogos/ciclo e cooldown de 4h por jogo.

## Fontes oficiais

- https://goal-api.com/documentation
- https://goal-api.com/openapi.json
- https://openfootapi.com/docs

**Antes de declarar ganhos**, consultar o workflow de ativação pós-merge e comparar o `data/lab/ft-ledger.json` com o snapshot anterior. Um fornecedor validado e 294 jogos disponíveis não são prova de 294 resultados AsianOdds.

## Dois pares revistos estritamente (não são aliases gerais)

O catálogo autenticado da OpenFoot para a Taça da Roménia de 27/10/2026 permite rever apenas estes dois eventos, ambos presentes como **PENDING** no LAB antes da V11:

- `2026-10-27,95935,1688`: AsianOdds `AFC Progresul Spartac '44` – `FC Petrolul Ploieşti` (15:00 UTC), OpenFoot `Progresul Spartac` – `Petrolul Ploiești`.
- `2026-10-27,22207,24472`: AsianOdds `FCM Uzina Textila Arad (UTA)` – `FC SA Botoşani` (17:00 UTC), OpenFoot `UTA Arad` – `Botoșani`.

A exceção exige a identidade exata original, a chave `match_key`, o horário original, os nomes OpenFoot exatos, `competitionId=comp_cupa_romaniei_ro`, início com desvio máximo de cinco minutos, ausência de outros clubes/jogos na janela e FT explícito. A proveniência aparece como `REVIEWED_PAIR`; **não aplicar estas variantes a outros jogos, dias ou competições**.
