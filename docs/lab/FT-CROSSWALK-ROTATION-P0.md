# MASTER BRAIN — P0: catálogo confirmado de IDs e rotação histórica de datas

Implementação proposta em 28/10/2026. Aplicável apenas depois de merge e execução real.

## Porque era necessário

A fila FT seleciona até 30 jogos por ciclo; os adaptadores GOAL, OpenFoot e
API-Football carregavam a primeira data encontrada, até esgotarem 2, 2 ou
3 datas, respetivamente. Os jogos mais antigos podiam ficar sem chamadas
dessas APIs, mesmo estando elegíveis na fila. O sistema já disponibilizava
pesquisas históricas por **data** (não foi descoberto um novo endpoint).

## O que foi implementado

- `h1lab/lab_ft_rotation.py`: usa a seleção real da fila (pré-visualização
  sem pedidos HTTP) para distribuir as datas por fornecedor.
- Ordena as datas elegíveis por última consulta efetiva, favorecendo as
  ainda nunca consultadas; pedidos repetidos numa mesma data aproveitam a
  cache existente do adaptador. Cada fornecedor mantém a própria rotação.
- O histórico persistente `data/lab/ft-provider-day-rotation.json` guarda
  datas efetivamente requisitadas, não datas apenas planeadas; o orçamento
  de 2/2/3 datas por execução nunca aumenta.
- Contabilidade conservadora no próprio workflow: até 90 chamadas/dia à
  API-Football e até 4500/mês à OpenFoot. **Não é contabilidade de chamadas
  feitas fora deste repositório** nem reconstrução de consumo antes da
  implementação. GOAL continua limitado a 2 datas/execução; falta
  confirmação independente da quota contratual total antes de definir
  um limite mensal.
- `h1lab/lab_ft_crosswalk.py`: extrai exclusivamente IDs estáveis de
  URLs de eventos que os adaptadores já validaram como FT. Mantém os
  vínculos `match_key → fornecedor → ID` e as equipas/KO de referência.
  Quando dois `match_key` tentam reclamar o mesmo ID, o registo marca
  `COLLISION_REVIEW`, nunca funde os jogos.
- Cada novo FT pode guardar os URLs de **todos** os fornecedores cujos
  resultados foram confirmados em concordância, sem duplicar pedidos.
  Uma nova liquidação que reutilize um ID já confirmado de outro jogo
  é bloqueada e fica em revisão.
- URLs de listas por data (incluindo OpenFoot) não constituem IDs únicos;
  candidatos fuzzy e a fila `ft-identity-review.json` continuam apenas
  diagnósticos e não alimentam automaticamente o catálogo de identidades.

## Limites importantes

A pesquisa por data era suportada pelos adaptadores existentes; este
trabalho melhora o *agendamento histórico*, mas não implementa um novo
endpoint de pesquisa direta por ID. A BSD já inclui validação de eventos
por ID na arquitetura anterior. Para GOAL/API-Football, uma consulta
direta por ID requer verificação de documentação e quota antes de ser
autorizada em produção. Um ID confirmado associado a um FT não permite
inferir qualquer outro FT.

Uma resposta `*_day_rotation_deferred` identifica ausência de orçamento
para aquela data — não falta de cobertura da competição. Não elimina
o jogo nem o considera derrotado. A fila continua com KO+3h, limite de 30,
cooldowns progressivos e horizonte de 30 dias. O histórico de utilização
conta apenas pedidos efetuados desde a instalação.

## Aceitação

Testes isolados de rotação, limites diários/mensais e colisões de IDs
(`tests/test_lab_ft_rotation.py`), seguidos da bateria completa da CI.
Em produção, confirmar `ft_queue.date_rotation`, os arrays
`selected_days` / `requested_days`, pedidos por fornecedor e painel
FT. A taxa de recuperação de jogos antigos só pode ser considerada
comprovada depois de observações reais com resultado confirmado.

Não modificar H1, triplas FIFO, Telegram ou previsões congeladas V6.
