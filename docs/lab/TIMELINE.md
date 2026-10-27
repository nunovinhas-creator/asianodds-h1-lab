# Cronologia por jogo — modelo de dados e critérios

**Estado:** `DESCRIPTIVE_SHADOW_AUDIT_NOT_CERTIFIED`. Diagnóstico descritivo do LAB. Não cria apostas, não altera o H1 e não mede rentabilidade.

Código: `h1lab/timeline.py` · script: `scripts/lab_match_trajectories.py` · testes: `tests/test_timeline.py` · saída: `docs/lab/match-trajectories.json`.

## 1. Camadas

```
Mensagem Telegram (event_id, observed_at)
  └─ snapshot(s) de odds: total | asian_handicap | one_x_two  (cada um com origin)
       └─ movimento de mercado: pares de mensagens relacionadas → episódios
            └─ trajetória do jogo (match_key): linha observada, transições, reversões
                 └─ resultado FT (fora deste módulo; não usado aqui)
```

A **unidade de avaliação de uma aposta é o jogo** (`match_key`). Mensagens e snapshots não são ensaios independentes.

## 2. Regras

| Regra | Implementação |
| --- | --- |
| Agrupar por `match_key` | Chave H1 quando existe; senão a chave V4. Mensagens só com V4 também entram. |
| Preservar `event_id` e hora | Todas as mensagens ficam em `events`; ordem por instante UTC e, em empate, pelo número da mensagem (inteiro). |
| Origem dos valores | `V4_EXPLICIT` quando o V4 tem a tabela; caso contrário `H1_LEGACY_ONLY`. Se ambos existem, `v4_vs_h1_record` indica `AGREE`/`DIFFER` com os campos; nunca se fazem médias nem substituições. |
| Sem interpolação | Só os pontos `before`/`after` de cada alerta. Diferença de linha entre o `after` de um alerta e o `before` do seguinte = `UNOBSERVED_CHANGE`. |
| Continuidade | `CONTINUOUS` (mesma linha); `prices_at_line` diz se os preços mudaram sem observação. |
| Reversões | Mudança de sinal entre movimentos de linha observados (dentro do alerta ou na lacuna). |
| Repetições | Mesmo jogo, Total presente nos dois, separação ≤ `near_seconds` (120 s por omissão). |
| Ambiguidade | Mesmas linhas antes/depois fora da janela → `AMBIGUOUS_REPEAT_OR_REVERSAL` (não conta como reversão). |
| Nunca apagar | Toda a relação tem `action: ANNOTATE_ONLY_NEVER_DELETE`. |

### Classificação de mensagens relacionadas

| `evidence` | Significado | Conta como snapshot potencialmente redundante? |
| --- | --- | --- |
| `IDENTICAL_TOTAL_SNAPSHOT` | as seis células do Total iguais | Sim (`possibly_redundant_event_ids`) |
| `SAME_TOTAL_LINE_MOVE_DIFFERENT_PRICES` | mesmas linhas, preços ligeiramente diferentes | Não; apenas o mesmo movimento provável |

| `classification` | Significado |
| --- | --- |
| `SAME_MOVEMENT_DIFFERENT_MESSAGE` | mensagens diferentes (ex. 1X2 e Total) do mesmo movimento |
| `REPEATED_SNAPSHOT_SAME_TRIGGER` | mesmo tipo de disparo repetido |

`movement_episodes` junta mensagens ligadas por estas relações. `movement_episodes_upper_bound` é um **limite superior** do número de movimentos independentes; a independência real continua por demonstrar.

## 3. Casos reais validados (`tests/test_timeline.py`, classe `RealDataTests`)

| Jogo | Eventos | Resultado esperado |
| --- | --- | --- |
| Blackpool – Aston Villa U21 | 50588 · 50675 · 50681 | 3 mensagens; 50588 `H1_LEGACY_ONLY`; Total 3,50→3,75 · 3,75→3,75 · 3,75→4,00 com duas transições `CONTINUOUS`; AH −1,75→−2,00 em 50675; sem pares relacionados |
| Dortmund – Werder Bremen | 50582 · 50685 · 50686 | 50685/50686 a 1 s, `IDENTICAL_TOTAL_SNAPSHOT`, `SAME_MOVEMENT_DIFFERENT_MESSAGE`, mesmo episódio; nenhum evento removido |
| Braga – Famalicão | 50654 / 50655 | par a 2 s, `mixed_origin: true` (50654 é anterior ao V4) |
| Real Bedford – Stourbridge | 50710 / 50711 | par a 2 s, disparos Total→1X2, ambos V4 |

Os testes são ignorados (não falham) se esses eventos deixarem de existir nos dados — nunca são reescritos para passar.

## 4. Publicação e workflows

- **`Lab - Audit V4 vs H1 (shadow)`** (`lab-v4-audit.yml`, depois de cada recolha H1): passo `Build per-match chronology` com `continue-on-error: true`. Corre os testes de cronologia e só depois gera o JSON. Se falhar, o JSON anterior fica e a publicação V4/Golden continua.
- **`Lab - Match chronology smoke (PR)`** (`lab-timeline-smoke.yml`): testes + geração sobre os dados reais da PR + asserções dos casos reais; não faz commit.
- Permissões: o workflow LAB já tem `contents: write`; o smoke só `contents: read`.
- Corridas: o JSON é calculado sobre a `HEAD` depois de `git pull --rebase`; `source_commit` regista essa versão. A publicação usa o ciclo existente `fetch → rebase → push` com 5 tentativas. Ficheiros escritos são disjuntos dos do H1 (`data/state.json`, `docs/data.json`), por isso o rebase não colide com o coletor.
- Escrita atómica (`.tmp` → `replace`); `*.tmp` fora de `data/lab` não é adicionado ao commit.

## 5. Tamanho e amostragem

- Só jogos com ≥ 2 mensagens aparecem em detalhe; os restantes contam no resumo.
- Máximo `max_timelines` (400) jogos, os mais recentes primeiro; `sampling.timelines_omitted` diz quantos ficaram de fora.
- `issues` limitado a 200 entradas; `issue_count` e `issue_counts` mantêm o total.
- Sem texto Telegram, URLs, capturas ou credenciais.

## 6. Critérios de aceitação

1. Nenhuma mensagem perdida: `messages + messages_excluded − messages_v4_only = len(state.alerts)`.
2. Todos os casos reais da secção 3 confirmados.
3. Diferenças V4 vs registo H1 sempre listadas por campo.
4. Relatório < 2 MB.
5. Ficheiros H1 protegidos sem alterações (comparação de commits).

## 7. Limitações

- O canal só publica alguns movimentos; não há série contínua de preços.
- A janela de 120 s é uma convenção configurável, não um valor estimado.
- Tabelas Total soltas sem cabeçalho continuam com identidade não comprovada.
- A percentagem 1X2 mostrada pelo Telegram fica como `trigger_displayed_pct_unvalidated`; não usar como variável preditiva.
