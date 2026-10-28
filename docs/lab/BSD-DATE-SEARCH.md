> **Histórico 28/10/2026:** a baseline abaixo de 138 jogos e 3 FT corresponde ao início do processo de recuperação, não ao estado atual. [ft-results.json](ft-results.json) registava 267 jogos e 63 FT em 28/10, 11:15 UTC. A procura BSD por data é hoje apenas uma das fontes do [pipeline LAB](../../.github/workflows/lab-ft-results.yml); a [ponte FT LAB → H1](../../h1lab/lab_promotion.py) liquida sinais existentes. Ver [arquitetura canónica](ARCHITECTURE.md).

# UNDER TESTE LAB — Pesquisa BSD alternativa por data

## Problema observado e baseline
Relatório real em 28/10/2026 05:55 UTC: 138 jogos únicos observados, apenas 3 FT e 135 sem FT verificado. As 40 consultas já efetuadas pelo LAB tinham muitos diagnósticos `bsd_no_exact_match` após filtrar pelo nome da equipa. Esse diagnóstico **não prova** que o fornecedor não tenha o encontro. Uma parte da ausência de resultados pode derivar de variações de nomes no índice `team_name`.

Documentação oficial BSD: `GET /api/v2/events/` suporta `date_from`, `date_to`, `status`, `limit` (até 200) e `offset`. O nome da equipa é um filtro fuzzy. Fonte: https://sports.bzzoiro.com/docs/football/events/

## Desenho técnico e garantia de integridade
1. Em `scripts.lab_results`, tentar **primeiro** a pesquisa BSD existente `h1lab.bsd.find_result` (filtrada por nome + data), sem a alterar.
2. Apenas quando há `bsd_no_exact_match` ou `bsd_paginated_requires_review`, fazer uma pesquisa **apenas por data UTC + status=finished**, limitada a no máximo 3 datas por execução e até 3 páginas de 200 eventos por data (máximo absoluto configurável 4×4). Todas as pesquisas da mesma data usam um cache de memória **local apenas ao run**.
3. **Só se todas as páginas forem obtidas** e existir exatamente uma correspondência por *nome ordenado das equipas e hora* usando `bsd.matches_identity`, consultar `/api/v2/events/{id}/` e validar o marcador regulamentar usando `bsd.regulation_result`. Duas correspondências, paginação incompleta, resposta inválida ou identidade divergente → **não confirmar FT**.
4. Usar apenas o marcador de 90 minutos + descontos. Não interpolar ou aceitar nomes parecidos sem identidade exata; não inventar jogos nem resultados.
5. Controlar pedidos: a pesquisa de 20 jogos continua com limite H1/LAB existente; até 9 consultas adicionais ao índice BSD por data (com limites predefinidos), mais detalhe apenas dos candidatos unívocos. A própria pesquisa inicial tem pedidos extra já existentes.
6. Reportar `bsd_date_search.date_days_examined`, `date_list_requests`, `date_detail_requests`, `fallback_results_recovered` e `lookup_reason_counts`. O número de recuperados representa **apenas o run atual**, não cobertura acumulada.
7. Sem token BSD → sem chamadas BSD. Erros não propagam tokens/URL de consulta para logs ou artefactos. Não publicar a resposta de pesquisa nem nomes de credenciais.

## Limites e estados
- `LAB_BSD_DATE_MAX_DAYS`: padrão 3, permitido 0–4 (0 desliga este fallback).
- `LAB_BSD_DATE_MAX_PAGES`: padrão 3, permitido 1–4; 200 eventos por página.
- `bsd_date_budget_deferred`: limite de datas do run; o jogo fica pendente e pode ser verificado noutra execução.
- `bsd_date_incomplete_pagination`: não confirmar mesmo que uma página inicial contenha um encontro aparentemente certo.
- `bsd_date_ambiguous_match`: várias correspondências; revisão externa necessária.
- `verified_bsd_ft_via_date`: resultado BSD validado pelo endpoint de detalhe, rotulado no LAB como fonte BSD apenas ou duas fontes conforme a TheSportsDB.

A TheSportsDB V1 gratuita limita a pesquisa de eventos a 1 resultado por pedido; o endpoint `eventsday.php` gratuito também tem limite 3 eventos. Por isso **não** usar pesquisa global por dia da TheSportsDB para afirmar ausência, nem assumir que a pesquisa textual devolve o universo. Fonte: https://www.thesportsdb.com/documentation

## Segurança e teste
- Só altera `h1lab/lab_bsd_search.py`, `scripts/lab_results.py`, `.github/workflows/lab-ft-results.yml`, `tests/test_lab_bsd_search.py`, a página/este documento e a referência na documentação LAB.
- O H1, o cron a cada cinco minutos, os ficheiros H1 de resultados, os picks, o Telegram e `h1lab/bsd.py` **não são alterados**.
- Testar com fixtures sintéticas: recuperação por data, cache, orçamento, paginação completa/incompleta, colisões, validação de detalhe, proteção de segredos e manutenção do caminho BSD original.
- Só declarar melhoria de cobertura **depois de um run real com `fallback_results_recovered > 0`**. No caso contrário, reportar honestamente 0 e investigar limitações de nomes e cobertura do fornecedor, sem flexibilizar a validação.
