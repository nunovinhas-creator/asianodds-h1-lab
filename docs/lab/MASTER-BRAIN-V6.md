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
