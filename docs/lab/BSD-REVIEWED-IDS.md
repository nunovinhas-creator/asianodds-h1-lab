# LAB — IDs BSD reais descobertos para liquidação direta (28/10/2026)

## Prova
O diagnóstico read-only de produção `Lab - BSD event ID discovery diagnostic`, run [40656748110](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40656748110), consultou a BSD e obteve:
- 71 jogos terminados no catálogo de 27/10 e 1 de 28/10 (72 eventos).
- Entre 51 jogos pendentes de 27/10, **0 correspondências com nomes iguais** e **3 candidatos fortes de nomes alternativos**, com horário coincidente em ±90 minutos.
- Nenhuma liquidação foi feita por este diagnóstico.

Correlações explícitas, restritas a cada `match_key` e ao início UTC original:
- `2026-10-27,505,27518`: AA Argentinos Juniors – CS Independiente Rivadavia, 22:00 UTC -> BSD **223844** (Argentinos Juniors – Independiente Rivadavia).
- `2026-10-27,226,1739`: 1. FC Köln – Union Berlin, 19:45 UTC -> BSD **602348** (1. FC Köln – 1. FC Union Berlin).
- `2026-10-27,240,227`: Roma – Cagliari, 19:45 UTC -> BSD **210138** (AS Roma – Cagliari).

## Novo caminho
1. Se o LAB não encontrar o jogo por pesquisa normal BSD, usa o registo restrito `h1lab/lab_reviewed_bsd_ids.py` para identificar o ID BSD real.
2. Invoca o mesmo código de consulta direta BSD usado para o Monte-Carlos: `GET /api/v2/events/{id}/`, incluindo suporte a envelopes, status e até cinco `replaced_by`.
3. A API tem de devolver o **mesmo ID numérico**, nomes casa/fora BSD ordenados, data/hora compatível e resultado do tempo regulamentar. Um evento divergente ou sem marcador explícito permanece pendente.
4. Os três jogos têm direito a **uma única verificação imediata** mesmo dentro do cooldown de 4 horas. Depois, não se permite nova tentativa extraordinária.
5. Todos os outros fornecedores e as regras de resolução de conflitos ficam disponíveis e inalteradas. O resultado é rotulado como fonte BSD; o ID não é um ID AsianOdds.

**Em nenhuma circunstância** os IDs numéricos da chave AsianOdds são usados como ID BSD sem descoberta prévia do correspondente. A existência do candidato não confirma automaticamente o resultado; só a consulta direta com validação integral o pode confirmar.

## Segurança e limitações
São três candidatos descobertos num universo limitado. A BSD gratuita só listou 72 eventos (71 no dia principal), pelo que muitos dos restantes jogos podem não ter cobertura. Taças e jogos com prolongamento só serão aceites se houver marcador regulamentar explícito. Sem ROI, GREEN/RED ou atualização do motor de apostas H1.

Teste com SQLite sintético, nomes alterados, ID errado, hora divergente, status ET e verificação única do cooldown. Saídas apenas `data/lab/ft-ledger.json` e `docs/lab/ft-results.json`.
