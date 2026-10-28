# LAB — Ampliação de cobertura da pesquisa FT dirigida (28/10/2026)

**Prioridade:** jogos já disputados ainda sem marcador regulamentar validado.

## Problema observado
A SportScore devolve uma listagem diária que pode parar nos primeiros 200 resultados. O motor LAB já faz pesquisa adicional da equipa por nome exato e depois consulta o calendário usando o slug devolvido pelo fornecedor. Contudo, o limite anterior de **8 pesquisas dirigidas e 24 pedidos por execução** deixava muitos dos 30 jogos da fila sem pesquisa específica.

## Alteração
- Mantém-se o limite de **30 jogos por ciclo** e a agenda de **30 em 30 minutos**.
- O orçamento SportScore sobe para **45 pedidos totais e 20 pesquisas de equipas** por ciclo. O cache de consultas idênticas permanece ativo, não há scraping nem listas republicadas.
- A pesquisa dirigida só é feita usando um slug efetivamente devolvido pelo fornecedor para um nome de equipa normalizado **idêntico**. Não gera slugs ou equipas por aproximação.
- A especificação pública SportScore informa um limite aproximado de **10 000 pedidos/24h/IP** e tolerância a rajadas de ~15/s. Mesmo com 48 ciclos/dia × 45 pedidos/ciclo, o teto desta Action é de 2160 pedidos/dia, antes de descontar cache e ciclos sem jogos elegíveis; inferior ao limite anunciado. A atribuição visível SportScore mantém-se.
- `LOOKUP_SOURCE_VERSION=5` autoriza uma **única reconsulta extraordinária por jogo pendente** após a ampliação da pesquisa. Depois, regressa ao cooldown normal de quatro horas, sem repetição abusiva.
- Não altera a retenção de resultados, critérios rigorosos de identidade, integridade de casa/fora, distinção de 90 minutos, nem tratamento de jogos de taça.
- Continuam bloqueados os quatro jogos cuja URL do fornecedor demonstrou inversão casa/fora.

## Confirmação
Testes unitários (budget e retry) e CI completo, seguidos de uma execução real do LAB na `main`. Reportar número de jogos consultados, novos FT com fonte, pedidos SportScore e respetivos limites. Não deduzir lucratividade com esta amostra.

Sem alterações ao H1, Telegram, cron de cinco minutos, picks ou resultados oficiais.
