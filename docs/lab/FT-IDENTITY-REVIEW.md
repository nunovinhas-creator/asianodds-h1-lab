# MASTER BRAIN — Fila automática de revisão de identidades FT

**Escopo:** exclusivamente observacional; não modifica H1, picks, triplas, notificações, previsões, aliases aprovados ou marcadores FT.

## O que implementa

Em cada reconciliação FT regular, depois de consultar até 30 jogos com os mesmos limites de cada fornecedor, o sistema percorre **apenas os caches de resposta dessa execução**: API-Football, GOAL, OpenFoot, BSD (somente páginas completas) e SportScore (índices de consulta potencialmente parciais).

O módulo \`h1lab/lab_identity_review.py\` recebe o ledger FT já reconciliado e os caches na memória. Seleciona os jogos não confirmados que passaram KO+3h, identifica correspondências candidatas na janela temporal de ±90 minutos e armazena, no máximo, **2 candidatos por fornecedor / 6 por jogo**. Guarda apenas nomes de equipas, KO, competição, identificador público, URL de referência permitida, orientação casa/fora e métrica de similaridade diagnóstica, **nunca os marcadores, o payload integral da API ou as credenciais**.

A fila incorpora também colisões internas do AsianOdds quando dois \`match_key\` têm a mesma equipa no mesmo horário, sem fundir entradas. Inclui códigos de revisão para conflitos e para falta de prova dos 90 minutos.

O ficheiro \`docs/lab/ft-identity-review.json\` é uma **projeção mutável para revisão humana**, guardada entre ciclos. Mantém candidatos antigos apenas se \`home\`, \`away\` e \`kickoff_utc\` forem exatamente os mesmos; tais candidatos são marcados como \`observed_this_run=false\`, não como confirmação atual. Elimina jogos quando já têm FT ou deixam de ser elegíveis. A lista limita-se a 500 entradas, com contagem explícita de omissões.

## Proteções essenciais

- \`name_similarity_diagnostic\` **nunca** entra na validação ou liquidação. Não há novos aliases, cruzamentos automáticos, alterações de \`lab_identity.py\`, previsões retroativas ou resultados presumidos.
- Os dados dos caches são utilizados **depois** da reconciliação; nenhuma API é chamada para criar a fila.
- A razão \`NO_MATCH_FOUND_IN_AVAILABLE_CACHES\` não prova a ausência real do encontro; resultados podem faltar ou as listagens ser parciais.
- Candidatos preservados de execuções anteriores **não são observações atuais**.
- O pipeline FT pode publicar os FT mesmo que a construção não crítica da fila falhe: o erro não modifica o ledger.
- O dashboard em \`docs/ft-identity-review.html\` apresenta estados de revisão e os motivos da última tentativa, mas não valores de golos nem resultados inventados.

## Validação e operação

Testes sintéticos em \`tests/test_lab_identity_review.py\` verificam coincidências, inversões, qualificadores U19/U21, duplicados, persistência, invalidação por mudança de identidade, separação futuros/tolerância de 3h, falhas de paginação e ausência de marcadores/segredos.

Depois do merge, esperar uma execução real de \`Lab - Reconcile FT for all observed matches\` e confirmar: \`LAB_FT_IDENTITY_REVIEW\` nos logs, publicação do JSON, \`total_eligible\` consistente com a fila de atrasados e zero mudanças no resultado dos testes/ledger por efeito da fila. Os valores do snapshot só são reais após essa execução.

**Links:** [Painel de revisão](../ft-identity-review.html) · [JSON da fila](ft-identity-review.json) · [FT atrasados](ft-backlog.json).
