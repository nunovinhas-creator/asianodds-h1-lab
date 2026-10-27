# UNDER TESTE — ponto de situação e passagem de trabalho para o Claude

**Atualizado:** 2026-10-27, ~20:32 UTC. Este é um **instantâneo** de auditoria: ler novamente a `main`, as Actions e os JSON atuais antes de alterar código.

**Repositório:** https://github.com/nunovinhas-creator/asianodds-h1-lab

## 1. Regra absoluta: H1 em produção é intocável

O H1 original recolhe alertas via Telegram/Telethon, escolhe primeiro sinal H1 por jogo, forma triplas FIFO, notifica e liquida Under asiáticos via fornecedores disponíveis. Não modificar **sem autorização expressa e PR isolada**:

- `h1lab/core.py`, `h1lab/cli.py`, `h1lab/bot.py`, `h1lab/notify.py`, `h1lab/bsd.py`, `h1lab/results.py`, `h1lab/session.py`;
- `.github/workflows/collect.yml`, `.github/workflows/results.yml`, `scheduler/**`, `data/state.json`, `data/results.csv`, `data/result_audit.json`;
- condições H1, triplas FIFO, política de um sinal por jogo, liquidação, e qualquer entrega Telegram em produção.

**Não parar o cron, não alterar secrets e não fundir uma PR com alterações H1.** O laboratório não cria apostas.

## 2. Componentes existentes e estado

| Área | Localização | Estado e função |
| --- | --- | --- |
| Produção H1 | `h1lab/core.py`, `cli.py`, `notify.py`, `results.py`, `.github/workflows/collect.yml` | Preservar |
| Shadow V4 | `h1lab/market_v4.py`, `h1lab/shadow_formats.py`, `data/lab/markets-*.jsonl`, `formats-*.jsonl` | Recolhe mercados Total, 1X2, AH; não escolhe picks |
| Auditor V4 vs H1 | `h1lab/v4_audit.py`, `scripts/lab_v4_audit.py`, `docs/lab/v4-audit.json`, `data/lab/v4-runchecks.jsonl` | PENDING; dados posteriores ao cutover e logs auditados |
| Golden Set | `h1lab/golden.py`, `scripts/lab_golden.py`, `data/lab/golden/{reviews,corroborations,attestations}`, `docs/lab/golden-report.json` | Revisão humana por mensagem; global NOT_CERTIFIED |
| Prioridades de revisão | `h1lab/golden_priority.py`, `scripts/lab_golden_priority.py`, `docs/lab/golden-priority.json` | Ordena casos reais sem pré-preencher odds |
| Site LAB | `docs/golden-review.html`, `docs/lab-v4-audit.html` | Separado do dashboard H1 `docs/index.html` |
| Cronologia por jogo | **Ainda só existe no pacote local anexo**: `market_timeline_lab/scripts/lab_match_trajectories.py`, `tests/test_trajectories.py` | **Não integrado**; 5 testes locais, sem teste de integração Actions |

### Dados reais verificados neste instantâneo

- O coletor H1 disparou por `workflow_dispatch` às **20:10:52, 20:15:52, 20:20:52, 20:25:52 e 20:30:52 UTC**, com conclusões `success`. O run `40578712731` confirmou `COLLECT_TRIGGER: cloudflare-cron` no log. Isto comprova esses disparos, não uma garantia universal de execução futura 24/7.
- Auditor V4 (relatório de 20:26 UTC): **60/60** mensagens capturadas na janela, zero divergências nas **582 comparações numéricas** disponíveis (108 AH, 108 1X2, 366 Total), **47** runs inspecionados sem marcador de erro V4. Estado **PENDING**.
- Os gates `field_agreement_100=false` e `independent_identity=false` decorrem de **12 alertas no início da janela** sem metadados de proveniência/commit. Não reescrever históricos para fazer os gates passar. Separar o período transitório legado de uma nova janela integral com parser revisto, se fundamentado e documentado.
- `logs_clean_24h=false`, `minimum_evidence=false`, `window_elapsed=false`, `golden_set_verified=false` continuam corretos. Intervalos exatos 95% devem considerar a **mensagem**, estratificada por formato; nunca 18 campos como 18 amostras independentes.
- Quatro mensagens foram transcritas a partir de materiais fornecidos pelo utilizador: `50655` (7/7), `50656` (7/7), `50658` (19/19), `50671` (19/19). **52/52 campos**, mas só `50671` tem declaração explícita de validação de fonte pelo utilizador; as restantes ainda são R1. Um único utilizador que tira fotografia e copia a mesma mensagem **não é dois revisores independentes**.
- As percentagens `1x2 (...%)` do Telegram não seguem necessariamente a variação aritmética simples da odd: guardar como *mostradas*, com fórmula **não verificada**.

## 3. Descoberta nova: repetição e dependência entre alertas

Num levantamento do histórico `data/state.json` em 27/10/2026 encontraram-se **133 alertas, 101 jogos distintos (`match_key`) e 27 jogos repetidos**, responsáveis por **59 alertas**. **Estes números variam** quando o coletor adiciona novos dados.

Sequências reais:
- **Blackpool – Aston Villa U21**: `50588` (Total 3,50→3,75; 12:28:58), `50675` (1X2+AH+Total; 17:48:13), `50681` (Total 3,75→4,00; 18:11:51). O AH no `50675` mudou de −1,75 para −2,00.
- **Dortmund – Werder Bremen**: `50582` (Total 3,25→3,50; 12:01:50), `50685` (1X2+AH+Total; 18:36:11), `50686` (Total 3,50→3,75; 18:36:12). `50685` e `50686` possuem os mesmos seis valores Was/Now da tabela Total, a apenas um segundo de diferença.
- Outros pares potencialmente redundantes: `50649/50650` (Mamelodi Sundowns–Marumo Gallants), `50654/50655` (Braga–Famalicão), `50710/50711` (Real Bedford–Stourbridge), ~2 segundos.
- Estes alertas **nunca devem ser apagados**, mas podem pertencer ao **mesmo movimento de mercado**. Um movimento observado em 1X2 e Total não representa duas oportunidades estatisticamente independentes.
- As tabelas de Total isoladas sem cabeçalho foram associadas a `50582` e `50588` por **compatibilidade numérica com o histórico**, não por prova autónoma de origem. Não certificar identidade com base numa tabela solta.

## 4. Pendências por prioridade

### P0 — integração segura da cronologia sem tocar no H1

O utilizador dispõe de um pacote local `under_teste_cronologia_jogos.zip`. **Pedir esse ZIP como anexo ao Claude se não estiver no workspace dele.** Rever criticamente o código (não integrar sem auditoria), adaptar/colocar `scripts/lab_match_trajectories.py` e `tests/test_trajectories.py` no projeto, excluir `__pycache__`, `.pyc`, temporários e fontes privadas.

Requisitos:
1. `match_key` como identidade estável; `event_id` e `observed_at` preservados em cronologia; ordenar por UTC validado.
2. Separar **mensagem**, **snapshot**, **movimento** e **jogo**. Possível redundância exige mesmo jogo, seis células do Total iguais e proximidade temporal configurável (ex. 120 s), mas continua só uma suspeita, não deduplicação destrutiva.
3. Diferenciar `V4_EXPLICIT` e `H1_LEGACY_ONLY`; proibir contagem de dados herdados como validação independente; reportar conflitos de identidade/horário.
4. Registar continuidade da *linha*, lacunas ou reversões; **não** inferir preços intermédios entre alertas ou resultados.
5. Somente artefactos em `docs/lab/`, com tamanho limitado, transparência de amostragem, sem credenciais/dados pessoais/texto Telegram.
6. Integrar no workflow **Lab**, com testes unitários + teste sobre dados reais e comparação de métricas; nunca bloquear `collect.yml`/H1. Documentar permissão, race conditions e retries de publicação.

### P1 — referências reais pendentes do Golden Set

Adicionar, numa PR separada e com proveniência honesta, as transcrições partilhadas nesta conversa para:
- `50675` Blackpool 1X2/AH/Total (19 campos),
- `50681` Blackpool Total (7 campos),
- `50685` Dortmund 1X2/AH/Total (19 campos),
- `50686` Dortmund Total (7 campos).

**Não inventar SHA-256** do texto ou da imagem. Se não houver acesso aos textos originais exatos no ambiente Claude, requerer que o utilizador forneça/cole novamente, ou aproveitar transcrições verificáveis disponibilizadas por ficheiro de passagem. Não criar `R2` ou declaração do utilizador que ele ainda não fez. Comparar referências manualmente com os valores atuais V4 e registar diferenças, sem autopreencher valores esperados a partir do V4.

### P2 — auditoria e documentação

- Rever `README.md` (ainda indica que Cloudflare Cron está por ativar, apesar do log `COLLECT_TRIGGER: cloudflare-cron` comprovado no run citado). Atualizar apenas após ler Actions atuais.
- `docs/lab/quality.json` aparece com geração antiga de **16:11 UTC**; não apresentar como estado de saúde atual. Decidir se se atualiza, se se marca **histórico** ou se se retira do menu, sem tocar no H1.
- `docs/MARKET-INTELLIGENCE.md` descreve protótipos V1/V2 e pode confundir com V4/Golden. Criar mapa canónico de arquitetura com responsabilidades e estados; não apagar dados históricos ou protótipos antes de verificar dependências.
- Manter `status=NOT_CERTIFIED` até existir evidência humana suficiente, distinção de origem de campos, amostra representativa e validação temporal fora da amostra.
- Não usar ROI/EV/padrões lucrativos até existir desenho experimental auditável, amostragem por jogo e liquidação FT fiável.

## 5. Entrega pretendida do Claude

Trabalhar no repositório através de **branches específicas e PRs pequenas**, sem alterações em produção H1. Fazer inventário read-only antes da primeira modificação e guardar commits iniciais.

Entregar, por PR:
- diffs e testes reproduzíveis;
- resultados de Actions, dados reais vs fixtures e limitações;
- evidência de que ficheiros H1 protegidos não mudaram;
- artefactos de diagnóstico `docs/lab/match-trajectories.json` com `status` explícito e sem duplicação estatística;
- documentação concisa do modelo de dados, da estratégia de amostragem e de critérios de aceitação.

**Não declarar trabalho integrado antes de merge comprovado; não declarar `PASS` estatístico com dados apenas de sombra.** Se qualquer teste ou difusão para H1 falhar, interromper o merge e corrigir.
