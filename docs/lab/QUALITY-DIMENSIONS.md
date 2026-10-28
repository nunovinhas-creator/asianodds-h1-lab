> **Atualização de leitura 28/10/2026:** o diagnóstico de gates e contagens de 27/10 abaixo é uma **fotografia histórica**. A fonte atual é [v4-audit.json](v4-audit.json), que às 11:46 UTC ainda marcava `PENDING`, embora `coverage_99` e `data_integrity` fossem verdadeiros. O Golden Set permanece `NOT_CERTIFIED`; a concordância entre parsers não valida as mensagens originais. O [cérebro V5](CEREBRO-ODDS.md) é uma investigação de padrões separada e **não certifica automaticamente o V4**.

# Qualidade V4 — dimensões separadas e critérios estatísticos

Bloco `quality_dimensions` em `docs/lab/v4-audit.json`. **É informativo: não altera `acceptance_gates` nem `status`.** Os gates oficiais continuam exatamente como estavam.

## 1. Porque os gates estão PENDING (diagnóstico de 27/10/2026, ~20:36 UTC)

| Gate | Valor | Causa verificada |
| --- | --- | --- |
| `field_agreement_100` | false | Os **valores** coincidem (582/582 campos). O gate falha porque conta como erro qualquer *issue* da janela, e há 12 registos (50657–50668) sem `identity_source`, `parser_revision`, `parser_commit` e `field_source`: foram capturados antes de existir proveniência (7e1993e). |
| `independent_identity` | false | Os mesmos 12 registos não têm proveniência de identidade. |
| `minimum_evidence` | false | 18 mensagens 1X2 e 43 Total; são precisas ~299 por família com 0 falhas para um limite inferior de 99%. |
| `window_elapsed` | false | A janela termina a 28/10 16:40:50 UTC. |
| `logs_clean_24h` | false | Logs só certificáveis no fim da janela. |
| `golden_set_verified` | false | Por construção; exige revisão humana independente. |

Os 12 registos **não são reescritos**. Em vez disso, o bloco `provenance_window` mede, em paralelo, as primeiras 24 h a partir do primeiro registo com proveniência (50669, 17:31:15 UTC). Essa janela é `INFORMATIONAL_NOT_A_GATE`: substituir a janela oficial exige decisão explícita do utilizador numa PR própria.

## 2. Dimensões

| Dimensão | Pergunta | Fonte | Estado atual |
| --- | --- | --- | --- |
| Cobertura de recolha | Cada alerta tem registo V4? | `collection_coverage` | 61/61 |
| Exatidão da extração | O valor extraído é o da mensagem original? | Golden Set (humano) | Não medida por comparação de parsers |
| Identidade independente | `match_key`/kickoff vêm do próprio texto? | `identity_independence` | 49/61 |
| Concordância entre parsers | V4 = registo H1 nos campos disponíveis? | `parser_agreement` | 61/61 mensagens |
| Validação humana | Um humano conferiu a mensagem original? | `golden-report.json` | 4 R1, 1 confirmação do utilizador |
| Independência entre movimentos | Duas mensagens são o mesmo movimento? | `match-trajectories.json` | 6 pares relacionados |
| Certificação estatística | Limite inferior 95% ≥ 99% por família, logs, Golden | gates oficiais | NOT_CERTIFIED |

**100% de concordância nos campos disponíveis não é exatidão global**: os dois parsers leem o mesmo texto e podem errar da mesma forma; campos que nenhum dos dois lê não entram.

## 3. Critérios estatísticos

- **Unidade:** a mensagem Telegram. Um alerta 1X2 tem 18 campos mas conta **uma** vez.
- **Método:** limite inferior exato unilateral de Clopper–Pearson a 95% (`lower_95_by_message`). Com *n* sucessos em *n*, o limite é 0,05^(1/n).
- **Estratos:** família (`total`, `1x2`) × período do parser (`by_parser_period_and_family`). Períodos:
  - `v4_initial_no_provenance` — desde o cutover (59d761b, 16:40:50) até ao primeiro registo com revisão;
  - `v4_provenance_1` — registos com `parser_revision`;
  - `v4_provenance_1_anchored_rows` — depois do merge de #16 (4e4a805, 19:56:41);
  - `v4_source_<sha12>` — registos novos com `parser_source_sha256` (identifica o **código** do parser; `parser_commit` é apenas a HEAD do checkout do coletor e muda a cada commit de dados).
  A atribuição por hora de observação é aproximada até um ciclo de recolha.
- **Agrupamento por jogo:** para qualquer métrica de movimento ou de resultado, a unidade é o jogo (`match_key`), não a mensagem; ver `docs/lab/TIMELINE.md`.
- **Percentagem 1X2 mostrada pelo Telegram:** `FORMULA_UNVALIDATED`. Em 18 mensagens, nenhuma coincide com a variação simples da odd (tolerância 0,2 p.p.) e o mínimo absoluto mostrado é 10,0. Guardar como mostrada; **não usar como variável preditiva** sem investigação própria.

## 4. Proibições mantidas

- Não alterar registos antigos para fazer passar gates.
- Não converter `golden_set_verified` em `true` automaticamente.
- Não declarar `PASS` estatístico com dados apenas de sombra.
- Não calcular ROI, EV ou padrões rentáveis a partir destas métricas.
