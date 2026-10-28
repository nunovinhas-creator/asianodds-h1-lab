# Recuperação FT V9 — FotMob por data (LAB isolado)

**Diagnóstico empírico, 28/10/2026.** A BSD + Monte-Carlos encontrou 0 IDs para os jogos pesquisados; ESPN não tem mapeamento para numerosas taças/reservas; SportScore marcou 14 resultados de taça como `cup_regulation_unverified`; TheSportsDB atingiu HTTP 429.

Foi realizado um teste read-only no GitHub Actions:
https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40667619390

| Fonte | 27/10 | 28/10 |
|---|---:|---:|
| FotMob (`/api/data/matches?date=YYYYMMDD`) | 220 jogos | 271 jogos |
| Sofascore (calendário) | HTTP 403 | HTTP 403 |

O cruzamento da lista FotMob com o ledger anterior identificou **13 jogos** com equipas e início UTC consistentes, dos quais **11 tinham indicação `FT`** e dois tinham `Pen`. Um dos 11 é um jogo SportScore com conflito casa/fora já bloqueado, portanto **no máximo dez jogos eram imediatamente elegíveis a novos FT** nesse snapshot (antes de confirmação no pipeline). A API da FotMob é pública mas não oficialmente documentada como API de terceiros; pode mudar ou indisponibilizar-se. Não contornar 403 nem medidas anti-bot.

## Implementação

`h1lab/lab_fotmob.py` lê **uma única página por data**, partilhada entre todos os jogos observados, com limite máximo de três datas por ciclo. Não pede token nem acede a cookies de conta. Recusa respostas malformadas, ausentes ou excessivas.

Validação obrigatória, sem correspondência aproximada:
1. `match_key` mantém-se AsianOdds e **nunca é um ID FotMob**.
2. Equipas casa/fora pela ordem correta, `EXACT` ou `CORE_NAME` já auditado, e início UTC ±90 minutos.
3. Único jogo na janela; rejeita encontros duplicados, equipa repetida e ordem invertida, inclusive quando o primeiro candidato tem nomes exatos.
4. `started=true`, `finished=true`, `cancelled!=true`, estado final **expressamente `FT` ou `Full Time`**. `Pen`, `AET`, estados desconhecidos e marcadores ambíguos **não liquidam**.
5. `home.score` e `away.score` inteiros não negativos, `status.scoreStr` se presente coerente, IDs numéricos válidos. O URL de origem liga ao `matchId` FotMob.
6. Conflito de golos com BSD/ESPN/TheSportsDB/SportScore fica `SCORE_CONFLICT` sem marcador automático. Os quatro `SOURCE_ORDER_CONFLICT` existentes não são reprocessados automaticamente.
7. A integração é exclusivamente LAB: nenhuma regra H1, cron Cloudflare, Telegram ou ficheiro H1 sofre alteração.

A reconciliação `LOOKUP_SOURCE_VERSION=9` agenda uma reconsulta dos pendentes com o fornecedor novo; continua a limitar-se a 30 jogos/ciclo e intervalo normal de quatro horas depois de consultados. O relatório FT inclui `fotmob_search.requests`, `cached_days`, `verified_in_run` e motivos. Não declarar ganhos de cobertura só porque o parser encontra candidatos: consultar o workflow **após merge**.

## Questões seguintes

- Dois jogos FotMob com `Pen`: investigar detalhe que forneça golos `normaltime` explicitamente; não inferir que o marcador apresentado já é 90 minutos.
- SportScore com casa/fora invertidos: revisão independente e documentada antes de recuperar.
- Onde FotMob não tem fixture: fontes específicas por competição, com proveniência auditável e respeito pelos termos de acesso.
