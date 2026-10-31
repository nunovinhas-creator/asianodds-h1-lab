# MASTER BRAIN — AsianOdds H1 + Observatório V4 + Cérebro V5

**Telegram (31/10/2026): duas regras independentes.** A regra original de [3 ou mais movimentos distintos Total V4](docs/lab/TELEGRAM-THREE-TOTAL-MOVES.md) continua sem alterações; foi **acrescentada** uma [segunda regra de 2 ou mais subidas Total V4 distintas, sem descida explícita e com subida líquida ≥0,50](docs/lab/TELEGRAM-TWO-UP-TOTAL.md). Os jogos futuros são elegíveis sem limite de 12 horas nem máximo de seis mensagens; um aviso por jogo **e por regra**, cada uma com o seu ledger e título próprios. E4, T05, H1 e triplas permanecem silenciados. Nenhum destes padrões foi validado como previsão de golos.

**MASTER BRAIN** é o novo nome e a interface principal da ferramenta (anteriormente UNDER TESTE). O **cérebro V5**, as hipóteses de investigação e o observatório de jogos futuros são agora os painéis principais. **Under H1 e triplas passam para arquivo secundário** em [h1.html](https://nunovinhas-creator.github.io/asianodds-h1-lab/h1.html#h1), mantendo os motores e os resultados originais.

Observatório experimental de odds asiáticas: recolhe alertas estruturados de um canal Telegram autorizado, regista movimentos de mercado, forma sinais e triplas H1 simuladas e investiga combinações de padrões com resultados finais. **Não executa apostas reais, não garante rentabilidade e não ativa automaticamente estratégias descobertas pelo LAB.**

**Investigador LLM V6 experimental:** [painel visual de cruzamentos](https://nunovinhas-creator.github.io/asianodds-h1-lab/llm-investigator.html) · [workflow manual](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/workflows/v6-llm-investigator.yml) · [metodologia e limites](docs/lab/V6-LLM-INVESTIGATOR.md). Apenas chamadas Cloudflare confirmadas manualmente produzem propostas DRAFT; sem cron de IA, alertas automáticos, provas de rentabilidade ou alterações às apostas.


**V10 — descoberta e persistência de IDs BSD:** os jogos sem ID no Monte-Carlos passam a aproveitar listagens BSD completas, verificadas por `count`/`next`, até 3 datas por execução e um intervalo mínimo de 4 horas por dia. A associação inicial exige equipa casa/fora, categoria, orientação, KO ±5 minutos e unicidade; o ID é persistido para futuras consultas diretas por `/api/v2/events/{id}/`, sem pesquisas repetidas por `team_name`. Marcadores só são registados após confirmar o próprio detalhe BSD. [Critérios e métricas](docs/lab/ft-bsd-id-discovery.md).

**BSD / Monte-Carlos — resolução direta por ID:** o LAB tenta primeiro consultar na BSD o `event_id` real já arquivado no Monte-Carlos, com correspondência única de equipa casa/fora e horário UTC, antes das pesquisas por nomes ou datas. Corrige designadores portugueses como «FC do Porto» → «FC Porto»; o exemplo auditado no arquivo é FC do Porto–Académico de Viseu (28/10), cujo ID BSD é `599528`. Nunca aceita a pontuação guardada no SQLite sem voltar a confirmar o próprio evento BSD. Não modifica o H1. [Documentação BSD](https://sports.bzzoiro.com/docs/football/events/).

**V9 — memória persistente de FT por fornecedor:** o LAB passa a conservar provas regulamentares de um fornecedor numa execução e a reutilizá-las quando outro fornecedor confirma o mesmo jogo posteriormente, sempre com ID/KO/equipas fortes, hash e carimbo temporal da primeira observação. Revisões do marcador ativam quarentena, não liquidação; o Radar V6 não certifica automaticamente a cronologia. Não aumenta o número de pedidos. [Critérios e auditoria](docs/lab/ft-v7-reviewed-batch.md).

**V8 — recuperação FT por consenso de duas fontes:** o LAB passa a cruzar candidatos STRONG do mesmo jogo em listas COMPLETAS de API-Football, GOAL e OpenFoot já obtidas. Só declara um resultado se dois fornecedores distintos devolverem FT regulamentar idêntico, com IDs, equipa, KO e competição verificados; conflito ou fonte ausente ficam pendentes. O GOAL por ID deixa de depender do cooldown da lista por data, dentro das quotas; o BSD LAB reutiliza a leitura de envelopes comprovada pelo Monte-Carlos. Não são criadas chamadas extra nem alterados H1 ou Telegram. [Plano e limites da V8](docs/lab/ft-v7-reviewed-batch.md).

**P0 — evidência FT persistente e revalidação BSD dirigida:** respostas de rotação/quotas já não apagam a última pista GOAL útil; cada GET GOAL por ID tem cooldown próprio de 24 horas. Foram adicionados dois `match_key` individualmente revistos com IDs BSD observados em pelo menos duas fontes, sujeitos a nova validação estrita dos 90 minutos, sem aliases gerais nem FT presumidos. [Auditoria técnica e critérios](docs/lab/FT-P0-EVIDENCE-AND-TARGETED-RECOVERY.md).

**P0 — revalidação GOAL por ID:** quando a fila encontra um único ID GOAL de um jogo elegível, confirmado por nomes deterministas e KO rigoroso, pode trocar **uma** das duas consultas por data por um `GET /fixtures/:id`. A resposta é novamente validada quanto ao resultado dos 90 minutos; candidatos ambíguos continuam pendentes. [Documentação e testes](docs/lab/FT-ID-PROBE-P0.md).

**Recuperação FT P0 — cruzamento de IDs e rotação histórica:** os adaptadores GOAL, OpenFoot e API-Football distribuem as datas elegíveis segundo uma rotação persistente e quotas conservadoras, sem aumentar os pedidos máximos por execução. O [painel de recuperação](https://nunovinhas-creator.github.io/asianodds-h1-lab/ft-recovery.html) mostra datas autorizadas e requisitadas; o [registo de IDs confirmados](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab/ft-provider-identity.json) identifica colisões sem liquidar jogos por semelhanças de nomes. [Critérios e limitações](docs/lab/FT-CROSSWALK-ROTATION-P0.md). O registo guarda apenas IDs de URLs de eventos já confirmados; não introduz consultas diretas por ID não verificadas.

**Recuperação FT P0 — fila automática:** [painel de cobertura, prioridade, próxima consulta e motivos de bloqueio](https://nunovinhas-creator.github.io/asianodds-h1-lab/ft-recovery.html) · [especificação e limitações](docs/lab/FT-QUEUE-P0.md). Primeira consulta precede repetições normais, respeitando KO+3h, 30 jogos/ciclo e cooldown progressivo para casos difíceis. As contagens por fornecedor medem invocações de adaptadores, não pedidos HTTP, e só são fiáveis desde a instrumentação. Um resultado inconclusivo nunca é contabilizado como derrota.

**Fila de revisão de identidades FT (experimental):** [painel dedicado](https://nunovinhas-creator.github.io/asianodds-h1-lab/ft-identity-review.html) · [método e limites](docs/lab/FT-IDENTITY-REVIEW.md). Compara, sem novas chamadas, os nomes dos jogos em atraso com os dados já recebidos das APIs. Mantém candidatos anteriores assinalados como não atualizados; não mistura jogos, não adiciona aliases automaticamente e nunca infere FT. Publicação após a primeira reconciliação em produção com esta versão.

**Radar Científico V6.2:** [Abrir painel de hipóteses, previsões congeladas e resultados FT](https://nunovinhas-creator.github.io/asianodds-h1-lab/scientific-radar.html) — rastreabilidade em dois cliques: hipótese formal → jogo → observação original V4, previsão com hash, fonte FT e dez falsificações. Mostra apenas hipóteses formalmente registadas (máximo dez), nunca apresenta V5 exploratório como validado. O relatório público é `docs/lab/v6-scientific-radar.json`, derivado dos diários JSONL, e pode aparecer indisponível até à primeira execução após o merge. **Continua INCONCLUSIVO** e não é um motor de apostas.

**Monitor científico semanal V6.2:** as calibrações, a distribuição de probabilidades, as famílias de formatos Telegram e a qualidade das cotações passam a ter uma fotografia SHA-256 por semana, com limiares predefinidos e estado `INSUFFICIENT_HISTORY` enquanto faltar amostra. O painel do [Radar Científico](https://nunovinhas-creator.github.io/asianodds-h1-lab/scientific-radar.html) mostra os resultados sem alterar H1, Telegram ou gerar novas consultas à API. Relatório `docs/lab/v6-weekly-drift.json`, diário `data/lab/v6-weekly-snapshots.jsonl`.

**Acesso rápido:** [MASTER BRAIN · Radar](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html) · [Jogos futuros](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html#futuros) · [Padrões](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html#padroes) · [Validação](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html#validacao) · [Under H1 secundário](https://nunovinhas-creator.github.io/asianodds-h1-lab/h1.html#h1).

**Referências técnicas:** [Centro de controlo](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html) · [Sinais H1](https://nunovinhas-creator.github.io/asianodds-h1-lab/h1.html#h1) · [Cérebro V5 / investigação](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-research.html) · [Resultados de todos os jogos](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-results.html) · [Auditoria V4](https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-v4-audit.html).

## MASTER BRAIN V6 — controlo de qualidade e validação prospetiva (sombra)

O V6 acrescenta auditoria por snapshot, quarentena de cotações suspeitas e um **diário de previsões registadas antes do início** com hora real `known_at` e cadeia de hashes. Compara o Over 2,5 real com o **baseline implícito pelo mercado** (resíduo), sem treino ML/LLM nem substituição de alertas Telegram. A condição Pattern Watch de 28/10/2026 é **pós-hoc**, permanece separada da sua variante estrita, e tem estado `INCONCLUSIVO` até validação prospetiva suficiente. [Decisões, especificação e limites do V6](docs/lab/MASTER-BRAIN-V6.md). O complemento V6 analisa também **todas as hipóteses exploratórias vs a referência do mercado** (não só o top-40), publicando `docs/lab/v6-residual-research.json` após a execução FT; não confundir exploração retrospetiva com OOS congelado. A auditoria publicou já `docs/lab/v6-shadow.json` e `docs/lab/v6-price-quality.json` após a primeira execução.

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


### V6.2 — P2 n.º 13: hipóteses redundantes

O catálogo original das 800 hipóteses V5 está arquivado em [data/lab/v6-pruning-catalog-v1.json](data/lab/v6-pruning-catalog-v1.json). A primeira execução fixa a matriz observacional, seleciona até 300 representantes por diversidade e publica um mapa original→representante em [docs/lab/v6-pruning.json](docs/lab/v6-pruning.json). A dimensão efetiva é uma estimativa descritiva, não um ajuste de significância. A escolha não lê FT, ganhos, odds de fecho ou resíduos, nem altera H1, Telegram, memórias ou previsões V6. O Radar Científico apresenta-a como investigação exploratória.


### V6.2 — P2 n.º 14: arquivo mensal verificável

Os diários de observações, revisões V4, resultados FT, previsões V6, cinco memórias científicas e descobertas passam a admitir **partes mensais limitadas a 20.000.000 bytes**, sem reescrever os registos nem alterar a cadeia SHA. As projeções atualizáveis `markets`/`formats` são divididas de modo independente. O [índice de arquivos selados](data/lab/v6-archive-index.json) regista SHA-256 integral de cada parte de meses fechados, e o [relatório de saúde](docs/lab/v6-archive-health.json) verifica o histórico e todos os ficheiros LAB. A verificação não exige novas APIs nem workflows. Consulte [MASTER-BRAIN-V6.md](docs/lab/MASTER-BRAIN-V6.md) para recuperação, limites e semântica temporal. Estado científico: INCONCLUSIVO.


### P0 científico V6 — controlo de 7/14 dias, 10 000 nulos e FT cronológico

O [relatório dos gates prospetivos](docs/lab/v6-p0-gates.json) mantém os gates de 7/14 dias bloqueados até cobertura de 99% e revisão independente de logs Git/Telegram. A [simulação científica fixa](docs/lab/v6-p0-null-simulation.json) reproduz a mistura do teste sequencial em 10 000 caminhos nulos e mostra potência sintética por checkpoints, sem se confundir com FT reais ou uma hipótese validada. Implementado em modo LAB sombra; consulte [MASTER-BRAIN-V6.md](docs/lab/MASTER-BRAIN-V6.md). 


### LAB FT: recuperação de resultados e auditoria dos atrasados (V12)

A [fila FT verificável](docs/lab/ft-backlog.json) distingue finais confirmados, jogos futuros, intervalo de 3 horas após o KO, casos em revisão e **jogos efetivamente atrasados**. Por data UTC expõe pendentes nunca consultados e, separadamente, fornecedores **ausentes da última tentativa** (isto NÃO é uma prova de que nunca tenham sido usados). A [documentação de recuperação](docs/lab/FT-BACKLOG-RECOVERY-V12.md) explica a execução limitada de um único merge, a utilização das chaves API-Football/GOAL/OpenFoot, quotas e a necessidade de confirmar disparos reais do cron no GitHub. Nenhum marcador é inventado; H1 e FIFO ficam intactos.
