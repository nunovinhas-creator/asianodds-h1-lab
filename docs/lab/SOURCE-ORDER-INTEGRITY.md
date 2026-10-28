# Correção crítica — integridade casa/fora no resultado SportScore

O LAB confirmou 25 resultados FT no run de 28/10/2026 às 08:09 UTC. Numa auditoria ao URL original de alguns dos novos resultados, foram encontrados **dois casos em que o endereço do jogo na SportScore identifica a ordem das equipas invertida face à resposta da API**.

Casos detetados, por chave dos alertas:
- `2026-10-27,10102013,10048381`: API apresentou Montevideo City Torque Reserves em casa contra Albion FC Reserves; URL original indica Albion FC Reserves vs Montevideo City Torque Reserves.
- `2026-10-27,70933,35866`: API apresentou Ludogorets Razgrad II em casa contra FC Dobrudzha Dobrich; URL original indica FC Dobrudzha Dobrich vs Ludogorets Razgrad II.

**Não é seguro usar o marcador da API nesses jogos sem saber a qual equipa atribuir cada golo.** O LAB não inverte automaticamente o resultado — isso também seria uma inferência sem confirmação.

## Correção
- Nova função pura `source_order_conflict` valida o URL HTTPS da SportScore; apenas identifica conflito quando **ambas as equipas da URL coincidem exatamente, mas em ordem inversa**, com os nomes que a própria SportScore devolveu para o evento. URL de estrutura desconhecida não é interpretado.
- O validador da SportScore passa a rejeitar estes jogos com `source_home_away_conflict`.
- **Retroatividade:** o reconciliador percorre os FT guardados com evidência exclusivamente SportScore e, para os casos provadamente inversos, retira o marcador dos dados publicados e muda o estado para `SOURCE_ORDER_CONFLICT`. Não trata o jogo como perdido nem o aceita em estudos.
- O relatório e a página pública mostram essa condição, sem golos, como caso bloqueado para revisão documental; continuam a existir em `match_key`.
- Os jogos de ordem correta continuam FINAL e não se fazem novos pedidos só porque já há FT.
- Testes sintéticos e exemplos reais abrangem os dois URL inversos, um URL na ordem correta, URL não interpretável e correção retroativa no ledger.

Não alteramos H1, cron Cloudflare, Telegram, picks nem resultados oficiais. **Indicadores anteriores à correção devem ser considerados provisórios para os dois jogos identificados.** Para os voltar a liquidar será necessária evidência independente do marcador aos 90 minutos e da orientação casa/fora.
