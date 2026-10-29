# MASTER BRAIN — auditoria independente de fiabilidade, issue #107

Corte de dados: **2026-10-29 14:16:10 UTC**. Baseline `ed68f3850c797eb4642d972be874d95630825f7c`, árvore `ae04f0ef4436e1de4c9688c5cf0c88b61def4aa1`. As consultas de metadados posteriores ao corte estão identificadas na tabela de workflows. Nenhum merge, dispatch, alteração de main, secret, Worker, cron, workflow produtivo ou envio Telegram foi executado nesta auditoria. Zero chamadas às APIs desportivas. Testes e reproduções em cópia local e diretórios temporários.

**Conclusão: DEGRADED; estabilidade NÃO demonstrada.** A missão não autoriza concluir cobertura exaustiva dos estados de falha nem substituir observação longitudinal por CI. Este relatório cobre o inventário completo, inspeção dirigida dos pontos críticos, regressões adversariais e amostra operacional; as limitações de profundidade estão explícitas. A aceitação operacional da issue permanece aberta.

Legenda: VERIFIED = diretamente observado no código/artefacto/log; REPRODUCED = cenário executado offline; SUSPECTED = hipótese não confirmada em produção; NOT_TESTED = sem evidência suficiente. Severidade refere impacto potencial, não probabilidade estimada.

## Resultados prioritários e evidência

Links de código neste relatório referem sempre o baseline, não main móvel.

| ID | Prioridade / evidência | Falha, alcance e correção |
|---|---|---|
| F01 | P0 observabilidade / REPRODUCED | `h1lab/lab_results.py:364,414–421,509–514`: exceções viram `provider_unavailable`, mas `evidence_retry=True` elimina esses motivos se não houver snapshot efetivo. Replay com dois adaptadores a lançar RuntimeError produz PENDING, `awaiting_ft`, reasons vazio, zero tentativas; erro operacional desaparece. PR de diagnóstico separa `last_provider_visit`/classe da exceção dos timestamps de evidência; reporta DEGRADED, sem mudar FT, cooldown, ordem ou quotas. |
| F02 | P1 integridade temporal / REPRODUCED | `h1lab/v6_ft_events.py:92–120,141–176`: hashes/lineage válidos não impedem regressão de recorded_at. Replay aceitou 12h seguido de 11h no mesmo mês; mesmo evento rehashado passa o leitor. PR rejeita regressão antes do append e no replay, permitindo timestamps iguais. Nenhum journal histórico reescrito. Não se observou retrodatação nos dados reais. |
| F03 | P1 painel / VERIFIED, testes novos | `docs/master-brain.js:107–124,135–143`: `{}` e `[]` passam o teste typeof object; arrays ausentes viram zero jogos rigorosos e zero validados; tipos internos errados podem lançar no render e impedir reativação do botão. PR valida contratos mínimos dos seis feeds, equação FT, tipos e timestamps; marca frescura >2h/futuro; elimina feed inválido e mostra erro de render. Contrato não é validação semântica de todos os campos. |
| F04 | P0 operação / VERIFIED | `results.yml` prevê execução horária; último run observado em 29/10 07:39:47, último check de resultado 07:40, enquanto recolha publica às 14:16. Resultado H1 tem idade de 396 min no corte. Watchdog FT protege apenas LAB. Não foi determinada a causa do atraso do schedule. NÃO corrigido: H1/workflows protegidos. Checker offline independente deteta STALE. |
| F05 | P1 isolamento/publicação / VERIFIED código, incidente NOT_TESTED | `lab-v4-audit.yml` contém 11 continue-on-error; `lab-ft-results.yml` contém 6. Vários outputs são staged apenas por existência, outros protegidos por outcome. Um step pode produzir parcialmente ficheiros e falhar; existência não prova bundle completo. Logs amostrados tiveram todos os steps bem-sucedidos. Proposta: manifest por bundle, staging condicionado ao contrato e outcome; requer autorização para workflow. |
| F06 | P1 notificações / VERIFIED arquitetura, duplicação SUSPECTED | `pattern_notify.py:100–124,151–154` marca recibo apenas em memória, envia, grava localmente; collect faz push depois. Interrupção/push falhado após envio perde recibo e permite novo envio. Não existe transação distribuída Git/Telegram; política “no retry” não cobre perda de checkpoint. Não modificar Telegram/H1 nesta missão. Propor outbox e documentar entrega incerta; dedupe externo não comprovado. |
| F07 | P1 frescura / VERIFIED | `scripts/lab_ft_watchdog.py:33–56` decide por created_at, incluindo runs falhados/cancelados. Cloudflare também considera started runs. É proteção contra excesso de dispatch, não certificado de saúde. Manter throttling; acrescentar monitor de publicação independente em vez de retries agressivos. |
| F08 | P1 falha offline / VERIFIED código | `h1lab/lab_results.py:539–541` ignora exceção do postcheck dual com continue. PR F01 conserva classe/timestamp e contagem sem FT fictício. Cobertura de ramo adicionada em teste. |
| F09 | P2 relatório antigo / VERIFIED | `docs/lab/quality.json` de 27/10 16:11; workflow manual, não quebra SLA automático inexistente. Precisa rótulo de fotografia manual. Não confundir com V4 audit ativo. |
| F10 | P1 proveniência / VERIFIED desenho, impacto SUSPECTED | Workflows fazem pull/rebase após checkout e usam github.sha em campos source. SHA do trigger pode diferir do código/dados realmente usados. No run FT 14:11 há rebase antes do push; publicação final é 871f6f3, não o SHA inicial. Manifest deve distinguir trigger/head/input/publish SHA. |
| F11 | P1 disponibilidade fornecedores / VERIFIED limite | Adaptadores preservam muitos motivos específicos, mas GOAL/OpenFoot/SportScore agregam alguns HTTP/JSON/timeouts como unavailable. Não é possível inferir taxa real por HTTP status desses agregados. Melhorar taxonomia sem expor corpos/URLs autenticados; não introduzir retry automático. |
| F12 | P1 cobertura científica / VERIFIED | V6 gates 7/14 dias WARMUP, scientific_acceptance BLOCKED, 134/137 oportunidades elegíveis congeladas (97,81%); 37 FT no gate observado, não 1000 OOS. Golden Set NOT_CERTIFIED e concordância por campo/identidade independente ainda falsas. Nenhuma promoção científica. |

[Reconciliação](https://github.com/nunovinhas-creator/asianodds-h1-lab/blob/ed68f3850c797eb4642d972be874d95630825f7c/h1lab/lab_results.py#L364) · [Journal](https://github.com/nunovinhas-creator/asianodds-h1-lab/blob/ed68f3850c797eb4642d972be874d95630825f7c/h1lab/v6_ft_events.py#L92) · [Painel](https://github.com/nunovinhas-creator/asianodds-h1-lab/blob/ed68f3850c797eb4642d972be874d95630825f7c/docs/master-brain.js#L107) · [Notificação](https://github.com/nunovinhas-creator/asianodds-h1-lab/blob/ed68f3850c797eb4642d972be874d95630825f7c/h1lab/pattern_notify.py#L100) · [Watchdog](https://github.com/nunovinhas-creator/asianodds-h1-lab/blob/ed68f3850c797eb4642d972be874d95630825f7c/scripts/lab_ft_watchdog.py#L33).

## Reconciliação operacional

- Universo **485 = 161 FINAL + 200 FUTURE + 16 IN_3H_GRACE + 108 vencidos pendentes**. Dos 108, 71 sem evidência efetiva e 37 em cooldown. “Nunca consultado” nesta versão significa sem tentativa efetiva de evidência; NÃO significa zero invocações/HTTP na história.
- Cobertura FT: **33,20% do universo**; **59,85% dos 269 jogos FINAL ou vencidos**, excluindo futuros e graça. Denominadores explícitos, sem converter pendentes em LOSS.
- H1 replay dos CSV/state coincide com docs/data.json: 152 sinais, 41 liquidados, 111 pendentes; 47 triplas, 2 liquidadas, 45 pendentes. ROI publicado reproduzido: simples 5,59%, triplas 76,72% (apenas 2 liquidadas; não demonstra vantagem).
- Bridge `propose()` offline: zero novos resultados elegíveis; 110 rejeições not_final e uma unrecognized_evidence. Não se modificou regra de evidência para liquidar mais.
- Replay de hashes: **622 revisões V4, 404 forecasts, 664 eventos FT**, memórias 404 observações/404 padrões/1 hipótese/54 evidências/1 decisão, 1 snapshot semanal. `validate_against_ledger` FT verdadeiro. Hashes provam consistência interna, não verdade externa dos scores.

### Cadeia run → publicação

| Pipeline | Run / entrada | Evidência de saída |
|---|---|---|
| LAB FT | [40888982990](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40888982990), head 120a6cf, 14:11:15 | job 123500289361: catalog 485/final 161, 3 jogos visitados, zero novos FT; commit local 009169e, rebase e push **871f6f3** às 14:11:53, LAB_FT_PUBLISHED. |
| V4/V6 | [40889003434](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40889003434), 120a6cf, 14:11:23 | job 123500354161: replay/archive OK, gates WARMUP; push **dc08366** 14:11:43, LAB_AUDIT_PUBLISHED. |
| Recolha | [40889734723](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40889734723), 871f6f3, 14:15:52 | job 123502954574: push **ed68f38** 14:16:09; watchdog recent run 14:11:15. Persistência comprovada; receção final Telegram não verificada. |
| H1 resultados | [40836869737](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40836869737), 3554ef9, 07:39:47 | job 123323589752: checked 20, new finals 0, provider errors 10, unresolved 92; push **b101f85** 07:40:02. Job verde não equivale a fornecedores saudáveis. |

Pages GET somente leitura: index HTTP 200 e bytes iguais ao baseline; FT JSON HTTP 200 e bytes iguais ao baseline, timestamp 14:11:27, SHA256 `75ddbc88affe42babfed97359387297d78d95afb105c15f2e74592b6c19e7c4d`. data.json já atualizado para 14:21:10 na consulta posterior; não o comparar como se pertencesse ao corte. JS servido SHA256 `2692e2a0822e368beb31fff7a03d9fd0670c854dea983de873b596ff4e6c1e29`; alterações locais ainda não publicadas. Renderização visual/mobile real: NOT_TESTED; sintaxe e contratos JS testados offline.

### BSD pós-106

VERIFIED: planner e `_date_index` partilham `date_in_cooldown`; cache de execução é reutilizável; refusas por cooldown não entram nos probes; ID persiste; detalhe remoto continua obrigatório no caminho BSD/Monte. No run amostrado: `bsd_date_pages=0`, três `bsd_date_cooldown_deferred`; probes persistidos 27/10→12:21:23 e 28–29/10→13:36:23. Registro contém um ID BSD, FC Porto/Académico Viseu, 599528, sem conflitos registados. Comparisons vazias durante cooldown não prova que a descoberta falhou. Testes existentes cobrem orçamento, colisões, paginação e não prolongamento; nenhum bypass introduzido.

Pedidos no run: SportScore 5, TheSportsDB 3, listagem BSD/API-Football/GOAL/OpenFoot/FotMob/ESPN 0. Não chamar “8 HTTP globais”: o download do arquivo Monte e os caminhos de detalhe têm contabilidade separada. Auditoria global de todos os HTTP emitidos ainda incompleta. Não repetir probes só para melhorar esta fotografia.

## Mapa end-to-end e scorecard

| Subsistema / cadeia | Proteção observada | Saúde no corte / próximo passo |
|---|---|---|
| Cloudflare → dispatch → collect → Telethon → parsing → state | trigger_source, token em header, min_id, dedupe, batch 1500, revisit de 80 editadas | UNKNOWN para deployment Worker/Telegram externo; recolha/publicação recentes VERIFIED. Verificar entrega externa e limites de edits. |
| H1 parse → primeiro sinal Under → FIFO → results CSV → ROI | replay coincide; shared concurrency collect/results; critérios FT e bridge | DEGRADED por resultados STALE, recolha recente não compensa. Investigar schedule sem tocar em lógica. |
| V4 Total/1X2/AH → snapshots → revisions → timeline → audit/golden | parser independente, hashes e lineage; erros de parsing logados | DEGRADED: Golden não certificado; catches não fatais e publicação parcial possíveis. |
| V5 features → padrões/combinatórias → pesquisa → watch → discovery | estados exploratórios, pré-KO, dedupe por jogo; ausência FT não é red | DEGRADED global; relatórios recentes e 8 FT prospectivos no log. Validar publicação agrupada e feeds. |
| FT universal → fila → fornecedores → identidade/90m → ledger/journal → relatórios | graça 3h, retries limitados, conflito/quarentena, IDs, fontes | DEGRADED: 108 vencidos pendentes; F01 diagnóstico e continuidade de observação. |
| BSD registry → Monte ID → detalhe BSD → fallback data | cooldown nas duas fronteiras, count/next, limites 3 dias×3 páginas e budget detalhes | Bloqueado legitimamente por cooldown no corte; recuperação após janela NOT_TESTED nesta auditoria. |
| API-Football/GOAL/OpenFoot → listas/detalhes → dual | quotas/rotations, validação 90m, conflitos, atestações | UNKNOWN disponibilidade corrente; zero requests desses adaptadores na amostra. Falhas históricas não inferem saúde atual. |
| ESPN/SportScore/FotMob/TSDB | FT regulamentar/identidade, motivos de rejeição; SportScore source order | DEGRADED cobertura; taxonomia HTTP incompleta. Não substituir resultado regulamentar por AET. |
| V6 forecast/known_at → resíduos/falsificação/poda → OOS/calibração | forecasts imutáveis; gates reais; replay; calendário mensal | INCONCLUSIVO/BLOCKED científico. F02 melhora chronology FT, não resolve toda semântica temporal dos demais streams. |
| Memórias/weekly/archive | replay multi-stream; 20 MB; shards sequenciais; seal | Integridade interna VERIFIED; um snapshot semanal, zero meses selados nesta fotografia. Rollover real NOT_TESTED. |
| Git push → Pages → seis feeds → MASTER BRAIN | push errors não ignorados nos steps principais; fetch HTTP errors com banner | DEGRADED: F03 contratos e frescura; falta manifest de publicação única. |
| Pattern Watch → Telegram → recibo Git | sem picks automáticas, dedupe por jogo, baseline, falha de entrega incerta | UNKNOWN receção externa; risco F06 entre envio e push. Sem novos alertas ativados. |

Taxa de falhas detetadas: suite baseline 670/670 passou; reproduções adversariais novas FT falharam 4/4 antes das correções. Isto NÃO estima taxa operacional. Falhas desconhecidas: **não quantificáveis**. A amostra operacional contém quatro jobs de três pipelines mais H1 resultados; não constitui 24h/48h/7d de observação.

## Matriz de falhas e alcance dos testes

| Falha | Deteção atual / nesta auditoria | Falta / ação |
|---|---|---|
| Missing secret, HTTP 401/403/429/5xx, timeout | testes de adapters e motivos not_configured/unavailable existentes; H1 log 10 provider errors | matriz uniforme por fornecedor e HTTP real NOT_TESTED integralmente; não consumir API para reproduzir |
| Schema inválido, count/next parcial | testes BSD/adapters existentes + novos contratos de feeds | fuzzing de todos os schemas externos NOT_TESTED |
| Exceção inesperada sem snapshot | nova regressão F01, antes invisível, depois DEGRADED | integrar estado no contrato operacional de todos os pipelines |
| Dual offline crash | F08 diagnóstico separado, zero rede | não modificar resultado nem idade de evidência |
| Relógio recua/hash válido | F02 repro escrita e leitura | mesma política temporal para streams V4/forecast/memory exige auditoria compatibilidade própria |
| FT conflitante/AET/identidade/ID colisão | testes existentes, ledger replay e source-order quarentena | não houve revalidação independente de 161 scores por fontes externas nesta sessão |
| Telegram edit fora de 80 mensagens | limite explícito no collector | impossível certificar ausência de perda por replay local |
| Push 403/rebase conflitante/cancelamento | steps principais falham; amostra FT rebase+push comprovado | injeção completa de processos/concorrência NOT_TESTED; manifest antes de publicação |
| Falha entre envio e persistência | F06 arquitetura verificada | entrega exactly-once não garantida; desenho separado protegido |
| HTTP 200 com `{}`/array/contagem divergente | F03 rejeita contratos; erro visível | browser mobile e nested render malformado exaustivo NOT_TESTED |
| JSON antigo mas fetch 200 | F03 alerta >2h; checker separa resultado de recolha | timestamp não comprova bundle SHA nem entrega externa |
| Job esperado não corre | F04 último run antigo e dados antigos confirmados | watcher H1/publicação requer autorização operacional |
| Mês/shard faltante ou corrupção | suite archive e replay existente | rollover em produção ainda não observado |
| Fuga temporal/seleção de hipóteses | gates WARMUP/BLOCKED, frozen journal, testes existentes | 1000 FT OOS e 7/14 dias não atingidos; não promover |

## Correções e mecanismo leve

Quatro PRs independentes: F01 diagnóstico FT (+ F08), F02 cronologia journal FT, F03 contratos do painel, relatório + checker offline. Todas partem do mesmo baseline; não dependem de merge de outra. Ficheiros H1 protegidos, workflows, scheduler, históricos e dados publicados não alterados. Quota adicional: zero. Sem infra/pagamentos.

`python -m scripts.audit_health --now 2026-10-29T14:16:10Z` lê snapshots, verifica contagens e replay H1/FT, frescura recolha/resultado/pesquisa/watch/V4, escreve apenas JSON em stdout e sai 1 se DEGRADED/FAILED. Resultado no corte: DEGRADED, h1_result_activity STALE (396,17min), outros checks listados OK. “OK” é restrito àquele check; UNKNOWN não vira zero. Thresholds operacionais explícitos: 90min para heartbeat/FT e 120min para resultado H1/relatórios, sem pressupor fluxo constante de jogos. Ativação periódica/alertas depende de autorização; não há auto-dispatch.

Contrato completo recomendado (ainda não ligado aos workflows): run_id, trigger_sha, checkout_sha, input digests, started_at, finished_at, source_freshness, records_seen/valid/rejected/written, adapter_invocations, http_requests por caminho, cooldown_skips, status/reason_codes e publish_sha obtido depois do commit. Manifest deve evitar circularidade: conter SHA de conteúdo ou ser emitido como recibo de publicação separado. Gate antes de staging por bundle; operações mandatórias não-zero; opcionais DEGRADED explícito. Nunca usar ausência de novos jogos como falha.

## Backlog executável e aceitação

1. **S / sem dependências:** rever PR F01, F02, F03 e health; confirmar novas regressões e scope. Merge somente autorizado. Rollback por revert do commit de cada PR, sem rollback de dados/journals.
2. **M / autorização H1/workflows:** investigar atraso results.yml (eventos schedule, queues, concorrência, políticas); watcher apenas leitura da publicação e heartbeat separado; não disparar loops. Resultado esperado: H1 result activity recente OU motivo BLOCKED explícito. Não alterar Under/FIFO.
3. **M / contrato:** bundles de outputs, source/publish SHA e guard de staging nos workflows V4/FT; fault injection em cópias com falha a meio e push/rebase. Preservar último bundle íntegro e sinalizar stale.
4. **M / observabilidade adaptadores:** taxonomia NOT_ATTEMPTED/COOLDOWN/RATE_LIMITED/DATA_MISSING/AMBIGUOUS/PARTIAL/STALE/ERROR/CONFIRMED; contador HTTP na fronteira real. Não reclassificar histórico automaticamente.
5. **M / aprovação Telegram:** durabilidade outbox/dedupe, ensaio crash antes/depois de envio em mock; política clara para entrega incerta, sem ativar alertas novos.
6. **M / ciência:** novos casos cronologia nos demais journals, identidades concorrentes/score revision, hipóteses fora da amostra e Golden Set independente. Gates permanecem bloqueados até evidência.
7. **S–M / interface:** render real desktop/mobile, falhas nested schema, acessibilidade/NaN, caches de assets e coherent bundle id. Checks JS atuais são necessários, insuficientes.

Janelas a iniciar APÓS merge autorizado, não consideradas cumpridas:
- **24h:** todos os ciclos esperados associados a dado publicado ou reason_code explícito; zero erros inesperados sem diagnóstico; equações FT e replay sem divergência; H1 invariantes; zero bypass quota/cooldown; todas as falhas injetadas prioritárias detetadas.
- **48h:** duas janelas diárias incluindo períodos sem jogos; perda de API/schema/push simulada offline; recuperar sem duplicação de resultados/notificações; guardar run/head/publish SHA. Monitor só promove subsystem OK com publicação recente e checks sem falha, não pela cor do job.
- **7d:** ausência de falhas críticas conhecidas sem diagnóstico durante sete dias documentados; observar backlog por idade/coorte e cobertura real; não exigir taxa arbitrária de FT fora da cobertura dos fornecedores; revisão dos incidentes/residuais. Isto não substitui gates científicos 7/14 dias e 1000 FT.
- Rollback interrompe adoção do código novo, preserva dados append-only e evidência; nenhum histórico alterado para “fazer passar” replay.

## Limitações e segurança

Não auditados integralmente: sessão Telegram/delivery, Cloudflare deployment/logs, secrets/permissões administrativas, todos os logs históricos, fault injection completa de 19 workflows, todos os schemas adversariais e 161 scores externos. Dependência direta Telethon pinada 1.45.0; transitivas sem lock/hashes. CVE/advisory live não verificado; não afirmar ausência de vulnerabilidades. Actions usam tags, não SHAs imutáveis. Nenhum segredo incluído.

Inspeção estrutural de todos os módulos e caminhos de exceção; revisão semântica dirigida aos componentes citados, não leitura linha-a-linha certificada de cada módulo. Inventário abaixo explicita comandos e ficheiros; a presença no inventário não equivale a auditoria semântica total. A issue não deve ser encerrada como estabilidade comprovada.

## Inventário de workflows — metadados consultados em 29/10 (~14:20 UTC)

19 YAML no baseline; API mantém ainda 3 entradas históricas sem YAML e Pages dinâmico. Estado API active dessas entradas não prova que ainda sejam executáveis. Último run não equivale a última publicação; só quatro pipelines têm push/log cruzado acima.

| Workflow | Trigger/configuração | Último run UTC / conclusão | Verificação |
|---|---|---|---|
| tests.yml | push:; pull_request:; workflow_dispatch: | [40885637840](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40885637840) 2026-10-29T13:50:21Z success | metadados; output/entrega não certificado |
| results.yml | push:; workflow_dispatch:; - cron: "41 * * * *" | [40836869737](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40836869737) 2026-10-29T07:39:47Z success | código e metadados; logs detalhados acima |
| collect.yml | workflow_dispatch:; push:; - cron: '2-57/5 * * * *' | [40889734723](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40889734723) 2026-10-29T14:15:52Z success | código e metadados; logs detalhados acima |
| pages-build-deployment | Sem YAML no baseline / histórico ou Pages | [40889871783](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40889871783) 2026-10-29T14:16:42Z success | metadados; output/entrega não certificado |
| bot-smoke.yml | workflow_dispatch: | [40700469338](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40700469338) 2026-10-28T13:52:33Z success | metadados; output/entrega não certificado |
| bsd-smoke.yml | workflow_dispatch:; push: | [40510139832](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40510139832) 2026-10-27T13:13:21Z success | metadados; output/entrega não certificado |
| bsd-coverage.yml | workflow_dispatch:; push: | [40509786589](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40509786589) 2026-10-27T13:10:52Z success | metadados; output/entrega não certificado |
| bsd-europa-audit.yml | workflow_dispatch: | [40531326688](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40531326688) 2026-10-27T15:28:29Z success | metadados; output/entrega não certificado |
| lab-quality.yml | workflow_dispatch: | [40538447171](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40538447171) 2026-10-27T16:11:25Z success | metadados; output/entrega não certificado |
| lab-v4-smoke.yml | pull_request:; workflow_dispatch: | [40733126996](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40733126996) 2026-10-28T17:10:19Z success | metadados; output/entrega não certificado |
| lab-v4-audit.yml | workflow_dispatch:; workflow_run: | [40889810770](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40889810770) 2026-10-29T14:16:20Z success | código e metadados; logs detalhados acima |
| lab-v4-log-diagnostic.yml | Sem YAML no baseline / histórico ou Pages | [40549422035](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40549422035) 2026-10-27T17:19:04Z success | metadados; output/entrega não certificado |
| lab-golden-smoke.yml | pull_request:; workflow_dispatch: | [40690755433](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40690755433) 2026-10-28T12:47:35Z success | metadados; output/entrega não certificado |
| lab-timeline-smoke.yml | pull_request:; workflow_dispatch: | [40730293164](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40730293164) 2026-10-28T16:52:50Z success | metadados; output/entrega não certificado |
| dashboard-ui-smoke.yml | pull_request:; push:; workflow_dispatch: | [40762456135](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40762456135) 2026-10-28T20:20:51Z success | metadados; output/entrega não certificado |
| lab-trajectory-research-smoke.yml | pull_request:; workflow_dispatch: | [40733127122](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40733127122) 2026-10-28T17:10:19Z success | metadados; output/entrega não certificado |
| lab-ft-results.yml | workflow_dispatch:; - cron: '12,42 * * * *'; push: | [40888982990](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40888982990) 2026-10-29T14:11:15Z success | código e metadados; logs detalhados acima |
| lab-source-coverage-probe.yml | workflow_dispatch:; push: | [40652006963](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40652006963) 2026-10-28T07:44:18Z success | metadados; output/entrega não certificado |
| lab-ft-forensics.yml | workflow_dispatch:; push: | [40654173119](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40654173119) 2026-10-28T08:04:07Z success | metadados; output/entrega não certificado |
| lab-bsd-id-discovery.yml | workflow_dispatch:; push: | [40656748110](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40656748110) 2026-10-28T08:26:04Z success | metadados; output/entrega não certificado |
| lab-provider-probe.yml | workflow_dispatch: | [40667619390](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40667619390) 2026-10-28T09:52:16Z success | metadados; output/entrega não certificado |
| lab-openfoot-probe.yml | Sem YAML no baseline / histórico ou Pages | [40673913369](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40673913369) 2026-10-28T10:39:57Z failure | metadados; output/entrega não certificado |
| lab-goal-probe.yml | Sem YAML no baseline / histórico ou Pages | [40673908943](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40673908943) 2026-10-28T10:39:55Z failure | metadados; output/entrega não certificado |

### Comandos por workflow (extraídos do código; não executados)

- **bot-smoke.yml**: 
- **bsd-coverage.yml**: 
- **bsd-europa-audit.yml**: `run: python -m unittest tests.test_bsd_europa_audit -v`; `python -m tools.bsd_europa_audit bsd-europa-audit.json 2>&1 | tee bsd-europa-audit.log`
- **bsd-smoke.yml**: 
- **collect.yml**: `run: python -m h1lab.cli collect`; `run: python -m h1lab.pattern_notify`; `git push origin main`; `run: python -m scripts.lab_ft_watchdog`
- **dashboard-ui-smoke.yml**: `node --check docs/dashboard.js`; `node --test tests/dashboard-ui.test.cjs`
- **lab-bsd-id-discovery.yml**: 
- **lab-ft-forensics.yml**: 
- **lab-ft-results.yml**: `python -m unittest discover -s tests -p 'test_lab_results.py' -v`; `python -m unittest discover -s tests -p 'test_lab_ft_v7.py' -v`; `python -m unittest discover -s tests -p 'test_lab_ft_fair_queue.py' -v`; `python -m unittest discover -s tests -p 'test_lab_ft_dual_consensus.py' -v`; `python -m unittest discover -s tests -p 'test_lab_bsd_payload.py' -v`; `python -m unittest discover -s tests -p 'test_lab_ft_rotation.py' -v`; `python -m unittest discover -s tests -p 'test_lab_goal_id_probe.py' -v`; `python -m unittest discover -s tests -p 'test_lab_goal_reviewed.py' -v`; `python -m unittest discover -s tests -p 'test_lab_fotmob.py' -v`; `python -m unittest discover -s tests -p 'test_lab_api_football.py' -v`; `python -m unittest discover -s tests -p 'test_lab_api_football_diagnostics.py' -v`; `python -m unittest discover -s tests -p 'test_lab_api_football_access.py' -v`; `python -m unittest discover -s tests -p 'test_lab_api_football_reviewed.py' -v`; `python -m unittest discover -s tests -p 'test_lab_ft_day_identity.py' -v`; `python -m unittest discover -s tests -p 'test_lab_goal_openfoot.py' -v`; `python -m unittest discover -s tests -p 'test_lab_ft_diagnostics.py' -v`; `python -m unittest discover -s tests -p 'test_lab_identity_review.py' -v`; `python -m unittest discover -s tests -p 'test_lab_bsd_search.py' -v`; `python -m unittest discover -s tests -p 'test_lab_espn.py' -v`; `python -m unittest discover -s tests -p 'test_lab_sportscore.py' -v`; `python -m unittest discover -s tests -p 'test_lab_reviewed_aliases.py' -v`; `python -m unittest discover -s tests -p 'test_lab_source_order.py' -v`; `python -m unittest discover -s tests -p 'test_lab_ft_recovery.py' -v`; `python -m unittest discover -s tests -p 'test_lab_ft_reviewed_evidence.py' -v`; `python -m unittest discover -s tests -p 'test_lab_ft_overdue_reviews.py' -v`; `python -m unittest discover -s tests -p 'test_lab_monte_bsd.py' -v`; `python -m unittest discover -s tests -p 'test_lab_bsd_monte_first.py' -v`; `python -m unittest discover -s tests -p 'test_lab_bsd_id_registry.py' -v`; `python -m unittest discover -s tests -p 'test_lab_identity.py' -v`; `python -m unittest discover -s tests -p 'test_lab_reviewed_bsd_ids.py' -v`; `run: python -m scripts.lab_results`; `python -m unittest discover -s tests -p 'test_v6_ft_events.py' -v`; `python -m scripts.lab_v6_ft_events`; `python -m scripts.lab_v6_ft_events --verify-only`; `python -m unittest discover -s tests -p 'test_v6_hypothesis_pruning.py' -v`; `python -m scripts.lab_v6_hypothesis_pruning`; `python -m scripts.lab_v6_hypothesis_pruning --verify-only`; `python -m unittest discover -s tests -p 'test_pattern_engine.py'`; `python -m scripts.lab_pattern_research`; `python -m unittest discover -s tests -p 'test_v6_residual.py' -v`; `python -m scripts.lab_v6_residual`; `python -m unittest discover -s tests -p 'test_pattern_watch.py' -v`; `python -m scripts.lab_pattern_watch`; `python -m unittest discover -s tests -p 'test_discovery_timeline.py' -v`; `python -m scripts.lab_discoveries`; `if git push origin HEAD:main; then`
- **lab-golden-smoke.yml**: `run: python -m unittest discover -s tests -p 'test_golden.py' -v`; `run: python -m unittest discover -s tests -p 'test_golden_pending.py' -v`; `run: python -m unittest discover -s tests -p 'test_golden_priority.py' -v`; `run: python -m scripts.lab_golden`; `run: python -m scripts.lab_golden_priority`
- **lab-provider-probe.yml**: `run: python -m scripts.lab_provider_probe`
- **lab-quality.yml**: `run: python -m scripts.lab_quality`; `git push origin main`
- **lab-source-coverage-probe.yml**: 
- **lab-timeline-smoke.yml**: `run: python -m unittest discover -s tests -p 'test_timeline.py' -v`; `run: python -m scripts.lab_match_trajectories`
- **lab-trajectory-research-smoke.yml**: `python -m compileall -q h1lab/trajectory_research.py scripts/lab_trajectory_research.py`; `python -m unittest discover -s tests -p 'test_trajectory_research.py' -v`; `run: python -m scripts.lab_trajectory_research`; `python -m unittest discover -s tests -p 'test_outcome_readiness.py' -v`; `python -m scripts.lab_outcome_readiness`; `python -m unittest discover -s tests -p 'test_pattern_engine.py' -v`; `python -m scripts.lab_pattern_research`
- **lab-v4-audit.yml**: `python -m unittest discover -s tests -p 'test_v6_shadow.py' -v`; `python -m unittest discover -s tests -p 'test_v6_features_v2.py' -v`; `python -m scripts.lab_v6_shadow`; `python -m scripts.lab_v6_feature_coverage`; `python -m unittest discover -s tests -p 'test_v6_science_memory.py' -v`; `python -m scripts.lab_v6_memory`; `python -m scripts.lab_v6_memory --verify-only`; `python -m unittest discover -s tests -p 'test_v6_falsification.py' -v`; `python -m scripts.lab_v6_falsification`; `python -m scripts.lab_v6_falsification --verify-only`; `python -m unittest discover -s tests -p 'test_v4_audit.py' -v`; `python -m unittest discover -s tests -p 'test_v4_logscan.py' -v`; `run: python -m scripts.lab_v4_audit`; `run: python -m scripts.lab_golden`; `run: python -m scripts.lab_golden_priority`; `python -m unittest discover -s tests -p 'test_timeline.py'`; `python -m scripts.lab_match_trajectories`; `python -m unittest discover -s tests -p 'test_trajectory_research.py' -v`; `python -m scripts.lab_trajectory_research`; `python -m unittest discover -s tests -p 'test_outcome_readiness.py' -v`; `python -m scripts.lab_outcome_readiness`; `python -m unittest discover -s tests -p 'test_v4_revisions.py' -v`; `python -m scripts.lab_v4_revisions`; `python -m scripts.lab_v4_revisions --verify-only`; `python -m unittest discover -s tests -p 'test_v6_scientific_radar.py' -v`; `python -m scripts.lab_v6_scientific_radar`; `python -m scripts.lab_v6_scientific_radar --verify-only`; `python -m scripts.lab_v6_weekly_monitor`; `python -m scripts.lab_v6_weekly_monitor --verify-only`; `python -m unittest discover -s tests -p 'test_lab_archive.py' -v`; `python -m scripts.lab_v6_archive`; `python -m scripts.lab_v6_archive --verify-only`; `python -m unittest discover -s tests -p 'test_v6_p0_gates.py' -v`; `python -m scripts.lab_v6_p0`; `python -m scripts.lab_v6_p0 --verify-only`; `if git push origin HEAD:main; then`
- **lab-v4-smoke.yml**: `run: python -m scripts.lab_v4_audit`
- **results.yml**: `run: python -m h1lab.results`; `run: python -m h1lab.lab_promotion`; `run: python -m h1lab.cli render`; `git push origin main`
- **tests.yml**: `- run: python -m compileall -q h1lab scripts`; `- run: python -m unittest discover -s tests -v`; `python -m scripts.lab_v6_p0 --recompute-nulls`; `python -m scripts.lab_v6_p0 --verify-only`; `python -m scripts.lab_v6_archive`; `python -m scripts.lab_v6_archive --verify-only`; `python -m scripts.lab_v6_hypothesis_pruning`; `python -m scripts.lab_v6_hypothesis_pruning --verify-only`; `python -m scripts.lab_v6_residual`; `python -m scripts.lab_v6_shadow`; `python -m scripts.lab_v6_feature_coverage`; `python -m scripts.lab_v6_memory`; `python -m scripts.lab_v6_memory --verify-only`; `python -m scripts.lab_v6_falsification`; `python -m scripts.lab_v6_falsification --verify-only`; `python -m scripts.lab_v6_ft_events`; `python -m scripts.lab_v6_ft_events --verify-only`; `python -m scripts.lab_v6_scientific_radar`; `python -m scripts.lab_v6_scientific_radar --verify-only`; `run: node --check docs/scientific-radar.js`; `python -m scripts.lab_v6_weekly_monitor`; `python -m scripts.lab_v6_weekly_monitor --verify-only`; `run: node --test scheduler/worker.test.mjs`

### Módulos, scripts e saídas

Inventário estrutural, com descrição declarada pelo módulo (não uma afirmação independente de correção).

| Ficheiro | Função declarada / dimensão |
|---|---|
| `h1lab/__init__.py` | AsianOdds H1 Lab — análise de alertas e ROI simulado. (1 linhas) |
| `h1lab/bot.py` | Private Telegram Bot API delivery. Tokens are never logged or persisted. (55 linhas) |
| `h1lab/bsd.py` | BSD football v2 score verification, fail-closed on unclear 90-minute data. (141 linhas) |
| `h1lab/cli.py` | Poll an already-subscribed Telegram channel; commit structured market observations. (200 linhas) |
| `h1lab/core.py` | AsianOdds H1: structured parsing, frozen picks, Asian settlement and ROI. (196 linhas) |
| `h1lab/discovery_timeline.py` | MASTER BRAIN discovery chronology (read-only, independent of H1). (304 linhas) |
| `h1lab/golden.py` | Independent, manually transcribed Telegram golden-set review. (636 linhas) |
| `h1lab/golden_priority.py` | Select high-information *real* Telegram events for independent human review. (170 linhas) |
| `h1lab/intelligence.py` | Independent exploratory market intelligence. Never produces H1 picks or tickets. (78 linhas) |
| `h1lab/lab_api_football.py` | Optional, officially documented API-Football v3 FT provider for LAB only. (311 linhas) |
| `h1lab/lab_api_football_access.py` | Fail-closed, evidence-only gate for provider-confirmed history restrictions. (105 linhas) |
| `h1lab/lab_api_football_errors.py` | Small, score-free API-Football error envelope for quota-safe diagnostics. (75 linhas) |
| `h1lab/lab_api_football_reviewed.py` | Human-approved API-Football fixture crosswalk: NEVER fuzzy auto-settlement. (324 linhas) |
| `h1lab/lab_archive.py` | V6.2 P2#14 — lossless monthly LAB journals, size bounds and seal verification. (263 linhas) |
| `h1lab/lab_bsd_id_registry.py` | Persist BSD fixture IDs learned from COMPLETE date pages, not guessed team IDs. (393 linhas) |
| `h1lab/lab_bsd_payload.py` | BSD LAB-only response compatibility, based on Monte-Carlos settlement parsing. (93 linhas) |
| `h1lab/lab_bsd_priority.py` | BSD-first FT reconciliation using the owner's working Monte-Carlos IDs. (46 linhas) |
| `h1lab/lab_bsd_search.py` | BSD date-indexed fallback for LAB only. (217 linhas) |
| `h1lab/lab_espn.py` | LAB-only ESPN scoreboard corroboration for explicitly mapped competitions. (214 linhas) |
| `h1lab/lab_fotmob.py` | LAB-only FotMob daily-result adapter. (192 linhas) |
| `h1lab/lab_ft_attestations.py` | V9: persist minimal, validated FT provider attestations across ordinary runs. (163 linhas) |
| `h1lab/lab_ft_backlog.py` | Safe, read-only live FT backlog diagnostics — one fixture, not one bet. (140 linhas) |
| `h1lab/lab_ft_crosswalk.py` | Read-only identity registry: only event URLs from confirmed FT results. (70 linhas) |
| `h1lab/lab_ft_day_identity.py` | Score-free, complete API-Football day identity index for human FT review. (150 linhas) |
| `h1lab/lab_ft_diagnostics.py` | Read-only coverage diagnostics for the independent LAB FT collector. (46 linhas) |
| `h1lab/lab_ft_dual_consensus.py` | FT V8: zero-extra-request two-provider corroboration from COMPLETE day caches. (268 linhas) |
| `h1lab/lab_ft_evidence.py` | Minimal, score-free fingerprints of authenticated provider day lists. (118 linhas) |
| `h1lab/lab_ft_reviewed_evidence.py` | Frozen, two-source, fixture-specific *manual* reviews of three SportScore quarantines. (257 linhas) |
| `h1lab/lab_ft_rotation.py` | Bounded, persisted per-provider date rotation; no network operations. (179 linhas) |
| `h1lab/lab_goal.py` | GOAL API daily FT recovery for LAB; 90-minute evidence only. (283 linhas) |
| `h1lab/lab_goal_id_probe.py` | One quota-neutral GOAL fixture-ID probe, selected from existing review evidence. (88 linhas) |
| `h1lab/lab_goal_reviewed.py` | Reviewed GOAL fixture-ID bridge; never settle a disputed score automatically. (177 linhas) |
| `h1lab/lab_identity.py` | Fail-closed team-name identity for LAB FT reconciliation (never used by H1). (164 linhas) |
| `h1lab/lab_identity_review.py` | Read-only, persistent candidate queue from ALREADY FETCHED FT provider date caches. (337 linhas) |
| `h1lab/lab_monte_bsd.py` | Read-only Monte-Carlos -> BSD event-ID resolver for LAB-only FT reconciliation. (383 linhas) |
| `h1lab/lab_openfoot.py` | OpenFoot Starter FT lookup for LAB only. Fail closed on ambiguity or ET. (177 linhas) |
| `h1lab/lab_promotion.py` | Conservative LAB->H1 score transport. Does not change H1 signal or ticket rules. (176 linhas) |
| `h1lab/lab_results.py` | Independent, bounded, fail-closed FT result collection for *all* observed LAB fixtures. (679 linhas) |
| `h1lab/lab_reviewed_aliases.py` | Explicitly reviewed source-specific fixture names, NOT fuzzy runtime matching. (72 linhas) |
| `h1lab/lab_reviewed_bsd_ids.py` | Reviewed BSD event IDs from actual finished-event catalogue (2026-10-28). (49 linhas) |
| `h1lab/lab_sportscore.py` | SportScore public API lookup for LAB research. Explicit attribution required. (244 linhas) |
| `h1lab/lab_stats.py` | Small, dependency-free statistics for the LAB research engine. (101 linhas) |
| `h1lab/market_math.py` | Pure market arithmetic for the LAB research engine (no I/O, no H1 imports). (130 linhas) |
| `h1lab/market_v2.py` | Conservative multi-market projections of structured LEGACY observations. (111 linhas) |
| `h1lab/market_v4.py` | Independent, conservative Telegram multi-market shadow parser. (226 linhas) |
| `h1lab/notify.py` | Notify H1 triples to an explicitly configured Telegram bot chat. (57 linhas) |
| `h1lab/outcome_readiness.py` | Read-only research readiness: repeated-game outcomes, never betting returns. (162 linhas) |
| `h1lab/pattern_engine.py` | LAB V5 research engine: patterns, combinations, outcome association, (725 linhas) |
| `h1lab/pattern_features.py` | Match-level features and individual odds-movement patterns (LAB V5). (336 linhas) |
| `h1lab/pattern_notify.py` | Send prospective MASTER BRAIN observations, never H1 tickets or betting picks. (155 linhas) |
| `h1lab/pattern_watch.py` | Prospective V5 market-movement observer; NEVER a pick generator. (210 linhas) |
| `h1lab/results.py` | Conservative final-score reconciler using TheSportsDB free V1 search. (241 linhas) |
| `h1lab/session.py` | Carrega uma sessão Telethon sem expor o seu conteúdo nos logs. (36 linhas) |
| `h1lab/shadow_formats.py` | Shadow-only format inventory. No raw Telegram message content is persisted. (119 linhas) |
| `h1lab/similarity.py` | Interpretable "similar historical matches" search for the LAB (no ML). (139 linhas) |
| `h1lab/timeline.py` | Per-match chronology of observed Telegram alerts (read-only, shadow LAB). (546 linhas) |
| `h1lab/trajectory_research.py` | Exploratory, match-level analysis of *observed* repeated Telegram alerts. (268 linhas) |
| `h1lab/v4_audit.py` | Read-only V4 vs legacy audit. No imports from H1 betting or collection code. (585 linhas) |
| `h1lab/v4_revisions.py` | V4 Telegram revision evidence, separate from H1 and the current V4 projection. (206 linhas) |
| `h1lab/v6_falsification.py` | V6 deterministic falsification battery: 10 challenges to a frozen hypothesis. (389 linhas) |
| `h1lab/v6_features_v2.py` | Versioned V6 *capture-time* cross-market features; no H1 or V5 changes. (261 linhas) |
| `h1lab/v6_ft_events.py` | Append-only LAB FT state/evidence audit. Shadow; never settles H1 bets. (229 linhas) |
| `h1lab/v6_hypotheses.py` | Append-only formal registration of the historic post-hoc V6 hypothesis. (65 linhas) |
| `h1lab/v6_hypothesis_pruning.py` | V6.2 P2#13. Outcome-blind reduction of a frozen V5 exploratory catalogue. (220 linhas) |
| `h1lab/v6_null_simulation.py` | P0: prespecified e-process Monte Carlo under synthetic, calibrated market null. (151 linhas) |
| `h1lab/v6_p0_gates.py` | P0 7/14-day readiness and per-FT knowledge chronology, independent of H1. (192 linhas) |
| `h1lab/v6_readiness.py` | V6 prospective coverage gate, explicitly based on observable source opportunities. (95 linhas) |
| `h1lab/v6_residual.py` | V6 independent, *exploratory* market-relative audit of ALL V5 hypotheses. (173 linhas) |
| `h1lab/v6_science_memory.py` | MASTER BRAIN V6 experimental scientific memory, SHADOW only. (346 linhas) |
| `h1lab/v6_scientific_radar.py` | V6.2 P2#11: bounded, auditable scientific radar derived from immutable journals. (271 linhas) |
| `h1lab/v6_shadow.py` | MASTER BRAIN V6 shadow journal: quality, genuinely prospective baselines, evidence. (403 linhas) |
| `h1lab/v6_weekly_monitor.py` | MASTER BRAIN V6.2: weekly, observation-only market/calibration/format drift. (358 linhas) |
| `scripts/authorize.py` | Autenticação local e interativa de uma conta Telegram via Telethon. (53 linhas) |
| `scripts/lab_discoveries.py` | Materialize incremental V5 discovery history and prospective FT without API calls. (93 linhas) |
| `scripts/lab_ft_watchdog.py` | Nonblocking GitHub FT workflow watchdog, run AFTER H1 data were safely pushed. (115 linhas) |
| `scripts/lab_golden.py` | Reproducible, offline-capable Golden Set publication (never modifies H1). (29 linhas) |
| `scripts/lab_golden_priority.py` | Publish an explicitly unverified priority queue for manual Golden reviews. (27 linhas) |
| `scripts/lab_match_trajectories.py` | Publish docs/lab/match-trajectories.json (read-only over H1 + V4 data). (47 linhas) |
| `scripts/lab_outcome_readiness.py` | Generate outcome coverage diagnostics from tracked data (LAB-only). (34 linhas) |
| `scripts/lab_pattern_research.py` | LAB V5: build docs/lab/pattern-research.json (read-only over H1 + V4 + LAB FT). (99 linhas) |
| `scripts/lab_pattern_watch.py` | Refresh V5 future-only movement watch without odds provider API requests. (61 linhas) |
| `scripts/lab_provider_probe.py` | One-shot LAB coverage audit. Read-only; NEVER settles or writes scores. (167 linhas) |
| `scripts/lab_quality.py` | Build a small public data-quality aggregate; no raw channel content. (33 linhas) |
| `scripts/lab_results.py` | Scheduled LAB-only result collector. No H1 mutations, no channel text. (783 linhas) |
| `scripts/lab_trajectory_research.py` | Publish a descriptive repeated-match analysis into LAB only. (40 linhas) |
| `scripts/lab_v4_audit.py` | Build the V4 report from tracked evidence; inspect collection logs when authorised. (244 linhas) |
| `scripts/lab_v4_revisions.py` | Rebuild V4 edit/revision evidence from the immutable journal. (40 linhas) |
| `scripts/lab_v6_archive.py` | V6.2 P2#14 archive integrity and SHA replay; no API, no extra schedule. (23 linhas) |
| `scripts/lab_v6_falsification.py` | Publish a deterministic, strictly read-only V6 falsification report. (49 linhas) |
| `scripts/lab_v6_feature_coverage.py` | Source-only report for V6F2 feature observations, not a prediction. (54 linhas) |
| `scripts/lab_v6_ft_events.py` | Create and verify append-only V6 FT audit after the existing LAB reconciliation. (43 linhas) |
| `scripts/lab_v6_hypothesis_pruning.py` | V6.2 P2#13 freeze/replay without API or match outcomes. (19 linhas) |
| `scripts/lab_v6_memory.py` | Build and verify V6 scientific memory independently of the production H1. (42 linhas) |
| `scripts/lab_v6_p0.py` | Publish P0 scientific gates and one fixed-seed 10,000-null Monte Carlo suite. (94 linhas) |
| `scripts/lab_v6_residual.py` | Publish all V5 hypothesis effects in the market-relative V6 reference frame. (27 linhas) |
| `scripts/lab_v6_scientific_radar.py` | Publish the V6.2 scientific radar as a bounded, replayable JSON projection. (36 linhas) |
| `scripts/lab_v6_shadow.py` | V6 shadow audit after an H1 collector checkpoint: never sends messages. (69 linhas) |
| `scripts/lab_v6_weekly_monitor.py` | Record at most one immutable scientific-drift report per UTC ISO week. (139 linhas) |

Ficheiros de dados, páginas, configuração, testes e documentação no baseline:

**data/**

`data/lab/discovery-events-2026-10.jsonl`, `data/lab/discovery-state.json`, `data/lab/formats-2026-10.jsonl`, `data/lab/ft-api-audit.json`, `data/lab/ft-api-football-day-index.json`, `data/lab/ft-api-football-reviewed.json`, `data/lab/ft-bsd-event-ids.json`, `data/lab/ft-goal-reviewed.json`, `data/lab/ft-ledger.json`, `data/lab/ft-provider-attestations.json`, `data/lab/ft-provider-day-rotation.json`, `data/lab/ft-provider-identity.json`, `data/lab/golden/attestations/3571094759_50671__firsthand.json`, `data/lab/golden/corroborations/3571094759_50671__pasted_text.json`, `data/lab/golden/pending/registry.json`, `data/lab/golden/reviews/3571094759_50655__R1.json`, `data/lab/golden/reviews/3571094759_50656__R1.json`, `data/lab/golden/reviews/3571094759_50658__R1.json`, `data/lab/golden/reviews/3571094759_50671__R1.json`, `data/lab/golden/reviews/README.md`, `data/lab/markets-2026-10.jsonl`, `data/lab/pattern-registry.json`, `data/lab/pattern-watch-first-seen.json`, `data/lab/v4-revisions-2026-10.jsonl`, `data/lab/v4-runchecks.jsonl`, `data/lab/v6-archive-index.json`, `data/lab/v6-forecasts-2026-10.jsonl`, `data/lab/v6-ft-events-2026-10.jsonl`, `data/lab/v6-hypotheses.jsonl`, `data/lab/v6-memory-decisions-2026-10.jsonl`, `data/lab/v6-memory-evidence-2026-10.jsonl`, `data/lab/v6-memory-hypotheses-2026-10.jsonl`, `data/lab/v6-memory-observations-2026-10.jsonl`, `data/lab/v6-memory-patterns-2026-10.jsonl`, `data/lab/v6-pruning-catalog-v1.json`, `data/lab/v6-pruning-selection-v1.json`, `data/lab/v6-weekly-snapshots.jsonl`, `data/pattern-notifications.json`, `data/result_audit.json`, `data/results.csv`, `data/state.json`

**docs/**

`docs/MARKET-INTELLIGENCE.md`, `docs/README.md`, `docs/dashboard.css`, `docs/dashboard.js`, `docs/data.json`, `docs/ft-identity-review.html`, `docs/ft-recovery.html`, `docs/golden-review.html`, `docs/h1.html`, `docs/index.html`, `docs/lab-pattern-watch.html`, `docs/lab-quality.html`, `docs/lab-research.html`, `docs/lab-results.html`, `docs/lab-v4-audit.html`, `docs/lab.html`, `docs/lab/ALL-OBSERVED-FT.md`, `docs/lab/API-FOOTBALL-V10.md`, `docs/lab/ARCHITECTURE.md`, `docs/lab/BSD-DATE-SEARCH.md`, `docs/lab/BSD-REVIEWED-IDS.md`, `docs/lab/CEREBRO-ODDS.md`, `docs/lab/CLAUDE-HANDOFF-2026-10-27.md`, `docs/lab/DISCOVERY-TIMELINE.md`, `docs/lab/FOTMOB-FT-V9.md`, `docs/lab/FT-BACKLOG-RECOVERY-V12.md`, `docs/lab/FT-COVERAGE-PRIORITY.md`, `docs/lab/FT-CROSSWALK-ROTATION-P0.md`, `docs/lab/FT-ID-PROBE-P0.md`, `docs/lab/FT-IDENTITY-REVIEW.md`, `docs/lab/FT-P0-EVIDENCE-AND-TARGETED-RECOVERY.md`, `docs/lab/FT-QUEUE-P0.md`, `docs/lab/GOAL-OPENFOOT-FT-V11.md`, `docs/lab/GOLDEN-REVIEW.md`, `docs/lab/MASTER-BRAIN-V6.md`, `docs/lab/MONTE-CARLOS-BSD.md`, `docs/lab/OUTCOME-READINESS.md`, `docs/lab/PATTERN-ENGINE.md`, `docs/lab/QUALITY-DIMENSIONS.md`, `docs/lab/REPEATED-ODDS-EMPIRICAL.md`, `docs/lab/REVIEWED-IDENTITIES.md`, `docs/lab/SOURCE-ORDER-INTEGRITY.md`, `docs/lab/SPORTSCORE-FT.md`, `docs/lab/TIMELINE.md`, `docs/lab/discoveries.json`, `docs/lab/ft-api-football-review-decisions.json`, `docs/lab/ft-backlog.json`, `docs/lab/ft-bsd-id-discovery.md`, `docs/lab/ft-identity-review.json`, `docs/lab/ft-provider-identity.json`, `docs/lab/ft-results.json`, `docs/lab/ft-v7-implementation.md`, `docs/lab/ft-v7-reviewed-batch.md`, `docs/lab/golden-candidates.json`, `docs/lab/golden-priority.json`, `docs/lab/golden-report.json`, `docs/lab/match-trajectories.json`, `docs/lab/outcome-readiness.json`, `docs/lab/pattern-research.json`, `docs/lab/pattern-watch.json`, `docs/lab/quality.json`, `docs/lab/trajectory-research.json`, `docs/lab/v4-audit.json`, `docs/lab/v4-revisions.json`, `docs/lab/v6-archive-health.json`, `docs/lab/v6-falsification.json`, `docs/lab/v6-feature-coverage.json`, `docs/lab/v6-ft-evidence.json`, `docs/lab/v6-memory.json`, `docs/lab/v6-p0-gates.json`, `docs/lab/v6-p0-null-simulation.json`, `docs/lab/v6-price-quality.json`, `docs/lab/v6-pruning.json`, `docs/lab/v6-readiness.json`, `docs/lab/v6-residual-research.json`, `docs/lab/v6-scientific-radar.json`, `docs/lab/v6-shadow.json`, `docs/lab/v6-weekly-drift.json`, `docs/market-intelligence.html`, `docs/master-brain.css`, `docs/master-brain.js`, `docs/scientific-radar.css`, `docs/scientific-radar.html`, `docs/scientific-radar.js`

**tests/**

`tests/dashboard-ui.test.cjs`, `tests/test_bot.py`, `tests/test_bsd.py`, `tests/test_bsd_europa_audit.py`, `tests/test_discovery_timeline.py`, `tests/test_golden.py`, `tests/test_golden_pending.py`, `tests/test_golden_priority.py`, `tests/test_h1.py`, `tests/test_h1_lab_promotion.py`, `tests/test_intelligence.py`, `tests/test_lab_api_football.py`, `tests/test_lab_api_football_access.py`, `tests/test_lab_api_football_diagnostics.py`, `tests/test_lab_api_football_reviewed.py`, `tests/test_lab_archive.py`, `tests/test_lab_bsd_id_registry.py`, `tests/test_lab_bsd_monte_first.py`, `tests/test_lab_bsd_payload.py`, `tests/test_lab_bsd_search.py`, `tests/test_lab_espn.py`, `tests/test_lab_fotmob.py`, `tests/test_lab_ft_backlog.py`, `tests/test_lab_ft_day_identity.py`, `tests/test_lab_ft_diagnostics.py`, `tests/test_lab_ft_dual_consensus.py`, `tests/test_lab_ft_fair_queue.py`, `tests/test_lab_ft_overdue_reviews.py`, `tests/test_lab_ft_recovery.py`, `tests/test_lab_ft_reviewed_evidence.py`, `tests/test_lab_ft_rotation.py`, `tests/test_lab_ft_v7.py`, `tests/test_lab_ft_watchdog.py`, `tests/test_lab_goal_id_probe.py`, `tests/test_lab_goal_openfoot.py`, `tests/test_lab_goal_reviewed.py`, `tests/test_lab_identity.py`, `tests/test_lab_identity_review.py`, `tests/test_lab_monte_bsd.py`, `tests/test_lab_quality.py`, `tests/test_lab_results.py`, `tests/test_lab_reviewed_aliases.py`, `tests/test_lab_reviewed_bsd_ids.py`, `tests/test_lab_source_order.py`, `tests/test_lab_sportscore.py`, `tests/test_market_v2.py`, `tests/test_market_v4.py`, `tests/test_master_brain_site.py`, `tests/test_outcome_readiness.py`, `tests/test_pattern_engine.py`, `tests/test_pattern_notify.py`, `tests/test_pattern_watch.py`, `tests/test_results.py`, `tests/test_session.py`, `tests/test_shadow_formats.py`, `tests/test_shadow_integration.py`, `tests/test_timeline.py`, `tests/test_trajectory_research.py`, `tests/test_v4_audit.py`, `tests/test_v4_logscan.py`, `tests/test_v4_quality_dimensions.py`, `tests/test_v4_revisions.py`, `tests/test_v6_falsification.py`, `tests/test_v6_features_v2.py`, `tests/test_v6_ft_events.py`, `tests/test_v6_hypothesis_pruning.py`, `tests/test_v6_p0_gates.py`, `tests/test_v6_readiness.py`, `tests/test_v6_residual.py`, `tests/test_v6_science_memory.py`, `tests/test_v6_scientific_radar.py`, `tests/test_v6_shadow.py`, `tests/test_v6_weekly_monitor.py`

**scheduler/**

`scheduler/README.md`, `scheduler/worker.mjs`, `scheduler/worker.test.mjs`, `scheduler/wrangler.toml`

**config/**

`config/oruseye_europe30.json`

**reports/**

`reports/README.md`, `reports/bsd-europa-audit.json`, `reports/bsd-europa-audit.log`, `reports/bsd-europa-audit.run_id`

**tools/**

`tools/__init__.py`, `tools/bsd_europa_audit.py`


## Atualização de compatibilidade — 29/10, 18:35 UTC

Após retoma, main avançou para `bf3bebdc19597a725fb737fd584a2963d0de9355` (árvore `96a34c9861cc322a3a14c2bf7e745e6d4b1b071c`). As PRs são preparadas SOBRE ESTE SHA; a auditoria inicial acima mantém o seu corte independente. Novos ficheiros strategy_notify, preview e ligação de padrões foram inspecionados como delta; as mudanças existentes de renderChronology/renderProspective, timeout de fetch e filtro de cronologia foram preservadas no merge local. Nenhum alerta foi enviado.

Nova fotografia: **513 = 167 FINAL + 190 FUTURE + 29 GRACE + 127 vencidos** (89 sem evidência efetiva, 38 cooldown). Cobertura 32,55% global e 56,80% de FINAL+vencidos. FT last_updated_at 18:25:22. Health offline às 18:35:28: FT/journal/H1 replay/collector/research/watch/V4 OK nos checks específicos; H1 result activity STALE com 235,46 minutos (último check 14:40). Portanto a lacuna inicial não significa que nunca voltou a correr: houve atividade às 14:40, novamente envelhecida neste corte.

F06 refere o notifier legado no baseline. A main passou a strategy_notify (cinco estratégias, janela 12h); a inspeção do novo `process/run` mostra que envio continua anterior à escrita local e push, pelo que o risco de perda de recibo entre envio e persistência continua aplicável. Não se alterou esse subsistema protegido.

Validação de compatibilidade: 702 testes Python passaram antes do último teste adicional de saúde; 23 testes Node passaram (contratos, dashboard, ligação de padrões, Worker). Nova regressão sintética comprova resultado antigo com collector fresco sem rede. Resultados finais por PR e CI constam das descrições das PRs. Não interpretar estes testes como observação operacional das correções: ainda não foram integradas.
