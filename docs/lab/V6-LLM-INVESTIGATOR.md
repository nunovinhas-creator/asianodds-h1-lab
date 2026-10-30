# V6.3 #16 — Investigador LLM (protótipo em sombra, desativado por defeito)

Estado: IMPLEMENTAÇÃO EXPERIMENTAL PARA REVISÃO. Não ativado em produção. Referências: issues #63 (V6) e #107 (fiabilidade). A execução científica V6.3 permanece dependente dos gates de 7/14 dias, cronologia independente, pelo menos 1000 FT prospetivos elegíveis da hipótese em 3 semanas e autorização sobre #15. Este módulo não satisfaz esses requisitos.

## Âmbito técnico

- Fontes somente leitura: cinco relatórios existentes em docs/lab/: v6-p0-gates.json, v6-falsification.json, v6-readiness.json, v6-weekly-drift.json e pattern-research.json (deste último, só as 49 definições de variáveis V5, nunca os resultados históricos).
- Contratos de schema, integridade sintática, limites de bytes, verificações de consistência e SHA-256 para cada ficheiro. Falhas bloqueiam o dossier; nenhum valor desconhecido é transformado em zero.
- Quatro questões de investigação fixas sem seleção por ROI: Total com 1X2, episódios repetidos de alertas, Total com AH e antecedência.
- O LLM, quando utilizado voluntariamente, só pode devolver propostas com estado DRAFT, hipótese nula, desenho de teste, falsificação, fatores de confusão e referências limitadas às cinco fontes. A resposta continua texto não fiável, sujeita a revisão humana. Não há estatística calculada pelo LLM.
- Não há leitura de mensagens Telegram, previsões congeladas, journals de dados brutos, tokens ou dados de apostas. Não escreve ficheiros do repositório.

## Como utilizar sem custos nem rede

No GitHub, após integração autorizada, abrir Actions > V6 - Investigator LLM dossier (manual only) > Run workflow. O modo por omissão `dossier` apenas executa os testes e gera um artefacto com `dossier.json`, sem chamadas à IA. Num repositório público, os artefactos e logs podem ser públicos: o dossier contém somente dados agregados e catálogo de variáveis, nunca segredos. Ao executar manualmente um GitHub Actions, porém, podem consumir-se minutos do plano de GitHub.

Na consola, num checkout do repositório:

    python -m scripts.lab_v6_llm_investigator --mode dossier

O comando imprime um JSON limitado no stdout, sem escrever nem fazer chamadas HTTP. Pode copiar-se o dossier para um LLM externo apenas por decisão humana.

Após criar uma resposta JSON com schema_version 1 e propostas conforme o schema presente no dossier:

    python -m scripts.lab_v6_llm_investigator --mode review --response-file /tmp/resposta-llm.json

O revisor confere contrato, comprimento, referências e unicidade. Não verifica a verdade factual das afirmações, nem regista ou promove hipóteses.

## Chamada a LLM opcional

Uma chamada HTTPS direta é suportada apenas por execução manual intencional a um endpoint compatível com Chat Completions. Exemplo genérico (o endereço não é um fornecedor real):

    export MASTER_BRAIN_LLM_API_KEY=CHAVE_PRIVADA
    python -m scripts.lab_v6_llm_investigator --mode invoke --allow-network --endpoint https://fornecedor-escolhido.example/v1/chat/completions --model modelo-escolhido

Não adicionar a chave a issues, logs, ficheiros ou workflows. A utilização de um serviço de IA poderá ter custos; este repositório não configura contas, preços nem credenciais. O timeout é limitado, os pedidos e respostas têm tamanho máximo e o dossier contém apenas indicadores agregados e definições de variáveis. Um fornecedor pode não suportar response_format=json_object e nesse caso a execução falha, sem fallback silencioso.

## Proteções e aprovação futura

- Sem schedule, push, cron, notificações, dispatch automático (apenas workflow_dispatch manual), comandos de aposta, edição de dados, alterações ao H1/ROI/FIFO/triplas ou reescrita de known_at.
- Os únicos outputs são stdout e, por pedido do utilizador, um artefacto temporário do workflow manual. Nenhuma resposta é inserida nas memórias/hypotheses/forecasts da V6.
- O dossier não prova vantagem, ROI, significância, calibração ou integridade do FT. Propostas são sempre pós-análise e requerem desenho pré-registado, ensaio prospetivo independente, correção de múltiplos testes e revisão antes de eventual ativação.
- Testes usam dados sintéticos e HTTP simulado. CI verde só prova isolamento técnico, não valida o LLM.

## Modo Cloudflare Workers AI — primeiro ensaio manual (sem cron)

A PR acrescenta ao workflow manual a opção `cloudflare_once`; não muda qualquer workflow existente nem o agendador Telegram. Depois da integração autorizada na main, no GitHub > Settings > Secrets and variables > Actions adicionar os secrets `CLOUDFLARE_ACCOUNT_ID` (32 caracteres hexadecimais) e `MASTER_BRAIN_LLM_API_KEY` (token exclusivamente Workers AI). Não divulgar o token em issues, screenshots, logs ou chat.

Abrir Actions > V6 - Investigator LLM (manual only) > Run workflow e escolher `dossier` para teste a custo de IA zero. Para chamar o modelo UMA VEZ, selecionar `cloudflare_once` e escrever exatamente `CONSUMIR_IA_UMA_VEZ` no campo de confirmação. A Action executa no máximo um pedido HTTPS, sem retry, com timeout de 30 segundos e `max_tokens=1600`, usa `@cf/meta/llama-3.1-8b-instruct-fast` e grava apenas um relatório de hipóteses DRAFT num artefacto de 7 dias. Com tokens em falta, erro HTTP, resposta não JSON ou proposta inválida, o passo falha sem publicar sugestões falsas.

No plano Cloudflare Workers Free, há 10.000 neurons gratuitos/dia partilhados por conta e o excesso é recusado; o código NÃO consulta a utilização atual nem fixa um orçamento de neurons a priori. Inspecionar a quota antes e depois do primeiro ensaio e não ativar recorrência. Nenhuma hipótese fica cientificamente validada ou afeta alertas e apostas. GitHub Actions pode consumir minutos do plano, mesmo quando a chamada IA é gratuita.
