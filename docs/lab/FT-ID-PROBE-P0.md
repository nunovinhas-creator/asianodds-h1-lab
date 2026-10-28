# P0 — Consulta por ID GOAL, sem aumento de quota

## Motivo e fonte oficial

A GOAL API documenta `GET /v1/fixtures/:id` com autenticação Bearer:
https://goal-api.com/documentation

No laboratório, `docs/lab/ft-identity-review.json` já conserva possíveis
IDs GOAL, mas esses candidatos são aproximações de nomes **sem força de prova**.
Uma consulta por ID pode revelar alterações tardias dos campos de FT,
mesmo quando os resultados por data não são novamente consultados.

## Implementação

- Apenas um ID por ciclo FT **agendado ou watchdog autorizado**, nunca
  num push normal sem chaves e quotas. O ID deve constar de uma única
  entrada da fila anterior, com `review_only=true`, orientação normal,
  diferença de KO até cinco minutos, sem possíveis duplicados e
  igualdade de ambos os clubes pelo validador determinista existente
  `pair_level`, sem confiar no score de similaridade.
- Só ativa em `goal_no_regulation_score`, `goal_not_finished_or_unverified`,
  `goal_unavailable` ou prova equivalente de ET/PEN, nunca em
  `goal_ambiguous_fixture` ou orientação trocada.
- O jogo deve pertencer aos **30 previamente elegíveis** da fila normal,
  ter sido consultado antes e ter pelo menos quatro horas desde a última
  tentativa. Não ignora cooldowns, revisões bloqueadas ou KO+3h.
- O GET valida envelope, ID retornado, equipas, KO e campos dos 90 minutos.
  Reutiliza `choose()` + `verify()`. Um nome aproximado ou um ID sem FT
  normal permanece PENDING. Não há promoções automáticas de aliases.
- A pesquisa **substitui uma das duas datas GOAL**: no máximo uma data
  mais um ID, ou duas datas sem ID. Nunca aumenta pedidos por ciclo.
  O histórico de quotas inclui ambos os tipos de pedidos e a fonte
  de auditoria expõe `date_requests` e `id_requests`.
- Nenhum H1, FIFO, Telegram ou previsão V6 é alterado. Não intervém
  nos oito jogos antigos de 27/10 sem candidato seguro.

## Aceitação

O teste `test_lab_goal_id_probe.py` reproduz datas, identidades, resultados
regulamentares, scores inválidos, duplicados, IDs incorretos e limites.
A CI exige no máximo um ID e dois pedidos GOAL por execução. Validação
real em produção só após uma execução agendada e um candidato elegível;
um push pós-merge não é prova de GET por ID. Diferenciar sempre
`candidates_planned`, `calls` e `newly_confirmed`.

## Próxima decisão

Confirmar num ciclo autorizado se um jogo com GOAL candidato e score
regulamentar por confirmar recupera um FT. Se não houver candidato
selecionado, não forçar pedidos. A extensão a API-Football/BSD deve
reutilizar a quota existente e respeitar a proveniência de cada ID.
