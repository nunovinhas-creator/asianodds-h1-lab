# Cérebro UNDER TESTE — como são cruzadas odds, padrões e resultados

**Estado:** motor de investigação V5 integrado no LAB e com relatório público; **não executa apostas**, **não escolhe picks para o H1** e **não calcula ROI ou EV**. É possível ver os resultados em [Análise técnica LAB / cérebro V5](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-research.html). Código: [pattern_engine.py](../../h1lab/pattern_engine.py); especificação completa: [PATTERN-ENGINE.md](PATTERN-ENGINE.md).

## 1. H1, V4 e V5 são coisas diferentes

| Motor | Objeto | Função |
| --- | --- | --- |
| **H1 original** | Sinal Under do 1.º alerta elegível por jogo; três sinais formam uma tripla FIFO | Simulação e liquidação asiática; nunca altera uma seleção com base nas conclusões V5 |
| **V4 observador** | Snapshots e movimentos das mensagens Telegram | Captura Total, 1X2 e AH com hora, identidade e origem dos dados; Golden Set ainda não certificado |
| **V5 cérebro** | **Jogo como unidade de análise**, com todos os alertas anteriores ao início | Descobre e testa hipóteses entre movimentos, sequências e resultados, com comparação entre grupos e validação fora da amostra |

O «cruzamento de apostas» significa aqui **cruzar características dos mercados e as suas relações estatísticas com resultados desportivos**. Não significa criar automaticamente múltiplas nem combinar odds de casas como se estivessem disponíveis na mesma altura.

## 2. O fluxo do cérebro

~~~text
Telegram AsianOdds → alertas com event_id / match_key / observed_at
                                  ↓
V4 (Total, 1X2, handicap) + alerta H1 legado com origem identificada
                                  ↓
Cronologia por jogo (snapshots, episódios, repetições, reversões)
                                  ↓
pattern_features.py → 49 padrões pré-definidos
                                  ↓
pattern_engine.py → HAS; AND; AND_NOT; BEFORE; trios
                                  ↓
FT verificados: ft-ledger.json + lacunas em results.csv
                                  ↓
Over 2,5; BTTS Sim; média de golos; base de comparação
                                  ↓
Fisher, Wilson, Newcombe, BH/FDR, cobertura e tempos
                                  ↓
EXPLORATORIO → CANDIDATO → EM_VALIDACAO → VALIDADO ou REJEITADO
                                  ↓
Relatório + pesquisa de jogos semelhantes (sem acesso ao resultado futuro)
~~~

**Os resultados entram depois da extração de características.** O cérebro nunca usa o resultado do próprio jogo para decidir quais os seus padrões pré-jogo.

## 3. Que informações concretas são cruzadas?

- **Total asiático:** alteração da linha, odds Over/Under e movimentos de preço **apenas quando comparáveis na mesma linha**.
- **Espaço comum de golos:** `market_math.py` calcula uma referência de golos implícitos λ e Over 2,5 a partir das odds asiáticas, considerando push e meia liquidação. É uma hipótese de modelo, não a cotação observada do mercado Over 2,5.
- **1X2:** evolução de probabilidades sem margem para casa, empate e fora.
- **AH:** alteração da linha de handicap e direção favorável à equipa da casa/fora.
- **Sequência temporal:** vários alertas, episódios repetidos, sentidos opostos, intensificação, primeira/última mensagem, intervalos, proximidade do início.
- **Contexto:** última linha, mercado que disparou a mensagem, presença simultânea de Total e 1X2 e variação antes/depois.

As hipóteses são do tipo **A**, **A e B**, **A sem B**, **A antes de B** e **A e B sem C**. A última combinação não é uma múltipla apostada: é uma condição lógica entre padrões.

### Exemplo sintético (não é um jogo real)

1. Em T−180 minutos: a linha Total passa de 2,50 para 2,75 e a odd Over sobe. O H1 pode registar um Under **se todas as suas regras temporais forem satisfeitas**.
2. Em T−90 minutos: há um movimento 1X2 e um movimento de handicap.
3. Em T−35 minutos: aparece um novo alerta Total em sentido oposto. O LAB regista a sequência; **não inventa cotações entre alertas**.
4. O V5 procura jogos com condições semelhantes, compara o seu comportamento FT com os jogos sem o conjunto e usa a probabilidade implícita do mercado como referência para Over 2,5.
5. **Não é criada uma aposta** por o padrão estar presente. Só com nova evidência independente e gates estatísticos rigorosos uma hipótese poderá ser classificada como validada no LAB.

## 4. Segurança contra descobertas falsas

| Regra | Porque existe |
| --- | --- |
| Um `match_key` = uma observação | Várias mensagens de um jogo não são vários ensaios independentes |
| Só informação anterior ao início | Evita «prever» com dados que ainda não existiam |
| Mínimo 5 jogos com/sem hipótese para geração | Descarta condições triviais e ultra-raras |
| Máximo 800 hipóteses | Controla explosão combinatória e explicita hipóteses descartadas |
| Controlo de FDR/BH, Fisher e IC | Reduz falsos positivos de testes múltiplos |
| Descoberta: ≥20 FT em ambos os grupos, q≤0,10, efeito ≥10 pp e estabilidade temporal | Exige evidência mínima antes do congelamento |
| Congelamento por hash em `pattern-registry.json` | Proíbe reescrever uma hipótese depois de conhecer novos resultados |
| Fora da amostra posterior ao congelamento | Os jogos usados na descoberta nunca validam a mesma hipótese |
| Checkpoints a 30, 60, 90… jogos OOS, com possibilidade de rejeição | Evita promoção com meia dúzia de jogos favoráveis |

Os cinco estados são `EXPLORATORIO`, `CANDIDATO`, `EM_VALIDACAO`, `VALIDADO` e `REJEITADO`. **VALIDADO** significa apenas que os critérios estatísticos internos foram cumpridos, não que uma estratégia real com retorno líquido positivo tenha sido demonstrada.

## 5. Estado empírico (fotografia consultada a 28/10/2026, 11:16 UTC)

| Medida | Valor |
| --- | ---: |
| Jogos observados | 267 |
| Jogos elegíveis para V5 | 263 |
| FT incluídos na investigação | 60 |
| Padrões individuais com suporte | 46 de 49 |
| Hipóteses avaliadas | 800 |
| Testes estatísticos reportados | 1 274 |
| Hipóteses em EXPLORATORIO | 800 |
| Candidatos congelados / VALIDADOS | **0 / 0** |
| Jogos semelhantes publicados | 30 |

O relatório [pattern-research.json](pattern-research.json) e o [registo](../../data/lab/pattern-registry.json) têm o estado efetivo da última execução. O FT universal continha 63 resultados noutra fotografia (11:15 UTC): as contagens podem não coincidir por elegibilidade, momento de decisão e publicação assíncrona.

**Nenhuma hipótese tem hoje vantagem estatística replicada demonstrada.** O mecanismo está preparado para estudar e falsificar hipóteses quando a amostra crescer.

## 6. O que vai e não vai para o dashboard H1

O V5 **não envia hipóteses, odds ou novas apostas para o H1**. A ligação `h1lab/lab_promotion.py` importa apenas **placares FT finais** do LAB, para liquidar sinais Under e triplas **que o H1 já tinha registado previamente**. Uma importação exige jogo, equipas, horário, golos e fonte válidos; não substitui um resultado H1 previamente confirmado.

A pesquisa V5 é executada depois da reconciliação FT no [workflow LAB](../../.github/workflows/lab-ft-results.yml), em modo `continue-on-error`: uma falha do cérebro não pode bloquear a liquidação nem criar decisões silenciosas.

## 7. Código, testes e documentação

- `h1lab/pattern_features.py` — criação de características/padrões;
- `h1lab/market_math.py` — comparação de linhas asiáticas por λ;
- `h1lab/pattern_engine.py` — combinações, testes estatísticos, estados e registo;
- `h1lab/similarity.py` — jogos semelhantes, só antecedentes elegíveis;
- `h1lab/lab_stats.py` — testes e intervalos;
- `scripts/lab_pattern_research.py` — execução e publicação;
- `tests/test_pattern_engine.py` — regressões sintéticas.

**Leitura complementar:** [metodologia detalhada V5](PATTERN-ENGINE.md), [arquitetura](ARCHITECTURE.md), [cronologia por jogo](TIMELINE.md), [todos os FT](ALL-OBSERVED-FT.md), [revisão Golden](GOLDEN-REVIEW.md) e [README raiz](../../README.md).

**Limitações:** universo seletivo do canal, ausência de série contínua de mercado, potencial correlação entre jogos, cobertura FT variável, múltiplas hipóteses e custo de execução real não modelado. Uma taxa histórica atraente não é um pick e não garante ROI.
