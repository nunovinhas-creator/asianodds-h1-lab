# PRIORIDADE MÁXIMA — Cobertura FT, LAB v3

**Sem modificações ao motor H1.** A investigação de odds aguarda resultados observados. Este plano mede resultados por jogo, não aposta, EV ou ROI.

## Diagnóstico antes da mudança
No ledger publicado após a PR #28, às 07h30 UTC de 28/10/2026 havia 147 jogos e 7 FT. A decomposição por datas reais (kickoff) era:
- **73 jogos ainda futuros** — não devem ser contabilizados como resultados em atraso.
- **7 jogos com FT** e fonte rastreável.
- **67 jogos passados há pelo menos três horas, sem FT**, sendo 14 nunca consultados, 20 já elegíveis a nova tentativa e 33 ainda no cooldown de 4 horas.

O filtro `team_name` da BSD cobre parte do universo mas é seletivo (88 competições). A pesquisa BSD por data já recuperou 1 resultado adicional, mas não resolve tudo. O endpoint gratuito `searchevents.php` da TheSportsDB devolve no máximo 1 resultado por pedido e há erros/limitação de requests. Não confundir cobertura da API com o universo real de jogos.

## Alterações nesta PR
1. Workflow LAB FT executa **duas vezes por hora** (cron `12,42 * * * *`) em vez de duas em duas horas, sem aumentar frequência do H1; continua com mutex LAB próprio. Recolhe no máximo 30 jogos elegíveis por execução (hard cap 30). Não consulta jogos futuros nem jogos nos primeiros 180 minutos após início.
2. TheSportsDB agora tem um **adaptador específico LAB** que espaça pedidos no mínimo 2,3 segundos (~26 pedidos/minuto) para respeitar o limite público de 30/min; ao receber HTTP 429, suspende novas consultas TheSportsDB nesse run. Conta pedidos/erros. O código H1 original não é modificado.
3. Uma **terceira fonte complementar ESPN** utiliza o endpoint público `site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates=YYYYMMDD` quando o alerta contém uma competição mapeada explicitamente. Caching por liga/data no run; no máximo 12 chamadas distintas. Este endpoint é **não oficial e pode mudar**, portanto nunca é a fonte única de verdade para jogos ambíguos.
4. Validar na ESPN equipa da casa e equipa visitante em ordem, igualdade exata de nomes normalizados, hora de início no máximo ±90 minutos, marcador inteiro, conclusão explícita de tempo regulamentar (FT/Full Time), sem prolongamento nem penáltis, e evento único. O resultado transporta URL do evento ESPN para auditoria.
5. **Conflito entre quaisquer fontes** (BSD, TheSportsDB, ESPN) → `SCORE_CONFLICT` sem resultado automático. Uma fonte confirmada apenas fica com evidência `espn_only`, `bsd_only`, ou `thesportsdb_only`. Duas ou três em acordo ficam com evidência específica.
6. O relatório passa a incluir **`timing_counts`** distinguindo FUTURE, IN_3H_GRACE, FINAL_RECORDED, ELIGIBLE_NEVER_QUERIED, ELIGIBLE_RETRY_DUE, ELIGIBLE_COOLDOWN e bloqueios. A página visual destaca resultados verdadeiramente em atraso, sem misturar os futuros.

## Limites e riscos
- Terceira fonte ESPN utiliza API pública sem contrato de estabilidade. Não se inventa ID nem alias de equipa, nem se assume que um torneio não mapeado está coberto. Resposta malformada não confirma nada.
- Jogos de equipas de reservas, taças e ligas locais podem não ter cobertura em nenhuma fonte gratuita. **Não inventar resultados para elevar a percentagem**.
- TheSportsDB limitado a 30/min pela documentação oficial e 1 resultado/event-search no plano free: https://www.thesportsdb.com/documentation .
- Lista pública de slugs ESPN para futebol: https://github.com/0xShakhawat/ESPN-API/blob/main/docs/sports/soccer.md . O endpoint não é oficialmente suportado.
- BSD documentação: https://sports.bzzoiro.com/docs/football/events/ .
- O custo de consultas fica limitado por execução; a agenda de 30 minutos aumenta tentativas regulares em comparação com o cron original de duas horas. Reavaliar a cadência após estabilizar a cobertura.
- Os resultados `FINAL` já registados mantêm a sua proveniência. O motor não regrava automaticamente resultados que já eram finais apenas porque foi adicionada uma terceira fonte.

## Prova exigida
`python -m unittest discover -s tests -v` e verificações CI: mocks de resultados ESPN, rejeição de ET e penáltis, divergência entre três fornecedores, classificação de jogos futuros, limites de consultas, throttling e regressões H1. Depois do merge: consultar logs do primeiro run real e relatar **quantos jogos passaram a FT** (sem atribuir automaticamente ganhos a uma alteração se vários fatores mudaram). Se a ESPN não recuperar qualquer jogo, indicar 0 e documentar limitações.

## Ficheiros protegidos
Não alterar: `h1lab/core.py`, `cli.py`, `bot.py`, `notify.py`, `results.py`, `bsd.py`, `session.py`, collector, H1 results workflow, cron Cloudflare, `data/state.json`, `data/results.csv`, `data/result_audit.json`, Telegram ou regras de picks.
