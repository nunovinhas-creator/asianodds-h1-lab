# UNDER TESTE — fase seguinte: prontidão para validação por resultados

**Estado:** preparação **sem testar resultados**. O script `h1lab/outcome_readiness.py` lê a cronologia de jogos repetidos e os ficheiros de liquidação H1 existentes, **sem modificar nenhuma destas fontes**. Executável: `python -m scripts.lab_outcome_readiness`. Saída: `docs/lab/outcome-readiness.json`.

## Porquê esta fase

O primeiro estudo `REPEATED-ODDS-EMPIRICAL.md` descreve a frequência e as direções dos movimentos, sem resultados finais. Até existir correspondência verificável entre **jogo → sequência observada antes do início → resultado FT**, qualquer conclusão sobre poder preditivo seria uma inferência sem base. O H1 apenas procura resultados das suas próprias apostas simuladas; **não segue todos os jogos do canal**. Portanto um jogo fora de `data/results.csv` **não pode** ser classificado como derrota, falta de golos nem falha da BSD.

## O que o relatório mede

- Jogos repetidos publicados vs omitidos por amostragem da cronologia. Cobertura só sobre os publicados; não generalizar.
- Quantos possuem um resultado FT válido já registado em `data/results.csv`, quantos estão em `data/result_audit.json` e quantos não são acompanhados pelo H1.
- Estágio temporal de cada jogo relativamente à hora do relatório: antes do início, antes de 3 h após o início, após essa janela, ou horário desconhecido.
- Quantos jogos têm todas as observações pré-início e quantos têm pelo menos duas mensagens Total pré-início não-flat. Duas mensagens **não provam dois movimentos independentes**.
- Rejeita resultados duplicados; só aceita `final` com golos inteiros não negativos e URL HTTPS. Uma entrada registada no H1 **não equivale a confirmação independente adicional neste estudo**.

Não calcula nem publica odds de entrada, valor esperado, ROI, GREEN/RED, significância estatística ou resultados por estratégia.

## Protocolo a pré-registar ANTES de ensaios fora da amostra

1. **Congelar** numa PR futura, antes do período de teste: instante UTC inicial, universo de ligas, regras de elegibilidade, mínimo de antecedência, tratamento de repetições e definição inequívoca de uma reversão. Não utilizar 27/10/2026 para escolher limiares com base nos resultados futuros.
2. **Unidade primária:** um `match_key` por jogo, nunca uma mensagem ou mercado. Quando o mesmo movimento surge em Total e 1X2, classificar como observações correlacionadas, não duas oportunidades.
3. **Sem fuga temporal:** usar somente alertas com `observed_at` e `minutes_to_kickoff` válidos, publicados ANTES do início. Alertas após o início excluídos da análise pré-jogo.
4. **Endpoint futuro:** total de golos regulamentares (90 min + descontos), de fonte externa auditável, correspondência inequívoca de equipas/hora, excluindo prorrogação/penáltis. Divergências de fornecedores ficam pendentes.
5. **Hipótese H1 exploratória:** comparar jogos com pelo menos duas direções Total pré-jogo opostas e jogos com direção única, definidos antes da observação dos resultados. Comparar por grupos temporais e ligas se a amostra permitir; reportar incerteza por jogo e viés de seleção do canal.
6. **Critérios de bloqueio:** nenhum teste inferencial se cobertura FT for baixa ou diferencial entre grupos; não antecipar a certificação V4, Golden Set, logs e amostra fora do período de desenvolvimento.
7. **Rentabilidade é projeto separado:** só depois de confirmar sinal preditivo e de obter cotações reais executáveis, margens, comissões e slippage num modelo pré-registado.

Esta PR **não congela ainda um corte temporal** nem declara o ensaio fora da amostra iniciado. Estabelece apenas um monitor para saber quando será tecnicamente justificável iniciar esse ensaio.

## Segurança e automação

Apenas cria ou altera ficheiros `h1lab/outcome_readiness.py`, `scripts/lab_outcome_readiness.py`, `tests/test_outcome_readiness.py`, este documento, `docs/lab/outcome-readiness.json` e o workflow **LAB**. A rotina de 5 minutos do H1, a regra H1, as triplas FIFO, o Telegram, a BSD e os resultados guardados não são alterados. Falhas do relatório de prontidão não podem bloquear a publicação V4/Golden nem o H1.

Testes: `python -m unittest discover -s tests -p 'test_outcome_readiness.py' -v`. O relatório exige `LAB_SOURCE_SHA` igual ao da cronologia quando executado em produção e recusa amostragem interna inconsistente.
