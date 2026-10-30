# MASTER BRAIN V6 — Autonomia controlada do Investigador LLM (fase experimental)

## Objetivo e alcance
Execução automática e limitada de novas hipóteses de cruzamento de variáveis do catálogo V5. Esta funcionalidade está isolada das estratégias H1/FT, Telegram, apostas e validação científica. A IA **não aprende nem valida estatisticamente** a partir de um prompt; apresenta uma hipótese DRAFT para testar em jogos futuros.

## Funcionamento
- Planeador Python offline calcula até 100 candidatos ainda não presentes em **todos** os arquivos. Dá preferência a dois códigos de famílias diferentes para maximizar a possibilidade de amostras suficientes e mantém um candidato de três famílias para explorar interações. Não usa resultados, ROI ou acertos para ordenar.
- A LLM recebe até três combinações inéditas, escolhe **uma** e tem liberdade para investigar mecanismo, argumentos contrários, enviesamentos, limitações, controlo, hipóteses alternativas e testes de falsificação. Só pode escolher combinações presentes nessa shortlist — impede regressar a hipóteses repetidas. O catálogo completo mantém 49 variáveis e 14.190 combinações teóricas, exploradas progressivamente.
- Outcome formal atual: `OVER_2_5`, baseline `MARKET_MODEL_OVER25` e métrica Brier/Log Loss. Outros mercados exigem fontes e baseline demonstravelmente suportados; não são falsamente propostos como validados.
- Executa um pedido HTTPS único ao modelo Cloudflare `@cf/meta/llama-3.1-8b-instruct-fast`. Em caso de resposta inválida, erro HTTP ou falta de secrets, **falha sem retry** e não publica falsas descobertas.
- Após sucesso, job separado, sem chave da IA, revalida o resultado e publica `docs/lab/llm-investigator-index.json`, `docs/lab/llm-discovery-plan.json` e arquivo imutável por run no mesmo commit. As propostas aparecem no painel visual; falhas ficam no GitHub Actions.

## Cadência e consumo
Workflow: `.github/workflows/v6-llm-autonomous.yml`.
- Cron UTC: **01:43, 07:43, 13:43, 19:43**, com até **4 pedidos automáticos por dia** e um por execução. O agendador GitHub é de melhor esforço; não garante horários nem execuções.
- Reexecuções do job de schedule (run_attempt maior que 1) são bloqueadas antes da IA. Modo manual de **pré-visualização não consome neurons**; um pedido manual pelo workflow autónomo requer `AUTONOMIA_LLM_UMA_VEZ`.
- O histórico arquivado aplica uma segunda proteção no limite diário de publicações automáticas, mas **não regista todas as chamadas falhadas**. São as quatro oportunidades de cron fixas, sem retries, que impõem o principal limite de chamadas automáticas.
- As capturas reais de 30/10/2026 mostram aproximadamente 25,14 neurons de variação no gráfico do modelo após uma chamada; **não é medição isolada**. Tokens e neurons são métricas distintas. O saldo da conta não é lido via API; `account_neurons_verified=false` e `neurons_consumed=null` permanecem explícitos. Não é possível garantir um orçamento rigoroso em neurons enquanto a API de consumo não estiver ligada.
- A Cloudflare indica uma franquia gratuita de 10.000 neurons/dia; no Workers Paid poderá haver cobranças pelo excedente. Monitorizar periodicamente no dashboard Cloudflare e confirmar plano de conta. Em caso de dúvidas de faturação, **desativar o workflow autónomo imediatamente**.

## Verificação e progressão científica
1. Testes e dry-run offline em PR. Não invocar Workers AI para passar testes.
2. Primeira execução agendada com dois jobs SUCCESS, arquivo novo e fila decrementada apenas uma vez.
3. Medir neurons da conta por janelas de tempo comparáveis e monitorizar a taxa de falhas da resposta, sem assumir um valor por pedido.
4. Para resultados concretos, criar uma camada **separada e independente** de teste offline: disponibilidade de variáveis por partida, conhecimento pré-jogo, FT verificado, baseline calculado, seleção múltipla e split temporal. Não declarar uma descoberta estatística enquanto estes critérios não forem cumpridos.
5. Manter os gates da issue #63 `INCONCLUSIVO` até prova real. O modelo não promove estratégias nem recomenda apostas.

## Reverter / desligar
GitHub > Actions > `V6 - LLM Autonomous Research (bounded)` > menu de workflow > Disable workflow. Desativar não toca no Investigador manual nem apaga arquivos. A alteração pode também ser revertida em PR para remover o `on.schedule`.

## Observabilidade
Abrir https://nunovinhas-creator.github.io/asianodds-h1-lab/llm-investigator.html. O painel exibe a proposta mais recente, proveniência, histórico e fila. O texto **última proposta** não significa que uma execução esteja a decorrer; para inspecionar falhas e runs pendentes abrir GitHub Actions.
