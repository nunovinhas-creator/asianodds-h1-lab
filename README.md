# AsianOdds H1 Lab

Observatório experimental de odds asiáticas: **recolha de um canal Telegram ao qual a tua conta já tem acesso**, normalização de alertas, identificação de H1, triplas FIFO pré-registadas e ROI simulado. Não executa apostas reais.

## Estado atual

- ✅ Parser para Total (Over/Under), snapshots 1X2 e handicap asiático, sem guardar o texto original do canal.
- ✅ Condição H1 fixa: linha Total sobe pelo menos 0,25 **e** odd Over sobe; seleção Under na nova linha e à odd comunicada.
- ✅ Um sinal por jogo, usando o primeiro H1 identificado; os alertas repetidos permanecem no histórico.
- ✅ Triplas FIFO: o terceiro sinal cria um bilhete se todos os jogos ainda começarem no futuro (margem mínima de 10 min), sem substituições.
- ✅ Liquidação asiática: vitória, derrota, meia vitória, meia derrota, devolução.
- ✅ Dashboard estático em `docs/index.html`, com ROI das singles e das triplas, calculado apenas sobre bilhetes já liquidados.
- ✅ Envio das triplas para as **Mensagens Guardadas** da tua própria conta Telegram com `python -m h1lab.notify`.
- ✅ Recolha real com Telethon e workflow de cinco em cinco minutos publicado; execução manual em produção e extração de H1 confirmadas. A **regularidade das execuções cron** ainda precisa de validação independente e o GitHub pode atrasar/omitir ticks.
- ⚠️ Envio de triplas configurado para *Mensagens Guardadas* via Telegram; ainda sem primeira entrega real comprovada. Mensagens Guardadas não garantem notificação push.
- ✅ Reconciliação automática horária de resultados com a **BSD Football v2**, caso `BSD_API_KEY` esteja configurado, em conjunto com a API V1 gratuita TheSportsDB. Confere ambas as fontes e bloqueia discrepâncias de marcador; sem chave BSD funciona apenas a TheSportsDB. Cobertura parcial: jogos sem identificação inequívoca permanecem pendentes, com motivo em `data/result_audit.json`.

## Como funciona

`canal AsianOdds → Telethon (conta subscritora) → alertas numéricos → primeiro H1 por jogo → fila cronológica de 3 jogos futuros → Saved Messages`

Em paralelo, `h1lab/results.py` tenta verificar resultados oficiais de FT na TheSportsDB, guarda os confirmados em `data/results.csv` e o estado dos pendentes em `data/result_audit.json`. O CSV alimenta o dashboard com retorno bruto por aposta de 1 unidade. Múltiplas são o produto dos retornos dos três Under asiáticos, incluindo meias liquidações. A odd combinada é **teórica**: as três cotações podem não estar simultaneamente disponíveis para uma aposta real.

## Ativação — única configuração sensível

1. Em https://my.telegram.org obtém um `api_id` e `api_hash` para a tua própria aplicação Telegram.
2. Na tua máquina/Android com Python (por exemplo Termux), instala dependências com `pip install -r requirements.txt`. Executa `python scripts/authorize.py`. Faz login com o código Telegram e, caso seja pedido, a verificação em dois passos. O script imprime a sessão de cliente e a lista de canais acessíveis. **Não partilhes essa sessão comigo, nem a coloques em ficheiros do repositório público.**
3. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Configura exatamente `TG_API_ID`, `TG_API_HASH`, `TG_SESSION`, `TG_CHANNEL`. O último corresponde ao **nome exato** `AsianOdds Dropping Odds`, ao ID da conversa ou ao @username público, caso exista.
4. Ativa no repositório, em **Settings → Pages**, o deployment a partir de **Deploy from a branch → main → /docs** para disponibilizar o dashboard.
5. O workflow [H1 - Collect Telegram](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/workflows/collect.yml) está programado a intervalos de cinco minutos; os dados ficam em `data/state.json` e `docs/data.json`. O workflow [Atualizar ROI H1](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/workflows/results.yml) consulta o fornecedor de resultados de hora a hora (minuto 41 UTC). Ambos permitem `Run workflow` manual. O cron do GitHub **não é garantido**; não considerar a automação como 24/7 sem observar execuções com `event=schedule`.

**Segurança:** a variável `TG_SESSION` confere acesso à tua conta pelo cliente Telegram. Nunca a guardes no histórico de commits, logs, Issues, PRs nem no dashboard. Se ficar exposta, revoga a sessão nas definições de dispositivos do Telegram e gera outra.

## Dados

- `data/state.json`: histórico estruturado de alertas, sinais e triplas, com checkpoint de ID Telegram e recibos de notificações.
- `data/results.csv`: resultados finais fornecidos pela TheSportsDB ou introduzidos manualmente, com URL da fonte (não estimados).
- `data/result_audit.json`: última pesquisa automática por jogo, estado e motivo da não liquidação; sem credenciais.
- `h1lab/results.py`: reconciliação de FT por nome exato e data/hora, com consulta gratuita e sem chave pessoal.
- `docs/data.json`: visão pública de sinais, triplas e ROI.
- `h1lab/core.py`: regras e liquidação, completamente testáveis sem Telegram.
- `h1lab/cli.py`: leitor Telegram e atualização do dashboard.
- `h1lab/notify.py`: mensagens com as triplas simuladas.
- `scripts/authorize.py`: criação interativa da sessão na tua máquina.

### Configurar a BSD

1. Em [BSD — Account](https://sports.bzzoiro.com/), copia a chave de API da tua conta, sem a publicar.
2. No repositório, abre **Settings → Secrets and variables → Actions → New repository secret**.
3. Cria o secret `BSD_API_KEY` com o valor da chave **sem o prefixo `Token`**.
4. Executa **Actions → Atualizar ROI H1 → Run workflow** para confirmar se o fornecedor responde. Em `data/result_audit.json` verás `bsd_no_exact_match`, `confirmed_bsd_only`, `confirmed_bsd_and_thesportsdb` ou outros motivos técnicos, sempre sem a chave.

A BSD usa `Authorization: Token …` e `GET /api/v2/events/` (filtro por nome da equipa, data e `status=finished`). Depois verifica `GET /api/v2/events/{id}/`, equipas, hora e marcador do período regulamentar. Só admite uma correspondência inequívoca, sem sinais de prolongamento ou penáltis; discrepâncias entre BSD e TheSportsDB **não são liquidadas automaticamente**. A pesquisa é iniciada a partir de três horas após o início, com tentativas espaçadas quatro horas e durante trinta dias. Documentação oficial: https://sports.bzzoiro.com/docs/football/events/

### Resultados finais

A reconciliação é automática e gratuita quando a TheSportsDB devolve um jogo identificável. O algoritmo só aceita `strStatus=FT`, equipas correspondentes (ignorando apenas abreviaturas de clube não ambíguas), início temporal compatível, golos inteiros e ausência de marcadores de prolongamento/penáltis. Jogos sem garantia de resultado nos 90 minutos, sem correspondência ou cuja API esteja indisponível **continuam pendentes**. Em taças, a fonte pode ser ambígua sobre prolongamento; nesse caso confirmar manualmente o resultado regulamentar antes de liquidar. Um FT reportado pela fonte não substitui auditoria independente dos mercados especiais.

A API V1 gratuita da TheSportsDB usa a chave pública `123`; as pesquisas gratuitas podem devolver apenas um jogo e não cobrem todas as competições. Consulta: https://www.thesportsdb.com/documentation. As pesquisas são limitadas a 20 jogos por execução, repetidas no mínimo de quatro em quatro horas e apenas nos 30 dias seguintes ao pontapé de saída. O histórico anterior a esse período exige verificação manual.


No CSV, escreve `match_key,status,home_goals,away_goals,source`, com `status=final` apenas após confirmação de resultado **90 minutos + compensação, sem prolongamento/penáltis para os mercados normais de 90 min**. Se a chave contiver vírgulas, coloca-a entre aspas CSV. A chave `match_key` é mostrada no JSON de sinais e normalmente corresponde ao parâmetro de jogo AsianOdds.

Exemplo sintético (não um jogo real):
```csv
match_key,status,home_goals,away_goals,source
"2026-10-28,123,456",final,1,1,https://example.org/match/123
```
Após editar o CSV, executar `python -m h1lab.cli render`. Sem resultado `final`, nenhuma aposta é classificada GREEN ou RED. Jogos anulados/adiados ficam pendentes até haver regra explícita de liquidação.

## Limitações e metodologia

- O H1 pode ser um ajuste normal da linha e **não é uma vantagem estatística demonstrada**.
- O histórico de alertas importado retrospetivamente **não deve gerar tickets de apostas prospetivas**.
- As múltiplas partilham jogos com as singles: são estratégias correlacionadas, não amostras independentes.
- Uma sessão Telegram automatizada pode sofrer limitações, revogação ou flood-waits. Respeita as regras do Telegram e os termos de utilização/direitos de conteúdo do canal e da AsianOdds. Evita republicar mensagens integrais.
- Repositórios públicos não devem guardar quaisquer dados privados pessoais ou credenciais.
- O GitHub Actions pode atrasar ou falhar execuções agendadas. **Não garante alerta imediato.**
- O ROI não é uma promessa de lucro e não inclui custos de slippage, limitação de contas ou disponibilidade efetiva das cotações.

### Testes

```bash
python -m unittest discover -s tests -v
python -m h1lab.cli render
```
