# Controlador central de quota LLM

## Contrato

- Orçamento operacional: **8 000 neurons estimados por dia UTC**. Não existe limite fixo de 4/5/6 chamadas nem exceção por data.
- Antes de cada pedido, reservar **1 000 neurons** de forma persistente. Uma execução (`GITHUB_RUN_ID`, independentemente da tentativa) só pode reservar uma vez.
- Uma resposta com contagem completa de tokens permite substituir a reserva por uma estimativa arredondada para cima. Não é a fatura nem o saldo real da conta Cloudflare.
- Sem medição, em timeout, cancelamento, JSON inválido ou falha de persistência, os 1 000 permanecem reservados. Não se presume consumo zero.
- Uma chamada, sem retries, Llama 3.3 70B, JSON Schema, até 2 400 tokens de saída e timeout de socket de 180 segundos. O job mantém o limite absoluto de 10 minutos.
- Reserva confirmada por CAS antes do HTTP. Conflito, confirmação perdida, estado inexistente/corrompido, histórico incompleto, quota insuficiente ou relógio inválido: **nenhuma chamada**.

## Persistência e concorrência

`h1lab/research_quota.py` é a autoridade. O estado fica em `data/research/quota-ledger.json` no branch dedicado **llm-quota-ledger**. O ficheiro incluído na main é apenas a semente inicial; o runtime nunca escreve o ledger na main.

A API Contents recebe o SHA do conteúdo anterior. Duas reservas concorrentes sobre o mesmo SHA não podem ambas ser aceites. Não há retry automático após conflito ou erro. Cada evento inclui o hash do anterior. A extensão é append-only; liquidações são novos eventos, não alterações de reservas. A deduplicação usa a execução inteira, e o limite de um HTTP também é verificado na fronteira do transporte.

O grupo `v6-llm-global` é preservado como proteção adicional. O job discover precisa de `actions: read` para o histórico e `contents: write` para o CAS do branch dedicado. Este token não é enviado ao modelo e não é persistido no checkout. O publicador científico continua separado e sem segredos do modelo.

## Histórico e UTC

A importação consulta todas as páginas dos dois workflows conhecidos, incluindo execuções antigas reexecutadas recentemente. Obtém todas as tentativas dos jobs relevantes, não só a última. Passos iniciados e falhados contam; skipped e queued sem início não contam. Identificadores de execução/job/passo evitam duplicações. Um run já controlado não volta a ser cobrado através da importação do mesmo passo.

Os registos originais do GitHub e a memória científica não são apagados ou reescritos. São importados os passos cujas execuções foram atualizadas desde o dia anterior, suficientes para a janela atual; os anteriores continuam no histórico original. A listagem é comparada novamente para detetar alterações durante a leitura. Dados ambíguos, outro pedido ainda em curso, paginação incompleta ou execução atual invisível bloqueiam a admissão.

Uma reserva não medida continua a contar nos dias seguintes: um timeout do cliente não prova que o fornecedor terminou. A sua libertação exige reconciliação fundamentada, nunca passagem automática da meia-noite. Pedidos liquidados que atravessam UTC contam nos dois dias. Tentativas históricas sem medição contam a reserva integral nas datas abrangidas e também no dia seguinte, conservadoramente. Um valor medido acima de 1 000 bloqueia futuras admissões até revisão humana.

## Limite por chamada e limites da estimativa

O antigo cálculo empírico de 2 bytes/token foi substituído por 1 token/byte de todo o pedido serializado, acrescido de 512 tokens de margem de framing. O teto do pedido do Llama 70B passa de 30 000 para 18 000 bytes; o cálculo conservador máximo é **986 neurons**, arredondado para cima. O JSON externo é contado com escaping e expansão de caracteres Unicode. Se necessário, retiram-se exemplos e entradas antigas do resumo de memória enviado; **nenhum registo persistido é removido**. A DSL, o schema de resposta, os três planos máximos e os critérios científicos não mudam.

As taxas e o contrato do modelo são pressupostos explícitos do limite interno. O controlador não mede o consumo de outras aplicações na conta e não certifica o saldo Cloudflare. O relatório expõe `account_quota_verified=false`, `cloudflare_remaining_neurons=null` e `INTERNAL_ESTIMATE_NOT_PROVIDER_QUOTA`.

Fontes oficiais verificadas em 2026-11-05:
- https://developers.cloudflare.com/workers-ai/platform/pricing/ — 10 000 neurons gratuitos/dia; reset às 00:00 UTC; dashboard como fonte do consumo real.
- https://developers.cloudflare.com/workers-ai/models/llama-3.3-70b-instruct-fp8-fast/ — modelo e contexto de 24 000 tokens.

O investigador legado usa um alias 8B sem taxas documentadas no perfil local. O seu transporte real fica preventivamente bloqueado; dossier, revisão offline, DSL e gate continuam disponíveis. Toda a investigação real deve passar pelo controlador novo. Não é criada uma via de quota alternativa.

## Ativação posterior (não executada neste PR)

1. Rever e integrar o PR mediante autorização. `llm_live_enabled=false` continua a impedir chamadas.
2. Criar **uma única vez** `llm-quota-ledger` a partir da main integrada, conservando o ficheiro semente. Se o branch já existir, inspecioná-lo; nunca substituir/resetar o seu histórico. Garantir que as regras do repositório permitem ao token do workflow atualizar este branch; uma recusa bloqueia a chamada.
3. Só mediante nova autorização, ativar o interruptor e realizar uma única investigação real com Llama 70B / 180 s. Voltar a desativar o workflow no final. Sem dispatch, enable ou chamada real durante a implementação.
4. Verificar reserva, resposta/timeout, liquidação e consumo no dashboard Cloudflare. Nunca concluir que o saldo interno é a quota real.

Limites de segurança operacionais: o ledger recusa crescer acima de 900 KB e a paginação recusa mais de 100 páginas por recurso. Atingir estes limites exige uma evolução auditada de arquivo/partições, mantendo o histórico; não existe truncagem nem reset automático.

## Verificação

Testes offline cobrem orçamento esgotado, aproveitamento de consumo medido (mais de oito chamadas pequenas), reservas sem medição, timeouts, crash/ack perdido, conflito CAS, duplicação, reexecuções, mudança UTC, relógio recuado, resposta malformada, paginação incompleta, histórico antigo reexecutado, escrita append-only, tamanho de pedido e fronteira HTTP. Integrações CLI usam fornecedores e persistência falsos; não há chamadas reais à Cloudflare.
