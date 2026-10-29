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

## Decisão de 29/10/2026 — revisão de identidades e bloqueios

A função `plan_reviewed_ids` deixa de confundir candidatos fracos de **outros**
jogos com colisões reais do fixture. Uma segunda associação `STRONG` noutra
chave continua a bloquear. Todas as aprovações recebem um estado verificável:
`ELIGIBLE` com as chaves fracas ignoradas, ou `REJECTED` com código e
contexto. Quando um jogo aprovado ainda não entrou na fila FT, o motivo é
`NOT_SELECTED_IN_CURRENT_FT_QUEUE`. O relatório fica em
`ft_queue.api_football_reviewed_id_probe.decisions` e num ficheiro de
diagnóstico persistente, `docs/lab/ft-api-football-review-decisions.json`.

**Independiente Reserves–Defensa y Justicia Reserves.** Aprovado o vínculo
`2026-10-27,77621,67110 → api_football:1612137`, com equipas
`18689/18684`, competição `906`, KO `2026-10-27T18:00:00Z`.
A lista completa de 27/10 contém o jogo e nenhuma outra participação
dos dois IDs em ±90 minutos. O ID `1612141` corresponde a uma irmã já
liquidada nessa competição. As referências fracas do `1612137` em
`2026-10-27,77680,51172` e `2026-10-27,10107877,10107878`
não são aprovações. O registo da aprovação **não** certifica um resultado:
a liquidação depende de `fixtures?ids=1612137` na próxima execução FT
autenticada, com `fixture.status.short=FT` e `score.fulltime==goals`.
Uma aprovação validada entra uma única vez na fila mesmo antes do fim do
cooldown geral, sem bypass à quota nem ao cooldown de ID.

**Banfield Reserves–Argentinos Juniors Reserves.** O fixture
`api_football:1612128` está na lista integral de **28/10 às 18h UTC**,
liga `906`, equipas `18679/18677`. A chave AsianOdds regista **27/10
às 18h UTC**. O próprio Club Atlético Banfield anunciou a reserva contra
Argentinos Juniors para **quarta 28/10/2026 às 15h na Argentina**, que
corresponde a **18h UTC**:
https://clubabanfield.org/acreditaciones-de-reserva/ .
Assim, é um **conflito cronológico de 24 horas documentado**, não ausência
do jogo; a chave observada e o relógio original não podem ser reescritos,
e a liquidação continua bloqueada. Fonte independente de confirmação de
data em https://tipstadium.com/football/matches/banfield-res-argentinos-juniors-res-af-1612128 .
Alguns agregadores mantêm 27/10, portanto não se deve equiparar a data
antiga à execução efetiva sem uma trilha documental.

**Express–Kataka.** `1635300` (Express `12452`, Kataka `28319`),
sem choque de equipa, mas ainda sem âncora confirmada para Kataka nem
segunda fonte pública independente com FT validado. Não aprovar.

**Pyunik–Ararat.** `1641902`, equipa Pyunik `709`, competição `709`
(IDs são domínios distintos), Ararat `3682`. Falta âncora confirmada da
mesma competição e distinguir Ararat de Ararat-Armenia e Ararat II. Não
aprovar; `AET` e `PEN` são recusados na liquidação.

**İçel/Mersin–Muş.** As duas chaves para o eventual fixture `1645449`
ficam em conflito de canonicidade. Não liquidar até escolher uma chave
com prova de identidade; não transformar o nome `Yeni Mersin Idmanyurdu`
num alias global sem validação de IDs.


## Auditoria de proveniência e prova FT (29/10/2026)

A aprovação do fixture `1612137` permanece estritamente **uma decisão de
identidade**. O campo `reviewed_by: user_authorized_assistant_review` deve
ser lido em conjunto com `review_provenance`, que discrimina: decisão
registada pelo assistente na sequência da concordância do utilizador,
fornecedor, data e fingerprint SHA-256 da lista completa de 326 fixtures
(27/10), a consulta de referência, IDs casa/fora `18689/18684`,
competição `906`, âncora já confirmada `1612141`, delta de kickoff de
zero minutos, inexistência de outra participação dos IDs em ±90 minutos e
as duas correspondências fracas rejeitadas. **Nenhum golo é atestado por
esta revisão**.

O resultado `fixtures?ids=1612137` só pode produzir FINAL quando a API
responde com `fixture.status.short == 'FT'`, o ID original e IDs de equipa
e liga aprovados, KO dentro de ±90 minutos do observado e ±5 minutos do
aprovado, e quando `goals.home/away == score.fulltime.home/away` com
valores inteiros válidos. `AET`, `PEN`, ausência de `FT`, falta de
`score.fulltime`, divergência de golos, IDs incorretos ou KO divergente
ficam em `PENDING` com motivo. Os testes de regressão contemplam essas
rejeições, sem usar dados reais nem chamar APIs.
