> **Histórico de integração (28/10/2026):** os 149 jogos / 13 FT abaixo são a baseline desta etapa, não a cobertura atual. A auditoria posterior detetou URLs SportScore com casa/fora invertidos; não usar esses marcadores sem validação independente. Os quatro conflitos desta fase foram analisados e resolvidos mediante evidência adicional, sem reescrever FT anteriores. Ver [integridade casa/fora](SOURCE-ORDER-INTEGRITY.md), [relatório atual](ft-results.json) e [arquitetura](ARCHITECTURE.md).

# Quarta fonte — SportScore para jogos não cobertos por BSD, TheSportsDB ou ESPN

**Prioridade: reduzir os resultados de jogos já terminados sem inventar ou assumir marcadores.**

## Evidência de viabilidade (28/10/2026)
- O LAB tinha 149 jogos observados, 13 FT, 75 futuros e **61 passados sem FT**.
- Os endpoints da SportScore foram sondados em GitHub Actions sem token nem exportação de dados. Um primeiro pedido falhou transitoriamente; o segundo devolveu 200 jogos finalizados de 27/10/2026. **10 observações coincidiam exatamente** nas equipas e hora. Não foi demonstrado ainda que fossem jogos novos ou que todos os marcadores pudessem ser usados; estes números são diagnóstico e não liquidações.
- A pesquisa de equipas retornou entradas com `name`, `slug` e `url`.

## Fluxo implementado
- Fonte documentada: `https://sportscore.com/api/v1/fixtures/?sport=football&date=AAAA-MM-DD&status=finished&limit=200`.
- Cache diário dentro da execução LAB (resultados da consulta não são guardados ou redistribuídos). O serviço limita o lote a 200: **não se presume cobertura completa**.
- Para jogos não encontrados no lote, opcionalmente consultar `/api/v1/search/?sport=football&q=HOME` e exigir exatamente um nome de equipa normalizado idêntico; só com o `slug` real devolvido pesquisar `/api/v1/fixtures/?team=slug&date=...`. Nunca construir slug a partir de nomes.
- Limite por run: 24 pedidos SportScore e 8 pesquisas de equipas. Esta fonte é adicional aos limites dos outros fornecedores, sem alteração do cron H1.
- Para verificar FT exige: casa/fora por ordem, nomes idênticos normalizados, hora ±90 minutos, `status=finished`, texto de estado explicitamente de FT/fim sem prolongamento ou penáltis, números inteiros não negativos e URL de fonte original sob domínio HTTPS `sportscore.com`. Em taças, o estado deve marcar explicitamente `FT` ou `Full Time`, não apenas `finished`.
- Ambiguidade de encontros, ausência de um marcador de tempo regulamentar, falha de API, diferença de resultados face a BSD/TSDB/ESPN → **não confirmar**. Todas as divergências ficam em `SCORE_CONFLICT`.
- `sportscore_only` rotula expressamente que um resultado é de uma única fonte. Não significa certificação de rentabilidade, aposta liquidada ou confirmação independente.

## Termos de utilização, attribution e privacidade
A [API pública SportScore](https://sportscore.com/developers/api/) permite uso gratuito em projetos abertos, **exigindo um link visível e dofollow «Powered by SportScore» em cada página que apresente dados dela**, conforme [termos de 23/04/2026](https://sportscore.com/developers/terms/). `docs/lab-results.html` inclui esse link estático, visível e com `rel="dofollow"`. A tabela de resultados identifica a fonte; não inclui extrações integrais das listagens nem pretende constituir uma API concorrente.

O fornecedor alerta que os resultados não devem ser usados isoladamente para decisões financeiras. O LAB **não calcula lucro ou aposta** nesta fase; antes de testar uma estratégia, a identidade e os resultados deverão ser verificados por mais do que uma fonte independente sempre que possível. Não fazer scraping de páginas nem contornar limites.

## Validação necessária
Testes unitários sintéticos cobrem estado, ET, penáltis, equipas, nomes, horas, paginação limitada, cache, pesquisas com slug confirmado, falhas e consenso de quatro fornecedores. Após o merge, ver workflow LAB FT e publicar apenas o número real de FT novos. Se a fonte rejeitar todos os jogos por falta de marcador 90', anotar a limitação e não a ultrapassar arbitrariamente.

## H1 protegido
Não modificar `h1lab/results.py`, `bsd.py`, `core.py`, `cli.py`, `notify.py`, `bot.py`, `.github/workflows/collect.yml`, scheduler Cloudflare, `data/state.json`, `data/results.csv` nem os alertas Telegram. Todos os resultados continuam num ledger isolado `data/lab/ft-ledger.json` e relatório `docs/lab/ft-results.json`.
