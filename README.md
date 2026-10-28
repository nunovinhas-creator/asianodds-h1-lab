# MASTER BRAIN — AsianOdds H1 + Observatório V4 + Cérebro V5

**MASTER BRAIN** é o novo nome e a interface principal da ferramenta (anteriormente UNDER TESTE). O **cérebro V5**, as hipóteses de investigação e o observatório de jogos futuros são agora os painéis principais. **Under H1 e triplas passam para arquivo secundário** em [h1.html](https://nunovinhas-creator.github.io/asianodds-h1-lab/h1.html#h1), mantendo os motores e os resultados originais.

Observatório experimental de odds asiáticas: recolhe alertas estruturados de um canal Telegram autorizado, regista movimentos de mercado, forma sinais e triplas H1 simuladas e investiga combinações de padrões com resultados finais. **Não executa apostas reais, não garante rentabilidade e não ativa automaticamente estratégias descobertas pelo LAB.**

**Acesso rápido:** [MASTER BRAIN · Radar](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html) · [Jogos futuros](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html#futuros) · [Padrões](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html#padroes) · [Validação](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html#validacao) · [Under H1 secundário](https://nunovinhas-creator.github.io/asianodds-h1-lab/h1.html#h1).

**Referências técnicas:** [Centro de controlo](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html) · [Sinais H1](https://nunovinhas-creator.github.io/asianodds-h1-lab/h1.html#h1) · [Cérebro V5 / investigação](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-research.html) · [Resultados de todos os jogos](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-results.html) · [Auditoria V4](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-v4-audit.html).

## Cronologia de descobertas — Fase 2

O **Radar** inclui agora uma cronologia de mudanças do V5: resultados FT acrescentados, diferenças entre taxas, inversões de efeito, alterações de estados, evolução por padrão com datas UTC reais e resultados dos jogos detetados prospetivamente. A primeira execução estabelece uma **baseline** sem reconstruir falsos acontecimentos passados.

- Fonte pública: [cronologia de descobertas](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab/discoveries.json).
- Motor incremental: `h1lab/discovery_timeline.py` e `scripts/lab_discoveries.py`.
- Arquivos imutáveis por mês: `data/lab/discovery-events-YYYY-MM.jsonl`; o frontend mantém apenas a janela recente.
- O histórico de primeiras deteções é **pré-kickoff** e os desfechos são associados apenas após FT confirmado. Os jogos sem FT não contam como derrotas.
- A amostra de descoberta nunca é confundida com a amostra posterior **fora da amostra (OOS)**. Nenhuma taxa ou tendência é apresentada como rentabilidade garantida.
- O motor acompanha os padrões individuais, cruzamentos publicados e hipóteses congeladas; não afirma acompanhar todos os 800 testes internos. Ver [documentação completa](docs/lab/DISCOVERY-TIMELINE.md).

A atualização reutiliza `lab-ft-results.yml`, sem novos pedidos API, cron ou alterações ao H1/Telegram.

## O cérebro que cruza odds, mercados e resultados (V5)

**Observatório de jogos futuros e alertas Telegram:** [padrão de múltiplos alertas, subidas e estabilidade dos golos implícitos](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-pattern-watch.html). Distingue episódios independentes de mensagens repetidas, com dados Total válidos; **não altera as hipóteses estatísticas V5 nem produz apostas**.

**O cérebro já existe e está operacional em modo LAB exploratório**: [guia acessível do cérebro V5](docs/lab/CEREBRO-ODDS.md), [especificação e validação](docs/lab/PATTERN-ENGINE.md), [código principal](h1lab/pattern_engine.py), [investigação visual](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-research.html) e [relatório estruturado](docs/lab/pattern-research.json).

| Motor | O que faz | Cria apostas? |
| --- | --- | --- |
| **H1 — produção** | Primeiro H1 de cada jogo: linha Total sobe pelo menos 0,25 **e** odd Over sobe; seleção Under e triplas cronológicas FIFO, com ROI simulado quando há FT. | Regista **apostas simuladas já definidas pela regra fixa**, não apostas reais. |
| **V4 — observação** | Extrai e audita alertas Total, **1X2 e handicap asiático (AH)**, horários, snapshots e sequências. | Não. Parser e Golden Set não certificados. |
| **V5 — cérebro** | Cruza padrões dos três mercados, preços, tempo até ao jogo, repetições e direções opostas; cria hipóteses A, A e B, A sem B, A antes de B e trios; confronta-as com resultados verificados. | **Não.** Procura associações estatísticas em Over 2,5 e BTTS, com controlo de falsos positivos e validação fora da amostra. |

O V5 combina **49 padrões pré-definidos**, normaliza Total asiático entre diferentes linhas para uma referência de golos implícitos, compara jogos com e sem cada combinação, cruza os resultados FT e procura jogos semelhantes sem utilizar o desfecho futuro. Não confunde três mensagens do mesmo jogo com três observações independentes. As hipóteses ficam `EXPLORATORIO` até cumprirem os critérios; `VALIDADO` nunca significa automaticamente que existe lucro real.

**Importante:** as **triplas H1** são agrupamentos FIFO de três sinais Under anteriores ao início; **não foram construídas nem otimizadas pelo V5**. O único fluxo do LAB para a liquidação H1 é a **importação de resultados FT verificados** para apostas que já existiam; não importa novos prognósticos.

### Como os módulos se ligam

~~~text
Telegram → collect.yml
          ├─ H1: core.py → data/state.json → sinais Under / triplas FIFO
          │     └─ results.yml (:41 UTC): BSD + TheSportsDB
          │            + lab_promotion.py (FT FINAL LAB verificado)
          │            → data/results.csv → docs/data.json → ROI H1
          └─ V4 sombra: market_v4.py + shadow_formats.py
                → mercados/odds + cronologia + auditoria V4/Golden
                → lab-ft-results.yml (:12 e :42 UTC)
                     ├─ FT de TODOS os jogos observados → ft-ledger.json
                     └─ V5: pattern_features + pattern_engine + similarity
                          → pattern-research.json + pattern-registry.json
~~~

**Fotografia consultada (não tempo real):** em 28/10/2026, 11:46 UTC, o H1 apresentava 84 sinais, 18 liquidados, 27 triplas e uma liquidada (ROI H1 simulado −17,17%). O LAB FT tinha 63 resultados em 267 jogos observados (ficheiro das 11:15 UTC). O cérebro tinha 60 FT elegíveis, 800 hipóteses **EXPLORATORIO**, **zero candidatas congeladas e zero hipóteses validadas** (relatório das 11:16 UTC). Os pipelines publicam em momentos diferentes: estas contagens não são diretamente sincronizadas. Para ver o estado atual consultar os JSON e o dashboard, não esta fotografia.

**Documentação canónica:** [Arquitetura completa](docs/lab/ARCHITECTURE.md) · [Índice de documentação](docs/README.md) · [Cérebro V5 explicado](docs/lab/CEREBRO-ODDS.md).

## Estado atual

- ✅ Parser para Total (Over/Under), snapshots 1X2 e handicap asiático, sem guardar o texto original do canal.
- ✅ Condição H1 fixa: linha Total sobe pelo menos 0,25 **e** odd Over sobe; seleção Under na nova linha e à odd comunicada.
- ✅ Um sinal por jogo, usando o primeiro H1 identificado; os alertas repetidos permanecem no histórico.
- ✅ Triplas FIFO: o terceiro sinal cria um bilhete se todos os jogos ainda começarem no futuro (margem mínima de 10 min), sem substituições.
- ✅ Liquidação asiática: vitória, derrota, meia vitória, meia derrota, devolução.
- ✅ Dashboard estático em `docs/index.html`, com ROI das singles e das triplas, calculado apenas sobre bilhetes já liquidados.
- ✅ Os alertas Telegram são exclusivamente do **padrão prospetivo rigoroso** do MASTER BRAIN: ≥2 episódios independentes de alertas pré-jogo, sem queda de λ ≤ −0,05 e com Total válido em todos os alertas. Cada aviso inclui a **linha de golos Total (Over/Under) do último alerta observado** (por exemplo, `2,75`) e, quando a linha se alterou nesse alerta, o movimento observado (por exemplo, `2,5 → 2,75`). Nunca deduz linhas de intervalos sem observação. O bot envia no máximo um aviso por jogo, como **observação exploratória, não aposta**. Motor `h1lab/pattern_notify.py`.
- ✅ Recolha real com Telethon de cinco em cinco minutos, disparada pelo Cloudflare Workers Cron (ver secção seguinte). O GitHub pode atrasar/omitir os seus próprios ticks.
- ℹ️ **Under H1 e triplas FIFO continuam a ser calculados, publicados e liquidados**, mas **já não produzem alertas Telegram**. Os avisos do cérebro são enviados pelo Bot API para `TG_CHAT_ID`; `data/pattern-notifications.json` guarda os recibos. Na primeira execução, os jogos já identificados formam a baseline e não são reenviados.
- ✅ Reconciliação horária H1 por BSD Football v2 e TheSportsDB, seguida de **importação estrita de FT FINAL do LAB** via `h1lab/lab_promotion.py`. A publicação preserva os resultados H1 existentes e atualiza o ROI. O LAB procura FT para **todos os jogos observados**, usando vários fornecedores com limites de pedidos; sem correspondência segura, os jogos continuam pendentes.

## Agendamento de 5 minutos — estado verificado (27/10/2026)

- O **Cloudflare Workers Cron** ([`scheduler/`](scheduler/README.md)) está ativo: entre 14:36 e 20:31 UTC de 27/10, 48 commits de recolha registam `collector.trigger_source = cloudflare-cron` em `data/state.json`, com intervalos de cinco minutos. O documento de passagem regista `COLLECT_TRIGGER: cloudflare-cron` no log do run `40578712731`.
- O cron nativo do GitHub (`schedule: 2-57/5 * * * *`) também disparou pelo menos uma vez (`github-schedule` às 18:12 UTC), mas continua sem garantia de regularidade.
- Isto comprova as execuções observadas, não uma garantia de funcionamento 24/7. Evidência e método de verificação em [`docs/lab/ARCHITECTURE.md`](docs/lab/ARCHITECTURE.md#5-agendamento--evidência-verificável-no-histórico-git).
- O token fine-grained do Worker deve continuar limitado a **Actions Read and write** apenas neste repositório.

## Laboratório (modo sombra)

O laboratório **não altera o H1** e não cria apostas. Mapa de componentes, relatórios e riscos: [`docs/lab/ARCHITECTURE.md`](docs/lab/ARCHITECTURE.md).

## Como funciona

`canal AsianOdds → Telethon (conta subscritora) → V4/V5 → episódios independentes → padrão sem queda relevante de λ → Bot Telegram (observação exploratória)`

Em paralelo, `h1lab/results.py` verifica resultados FT na BSD e TheSportsDB, e `h1lab/lab_promotion.py` acrescenta FT finais compatíveis confirmados pelo LAB; ambos alimentam `data/results.csv` e a proveniência em `data/result_audit.json`. O CSV alimenta o dashboard com retorno bruto por aposta de 1 unidade. Múltiplas são o produto dos retornos dos três Under asiáticos, incluindo meias liquidações. A odd combinada é **teórica**: as três cotações podem não estar simultaneamente disponíveis para uma aposta real.

## Ativação — única configuração sensível

1. Em https://my.telegram.org obtém um `api_id` e `api_hash` para a tua própria aplicação Telegram.
2. Na tua máquina/Android com Python (por exemplo Termux), instala dependências com `pip install -r requirements.txt`. Executa `python scripts/authorize.py`. Faz login com o código Telegram e, caso seja pedido, a verificação em dois passos. O script imprime a sessão de cliente e a lista de canais acessíveis. **Não partilhes essa sessão comigo, nem a coloques em ficheiros do repositório público.**
3. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Configura exatamente `TG_API_ID`, `TG_API_HASH`, `TG_SESSION`, `TG_CHANNEL`. O último corresponde ao **nome exato** `AsianOdds Dropping Odds`, ao ID da conversa ou ao @username público, caso exista.
4. Ativa no repositório, em **Settings → Pages**, o deployment a partir de **Deploy from a branch → main → /docs** para disponibilizar o dashboard.
5. O workflow [H1 - Collect Telegram](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/workflows/collect.yml) está programado a intervalos de cinco minutos; os dados ficam em `data/state.json` e `docs/data.json`. O workflow [Atualizar ROI H1](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/workflows/results.yml) consulta o fornecedor de resultados de hora a hora (minuto 41 UTC). Ambos permitem `Run workflow` manual. O cron do GitHub **não é garantido**; o disparo regular vem do Cloudflare Workers Cron.

**Segurança:** a variável `TG_SESSION` confere acesso à tua conta pelo cliente Telegram. Nunca a guardes no histórico de commits, logs, Issues, PRs nem no dashboard. Se ficar exposta, revoga a sessão nas definições de dispositivos do Telegram e gera outra.

## Dados

- `data/state.json`: histórico estruturado de alertas, sinais e triplas e checkpoint de ID Telegram; os novos recibos de Telegram ficam em `data/pattern-notifications.json`.
- `data/results.csv`: resultados finais confirmados pela BSD, TheSportsDB, pela ponte de FT FINAL do LAB ou por intervenção manual documentada, com URL de origem (nunca estimados).
- `data/result_audit.json`: última pesquisa automática por jogo, estado e motivo da não liquidação; sem credenciais.
- `h1lab/results.py`: reconciliação H1 de FT via BSD / TheSportsDB, com identidade, data/hora, proveniência e regras de período regulamentar.
- `h1lab/lab_promotion.py`: ponte **só de resultados** LAB → H1, sem alterar picks, triplas, resultados previamente liquidados ou regras do motor.
- `data/lab/ft-ledger.json`: todos os jogos observados no LAB (incluindo sem H1), com estados de verificação e evidências.
- `h1lab/pattern_engine.py`: **cérebro V5**; cruza 49 padrões, combinações e FT, com avaliação estatística e fora da amostra; não produz apostas.
- `docs/lab/pattern-research.json`: relatório público da investigação V5; `data/lab/pattern-registry.json` conserva hipóteses congeladas.
- `docs/data.json`: visão pública de sinais, triplas e ROI.
- `h1lab/core.py`: regras e liquidação, completamente testáveis sem Telegram.
- `h1lab/cli.py`: leitor Telegram e atualização do dashboard.
- `h1lab/notify.py`: módulo legado das triplas simuladas, **desativado no workflow de recolha**.
- `h1lab/pattern_notify.py`: único notificador ativo no `collect.yml`, reutiliza `pattern_watch.inspect`, sem depender de novos pedidos API; recibos em `data/pattern-notifications.json`.
- `scripts/authorize.py`: criação interativa da sessão na tua máquina.

### Configurar a BSD

1. Em [BSD — Account](https://sports.bzzoiro.com/), copia a chave de API da tua conta, sem a publicar.
2. No repositório, abre **Settings → Secrets and variables → Actions → New repository secret**.
3. Cria o secret `BSD_API_KEY` com o valor da chave **sem o prefixo `Token`**.
4. Executa **Actions → Atualizar ROI H1 → Run workflow** para confirmar se o fornecedor responde. Em `data/result_audit.json` verás `bsd_no_exact_match`, `confirmed_bsd_only`, `confirmed_bsd_and_thesportsdb` ou outros motivos técnicos, sempre sem a chave.

A BSD usa `Authorization: Token …` e `GET /api/v2/events/` (filtro por nome da equipa, data e `status=finished`). Depois verifica `GET /api/v2/events/{id}/`, equipas, hora e marcador do período regulamentar. Só admite uma correspondência inequívoca, sem sinais de prolongamento ou penáltis; discrepâncias entre BSD e TheSportsDB **não são liquidadas automaticamente**. A pesquisa é iniciada a partir de três horas após o início, com tentativas espaçadas quatro horas e durante trinta dias. Documentação oficial: https://sports.bzzoiro.com/docs/football/events/

### Resultados finais

A reconciliação direta H1 pode ser automática e gratuita quando a TheSportsDB devolve um jogo identificável; a BSD depende de chave configurada e existe uma ponte adicional de resultados FINAL do LAB. O algoritmo só aceita `strStatus=FT`, equipas correspondentes (ignorando apenas abreviaturas de clube não ambíguas), início temporal compatível, golos inteiros e ausência de marcadores de prolongamento/penáltis. Jogos sem garantia de resultado nos 90 minutos, sem correspondência ou cuja API esteja indisponível **continuam pendentes**. Em taças, a fonte pode ser ambígua sobre prolongamento; nesse caso confirmar manualmente o resultado regulamentar antes de liquidar. Um FT reportado pela fonte não substitui auditoria independente dos mercados especiais.

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
