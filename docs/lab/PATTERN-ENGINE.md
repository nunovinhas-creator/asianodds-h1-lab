> **Estado revisto em 28/10/2026:** este é o **cérebro de investigação V5 ativo** do MASTER BRAIN, agora apresentado na [página principal](../../docs/index.html) (não o H1 de triplas). Ver [guia visual e conceptual](CEREBRO-ODDS.md) e [dashboard](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-research.html). No relatório de 11:16 UTC, 267 jogos observados, 263 elegíveis, 60 FT nesta pesquisa, 800 hipóteses `EXPLORATORIO`, **zero CANDIDATO / VALIDADO** e registo congelado vazio. É um instantâneo, não os números atuais. `results.yml` importa FT finais via `h1lab/lab_promotion.py`, **mas não importa hipóteses V5 nem muda apostas**.

# Motor de investigação V5 — padrões, combinações e validação

Modo LAB. Não lê nem altera ficheiros H1 além de **ler** `data/state.json` e `data/results.csv`. Não cria apostas, não calcula ROI nem EV.

## 1. Cadeia de dados

```
state.json + markets-*.jsonl ──timeline.collect_timelines──► cronologia por jogo (mensagem → snapshot → movimento → jogo)
                                                     │
                                     pattern_features.match_features (só mensagens antes do início)
                                                     │
ft-ledger.json (LAB) + results.csv (H1, só preenche lacunas) ──► resultados confirmados de 90 min
                                                     │
                                pattern_engine.run ──► docs/lab/pattern-research.json
                                                   └─► data/lab/pattern-registry.json (append-only)
```

Execução: passo `continue-on-error` em `lab-ft-results.yml`, logo após a reconciliação FT (a cada 30 min). Cache de características em `data/lab/.cache/` via `actions/cache` (fora do git); só jogos com impressão digital alterada são recalculados.

## 2. Unidade e momento de decisão

- Unidade: **jogo** (`match_key`). Mensagens repetidas do mesmo movimento formam um **episódio** (ligações da cronologia) e nunca contam como ensaios independentes.
- Momento de decisão: `observed_at` da **última mensagem antes do início**. Alertas pós-início são contados e nunca usados.
- Jogos sem hora de início, com identidade inconsistente ou sem mensagem pré-início ficam excluídos (contados em `scope.excluded`).

## 3. Espaço comum entre linhas (`market_math`)

Odds de linhas diferentes não se comparam diretamente. Cada cotação Total (linha, Over, Under) é convertida na média de golos de Poisson λ que a torna justa, com liquidação asiática exata (push nas linhas inteiras, meia aposta nas linhas de quarto) e remoção proporcional da margem. `P(Over 2,5)` derivada de λ é uma **referência do modelo**, nunca uma odd de Over 2,5.

## 4. Padrões individuais (`FEATURE_VERSION = 1`)

49 padrões com limiares fixos a priori (ver `PATTERNS` em `h1lab/pattern_features.py`):

| Família | Exemplos | Regra |
| --- | --- | --- |
| TOTAL | linha sobe/desce/igual, salto ≥ 0,5 | dentro de uma mensagem (Was→Now) |
| OU_PRICE | Over/Under sobe/desce, ambos sobem | **só com a mesma linha**; variação > 0,005 |
| IMPLIED | λ sobe/desce/estável (±0,05), linha e λ em sentidos opostos, variação líquida 1.ª→última (±0,20 / < 0,10) | espaço λ |
| 1X2 | prob. sem margem da casa/empate/fora ± 1 pp | dentro da mensagem |
| AH | linha desce (casa mais favorecida) / sobe / igual | dentro da mensagem |
| TRIGGER | mercado e seleção que dispararam o alerta | |
| TIME | mensagem < 60 min ou > 24 h; 1.º alerta < 6 h / 6–24 h / > 24 h; intervalos < 30 min ou > 6 h | entre episódios |
| SEQUENCE | uma/várias mensagens, vários episódios, mesmo sentido repetido, sentidos opostos, intensificação/abrandamento, mudança de linha não observada | entre episódios |
| CONTEXT | última linha ≥ 3,25 / 2,5–3,0 / ≤ 2,25; Total e 1X2 no mesmo jogo | |

Entre duas mensagens só existe o que a cronologia regista: mudança **não observada**; nada é interpolado.

## 5. Geração de hipóteses

Só a partir dos padrões (os resultados nunca entram na geração):

- `HAS` A · `AND` A∧B · `AND_NOT` A sem B · `BEFORE` A antes de B (primeiras ocorrências em episódios diferentes) · trios A∧B sem C (25 pares mais frequentes).
- Suporte mínimo 5 jogos; complemento também ≥ 5.
- Redundância: conjunto de jogos igual (ou exatamente o complemento) de uma hipótese mais simples → descartada e listada como equivalente.
- Pares mutuamente exclusivos não são gerados. Máximo 800 hipóteses (ordem: complexidade, suporte, id).
- Id estável `P5-` + SHA-256 da definição canónica + versão das características.

## 6. Associação com resultados

Resultados testados: **Over 2,5** e **BTTS Sim** (Under 2,5 e BTTS Não são complementos, não são testados duas vezes). Total de golos: média e IC, descritivo.

Por hipótese e resultado: jogos, conhecidos/desconhecidos/futuros, acertos/falhas, taxa com IC de Wilson, taxa nos jogos sem a hipótese (referência), diferença com IC de Newcombe, Fisher exato bilateral, **q de Benjamini–Hochberg** sobre todos os testes da execução, taxa implícita pelo mercado e z face a ela (Over 2,5), cobertura FT de cada grupo, desempenho por dia e por metade cronológica.

Teste só com ≥ 10 jogos com FT em cada grupo.

## 7. Estados

| Estado | Regra |
| --- | --- |
| `EXPLORATORIO` | omissão; estatísticas sobre todos os FT conhecidos |
| `CANDIDATO` | cumpriu os critérios de descoberta e foi **congelada** no registo (definição, resultado, sentido, estatísticas, hora); < 10 resultados fora da amostra |
| `EM_VALIDACAO` | congelada; 10 ≤ n fora da amostra < 30 |
| `VALIDADO` | em ponto de controlo fixo (30, 60, 90… jogos fora da amostra): Fisher unilateral no sentido congelado com p ≤ 0,05 / (n.º de hipóteses alguma vez congeladas), efeito ≥ 5 pp no mesmo sentido, cobertura FT equilibrada (diferença ≤ 20 pp) e, para Over 2,5, z ≥ 1,645 face à probabilidade implícita pelo mercado |
| `REJEITADO` | falhou um ponto de controlo, ou inverteu cedo (n ≥ 15 com efeito contrário ≥ 10 pp). Terminal |

Critérios de descoberta para congelar: ≥ 20 FT em cada grupo, q ≤ 0,10, |diferença| ≥ 10 pp, cobertura FT equilibrada e mesmo sentido nas duas metades cronológicas. No máximo 10 hipóteses ativas.

**Fora da amostra** = jogos cujo **primeiro** alerta pré-início foi observado depois da hora de congelamento. Os dados da descoberta nunca servem de prova. As decisões dos pontos de controlo são acrescentadas ao registo; definições congeladas não podem ser alteradas (o motor recusa publicar se o hash não coincidir ou se uma entrada for reescrita/removida).

Degradação: uma hipótese `VALIDADO` cuja segunda metade fora da amostra inverte o sentido é marcada `degradation_flag`; o ponto de controlo seguinte decide.

## 8. Jogos semelhantes (`similarity`)

Distância de Gower com escalas fixas (não ajustadas aos dados) sobre: variação líquida de λ, maior variação numa mensagem, última linha, λ na decisão, n.º de episódios, antecedência do 1.º e do último alerta, 1X2 presente, sentido AH, sentidos opostos, alerta tardio; mais Jaccard dos padrões de movimento. Vizinho elegível só se o seu início + 3 h ≤ momento de decisão do jogo alvo. O marcador nunca é característica. Avaliação *walk-forward* (Brier) do estimador kNN contra taxa histórica e contra o mercado implícito, nos mesmos jogos.

## 9. Resultados FT — identidade `CORE_NAME`

`h1lab/lab_identity.py`: nomes iguais depois de remover uma lista fechada de designadores (`FC`, `AS`, `Calcio`, `1.`, `CS`, `AA`…) e mapear exónimos (`Köln`→`Cologne`, `Wien`→`Vienna`…). Sem semelhança aproximada nem subconjuntos. Rejeita: ordem invertida, dois candidatos, outro jogo na janela com o mesmo clube, qualificadores diferentes (U21, reservas, feminino). Aplicado ao ESPN e à lista diária BSD já descarregada (sem pedidos extra). O método fica em `identity_match` no ledger.

## 10. Limitações

- Universo = jogos anunciados pelo canal; conclusões condicionadas a haver alerta.
- Resultado desportivo ≠ liquidação de uma aposta asiática.
- Com poucas dezenas de FT, quase tudo fica `EXPLORATORIO`; isso é o comportamento correto.
