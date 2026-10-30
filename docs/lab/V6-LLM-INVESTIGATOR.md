# V6.3 #16 — Investigador LLM (protótipo em sombra, desativado por defeito)

Estado: IMPLEMENTAÇÃO EXPERIMENTAL PARA REVISÃO. Não ativado em produção. Referências: issues #63 (V6) e #107 (fiabilidade). A execução científica V6.3 permanece dependente dos gates de 7/14 dias, cronologia independente, pelo menos 1000 FT prospetivos elegíveis da hipótese em 3 semanas e autorização sobre #15. Este módulo não satisfaz esses requisitos.

## Âmbito técnico

- Fontes somente leitura: quatro relatórios agregados existentes em docs/lab/: v6-p0-gates.json, v6-falsification.json, v6-readiness.json e v6-weekly-drift.json.
- Contratos de schema, integridade sintática, limites de bytes, verificações de consistência e SHA-256 para cada ficheiro. Falhas bloqueiam o dossier; nenhum valor desconhecido é transformado em zero.
- Quatro questões de investigação fixas sem seleção por ROI: Total com 1X2, episódios repetidos de alertas, Total com AH e antecedência.
- O LLM, quando utilizado voluntariamente, só pode devolver propostas com estado DRAFT, hipótese nula, desenho de teste, falsificação, fatores de confusão e referências limitadas aos quatro relatórios. A resposta continua texto não fiável, sujeita a revisão humana. Não há estatística calculada pelo LLM.
- Não há leitura de mensagens Telegram, previsões congeladas, journals de dados brutos, tokens ou dados de apostas. Não escreve ficheiros do repositório.

## Como utilizar sem custos nem rede

No GitHub, após integração autorizada, abrir Actions > V6 - Investigator LLM dossier (manual only) > Run workflow. O job apenas executa os testes do módulo e gera um artefacto privado temporário denominado v6-llm-investigator-dossier com um ficheiro dossier.json. Não há calls a fornecedores de IA. Ao executar manualmente um GitHub Actions, porém, podem consumir-se minutos do plano de GitHub.

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

Não adicionar a chave a issues, logs, ficheiros ou workflows. A utilização de um serviço de IA poderá ter custos; este repositório não configura contas, preços nem credenciais. O timeout é limitado, os pedidos e respostas têm tamanho máximo e o dossier contém apenas quatro relatórios agregados. Um fornecedor pode não suportar response_format=json_object e nesse caso a execução falha, sem fallback silencioso.

## Proteções e aprovação futura

- Sem schedule, push, cron, notificações, dispatch automático, comandos de aposta, edição de dados, alterações ao H1/ROI/FIFO/triplas ou reescrita de known_at.
- Os únicos outputs são stdout e, por pedido do utilizador, um artefacto temporário do workflow manual. Nenhuma resposta é inserida nas memórias/hypotheses/forecasts da V6.
- O dossier não prova vantagem, ROI, significância, calibração ou integridade do FT. Propostas são sempre pós-análise e requerem desenho pré-registado, ensaio prospetivo independente, correção de múltiplos testes e revisão antes de eventual ativação.
- Testes usam dados sintéticos e HTTP simulado. CI verde só prova isolamento técnico, não valida o LLM.
