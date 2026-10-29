# MASTER BRAIN — alertas Telegram: cinco estratégias V5

**Ativação:** PR #110, substitui exclusivamente a etapa de notificações em `.github/workflows/collect.yml`. **O coletor H1, o reconciliador FT e os seus estados não são desligados.** O emissor anterior (`h1lab.pattern_notify`) deixa de ser chamado; `data/pattern-notifications.json` mantém os recibos antigos inalterados.

## As cinco estratégias fixas (não rotativas)

| Nº | Mercado | Padrão V5 | Condição técnica |
| --- | --- | --- | --- |
| 1 | Over 2,5 | P5-e9298e23d3 | `HAS M_AH_TOWARD_AWAY` |
| 2 | Over 2,5 | P5-8d66f63e92 | `M_IMPLIED_GOALS_FLAT AND NOT G_FIRST_LEAD_LT_6H` |
| 3 | Ambas marcam | P5-8d66f63e92 | Igual à nº 2, outcome `BTTS_YES` |
| 4 | Over 2,5 | P5-d92fc19ce8 | `G_LAST_LINE_HIGH AND NOT G_WEAKENING` |
| 5 | Over 2,5 | P5-8bced1b27e | `G_NET_IMPLIED_SMALL AND NOT G_FIRST_LEAD_LT_6H` |

Os IDs e condições vêm do relatório V5 existente em 29/10/2026. **A seleção não é reconstruída a partir do ranking** quando o relatório muda. Se a definição publicada passar a divergir, o emissor falha explicitamente; se o padrão sair do top N, continua a vigiar a regra fixa, mas não inventa taxas históricas.

## Processo

No workflow de recolha existente, o emissor usa apenas a cronologia `collect_timelines` e `match_features` do V5, reconstruídas com observações datadas até ao instante da execução, antes do início de cada jogo. Exige prova V4 explícita para as condições afirmativas; não infere AH, gols implícitos ou preços a partir de nome/linha imaginados. Condições de ausência são apenas verdadeiras **até à fotografia atual**: novo movimento pode invalidá-las antes do início. Para `G_WEAKENING`, se falta lambda dos episódios, não confirma ausência de enfraquecimento.

Pode identificar jogos **anteriormente observados** (inclusive hoje) desde que **ainda não tenham começado**. Não envia novas notificações após o início; não monitoriza jogos em direto e não é um sistema de apostas. Agrupa todos os mercados/estratégias recém-confirmados de um mesmo jogo numa só mensagem, com cabeçalhos `🎯 ESTRATÉGIA N/5 — MERCADO`, descrição factual, amostra histórica *quando publicada* e advertência `EXPLORATÓRIO`.

## Receção e duplicação

O ledger novo `data/strategy-notifications.json` guarda uma entrada por `match_key|strategy_number` e a ID da mensagem Telegram enviada. Um jogo com cinco condições origina até cinco recibos, mas **apenas uma mensagem** no mesmo ciclo. Só uma nova condição, ainda não enviada nesse jogo, pode originar uma mensagem adicional. Envio incerto fica `delivery_uncertain_manual_review` e não tem reenvio automático. Se o bot não estiver configurado, não consome recibos.

O workflow usa o grupo de concorrência `asianodds-h1-write`, mas **não há garantia de exactly-once**: se o processo morrer depois de o Telegram aceitar a mensagem e antes de o recibo ser enviado para o GitHub, um próximo ciclo pode repetir. Diagnosticar por logs/receção antes de reativar após um crash.

## Validação sem enviar

```bash
python -m h1lab.strategy_notify --dry-run
python -m unittest tests.test_strategy_notify -v
python -m unittest discover -s tests -v
```

O dry-run imprime `match_key`/nomes, início, números de estratégias e contagem total. **Não lê segredos do bot, não envia mensagens, não grava recibos.** A primeira execução real depois da ativação pode enviar alertas dos jogos já identificados **ainda futuros**; não faz despejo de partidas já começadas.

Os percentuais V5 são taxas históricas em jogos FT, **não** probabilidades calibradas nem demonstração de EV, ROI ou estratégia comprovada. Sem odds realmente disponíveis de entrada não se afirma rentabilidade.
