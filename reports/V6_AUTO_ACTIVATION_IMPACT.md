# V6 — Ativação automática após FT: relatório de impacto

Estado: **PR sem merge** (aguarda nova autorização). Âmbito: apenas `v6-offline-statistics.yml`.

## O que muda

| Antes | Depois |
|---|---|
| V6 só por `schedule` (02/08/14/20 h UTC, muitas vezes atrasado pelo GitHub) | Disparo principal: `workflow_run` após `lab-ft-results.yml` **concluído com `success` na `main`**; o `schedule` mantém-se igual, como reserva |
| Sem controlo de cadência | No máximo **1 cálculo por janela móvel de 6 h**, para `workflow_run`, `schedule` e `workflow_dispatch` |
| Uma falha só voltava a ser tentada no cron seguinte | Recuperação limitada: backoff de 6 h → 12 h → 24 h (teto de 1 tentativa/dia), sempre visível |
| `workflow_dispatch` sem regras | `force=true` + `reason` obrigatório + ator humano = exceção explícita (`RUN_FORCED_MANUAL`, anotação `warning`). Ignora **apenas** a janela de 6 h e o backoff; nunca `GATE_STATE_UNAVAILABLE`, `main` não verificada, execução anterior ativa ou regras de segurança |

## Correção ao risco de concorrência

O gate é o **primeiro job** do workflow e fica coberto pelo grupo `concurrency` de nível de
workflow (`v6-offline-statistics-main`, `cancel-in-progress: false`). Este grupo cobre
gate → evaluate → publish: o gate da execução seguinte só arranca depois de a anterior ter
publicado ou falhado. Dentro desta secção protegida, o gate:

1. volta a buscar `origin/main` (não usa o `github.sha` de uma execução que ficou à espera do mutex) e lê `generated_at` do relatório e a data do commit que o publicou;
2. lê o histórico de tentativas na API de Actions, já com todas as execuções anteriores concluídas;
3. defesa em profundidade: recusa (`CONCURRENT_ATTEMPT_IN_PROGRESS`) se existir uma execução **anterior** ainda ativa. As mais recentes, que estão em fila atrás desta, são ignoradas e decidem depois.

Contam como tentativa todas as execuções não-PR em que o job `evaluate` chegou a correr, seja
qual for o resultado (publicou, falhou, foi cancelada ou terminou `SUPERSEDED`). Assim, uma
tentativa que não publica não liberta a janela.

## Segurança

- Só se aceita o workflow FT pelo nome exato, com `conclusion == success`, `head_branch == main`, `event != pull_request` e o mesmo repositório (contra forks). Esta verificação existe duas vezes: no código do gate e no `if:` do job `evaluate`.
- Não faz checkout de `workflow_run.head_sha` nem descarrega artefactos do FT: lê apenas os metadados do evento. O código executado é o da `main` (`github.sha`).
- Permissões do gate: `contents: read` e `actions: read`. A escrita continua limitada ao job `publish` já existente.
- Se não conseguir ler o estado (falha da API, erro inesperado), recusa: `SKIPPED GATE_STATE_UNAVAILABLE:*`, com anotação `warning`.

## Observabilidade (linha `V6_ACTIVATION_GATE {json}`, anotação e resumo do job)

`trigger`, `upstream` (id, conclusão, branch, sha, evento, repositório), `decision`, `reason`
(motivo do `SKIPPED`), `mode` (`NORMAL`, `RECOVERY_AFTER_FAILURE`, `RECOVERY_AFTER_UNPUBLISHED`,
`FORCED_MANUAL_EXCEPTION`), `last_published_age_h`, `last_published_commit`,
`last_published_report_sha256`, `last_attempt`, `consecutive_failures`, `required_gap_h`,
`main_head_at_decision`, `history` (pedidos à API, truncagem) e os contadores
`llm_calls`, `provider_requests` e `telegram_requests`, sempre a 0.

Motivos de `SKIPPED`: `REPORT_FRESH`, `RECENT_ATTEMPT`, `RECENT_FAILED_ATTEMPT`,
`BACKOFF_AFTER_FAILURES`, `CONCURRENT_ATTEMPT_IN_PROGRESS`, `GATE_STATE_UNAVAILABLE:*`,
`UPSTREAM_NOT_SUCCESS:*`, `UPSTREAM_NOT_MAIN:*`, `UPSTREAM_FROM_PULL_REQUEST`,
`UPSTREAM_FOREIGN_REPOSITORY:*`, `UPSTREAM_NOT_FT_WORKFLOW:*`, `NOT_MAIN_REF:*`,
`FORCE_WITHOUT_REASON`, `FORCE_BY_AUTOMATION_REFUSED:*`.

## Provas (`tests/test_v6_activation_gate.py`, 54 testes, sem rede)

| Requisito | Prova |
|---|---|
| Dois FT quase simultâneos → 1 cálculo | `test_two_near_simultaneous_ft_events_compute_exactly_once` (threads com barreira, 25 repetições); o segundo é `REPORT_FRESH`, revalidado dentro do mutex |
| O risco existia | Controlo negativo `test_negative_control_original_proposal_computes_twice`: com o gate só por frescura e fora do mutex, há **2 cálculos** |
| Defesa em profundidade | Mesmo sem mutex, o gate final faz 1 cálculo (`CONCURRENT_ATTEMPT_IN_PROGRESS`) |
| Cadência de 6 h | 72 h simuladas: 156 eventos dão 12 cálculos, com intervalos de 6,0 h exatos |
| `schedule` de reserva | FT parado durante 48 h: o `schedule` assume, com 8 cálculos espaçados de 6 h |
| FT falhado não dispara V6 | `test_failed_ft_never_triggers_v6` (20 eventos, 0 cálculos) e casos de segurança (fork, PR, branch, nome) |
| Tempestade de falhas | V6 a falhar sempre durante 96 h: cerca de 200 eventos FT dão 6 cálculos, com intervalos de 6, 12, 24, 24 e 24 h |
| `SUPERSEDED` sem publicação | 24 h: 4 cálculos (não 48), modo `RECOVERY_AFTER_UNPUBLISHED` |
| Leitura de `main` atual | Repositório git real: um checkout desatualizado lê o relatório novo de `origin/main` |
| `force=true` limitado | Regressões: API indisponível, histórico inacessível (fim a fim), `main` não verificada, execução anterior ativa (unitário e com mutex) → `SKIPPED`; estado válido → `RUN_FORCED_MANUAL` mesmo em backoff |
| Limite de paginação | 3 páginas cheias → `pagination_truncated`/`history_truncated`; com só falhas visíveis o backoff sobe para 24 h (nunca desce) |
| Contrato do YAML | Gate no mutex, `needs`/`if`, permissões, cron de reserva e cron FT inalterados, sem `head_sha` nem artefactos |

Teste real só de leitura contra a API do repositório (2026-11-03 09:40 UTC):
`SKIPPED REPORT_FRESH`, idade 0,14 h, última tentativa = execução 41611525491 (`schedule`,
09:30), commit publicado `503d424`, 1 pedido de jobs. A CI do PR repete esta pré-visualização
(não vinculativa) no resumo do job `gate`.

Suite completa: 1486 testes OK antes das correções finais, que só acrescentaram testes ao gate.

## Custos

- LLM pagos: 0. Pedidos desportivos: 0. Telegram: 0. O gate não importa nenhum desses módulos.
- Runners: um job `gate` de cerca de 15 s por cada FT concluído (cerca de 48 por dia) e pelo cron de reserva. O repositório é público, por isso os minutos são gratuitos. O número de cálculos V6 completos fica em ≤ 4 por dia, igual ao teto atual.
- API (`GITHUB_TOKEN`): em regime normal, 3 a 15 pedidos por gate (≈ 30/h). No pior caso, durante uma tempestade de falhas, há um teto de 3 páginas e 120 consultas de jobs por gate. Se a consulta for truncada (limite de páginas ou de consultas de jobs), o gate assume o backoff máximo, o que é seguro.

## Limitações conhecidas

- Se o FT parar por completo e os crons de reserva ficarem a menos de 6 h do último cálculo (atrasos do GitHub), a cadência degrada para 6–12 h. A janela estrita foi preferida à frequência.
- "Re-run failed jobs" manual na interface do GitHub não volta a passar pelo gate. É uma ação humana, auditada pelo próprio GitHub.
- `workflow_run` usa sempre o ficheiro do workflow da `main`: o disparo automático só existe depois do merge. Até lá, o comportamento em produção não muda.

## Fora de âmbito (inalterado)

Publicadores FT, H1 e V4, `lab_v6_offline_publish_safe`, o histórico imutável
`docs/lab/llm-statistics-runs/`, os resultados certificados, as cadências FT
(`12,42 * * * *`) e as restantes, e as issues #107 e #63.
