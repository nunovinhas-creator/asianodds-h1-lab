# V7 — API-Football fixture IDs revistos (2026-10-28)

## Estado e isolamento

A recuperação por `fixtures?ids=` está instalada **sem pares aprovados** por defeito. O ficheiro
`data/lab/ft-api-football-reviewed.json` contém `{"schema_version":1,"pairs":{}}`:
assim, **zero** requests extra, **zero** liquidações com nomes semelhantes.

Para cada candidato do API-Football, a fila de revisão publica apenas os dados
de identidade (ID do jogo, IDs de ambas as equipas, ID da competição, nomes,
KO e orientação). Não publica resultados de jogos pendentes.

## Aprovação humana por jogo

Só depois de verificar manualmente o mesmo jogo, na fonte independente ou
competição oficial, acrescentar um registo **real** a `pairs`, indexado pelo
`match_key` AsianOdds, com estes campos:

- `status: "APPROVED"`
- `home`, `away`, `kickoff_utc`: identidade original imutável do ledger
- `provider_fixture_id`, `provider_home_team_id`, `provider_away_team_id`,
  `provider_competition_id`, `provider_kickoff_utc`: valores exatos de um
  candidato da fila de revisão previamente observado
- `reviewed_by`: identificador não vazio do revisor
- `reviewed_at_utc`: data/hora da aprovação real em UTC

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
