# Primeiro estudo empírico — alertas repetidos (exploratório)

**Componente:** `h1lab/trajectory_research.py`
**Entrada:** `docs/lab/match-trajectories.json`
**Saída:** `docs/lab/trajectory-research.json`
**Estado obrigatório:** `EXPLORATORY_NO_OUTCOME_TEST`

## Pergunta

Quando um jogo aparece mais do que uma vez no canal AsianOdds, que informação adicional é observável? Quantos movimentos de Total são de subida ou descida? Em quantos jogos se observam ambos os sentidos? Quantos alertas parecem reportar o mesmo movimento?

## Unidade de análise

- **Evento Telegram:** unidade descritiva para direções UP/DOWN/FLAT dentro da própria mensagem.
- **Jogo (`match_key`):** unidade para proporções de padrões, evitando que três alertas do mesmo jogo sejam três amostras independentes.
- **Movimento:** só uma relação anotada (ex.: snapshots Total idênticos com 120 segundos de proximidade). **Não se apagam mensagens nem se afirma independência real.**

Os relatórios usam apenas os jogos repetidos publicados no JSON de cronologia. O número de jogos ocultados por limite de publicação é explícito (`repeated_matches_omitted`). Se o limite entrar em ação, as percentagens passam a referir-se **somente à amostra de jogos repetidos publicados**, não a todos os jogos existentes.

## Métricas

| Campo | Interpretação |
| --- | --- |
| `total_line_within_alert.up/down/flat` | Movimento de linha dentro de cada alerta (tabela `Was/Now`) |
| `match_level_patterns.opposing_intra_alert_directions` | Pelo menos um alerta UP e outro DOWN para o mesmo jogo; **não comprova o percurso não observado entre eles** |
| `transitions.unobserved_change` | Linha do alerta seguinte começa diferente da linha no final do anterior |
| `transitions.ambiguous_repeat_or_reversal` | Linhas antes/depois repetidas fora da janela de proximidade |
| `transitions.identical_total_pairs` | Dois eventos com a mesma tabela Total; possível redundância, não certeza |
| `time_to_kickoff` | Mensagens por estágio: depois do início, T−0 a 60, T−60 a 360, T−360 a 1440, >T−1440, sem hora |
| `total_line_within_alert.by_origin` | Separação entre fonte V4 explícita e valores apenas do H1 legado |

As proporções por jogo são **descritivas e selecionadas**: o canal só observa movimentos que desencadeiam alerta. Não há linha de fecho, feed contínuo, controlo de eventos sem alerta, preços executáveis nem amostra aleatória.

## Regras de integridade

1. Verificar que a cronologia não tem IDs duplicados e que `sampling` corresponde ao resumo.
2. Guardar a origem V4 versus H1 legado, sem transformar o registo H1 em verificação independente.
3. Registar todos os alertas pós-início separadamente, não os misturar numa análise pré-jogo.
4. Rejeitar rótulos de movimento inesperados ou cronologia de commit diferente da recolha atual.
5. Não criar predições, picks, apostas, ROI ou EV.
6. Cada resultado exploratório é datado e ligado ao `source_commit` da cronologia.

## Fase seguinte, apenas quando existirem dados suficientes

Congelar hipóteses antes da recolha fora da amostra:

- **H1 — Reversão vs Total FT:** contraste de jogos com direções opostas observadas e jogos com direção única, com resultados FT independentes e tempos pré-jogo estratificados.
- **H2 — Persistência das mudanças:** exige *snapshots subsequentes com cobertura homogénea* e uma referência externa à linha de fecho, sem interpolação.
- **H3 — Redundância entre tipos de alerta:** estudar pares Total+1X2 sobre o mesmo `match_key`, usando jogo como cluster.

Para rentabilidade, fixar primeiro mercado, odd efetivamente disponível, regra de entrada ex ante, comissão/margem, unidade de aposta, liquidação FT, jogos sem sinal, temporadas fora da amostra e limites de confiança por jogo. **Não fazer apostas com base nesta análise inicial.**

## Execução

Manual: `python -m scripts.lab_trajectory_research`. Sem dependências externas.

Automática: após a geração da cronologia no workflow `lab-v4-audit.yml`, em **modo LAB não bloqueante**, com asserção de que `LAB_SOURCE_SHA` coincide com `source_commit`. A falha não interrompe o H1 nem falsifica o relatório.

Testes: `python -m unittest discover -s tests -p 'test_trajectory_research.py' -v` e workflow `Lab - Repeated odds empirical study smoke`.
