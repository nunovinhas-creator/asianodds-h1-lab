# V7 — API-Football fixture IDs revistos (2026-10-28)

## Estado e isolamento

A recuperação por `fixtures?ids=` está instalada **sem pares aprovados** por defeito. O ficheiro
`data/lab/ft-api-football-reviewed.json` contém `{"schema_version":1,"pairs":{}}`:
assim, **zero** requests extra, **zero** liquidações com nomes semelhantes.

Para cada candidato do API-Football, a fila de revisão publica apenas os dados
de identidade (ID do jogo, IDs de ambas as equipas, ID da competição, nomes,
KO e orientação). Não publica resultados de jogos pendentes.

## Prova de identidade proveniente da lista completa

O ficheiro `data/lab/ft-api-football-day-index.json` é produzido **somente**
a partir da lista completa do dia já consultada na execução autenticada. Só
contém IDs dos jogos e das duas equipas, nomes, ID/nome da competição, hora
UTC, data da consulta e SHA-256 da lista. Não armazena golos nem odds.

Se a lista original estiver incompleta, contiver jogos sem identidade
verificável ou houver IDs duplicados, o dia fica `INCOMPLETE` e **nenhuma**
aprovação por IDs nesse dia é autorizada. Um pedido HTTP falhado não altera
a última prova completa.

O planeador exige `competition_anchor_fixture_id` de **outro** jogo
anteriormente FINAL, presente em `ft-provider-identity.json` com o mesmo
fornecedor, e cuja competição no índice completo tenha exatamente o mesmo
ID. Exige ainda que nenhum ID de qualquer das equipas surja noutro jogo
no intervalo de 90 minutos antes ou depois do KO e que reservas, séniores,
U21 e futebol feminino nunca sejam confundidos.

Para `Express Red Eagles–Kataka FC`, exige também um
`opponent_anchor_fixture_id` de outro jogo FINAL com o mesmo ID de Kataka
ou `independent_public_ft` (URL HTTPS de uma segunda fonte pública
independente e golos casa/fora aos 90 minutos, previamente revistos). Quando
a segunda opção é usada, o resultado final da API deve coincidir exatamente
com essa prova, ou a liquidação é recusada. O código não confirma o conteúdo
do URL sozinho; a autenticidade dessa segunda fonte é responsabilidade da
revisão humana antes de inserir o par.

## Aprovação humana por jogo

Só depois de verificar manualmente o mesmo jogo, na fonte independente ou
competição oficial, acrescentar um registo **real** a `pairs`, indexado pelo
`match_key` AsianOdds, com estes campos:

- `match_key`: a mesma chave usada na tabela `pairs` e no ledger
- `status: "APPROVED"` e `provider: "api_football"` (fornecedor aprovado do par)
- `home`, `away`, `kickoff_utc`: identidade original imutável do ledger
- `provider_fixture_id`, `provider_home_team_id`, `provider_away_team_id`,
  `provider_competition_id`, `provider_kickoff_utc`: valores exatos de um
  candidato da fila de revisão previamente observado
- `reviewed_by`: identificador não vazio do revisor
- `reviewed_at_utc`: data/hora da aprovação real em UTC
- `competition_anchor_fixture_id`: ID de jogo do mesmo fornecedor com FT confirmado e igual ID de competição
- no Express–Kataka, `opponent_anchor_fixture_id` ou `independent_public_ft` com URL e resultado aos 90 minutos

O planeador recusa qualquer diferença entre a aprovação, a identidade
original e o candidato persistido; recusa também duplicados, colisões com
FT anteriormente verificados, diferenças de orientação e IDs ausentes.
Uma sugestão `WEAK_REVIEW_ONLY` **nunca** cria uma aprovação sozinha.
Não colocar IDs, equipa ou hora hipotéticos neste ficheiro.

## Consulta e liquidação

Em execução FT autenticada, o planeador procura apenas aprovações para
jogos elegíveis da fila, até 20 IDs por lote, com máximo de **um pedido**
`fixtures?ids=id1-id2` por execução; reserva um dos três pedidos
API-Football por ciclo, sem ultrapassar o teto persistente de 90/dia.
Uma consulta por ID (incluindo falhada) tem cooldown de 24 h.

O resultado só é aceite se a resposta indicar exatamente o mesmo ID de jogo,
IDs da casa/visitante na ordem correta, ID da competição, KO na janela dos
90 minutos e no máximo 5 minutos face ao KO aprovado, e estado `FT`.
A validação existente exige coerência entre `score.fulltime` e `goals`.
`AET`, `PEN`, resultado ausente, colisão ou erro deixam o jogo pendente.
`REVIEWED_PAIR` fica auditado na evidência. A revisão de identidade não é
uma segunda confirmação independente do **resultado**.

## Próxima validação real

1. Confirmar primeira execução autenticada V7 no `ft-api-audit.json`.
2. Inspecionar candidatos da Uganda PL e das duas reservas argentinas.
3. Rever individualmente IDs e orientação; acrescentar somente pares provados.
4. Validar `api_football_search.id_requests == 1` e respetivo FT com
   `REVIEWED_PAIR`, sem perdas de quota.
5. Só depois desenvolver um crosswalk persistente por **IDs das equipas**
   aprendidos de FT confirmados, sem aproveitar sugestões não revistas.
