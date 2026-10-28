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
