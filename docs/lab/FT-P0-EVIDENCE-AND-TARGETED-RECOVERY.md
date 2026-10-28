# P0 — Recuperação FT: prova persistente e dois IDs BSD revistos

**Data da análise:** 28/10/2026. Apenas LAB FT; não altera H1, Telegram,
triplas FIFO, previsões congeladas ou estados de jogos não confirmados.

## Falha diagnosticada

`reconcile()` guardava `provider_reasons` **só da última consulta**.
Quando a quota GOAL não abrangia uma data, `goal_day_rotation_deferred`
substituía `goal_no_regulation_score`, perdendo a indicação de que
um evento GOAL concreto havia sido encontrado e não tinha ainda prova FT.
Assim, a consulta direcionada por ID podia ficar eternamente inacessível,
mesmo com um candidato único já persistido na fila de revisão.

## Correção

- `goal_ft_last_evidence`: guarda apenas diagnósticos substantivos de
  um evento previamente identificado pelos validadores estritos:
  `goal_no_regulation_score`, `goal_not_finished_or_unverified`,
  `goal_et_evidence_missing`, `goal_penalty_evidence_missing`.
  É independente da última tentativa; indisponibilidades, limites e
  adiamentos por rotação não a substituem.
- A evidência é apagada ao mudar a identidade observada do jogo.
- O planeador GOAL considera a última evidência guardada, mas continua a
  exigir: jogo selecionado na fila normal; um único ID candidato não
  partilhado; equipas `CORE_NAME/EXACT`; orientação correta; KO a
  menos de 5 minutos; nenhuma suspeita de duplicação; quatro horas
  desde a última consulta.
- `goal_id_last_attempt_at`: marca pedidos por ID efetivamente tentados,
  incluindo falhas HTTP, e impede repetir o mesmo pedido antes de 24h.
  Evita também IDs já associados a outro jogo FINAL.
- Cada ID GOAL usa uma chamada **em substituição** de uma consulta por data,
  mantendo o limite global de 2 chamadas por ciclo.
- O painel FT apresenta a última evidência substantiva e o último pedido
  por ID, mesmo quando o motivo da última tentativa foi uma quota.

## Dois IDs BSD individualmente revistos (não aliases globais)

A fila persistente de observação de 28/10/2026 continha:

| match_key AsianOdds | Original | BSD event ID | Prova independente |
|---|---|---|---|
| `2026-10-28,1069,200` | Paderborn – VfB Stuttgart 1893, KO 17:00Z | `602346` | BSD `SC Paderborn 07 – VfB Stuttgart`; OpenFoot `match_olg_87630`, `comp_dfb_pokal_de`; GOAL `855378` DFB Pokal; mesma orientação e KO 17:00Z |
| `2026-10-28,521,159` | Halmstads BK – Malmö, KO 18:00Z | `46506` | BSD `Halmstads BK – Malmö FF`; GOAL `715653` Allsvenskan; mesma orientação e KO 18:00Z |

**Estas entradas são pistas de ID, não confirmação de resultado.**
Só operam para o `match_key`, nomes originais e kickoff exatos,
e obrigam uma **nova leitura da BSD** que verifica ID, ordem casa/fora,
KO e score regulamentar. Não propagam aliases para outros jogos,
nem copiam qualquer resultado de uma API para outra. As diferenças
de nomes foram verificadas individualmente, apoiadas por pelo menos dois
catálogos independentes de eventos. Não há evidência aqui para aprovar
os oito jogos difíceis de 27/10, pelo que continuam PENDING.

O catálogo global fica em cinco IDs aprovados, face aos três anteriores,
com orçamento BSD preexistente máximo de 12 pedidos por ciclo.
O flag `reviewed_bsd_id_check_version=1` impede rechecks compulsivos.

## Critérios de aceitação

1. Testes de preservação de evidência através de deferral, troca de identidade,
   exclusão de ID alheio e cooldown de 24h.
2. Testes de correspondência por `match_key`/equipas/KO e rejeição de
   resposta BSD contraditória; nunca converter prova ambígua em FT.
3. CI, gates de quotas e reconciliação sem novas falhas.
4. Em produção distinguir: jogo **consultado**, consulta dirigida **realizada**,
   resposta **confirmada** e FT **efetivamente novo**. Não declarar sucesso
   empírico sem nova confirmação.

A longo prazo, auditar a cobertura das competições sem arquivo em BSD,
API-Football ou GOAL e reconsiderar somente com dados oficiais adicionais.
