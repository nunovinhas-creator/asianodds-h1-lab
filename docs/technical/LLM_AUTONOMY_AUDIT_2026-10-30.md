# Investigador: auditoria e plano de autonomia — 30/10/2026

## Evidência e limites

Base inspecionada: b2861999d26917fb65361aaf93ce8089bb140601.
Índice público: 0 execuções do novo contrato, latest=null. A execução
41039239732 tem um job investigator bem-sucedido, sem job publish;
não demonstra o novo circuito de publicação.

O cliente fazia uma chamada, sem retries, max_tokens=1600 e corpo <=20 KB,
mas descartava usage. O relatório publicava neurons_consumed=null.
Esta alteração preserva contadores inteiros allowlisted de tokens (se disponíveis),
sem os confundir com neurons ou saldo disponível. Falhas podem consumir quota;
contar apenas relatórios publicados subestima utilização.

A documentação oficial consultada em 30/10/2026 indica 10.000 neurons/dia,
reset às 00:00 UTC. No Free, exceder a franquia falha; no Paid pode gerar custo.
Fonte: https://developers.cloudflare.com/workers-ai/platform/pricing/
Não foi verificado diretamente o plano nem o saldo atual da conta.
O alias configurado @cf/meta/llama-3.1-8b-instruct-fast não aparece literalmente
na tabela consultada: não lhe atribuir silenciosamente o preço de fp8-fast.
Limitar max_tokens restringe saída, mas não mede entrada nem garante custo zero.

## Uma execução controlada: pré-condições

1. No dashboard Cloudflare, abrir Workers AI / utilização e selecionar o dia UTC;
   confirmar Workers Free e registar timestamp, modelo e neurons consumidos A.
   Não colocar tokens de acesso em relatórios, issues ou mensagens.
2. Confirmar o preço/identidade do alias e o orçamento máximo de entrada+saída.
   Reservar pelo menos 50% da franquia para outros serviços. Se não for possível
   estabelecer margem suficiente, bloquear a chamada.
3. Com produção revista e autorização existente para uma chamada, executar
   workflow_dispatch cloudflare_once / CONSUMIR_IA_UMA_VEZ uma única vez.
   Registar run_id e SHA; não repetir automaticamente após erro.
4. Esperar a atualização das métricas Cloudflare e registar B no mesmo dia UTC.
   B-A é consumo da conta no intervalo: só atribuível a este pedido se não
   houve outros consumidores. Caso contrário, marcar como não atribuível.
5. Confirmar investigator, artefacto, publish, commit contendo índice e arquivo,
   deploy Pages bem-sucedido e renderização real no navegador. Git push não
   demonstra deploy Pages; pushes com GITHUB_TOKEN podem não disparar outros
   workflows. Verificar a configuração efetiva do Pages.
6. Conferir hashes e SHA das fontes. O publish faz novo checkout de main,
   pelo que uma atualização concorrente das fontes pode bloquear legitimamente
   o hash. Não contornar a verificação. O retry atual do git rebase termina
   imediatamente em conflitos devido a set -e; não promete resolver conflitos.

Sem acesso à medição da conta, a nova chamada permanece pendente. Não é uma
aprovação adicional: falta evidência técnica necessária à regra de custo.

## Descoberta híbrida proposta

Python enumera pares e triplos, uma variável por família; IDs canónicos
incluem outcome e baseline. Triplos com duas variáveis da mesma família eram
aceites e incluídos nos 19.305 potenciais: esse total não é o universo estrito
de famílias todas distintas. Manter o contador antigo como legado, e publicar
separadamente o total estrito. Nunca reescrever investigações antigas.

Uma fila offline exclui todos os cruzamentos presentes nos arquivos completos,
não apenas os 20 visíveis no índice. A ordem inicial é determinística e sem
resultados/ROI. Depois, priorizar disponibilidade pré-KO, cobertura, independência,
testabilidade e informação incremental; não otimizar retornos retrospetivos.

Antes de testes: congelar protocolo, unidade jogo, horizonte temporal, critérios
mínimos de amostra e efeito, baseline MARKET_MODEL_OVER25, Brier/log loss,
tratamento de FT em falta, agrupamento por jogo e multiplicidade (família total
de testes, não apenas vencedores). Separação temporal e replicação prospetiva.
Não usar os agregados atuais como se fossem observações individuais testáveis.

Memória proposta: eventos append-only com ID, hashes de dados, versão do método,
estado PROPOSED / PREREGISTERED / TESTED / REJECTED / INCONCLUSIVE /
VALIDATED_HUMAN_REVIEWED. Só revisão humana pode promover; gates V6 continuam
obrigatórios. Painel deve mostrar contagens, razões de bloqueio, testes e consumo.
O planeador offline não simula testes nem avança estados.

## Frequência, ainda desativada

Começar com execução Python manual sem IA; medir custo real de uma chamada.
Após pelo menos três medições atribuíveis em dias distintos, considerar no máximo
uma chamada LLM por semana, apenas com candidatos novos e dados suficientes.
É uma proposta conservadora, não uma frequência já demonstrada sustentável.
Orçamento diário de IA: menor de 500 neurons e 10% do saldo livre, com margem
para consumo paralelo; bloquear se saldo, preço, plano ou medição forem desconhecidos.
Não usar alerts de billing como limite rígido. Nenhum cron foi adicionado.
Nenhum componente de Telegram, H1, FT ou estratégias ativas é alterado.
