# AsianOdds H1 Lab

Observatório experimental de odds asiáticas: **recolha de um canal Telegram ao qual a tua conta já tem acesso**, normalização de alertas, identificação de H1, triplas FIFO pré-registadas e ROI simulado. Não executa apostas reais.

## Estado atual

- ✅ Parser para Total (Over/Under), snapshots 1X2 e handicap asiático, sem guardar o texto original do canal.
- ✅ Condição H1 fixa: linha Total sobe pelo menos 0,25 **e** odd Over sobe; seleção Under na nova linha e à odd comunicada.
- ✅ Um sinal por jogo, usando o primeiro H1 identificado; os alertas repetidos permanecem no histórico.
- ✅ Triplas FIFO: o terceiro sinal cria um bilhete se todos os jogos ainda começarem no futuro (margem mínima de 10 min), sem substituições.
- ✅ Liquidação asiática: vitória, derrota, meia vitória, meia derrota, devolução.
- ✅ Dashboard estático em \`docs/index.html\`, com ROI das singles e das triplas, calculado apenas sobre bilhetes já liquidados.
- ✅ Envio das triplas para as **Mensagens Guardadas** da tua própria conta Telegram com \`python -m h1lab.notify\`.
- ⏳ Recolha real e envio automático ainda **não ativados**. Exigem configuração de sessão e um workflow GitHub Actions autorizado.
- ⏳ Resultados finais: o motor usa \`data/results.csv\`; ainda não existe fornecedor automático de resultados fiável para todas estas ligas.

## Como funciona

\`canal AsianOdds → Telethon (conta subscritora) → alertas numéricos → primeiro H1 por jogo → fila cronológica de 3 jogos futuros → Saved Messages\`

Em paralelo, \`data/results.csv\` alimenta o dashboard com retorno bruto por aposta de 1 unidade. Múltiplas são o produto dos retornos dos três Under asiáticos, incluindo meias liquidações. A odd combinada é **teórica**: as três cotações podem não estar simultaneamente disponíveis para uma aposta real.

## Ativação — única configuração sensível

1. Em https://my.telegram.org obtém um \`api_id\` e \`api_hash\` para a tua própria aplicação Telegram.
2. Na tua máquina/Android com Python (por exemplo Termux), instala dependências com \`pip install -r requirements.txt\`. Executa \`python scripts/authorize.py\`. Faz login com o código Telegram e, caso seja pedido, a verificação em dois passos. O script imprime a sessão de cliente e a lista de canais acessíveis. **Não partilhes essa sessão comigo, nem a coloques em ficheiros do repositório público.**
3. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Configura exatamente \`TG_API_ID\`, \`TG_API_HASH\`, \`TG_SESSION\`, \`TG_CHANNEL\`. O último corresponde ao **nome exato** \`AsianOdds Dropping Odds\`, ao ID da conversa ou ao @username público, caso exista.
4. Ativa no repositório, em **Settings → Pages**, o deployment a partir de **Deploy from a branch → main → /docs** para disponibilizar o dashboard.
5. O agendamento de recolha continua pendente de configuração. Para uma execução local: definir essas quatro variáveis de ambiente e executar \`python -m h1lab.cli collect\`; depois \`python -m h1lab.notify\`. Num workflow GitHub Actions, as quatro variáveis devem provir de **repository secrets** e nunca ser escritas em texto no ficheiro. Agendamento mínimo do GitHub Actions: 5 minutos (sem garantia de pontualidade).

**Segurança:** a variável \`TG_SESSION\` confere acesso à tua conta pelo cliente Telegram. Nunca a guardes no histórico de commits, logs, Issues, PRs nem no dashboard. Se ficar exposta, revoga a sessão nas definições de dispositivos do Telegram e gera outra.

## Dados

- \`data/state.json\`: histórico estruturado de alertas, sinais e triplas, com checkpoint de ID Telegram e recibos de notificações.
- \`data/results.csv\`: resultados finais verificados (não estimados).
- \`docs/data.json\`: visão pública de sinais, triplas e ROI.
- \`h1lab/core.py\`: regras e liquidação, completamente testáveis sem Telegram.
- \`h1lab/cli.py\`: leitor Telegram e atualização do dashboard.
- \`h1lab/notify.py\`: mensagens com as triplas simuladas.
- \`scripts/authorize.py\`: criação interativa da sessão na tua máquina.

### Resultados finais

No CSV, escreve \`match_key,status,home_goals,away_goals,source\`, com \`status=final\` apenas após confirmação de resultado **90 minutos + compensação, sem prolongamento/penáltis para os mercados normais de 90 min**. Se a chave contiver vírgulas, coloca-a entre aspas CSV. A chave \`match_key\` é mostrada no JSON de sinais e normalmente corresponde ao parâmetro de jogo AsianOdds.

Exemplo sintético (não um jogo real):
\`\`\`csv
match_key,status,home_goals,away_goals,source
"2026-10-28,123,456",final,1,1,https://example.org/match/123
\`\`\`
Após editar o CSV, executar \`python -m h1lab.cli render\`. Sem resultado \`final\`, nenhuma aposta é classificada GREEN ou RED. Jogos anulados/adiados ficam pendentes até haver regra explícita de liquidação.

## Limitações e metodologia

- O H1 pode ser um ajuste normal da linha e **não é uma vantagem estatística demonstrada**.
- O histórico de alertas importado retrospetivamente **não deve gerar tickets de apostas prospetivas**.
- As múltiplas partilham jogos com as singles: são estratégias correlacionadas, não amostras independentes.
- Uma sessão Telegram automatizada pode sofrer limitações, revogação ou flood-waits. Respeita as regras do Telegram e os termos de utilização/direitos de conteúdo do canal e da AsianOdds. Evita republicar mensagens integrais.
- Repositórios públicos não devem guardar quaisquer dados privados pessoais ou credenciais.
- O GitHub Actions pode atrasar ou falhar execuções agendadas. **Não garante alerta imediato.**
- O ROI não é uma promessa de lucro e não inclui custos de slippage, limitação de contas ou disponibilidade efetiva das cotações.

### Testes

\`\`\`bash
python -m unittest discover -s tests -v
python -m h1lab.cli render
\`\`\`
