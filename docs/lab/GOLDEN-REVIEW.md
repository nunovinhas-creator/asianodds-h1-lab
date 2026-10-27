# Validação manual obrigatória — Golden Set V4

## Estado: NÃO VERIFICADO

Este projeto ainda **não dispõe** de um corpus de mensagens Telegram originais, verificado manualmente e de forma independente. Os resultados `108/108`, `10/10` ou posteriores são apenas concordância entre parsers, nunca verdade-terreno.

## Procedimento de recolha e dupla verificação

1. Selecionar mensagens reais do canal Telegram, incluindo Total ascendente, Total descendente, 1X2 com AH/Total, mudanças de linhas e variantes de apresentação.
2. Um revisor com acesso legítimo ao canal confronta cada mensagem original e respetivas entidades `text-url` com a transcrição. **Não publicar texto integral de mensagens privadas, tokens, credenciais, dados pessoais ou URL assinadas**.
3. Registar por `event_id` os valores verificáveis: identidade, data/hora, trigger, três cotações Was/Now de cada tabela e fontes da observação. Um segundo revisor ou segunda passagem independente valida linha a linha.
4. Comparar os resultados de `h1lab.market_v4.parse` contra os valores transcritos. Para cada campo manter `verified`, `missing`, `rejected` ou `unverified`; não transformar ausências em sucessos.
5. Ficar em **PENDING** se não houver cobertura real de cada família, se alguma origem não for auditável ou se a amostra for demasiado pequena.

## Amostras existentes (não contam como golden)

As mensagens Kaizer Chiefs–TS Galaxy, Al Shamal–Al Hilal e FK Fakel–FK Akhmat foram transcritas para testes em `tests/test_market_v4.py`. Esses testes são importantes para regressão mas **não** demonstram que correspondem a todo o conteúdo original do Telegram.

## Regra estatística

A unidade é a **mensagem Telegram**. Um único 1X2 com três tabelas não é três observações independentes. Calcular limites inferiores exatos unilaterais de Clopper–Pearson a 95% para cada família, sem usar o número de campos como tamanho de amostra. Com 0 falhas, apenas aproximadamente 299 observações independentes por família sustentam um limite inferior de 99%.

**Nenhuma auditoria deve converter automaticamente `golden_set_verified` em verdadeiro:** essa alteração exige evidência independente, testes de confronto e revisão explícita em PR.

## Separação da produção

Este corpus e os seus revisores pertencem exclusivamente ao Market Lab. Nunca modificar o H1, as triplas FIFO, a liquidação, o Telegram ou o cron para preparar ou validar os dados.
