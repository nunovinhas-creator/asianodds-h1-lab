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

## Falha real da primeira consulta por ID (29/10/2026, 07:36 UTC)

O watchdog iniciou a execução autenticada `40836485933` às 07:36 UTC,
selecionou `1612137`, cumpriu as verificações de identidade da aprovação
e consumiu **um pedido `fixtures?ids=`** (dois pedidos API-Football
na execução incluindo uma consulta de data). A API-Football registou
`api_football_reviewed_id_unavailable`; o jogo manteve-se PENDING.
O relatório anterior mostrava incorretamente
`api_football_identity_no_core_match` por reter a razão antiga da
pesquisa por nome na ausência de uma nova lista/resultado FT.

Agora o adaptador regista o motivo por `match_key` em
`reviewed_outcomes`, e o recolector grava
`api_football_reviewed_id_last_evidence` (hora UTC, fixture e razão),
além de atualizar `provider_reasons.api_football` com a tentativa real.
Uma falha HTTP/fornecedor **não** é uma rejeição de identidade nem
prova de resultado. O cooldown de ID de **24 horas** mantém-se e
não há repetição manual nem recuperação de scores não verificados.

A sequência de testes garante que `FT`, IDs de equipas e competição,
`score.fulltime` e `goals` são obrigatórios antes de qualquer
FINAL; `AET`, `PEN`, resultados omissos e divergentes são recusados.


## Diagnóstico de erros sem consumir pedidos adicionais — 29/10/2026

O pedido autenticado por ID `fixtures?ids=1612137` falhou em
29/10 às 07:36 UTC (`api_football_reviewed_id_unavailable`). Os resultados
de data 29/10 funcionaram com a mesma chave; essa observação **não**
demonstra que o plano gratuito bloqueia fixtures com mais de 24/48 horas.
A documentação oficial prevê `fixtures?ids=` com até 20 IDs e distingue
limites de época no plano Free, mas não estabelece a alegada janela de
"ontem a amanhã" para este endpoint. A hipótese fica **NOT_CONFIRMED**.

A partir desta versão, cada pedido por data ou ID pode produzir:
- `category`: `HTTP_ERROR`, `PROVIDER_ERRORS`,
  `TRANSPORT_ERROR`, `TIMEOUT`, `INVALID_JSON`,
  `RESPONSE_TOO_LARGE`, `INVALID_ENVELOPE`,
  `INCOMPLETE_PAGINATION` ou `INVALID_FIXTURE_IDS`;
- `http_status` (código real ou `null`);
- `provider_errors` (apenas o campo JSON `errors`, limitado a
  200 caracteres, com chave, URLs e tokens ocultados).

As decisões continuam fail-closed. Esta telemetria não guarda o corpo HTTP,
cabeçalhos, token, scores, requests URL ou equipa arbitrária. Fica no
`ft-api-audit.json`, relatório público e, para pedidos por ID, na última
evidência de tentativa do ledger. **Uma falha HTTP não autoriza repetição
antes das 24h de cooldown.** Não desativar automaticamente datas antigas
sem uma mensagem explícita do fornecedor; um erro de transporte pode ser
temporário.

## Arquivo de FT: requisito de segurança, não ativo

**Não guardar corpos brutos de API-Football em `actions/cache` em texto
simples no repositório público.** Segundo a documentação do GitHub, um PR
pode ler os caches da branch base, e o cache não é desenhado para guardar
dados sensíveis nem constitui armazenamento privado de origem auditável.
Antes de ativar um arquivo de resposta completa, exigir cifra autenticada
em repouso (p. ex. AES-GCM com chave guardada em GitHub Secrets, não na
própria cache), política de leitura em jobs autenticados, proteção contra
alteração, TTL/rotação e validação de marcador oficial FT, equipas,
competição, KO e `score.fulltime == goals` no momento de eventual
liquidação. Um cache de histórico não converte um candidato fraco em
identidade aprovada. Não fica qualquer arquivo bruto ativo nesta PR.

## Alternativa GOAL — revisão e conflito de fontes

No dia 27/10 às 18:00 UTC, o GOAL apresenta
`apiId=834934`, Independiente Res.–Defensa y Justicia Res.,
na competição Torneo Proyección. O ID aparece também como candidato
fraco noutros jogos da fila; `plan_goal_id()` recusa-o intencionalmente
pelas regras atuais de exclusividade, número de candidatos e motivo anterior
`goal_identity_no_core_match`. Não o promover a alias automático.

Uma futura aprovação por jogo no GOAL precisa de chave AsianOdds
imutável, ID `834934`, KO e nomes na ordem correta, competição da
mesma categoria, zero segunda associação STRONG, identificação positiva
de equipa de reserva de ambos os lados, ausência de ID já liquidado
noutro match_key e dados oficiais aos 90 minutos; a validação final
deve usar `homeTeamFtScore/awayTeamFtScore`, `matchPeriod=FINISHED`,
e rejeitar `AFTER_ET/AFTER_PEN` sem dados próprios de tempo regulamentar.
Preservar o limite de chamadas gratuitas e diário, sem acrescentar uma
requisição durante esta alteração.

Pesquisa pública (não usada como liquidação): várias páginas reportam
4–1 (por exemplo `https://locoxelrojo.com/independiente/2026/10/27/goleo-la-reserva-de-independiente-y-sigue-en-lo-mas-alto/`
e `https://footballtrends.app/es/fixtures/1612137/independiente-res-vs-defensa-y-justicia-res/standings`),
enquanto `https://oddseek.com/football/ca-independiente-r-vs-defensa-y-justicia-reserves-13649014`
apresenta 3–1. Essa discrepância **impede** que estes links sirvam,
sozinhos, para declarar o FT no ledger. É obrigatória nova verificação
da fonte e da cronologia original antes de eventual registo público.


## V7.4 — Restrições históricas confirmadas pelo fornecedor (29/10/2026)

A lista API-Football de 27/10 esteve `UNAVAILABLE` desde
29/10 às 05:38 UTC, com reconsulta V7 elegível a partir de 09:38 UTC,
**se a fila voltar a selecionar jogos de 27/10**. A lista de 28/10 foi
novamente `COMPLETE` às 08:16 UTC. Isto, por si só, não prova uma
janela "ontem a amanhã" do plano grátis.

### Gatilho estrito, sem consultas novas

O módulo `lab_api_football_access.py` lê as respostas classificadas da
PR #95 e **só** identifica uma restrição histórica quando a própria API
devolve `HTTP_ERROR` apropriado ou `PROVIDER_ERRORS`, incluindo
**explicitamente** plano, histórico/datas e proibição de acesso. Timeout,
erro genérico 403, envelope inválido, limite diário e ausência de resultados
não ativam qualquer bloqueio.

Um texto que refira explicitamente "yesterday ... today/tomorrow"
permite uma janela dinâmica *de dias de calendário* (ontem a amanhã).
Sem calendário explícito, a proteção aplica-se **apenas à data rejeitada**
e não inventa um limite global de 48 horas. Os factos ficam em
`data/lab/ft-provider-day-rotation.json.api_football_history_access`,
respeitando a auditoria pública.

Se um dia ficar explicitamente fora do acesso do plano, o agendador deixa
de o pedir e substitui-o por outras datas elegíveis, dentro das quotas.
Pedidos de ID humanos aprovados cujo KO pertença ao dia bloqueado ficam
`DEFERRED` com motivo `PROVIDER_CONFIRMED_*_HISTORY_*`, sem
desaprovar a identidade nem marcar `FINAL`. Trata-se de uma **suspensão
prudencial** que evita gastar um novo pedido potencialmente inútil;
não pressupõe que o erro de data prove o comportamento do endpoint ID.

### Um ID não é um lote

A documentação oficial fornece `GET /fixtures?id=710556`; para
`GET /fixtures?ids=710556-710557` adverte "if your plan supports".
Assim, o código escolhe agora `fixtures?id=1612137` quando só há
um fixture e mantém `fixtures?ids=...` apenas para dois ou mais IDs.
Nunca tenta ambos na mesma execução: um pedido autorizado continua a
consumir **uma** unidade de quota, independentemente de êxito.
Fonte: https://www.api-football.com/news/post/how-to-get-all-data-from-a-league-with-api-football

### GOAL `834934` e discordância 3–1 / 4–1

O GOAL é uma via alternativa potencial, mas `plan_goal_id()` tem
resguardos que não podem ser removidos sem **aprovação por jogo** e
sem correspondência individual, reserva vs equipa principal, liga,
orientação, KO e eventual reclamação concorrente forte. Não converter
candidatos fracos em aliases nem liquidar automaticamente por uma
única resposta GOAL.

Diversas fontes independentes atribuem 4–1 e localizam o 4.º golo aos
`90+5'`:
- https://locoxelrojo.com/independiente/2026/10/27/goleo-la-reserva-de-independiente-y-sigue-en-lo-mas-alto/
- https://scores24.live/en/soccer/m-27-10-2026-independiente-reserves-defensa-y-justicia-reserves
- https://footballtrends.app/es/fixtures/1612137/independiente-res-vs-defensa-y-justicia-res/standings

O OddSeek continua a apresentar 3–1:
https://oddseek.com/football/ca-independiente-r-vs-defensa-y-justicia-reserves-13649014

Os `90+5'` são **tempo de compensação regulamentar**, não prolongamento.
Esta evidência torna plausível uma atualização tardia do placar.
**Não há alteração de `PENDING` para `FINAL` por este documento**.
Se duas fontes de resultado FT efetivamente validadas apresentarem
marcadores distintos, a liquidação deve permanecer em `SCORE_CONFLICT`
até uma fonte oficial (AFA ou clube) permitir resolver a divergência.


## V7.5 — Isolamento de restrições entre endpoints (29/10/2026)

A PR #96 confirmou que o diário de acesso histórico regista apenas erros
provenientes de **listas por data**. Não é cientificamente válido aplicar
uma restrição desse endpoint a pedidos individuais `fixtures?id=...` sem
prova independente sobre o endpoint de ID. Por isso, a correção V7.5 mantém
`restriction_for_day()` na rotação por data, mas deixa de usar essa decisão
para adiar os IDs humanos aprovados. A função separada
`restriction_for_fixture_id()` não bloqueia pedidos enquanto o sistema
não tiver evidência de restrições especificamente relativas ao endpoint ID.
Todos os limites existentes (24 h de cooldown de ID, teto diário, seleção
na fila e validação de identidades) permanecem obrigatórios.

**Auditoria do estado:** a PR #96 foi integrada às 08:25 UTC, mas o diário
persistido às 09:32 mantém `confirmed_restrictions={}`. A execução FT
`40850279103` concluiu sem erros de workflow, mas não selecionou o jogo
`2026-10-27,77621,67110`, registando `NOT_SELECTED_IN_CURRENT_FT_QUEUE`.
Isso significa ausência na fila deste ciclo, **não** reprovação de identidade
nem confirmação do resultado. O jogo continua sem FT verificado pelo sistema.
A revisão futura deverá diagnosticar a priorização do jogo sem aumentar o
número de pedidos de APIs ou contornar cooldowns. A alternativa GOAL
`834934` continua apenas candidata, sem alias global nem liquidação.


## V7.6 — Diagnóstico sem ambiguidade dos dois cooldowns (29/10/2026)

A revisão do ledger real confirmou que a não seleção do Independiente–Defensa
nos ciclos das 08h16, 08h53 e 09h31 corresponde ao backoff adaptativo, não
a uma rejeição de identidade: GOAL teve evidência COMPLETE estável em
29/10 às 05h38 UTC, com janela de 12h até aproximadamente 17h38 UTC.
A tentativa individual API-Football ocorreu em 29/10 às 07h36 UTC e o
cooldown **independente** de 24h só permite nova tentativa a partir de
30/10 às 07h36 UTC. Os instantes são horários de elegibilidade, não
promessas de chamada: orçamento, fila e estado do fornecedor continuam a
prevalecer. A consulta usa agora `fixtures?id=...` em vez do antigo
`fixtures?ids=...` quando existe um único ID.

O diagnóstico de `plan_reviewed_ids` passa a publicar
`FT_QUEUE_OR_APPROVED_ID_COOLDOWN`, `ft_queue_not_before_utc` e
`api_id_not_before_utc` quando os dois bloqueios se aplicam a um jogo
aprovado que não foi selecionado. Nenhum cooldown foi reduzido, não houve
consulta manual, alteração de resultado ou aumento de quota.

### GOAL 834934 continua candidato a crosswalk por jogo

O GOAL `834934` está documentado na fila de revisão como candidato STRONG
com KO e orientação coincidentes, mas a via automática `plan_goal_id`
não o seleciona por ter múltiplas sugestões e motivo anterior
`goal_identity_no_core_match`. A documentação GOAL confirma o endpoint
`GET /v1/fixtures/:id`, mas o ID isolado não comprova identidade, reservas,
cronologia ou marcador. A próxima intervenção pode introduzir uma aprovação
restringida ao `match_key`, preservando colisões STRONG, o orçamento
GOAL (ID em substituição de um dia), o cooldown de 24h, a verificação de
`homeTeamFtScore/awayTeamFtScore` e a quarentena de qualquer conflito
3–1/4–1. Não ativar conversão automática em FINAL nesta fase.

Fontes documentais de enquadramento (não usadas como FT aceite):
- https://goal-api.com/documentation
- https://locoxelrojo.com/independiente/2026/10/27/goleo-la-reserva-de-independiente-y-sigue-en-lo-mas-alto/
