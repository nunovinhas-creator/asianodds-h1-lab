# MASTER BRAIN V6 — P0 auditado em sombra (28/10/2026)

**Estado:** observacional, sem promoção de apostas, sem alteração dos alertas.

## Origem e cautelas

Na auditoria ao commit 8d3db99, o Claude encontrou 409/409 mensagens, 102/325 mudanças de linha Total com pelo menos um preço Was=Now inalterado, 29 margens negativas, 64 FT e 1338 testes V5 sem nenhuma hipótese aprovada por FDR. São números da fotografia da auditoria, não métricas fixas.

O Pattern Watch resulta da condição histórica **G_MULTI_ALERT AND NOT M_IMPLIED_GOALS_DOWN**. Na fotografia de 28/10/2026 às 11:16 UTC tinha 11 FT, 10 Over, p nominal 0,016 e q=1. Foi escolhida **pós-hoc**. Esses 11 jogos não são evidência fora da amostra. A condição estrita do monitor atual (episódios independentes, todos os Totals válidos) **não equivale** à condição histórica. Ambas são registadas nas novas observações; os alertas existentes não são modificados.

## P0 implementado

**1. Price quality por evento:** h1lab/v6_shadow.py calcula, para cada Total explícito, as margens Before/After, se alguma odd repetiu durante mudança de linha, margens negativas, preços inválidos e margens elevadas (>12%, limite heurístico na política Q2; registos antigos Q1 não são reescritos). Os casos suspeitos são **assinalados, não apagados**. Uma cotação After duvidosa não produz baseline V6. docs/lab/v6-price-quality.json enumera os resultados de QA por evento, incluindo os históricos, sem os transformar em previsões.

**2. Pergunta certa:** na avaliação, resíduo por jogo = resultado Over 2,5 real (0/1) menos probabilidade-modelo de Over 2,5 estimada do Total asiático. O relatório separa o grupo com padrão histórico e os restantes jogos prospetivos congelados. A probabilidade vem de uma inversão Poisson, **não** de uma odd Over 2,5 efetivamente transacionável. Não há EV nem ROI.

**3. Diário imutável:** data/lab/v6-forecasts-AAAA-MM.jsonl é append-only e cada linha inclui event_id, observed_at, known_at, kickoff_utc, quality, baseline, sha256 e previous_sha256. known_at é o processamento real do workflow; nunca retrocedido à mensagem Telegram. Apenas jogos ainda futuros podem originar registos. Só **um jogo**, com o último snapshot congelado, entra uma vez na avaliação: várias mensagens nunca são ensaios independentes. O histórico Git ancora a cadeia contra truncamentos.

**4. Estatística sequencial:** para a única hipótese predefinida, um e-process de mistura fixa testa o excesso do Over 2,5 relativamente ao baseline do mercado (alternativas +5/+10/+20 pontos percentuais), com alfa 0,005. Os checkpoints não produzem rejeições terminais por baixa potência. O estado é **INCONCLUSIVO** até pelo menos 1000 FT prospetivos elegíveis da própria hipótese, e-value ≥200 e excesso médio ≥5 pp. A interpretação inferencial depende da calibração condicional do baseline e não transforma o monitor num modelo de apostas.

**5. Sem ML/LLM:** antes de 1000 FT independentes fora da amostra, não se treina nem introduz aprendizagem automática na recolha. Não existe alteração ao V5 histórico, H1, liquidação FIFO ou Telegram.

## Execução e integridade

A Action de auditoria LAB, .github/workflows/lab-v4-audit.yml, é disparada no fim de cada recolha H1. O novo passo V6 é executado após atualizar a main no checkout e antes das análises FT, com continue-on-error para preservar os mecanismos existentes. Publica:

- data/lab/v6-forecasts-AAAA-MM.jsonl — capturas novas, prospetivas e encadeadas por hash;
- docs/lab/v6-price-quality.json — auditoria de preços por evento, incluindo histórico, **não** previsões;
- docs/lab/v6-shadow.json — comparação com o mercado, cobertura e estado sequencial.

O registo começa apenas quando o workflow executar após a integração. Não são inventadas capturas passadas. Execuções sem novos snapshots futuros não acrescentam linhas.

## Validação obrigatória

Executar testes unitários de V6, testes de regressão integrais, compileall e a Action real após merge; inspecionar known_at anterior ao kickoff, idempotência, falhas sinalizadas e ausência de modificações em ficheiros H1/Telegram. Se houver erro, desligar apenas o passo V6, **sem eliminar** os diários já recolhidos.

**Limitações:** mercado selecionado por alertas, amostra reduzida, dados de Total não contínuos, qualidade dos snapshots incerta, modelação Poisson, FT incompletos e ausência de prova de rentabilidade.

## Complemento V6.0 — perguntas corrigidas em todas as hipóteses

O motor complementar `h1lab/v6_residual.py` percorre **todas** as hipóteses geradas pelo V5, não apenas as 40 apresentadas no Radar, e mede por jogo `Over_2_5_observado - p_mercado` com **último snapshot Total pré-início e preço classificado**. A análise de preços anteriores é retrospetiva e **NUNCA conta como previsão OOS**. A amostra limpa, exclusões, desvio face ao mercado e intervalo exploratório por bootstrap de dias são publicados em `docs/lab/v6-residual-research.json` após `lab-ft-results.yml`. Sem pelo menos três jornadas não se apresenta intervalo; sem três semanas distintas marca-se diversidade temporal insuficiente. BTTS fica sem baseline de mercado, claramente identificado.

Os antigos rankings e critérios V5 mantêm-se para não alterar silenciosamente significado histórico ou invalidar as séries passadas. **Não** constituem evidência confirmatória V6 e não podem promover apostas automaticamente.

A hipótese Pattern Watch da auditoria fica formalmente documentada no registo imutável `data/lab/v6-hypotheses.jsonl`, com hash, instante histórico *de seleção* atribuído pela auditoria (11:16 UTC), instante *real de registo* e proveniência `POST_HOC`. O registo novo nunca é falsamente retrodatado.

A verificação da versão das hipóteses antigas foi corrigida em `pattern_engine.load_registry`: cada definição é validada com a sua própria `feature_version`. Não se alterou o catálogo atual.

### Estado dos P1–P3 do plano original Claude

Este complemento **não** significa que as cinco memórias completas, o motor de falsificação com 10 testes, FEATURE_VERSION 2, journal de revisões V4/FT, Radar completo, drift semanal e ML/LLM tenham sido implementados. Esses componentes exigem branches, gates e provas de regressão separados; P3 exige ≥1000 FT OOS. Um conjunto de resultados historicamente calculado nunca substitui validação futura.

## V6.0 — controlo de cobertura prospetiva (7/14 dias)

O relatório derivado `docs/lab/v6-readiness.json` compara, nos jogos **cujo início já passou**, quantos tinham pelo menos uma mensagem do canal observada antes do início e quantos possuem `known_at` real anterior ao início no diário congelado. Publica também as causas de ausência de Total/preço utilizável e os IDs dos jogos potencialmente perdidos.

**Atenção:** o `observed_at` da mensagem não prova que tenha sido lida pelo coletor antes do início. A cobertura calculada é uma estimativa sobre **oportunidades observáveis no canal**; o estado `SOURCE_COVERAGE_PASS_PENDING_EXTERNAL_VERIFICATION` **não** certifica ingestão em tempo real. Não se passa para V6.1 sem examinar Git, logs das Actions e preservar continuidade das previsões.

- Gate P0: pelo menos 7 dias desde o primeiro `known_at`, amostra não vazia e ≥99% de cobertura sobre oportunidades observáveis.
- Gate reforçado V6.1: pelo menos 14 dias sob a mesma medição.
- Até decorrer o período exigido o estado é `WARMUP`; evidência estatística/probabilística continua `INCONCLUSIVO`.

## V6.1 P1 #6 — cinco memórias científicas (preparação em sombra)

A implementação `h1lab/v6_science_memory.py` e `scripts/lab_v6_memory.py` acrescenta cinco **diários append-only independentes**, com SHA-256 por evento, cadeia de hashes por fluxo, IDs determinísticos e validação no replay:

| Fluxo | Conteúdo | Fonte |
|---|---|---|
| observations | referências verificáveis a capturas congeladas com `known_at` verdadeiro | `v6-forecasts-*.jsonl` |
| patterns | duas condições Pattern Watch congeladas por snapshot, com versão | mesmo diário, sem recálculo futuro |
| hypotheses | registo formal da hipótese histórica pós-hoc | `v6-hypotheses.jsonl` |
| evidence | FT por jogo, fonte, nível de evidência, correções e quarentenas sem apagar eventos anteriores | ledger FT + H1 apenas para preenchimento |
| decisions | estado sequencial, motivo e métricas da decisão | relatório V6 congelado no momento da decisão |

Ficheiros: `data/lab/v6-memory-{observations,patterns,hypotheses,evidence,decisions}-AAAA-MM.jsonl`, com resumo reconstituível em `docs/lab/v6-memory.json`. O comando `python -m scripts.lab_v6_memory --verify-only` não escreve nada e falha se o resumo publicado divergir da reconstrução. O workflow apenas publica os cinco fluxos se a sincronização e reconstrução passarem; continua isolado do H1 e de Telegram.

A migração do que **já estava congelado** usa os `known_at` originais apenas como referência, mas os novos eventos de memória recebem a hora real `written_at`: nunca são retrodatados. Quando um FT desaparece ou muda, o fluxo de evidência acrescenta um evento de quarentena ou revisão; o anterior fica intacto. Esta operação **não altera** nem manda corrigir a liquidação de produção.

**Limite explícito da fase:** neste momento a memória de padrões só cobre as condições Pattern Watch já congeladas, **não** as 800 hipóteses exploratórias nem as 49 variáveis V5 em todas as suas versões. A memória não é ainda o Radar completo e não certifica 99% de ingestão. P0 requer sete dias observados e V6.1 exige o gate de estabilidade de 14 dias; enquanto isso, `V6_SCIENCE_MEMORY_SHADOW_WARMUP_NOT_VALIDATED`. P1 #7–#10 continuam pendentes.

## V6.1 P1 #7 — Falsificação determinista (experimental, sem promoção)

Módulo `h1lab/v6_falsification.py`, CLI `python -m scripts.lab_v6_falsification` e relatório público derivado `docs/lab/v6-falsification.json`. Executa dez desafios **fixados na versão `V6-FALSIFICATION-1`** à única hipótese formalmente registada (`V6-POSTHOC-20261028-NO-DOWN`), com estados `PASS`, `FAIL` ou `INSUFFICIENT_N`, n, limiar previamente definido, diagnósticos e jogos de origem:

1. **F01 — Independência**: distingue alertas de episódios realmente distintos.
2. **F02 — Composição**: subida em todos os episódios vs subida com estabilidade vs estabilidade apenas.
3. **F03 — Coerência entre mercados**: testa a direção conjunta de 1X2 e handicap quando disponíveis; **não** trata essa coerência como previsão de golos.
4. **F04 — Antecedência**: separa menos de 1 h, 1–6 h, 6–24 h e mais de 24 h.
5. **F05 — Competição**: usa categorias heurísticas (taça, jovens/reservas, restantes), sem afirmar classificação infalível.
6. **F06 — Robustez**: retira um dia de cada vez e os 5% de resíduos absolutos mais extremos.
7. **F07 — Mercado**: mede `Over observado − p_mercado` e não permite PASS antes de 1 000 FT realmente prospetivos em 3 semanas.
8. **F08 — Concorrentes**: compara contra jogos com linhas Total semelhantes em estratos predefinidos.
9. **F09 — Semelhantes**: pareia jogos com λ próximo (até 0,25) e antecedência próxima (até 6 h) sem repetir os controlos.
10. **F10 — Confirmação temporal**: exige registo formal, início posterior ao `known_at`, FT verificado, 1 000 jogos prospetivos, 3 semanas e gate de 14 dias.

**Rastreabilidade e ausência de fuga temporal:** o motor lê exclusivamente `v6-forecasts-*.jsonl`, `v6-hypotheses.jsonl` e o fluxo **append-only** `v6-memory-evidence-*.jsonl`; só considera FT com `ft_checked_at` comprovado entre o início e o instante da avaliação. Conservadoramente, as previsões **anteriores ao registo formal** da hipótese não servem para validação. Não reconstrói informação em falta usando dados observados mais tarde.

As **novas** capturas V6 passam a guardar `falsification_context` com contagens dos mercados observados, episódios, direções, antecedência, coerência AH/1X2 e classificação indicativa de competição. Os registos anteriores permanecem intactos, sem preencher contextos retroativamente.

Todos os `PASS` são **apenas verificações descritivas**, não resultados estatísticos confirmatórios. A única decisão global permitida continua `INCONCLUSIVO`; nenhuma mudança ao H1, V5, ROI, Telegram, Pattern Watch ou mecanismos de liquidação. O relatório é uma vista derivada, reexecutável com `--verify-only`; os factos permanecem nos cinco diários da memória. Esta fase **não** supera os gates `WARMUP` de 7/14 dias.

## V6.1 P1 #8 — Catálogo de variáveis de contexto V6F2

**Implementado em modo experimental, sem substituir o motor V5.** O módulo `h1lab/v6_features_v2.py` cria uma versão *V6F2* `FEATURE_VERSION = 2` independente. O V5 mantém `pattern_features.FEATURE_VERSION = 1` e os identificadores/hashes antigos das hipóteses permanecem inalterados.

No instante `known_at` real da recolha e **apenas para novos snapshots de jogos futuros**, o diário congela `feature_context_v2`, com SHA-256 verificado e ligação ao fluxo imutável de padrões. O contexto inclui:

- **Asian Handicap:** linha com sinal (incluindo valores negativos), variação da linha, direção casa/fora, mudanças de preços, margens before/after e proveniência V4/H1. Preços inválidos e margens negativas ou acima de 12% ficam desconhecidos/quarentenados, não são classificados como movimentos.
- **Competição:** designação realmente presente na fonte até `known_at`, sem inventar país ou divisão. Agrupamento heurístico `CUP`, `YOUTH_RESERVE`, `LEAGUE_OTHER` ou `UNKNOWN`, com ressalva de classificação não validada.
- **Total↔1X2:** probabilidade Over 2,5 extraída dos Totals válidos (Poisson, **não odd transacionável**) e probabilidades 1X2 normalizadas, com deltas intramensagem. Só assinala `CO_OBSERVED_SAME_MESSAGE` quando ambos os mercados constam da **mesma mensagem**. Cotação de Total numa mensagem e 1X2 noutra recebe `SEPARATE_MESSAGES_ONLY`: não se deduz simultaneidade ou causalidade.
- **Movimentos observados vs desconhecidos:** `Was→Now` de cada mercado na mesma mensagem é observado; todos os intervalos **entre mensagens** são classificados como `UNOBSERVED_LINE_GAP`, `SAME_BOUNDARY_LINE_PRICES_NOT_CONTINUOUSLY_OBSERVED` ou `MISSING_TOTAL_AT_BOUNDARY`. O movimento intermediário é **sempre nulo/desconhecido**, nunca interpolado.
- **Auditoria de proveniência:** `source_event_ids`, instante da captura, cada snapshot de mercado conhecido, categoria do jogo, número de mensagens e SHA do bloco V2.

**Compatibilidade:** a memória de padrões associa o hash V2 somente a eventos cujos diários congelados o contém. Capturas anteriores não são enriquecidas retroativamente. Qualquer divergência entre o hash V2 e o diário de origem impede a reconstrução da memória científica. O relatório `docs/lab/v6-feature-coverage.json` mostra quantas novas capturas têm dados V2 e a distribuição por mercados, contexto e intervalos sem observação — não é um simulador nem validação de uma estratégia.

Este catálogo é *descritivo*. Não passa automaticamente a ser um conjunto de hipóteses estatísticas, não altera os dez testes de falsificação previamente fixados e não faz qualquer escolha de apostas. A análise fora da amostra permanece bloqueada pelos gates 7/14 dias e 1000 FT da hipótese. P1 #9 e #10 continuam por executar.

## V6.1 P1 #9 — Registo de acontecimentos FT e prioridade científica

**Sem alterar a autoridade de liquidação.** `data/lab/ft-ledger.json` mantém-se como referência oficial do LAB. O módulo `h1lab/v6_ft_events.py` acrescenta uma memória específica para **todos os jogos observados**, mesmo sem previsão H1 ou V6: `data/lab/v6-ft-events-AAAA-MM.jsonl`. O primeiro registo de cada jogo é `INITIAL_LEDGER_OBSERVATION`, com `recorded_at` efetivo: **não inventa eventos históricos** anteriores à instalação deste módulo.

Mudanças substantivas de `PENDING`→`FINAL`, resultado 2-1→1-0, mudança de fonte ou de nível de evidência e retirada/reconfirmação de um resultado geram novos eventos com `previous_sha256`, `previous_match_event_id`, identidade, fontes, resultado e hash da fotografia FT. O histórico não é reescrito. Consultas de API repetidas sem alterar resultados/estado/proveniência **não geram eventos**. O reprodutor valida SHA, encadeamento entre eventos de cada jogo e a fotografia do ledger atualmente publicado. Em caso de falha, a Action isolada **não publica** diários V6 incompletos; a publicação habitual do LAB e a liquidação H1 permanecem independentes.

Cada confirmação FT recebe nível de evidência explicitamente não estatístico:
- `MULTI_PROVIDER`: múltiplos provedores distintos concordantes no ledger;
- `SINGLE_PROVIDER`: confirmação por uma só API;
- `REVIEWED_PUBLIC_CORROBORATED`: revisão pública com pelo menos dois URL de corroboração identificados;
- `REVIEWED_PUBLIC_UNCORROBORATED` ou `EVIDENCE_UNSPECIFIED`: informação insuficiente para nível superior;
- `QUARANTINED` ou `NOT_YET_VERIFIED`: não tratar como resultado final.

O relatório `docs/lab/v6-ft-evidence.json` é derivado do diário e conta os estados, os eventos, os níveis de evidência e os casos em quarentena. `python -m scripts.lab_v6_ft_events --verify-only` falha se a reconstrução divergir da fonte.

**Prioridade sem novas consultas:** a função `priority_hints` lê **apenas previsões V6 com `known_at` anterior ao início** e atribui peso maior aos jogos com condição estrita (3), condição histórica original (2) e baseline Total utilizável (1). A função `reconcile` conserva os casos críticos de revisão no topo da fila, só podendo usar a prioridade V6 **dentro do mesmo nível de prioridade atual**; continuam inalterados a espera de 3 h, a pausa de 4 h, os filtros de identidade, o teto de 30 jogos por execução, as quotas das APIs e a lógica de seleção/validação FT. Com diário V6 ausente ou inutilizável, volta à ordem preexistente, sem afetar a liquidação.

**Nota:** prioridade é uma estratégia de recolha de *evidência*, não é pick nem recomendação de aposta. A ordem dos jogos elegíveis pode mudar sem aumentar a quantidade máxima de pedidos; o valor dessa alteração depende da disponibilidade real de resultados nos provedores. A memória FT universal é separada da memória de evidências V6 associada a previsões congeladas (a qual não é modificada). Não altera H1, triplas, Telegram, nem critérios estatísticos. Continua `INCONCLUSIVO` enquanto os gates temporais não forem cumpridos.

## V6.1 P1 #10 — Revisões Telegram/V4, sem apagar versões anteriores

O V4 antigo guardava um registo por `event_id` em `data/lab/markets-AAAA-MM.jsonl`; se a mesma mensagem voltasse com alterações substantivas, substituía essa observação. A partir desta fase, cada versão encontrada é registada **antes da atualização** num novo diário `data/lab/v4-revisions-AAAA-MM.jsonl` (mês UTC de processamento) com hash SHA-256 encadeado, `revision_id`, `previous_event_revision_id`, valores V4 estruturados, `known_at` real, `telegram_original_at` e `telegram_edit_at` quando o Telegram fornece `msg.edit_date`. O ficheiro `markets-` continua uma **projeção da versão mais recente**, para manter intactos os atuais consumidores, mas **nenhuma versão anterior é destruída no diário**.

O primeiro registo dos dados que já estavam guardados antes desta alteração é identificado por `HISTORICAL_BASELINE_IMPORT`, com a hora efetiva de migração, **não** a hora de chegada original. Nas mensagens efetivamente lidas pela nova lógica há `FIRST_SEEN_BY_COLLECTOR`, `EDIT_DATE_CHANGED` ou `CONTENT_CHANGED_EDIT_UNPROVEN`. Alterações apenas a `parser_commit` e ao SHA do código não criam revisões falsas. Uma edição que volte a valores antigos produz um terceiro evento, nunca elimina o segundo.

**Deteção de edições:** o coletor mantém a recolha H1 normal e revisita, de forma adicional e **somente para o V4**, até às 80 mensagens mais recentes do canal. Esta janela limitada pode descobrir edições anteriores ao checkpoint sem as voltar a passar ao H1, triplas ou notificações. Não verifica todo o histórico do canal: edições de mensagens mais antigas que a janela poderão continuar por observar; edições que deixem a mensagem sem um mercado interpretável não são inventadas como preços válidos. A revisita usa a sessão Telegram já autorizada e envolve uma leitura adicional do canal, **não** pedidos novos às APIs de resultados/odds.

O relatório derivado `docs/lab/v4-revisions.json` conta as versões, mensagens com `edit_date` alterado, alterações de conteúdo sem prova de edição, e identifica a cauda de hash. `python -m scripts.lab_v4_revisions --verify-only` valida a cadeia, a ligação por mensagem e a igualdade entre a última versão estruturada e a vista atual. Uma divergência impede a publicação do novo relatório. Os workflows V4/H1 e a memória de previsões congeladas continuam separados; edições observadas **depois** de uma previsão não podem retroativamente mudar o respetivo `known_at`.

**Limites de inferência:** `msg.edit_date` descreve o estado da mensagem quando foi lida, não prova que todas as versões intermédias tenham sido observadas. As versões antigas guardadas antes da instalação não são recuperadas a partir da vista final. Não existe uma série contínua de odds; não são criadas apostas nem classificações automáticas de padrões.

## V6.2 P2 #11 — Radar Científico rastreável (primeira versão)

O novo [Radar Científico](../scientific-radar.html), em `docs/scientific-radar.html`, apresenta **até 10 hipóteses formalmente registadas** — atualmente apenas a definição pós-hoc `V6-POSTHOC-20261028-NO-DOWN`. **Não confunde as 800 hipóteses V5 exploratórias com hipóteses científicas congeladas.**

**Fluxo de dois cliques:** a partir do Radar, clicar na hipótese (1) e depois no jogo (2) abre a cadeia de evidência em três secções visíveis juntas:

1. **Observação Telegram/V4**: identificador exato da mensagem, data original e versão V4 se o diário das revisões comprovar que foi guardada antes do `known_at`. Se não houver prova, aparece `V4_HISTORY_NOT_PROVEN_AT_FREEZE`, sem reconstruir odds posteriores.
2. **Previsão realmente congelada**: `known_at`, linha e preços Total no momento da captura, probabilidade de referência de modelo, hash da previsão e hashes das memórias de observações e padrões; condição histórica original e condição estrita distinguíveis. A probabilidade do mercado modelada **não** é um preço executável.
3. **FT e qualidade da fonte**: evento e hash do diário FT universal, tipo de evidência, hora de verificação e resultado apenas quando temporalmente comprovável após o início. Distingue o FT universal da memória científica V6, que pode ainda não ter registado esse resultado. Um FT ausente ou não comprovado não é tratado como derrota.

A página inclui dez tentativas de falsificação com `PASS/FAIL/INSUFFICIENT_N`, resultado somente se o relatório corresponder aos hashes das caudas atuais dos diários. Um relatório antigo fica explicitamente marcado como desatualizado e não é apresentado como atual. Há pesquisa por equipa, jogo ou identificador, filtros de jogos com condição original/estrita, FT, ausência de FT ou versão V4 original comprovada, e links de leitura aos diários do GitHub.

**Origem e integridade:** `h1lab/v6_scientific_radar.py` valida o journal de previsões, as cinco memórias encadeadas, o registo formal de hipóteses, as revisões V4 e os FT universais, depois produz `docs/lab/v6-scientific-radar.json` como mera vista derivada. Um desvio nos hashes de origem interrompe a publicação. O CLI `python -m scripts.lab_v6_scientific_radar --verify-only` reconstrói a vista sem escrever dados. A Action publica somente após os passos de memória e falsificação aprovarem. Nenhum componente executa apostas ou modifica H1, Telegram, FT ou evidência anterior.

**Limitações assumidas:** o primeiro snapshot V4 anterior a esta auditoria pode não ter prova de existência antes do congelamento. Resultados FT universais não equivalem a resultados já incorporados na memória científica; a página distingue ambos. Não se afirma edge, ROI, validação fora da amostra, nem precisão de ingestão em tempo real. As exigências de 7/14 dias e 1000 FT prospetivos continuam pendentes.

## V6.2 P2 #12 — Monitor semanal de calibração e drift (sombra)

**Quatro verificações predefinidas, sem decisões de aposta ou promoção científica:**

1. **Calibração da referência de mercado**: um único snapshot V6 verdadeiramente pré-jogo por partida, recolhido depois do registo formal da hipótese, associado ao FT final verificado depois do início. Calcula taxa Over 2,5, probabilidade média prevista, Brier score e ECE descritivo em cinco intervalos. Menos de 30 FT: `INSUFFICIENT_N`. Para comparar duas semanas terminadas requer **100 FT válidos em cada** e deterioração do Brier de **0,05 ou mais** para sugerir revisão. O Brier mais baixo é melhor. *Não* mede apostas, ROI ou odds Over executáveis.
2. **Mudança no mercado**: distribuição da probabilidade Over 2,5 inferida a partir do Total Asiático válido, por jogo e semana de conhecimento real `known_at`. PSI em cinco intervalos fixos de probabilidade; pelo menos **50 jogos válidos por semana** e limiar **PSI ≥ 0,25**. Não se pressupõe ausência de mudança abaixo do limiar.
3. **Mudança nos formatos Telegram**: distribuição das famílias de formato normalizadas (agregando cabeçalhos direcionais Total) nas mensagens deduplicadas; divergência Jensen–Shannon **≥ 0,12 bits** ou proporção de famílias novas **≥ 20%**, só com **30 mensagens por semana**. Datas aqui são as originais das mensagens e **não provam** instante de receção; a vista de formatos pode ser atualizada, pelo que este indicador não é teste de proveniência imutável.
4. **Qualidade dos snapshots**: percentagem de referências de mercado inutilizáveis e motivos de quarentena. Exige **50 jogos observados em cada semana**; diferença absoluta da taxa de inutilizáveis **≥ 15 pontos percentuais** indica `SUSPECTED_DRIFT_REVIEW`.

Todas as comparações usam **as duas semanas ISO UTC completas mais recentes**, nunca a semana corrente incompleta. O estado normal quando faltam semanas ou amostras é `INSUFFICIENT_HISTORY` ou `INSUFFICIENT_N`, **nunca** `PASS` ou garantia de estabilidade. Os limiares são heurísticas operacionais previamente fixadas, não testes de significância; não há alegação de evidência causal.

**Periodicidade sem custo adicional:** o script `python -m scripts.lab_v6_weekly_monitor` corre dentro do workflow de auditoria V4 **já existente**. Apenas a **primeira execução de cada semana ISO UTC** cria novo registo no diário encadeado `data/lab/v6-weekly-snapshots.jsonl` e publica `docs/lab/v6-weekly-drift.json`. As execuções seguintes na mesma semana **não recalculam nem publicam** a fotografia, mesmo quando a evidência FT progride; o timestamp do snapshot e os hashes das fontes explicam exatamente que universo foi avaliado. Um resultado atrasado só afeta um relatório semanal posterior, não altera o histórico anterior. `--verify-only` confere a cadeia e a vista. **Sem novo workflow agendado, chamadas às APIs ou notificações Telegram.**

O [Radar Científico](../scientific-radar.html) apresenta as quatro avaliações, resultados por semana e avisos de insuficiência, sem converter drift em pick. Todos os dados V6 e FT provêm de diários verificáveis por SHA; os formatos são explicitamente identificados como projeção de mensagens Telegram com garantia histórica inferior. A implementação não altera H1, triplas, V5, registo formal de hipóteses, cron ou motores de liquidação.


## V6.2 — P2 n.º 13: catálogo e número efetivo de testes

O catálogo data/lab/v6-pruning-catalog-v1.json fixa as 800 definições V5, a versão original das variáveis, o commit de origem e o SHA do relatório. O gerador havia considerado 3.433 propostas, gerado 2.523 hipóteses distintas antes do teto 800 e detetado 642 redundâncias exatas/complementares na geração. Nenhuma dessas tentativas ou dos seus resultados é apagada. As 800 são um subconjunto e não toda a multiplicidade histórica.

O módulo h1lab/v6_hypothesis_pruning.py constrói uma matriz binária hipótese × match_key, usando características anteriores ao início e os predicados V5 de versão 1. Não lê FT, ROI, taxas de acerto, p-values, q-values, odds de fecho nem resíduos para fazer a escolha. A primeira execução fixa a matriz, os IDs de jogos e o hash em data/lab/v6-pruning-selection-v1.json. As seguintes reconstituem exclusivamente a seleção congelada, sem selecionar retroativamente por novos resultados. A opção --verify-only valida o relatório sem escrever ficheiros.

Os critérios são igualdade/complementaridade exata, correlação phi binária absoluta com limiares 0,95 (quase equivalência) e 0,90 (correlação elevada) e identificação das colunas sem variação. O algoritmo escolhe primeiro uma semente por família/operador; completa até 300 pelo método determinístico farthest-first, maximizando a distância mínima 1−|phi|, com desempates por equilíbrio observacional, simplicidade e ID. O mapa integral inclui 800 IDs, representante, motivo e força da associação.

A estimativa de número efetivo é o participation ratio da matriz de correlação R: m_eff = (tr R)² / tr(R²). Este índice descreve a dimensão efetiva dos indicadores binários, NÃO é uma correção rigorosa do alfa ou do enviesamento causado pelas 3.433 propostas, NÃO equivale aos 300 representantes e NÃO demonstra uma vantagem nas apostas. As observações históricas selecionadas por mensagens Telegram não são previsões OOS com known_at verificado.

A Action lab-ft-results.yml opera em sombra, sem pedidos externos adicionais, e publica apenas os ficheiros P2#13 quando testes e replay passam. O relatório docs/lab/v6-pruning.json integra o Radar Científico como EXPLORATÓRIO / INCONCLUSIVO. Nenhum código do H1, FIFO, triplas, notificações, forecasts congelados, registos formais ou diários append-only é modificado. Para repetir o estudo com outra janela é obrigatória uma v2, sem reescrever v1.

P2 n.º 14 permanece seguinte. Gates de 7/14 dias, 10.000 nulos e 1.000 FT prospetivos mantêm-se pendentes.


## V6.2 — P2 n.º 14: arquivos mensais, limites e reconstrução (28/10/2026)

A versão anterior já preservava muitos diários sob `data/lab/{prefixo}-AAAA-MM.jsonl`, mas os leitores não suportavam subdivisões e o diário semanal usava um ficheiro único. A nova implementação `h1lab/lab_archive.py` adiciona rotação por **limite de 20.000.000 bytes**, mantendo o mês UTC e a sequência de eventos: primeiro `prefixo-AAAA-MM.jsonl`, depois `prefixo-AAAA-MM-part0001.jsonl`, `part0002`, etc. As partes são percorridas por ordem cronológica; lacunas nos números, partes isoladas, nomes inesperados, linhas truncadas e ficheiros acima do limite impedem a reconstrução.

**Nunca reescrever históricos imutáveis:** a rotação apenas acrescenta novos segmentos, com os JSONL e SHA anteriores byte a byte intactos. Aplicam-se aos registos V4 de revisões, forecasts V6, eventos universais FT, cinco memórias científicas, descobertas V5 e extensões futuras do diário semanal. O diário semanal antigo `v6-weekly-snapshots.jsonl` mantém-se legível e só passa a novos segmentos mensais quando atingir o limite, preservando as verificações de SHA entre o último registo antigo e o primeiro novo.

**Projeções mutáveis não são arquivos imutáveis:** `markets-AAAA-MM` e `formats-AAAA-MM` representam a última versão conhecida dos eventos; uma revisão do Telegram pode atualizar uma linha passada. Estes ficheiros podem ser reparticionados (mesmas linhas e identificadores de evento únicos, em vários segmentos), mas NÃO são selados como provas históricas. As provas anteriores continuam no diário append-only `v4-revisions`. Os consumidores V4/V5/V6 passam a ler todos os segmentos. Estados mutáveis `discovery-state`, `ft-ledger`, `v4-runchecks` e caches continuam sem alterações semânticas; todos estão sujeitos à verificação de 20 MB, e o sistema falha de forma visível se algum exceder o limite. Estes estados têm de ser migrados para uma arquitetura versionada ANTES de atingirem 20 MB; não se devem truncar ou arquivar sem preservar a autoridade do resultado.

**Índice e selagem:** `data/lab/v6-archive-index.json` contém o nome, bytes, linhas e SHA-256 dos ficheiros JSONL append-only cujo mês UTC terminou. Nas execuções seguintes, uma alteração, remoção ou corrupção de uma entrada selada faz falhar a auditoria. Novos meses fechados são acrescentados ao índice. A primeira selagem de um mês antigo é uma fotografia do momento da instalação, NÃO uma prova de que todas as suas observações foram capturadas em tempo real.

**Replay verificável:** `python -m scripts.lab_v6_archive` verifica tamanho de todos os ficheiros `data/lab`, estado dos segmentos mensais, índice de meses selados e leitura integral dos diários V4 de revisões, previsões V6, eventos FT, cinco memórias científicas e monitor semanal. Publica `docs/lab/v6-archive-health.json` com contagens, estado `INCONCLUSIVO` e SHA do índice. `python -m scripts.lab_v6_archive --verify-only` reconstrói e compara os relatórios sem escrever. A CI executa o comando com os dados reais; a Action existente V4 publica o índice e relatório em modo sombra, sem agendador adicional nem pedidos às APIs.

**Plano de recuperação:** restaurar os segmentos em ordem por mês/parte a partir do repositório Git (usar o histórico Git para uma entrada cuja SHA não corresponda), comparar a entrada com o índice de mês fechado, executar os leitores de diários e `--verify-only`, e só depois reativar o publicador LAB. Nunca corrigir hashes manualmente, preencher `known_at` em falta ou substituir resultados através de interpolação. Falhas são bloqueantes para a parte de arquivo; H1/FIFO, triplas e Telegram não dependem deste módulo.

**Limitações:** a verificação de integridade não prova cobertura de todo o mercado, estabilidade 7/14 dias, rentabilidade, ou validação estatística. Ações concorrentes têm de respeitar os commits e os bloqueios de publicação Git preexistentes; não é introduzida uma segunda fonte de verdade para os resultados FT.


## V6 — P0 gates científicos de cobertura, nulos e cronologia FT (28/10/2026)

**Relatórios novos:** `docs/lab/v6-p0-gates.json` (7/14 dias, qualidade, auditoria temporal de cada FT com proveniência SHA) e `docs/lab/v6-p0-null-simulation.json` (simulação congelada). Implementação em `h1lab/v6_p0_gates.py` e `h1lab/v6_null_simulation.py`. Execução `python -m scripts.lab_v6_p0`; verificação `--verify-only` e recomputação integral `--recompute-nulls`. CI recomputa a simulação para garantir reprodução. O workflow LAB V4 existente publica estes artefactos, sem criar cron, chamadas API nem efeitos em H1/Telegram/FIFO/triplas.

**Gate temporal:** o relógio começa no primeiro `known_at` V6 real (28/10/2026, 14:31 UTC). Para 7 e 14 dias, medem-se oportunidades do Telegram anteriores ao KO já observáveis, capturas congeladas antes do KO e taxa de cobertura por dia de início UTC. As janelas não podem ser encerradas antes do tempo real. Mesmo que a taxa seja >=99%, fica `SOURCE_COVERAGE_PASSED_EXTERNAL_RUN_AUDIT_REQUIRED`, **não** aprovação científica: não há nos históricos V4 carimbo de ingestão individual para todas as mensagens nem prova exaustiva de ausência de falhas de jobs/push Git em 7/14 dias. A aprovação final exige inspeção independente dos logs e histórico Git em todo o intervalo, sem revisões retroativas. A cadeia SHA atual preserva integridade, mas uma cadeia inteira reescrita exigiria confronto com os commits históricos para detetar. Não inventar tempos de recebimento de mensagens.

**Simulação de tipo I:** 10.000 trajetórias Bernoulli calibradas condicionais a `p = 0,30; 0,50; 0,70` em ciclo fixo sintético, PRNG determinístico e semente `20261028`. Reproduz exatamente a mistura de alternativas `+0,05/+0,10/+0,20` e o threshold e-value `1/0,005 = 200` do V6 previamente registado. Em cada trajetória o limite é verificado em **cada observação** (optional monitoring), não só nos checkpoints 25, 50, 100, 250, 500 e 1000. Distingue a probabilidade empírica de alguma passagem do limiar da **regra completa** que requer 1000 FT, e-value final >=200 e resíduo >=5 pontos percentuais. Reporta contagens brutas, taxas e limite superior aproximado de Wilson (95%) da proporção nula. Sob o nulo formal e calibração condicional correta, a desigualdade de Ville garante `P(sup e >= 200) <=0,005` para a única hipótese pré-especificada. Não corrige as milhares de hipóteses históricas exploradas antes do congelamento.

**Potência ilustrativa:** 2500 trajetórias adicionais por efeito sintético `+0,05/+0,10/+0,20`; checkpoints e resultados separados. Estes números dependem de probabilidades fixas e da suposição de independência, **não são dados OOS, nem comprovam calibração real ou rentabilidade**. Qualquer alteração do código/limiares/seed do experimento é detetada pelo SHA das definições e do ficheiro-fonte, exigindo versionamento, e o ficheiro anterior não deve ser substituído silenciosamente.

**FT temporal:** cruza cada previsão V6 mais recente por jogo com o evento de evidência científica e o diário de memórias (SHA íntegros): `known_at` depois de registo e antes do início, resultado verificado ≥90 minutos após KO, `ft_checked_at` não posterior a `written_at` nem ao instante atual, `frozen_source_sha256` coincidente. Se faltar hora, existir contradição ou resultado estiver em quarentena, não é aceite como FT cronologicamente consistente. Um `checked_at` vindo do ledger pode ser interno e não substitui prova independente do provedor. Zero FT elegíveis implica `INSUFFICIENT_N`, nunca aprovação.

**Estado:** a auditoria de origem documenta **97,06%** das 34 oportunidades observáveis (33 congeladas) no dia 28/10/2026 e `WARMUP` nos dois gates, sem alegar que a cobertura do canal equivale à de todos os jogos. Só depois dos gates de 7/14 dias, demonstração estatística de erro tipo I e pelo menos 1000 FT verdadeiramente prospetivos sob registo formal e diversidade temporal se poderá ponderar V6.3; sem promoção automática.
