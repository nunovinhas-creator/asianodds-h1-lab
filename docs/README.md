# Documentação UNDER TESTE — índice e estado

**Referência viva:** [README principal](../README.md) · [Dashboard](https://nunovinhas-creator.github.io/asianodds-h1-lab/index.html). **Estado técnico:** usar o código na main e os JSON publicados; valores de relatórios com data são fotografias históricas, não indicadores de hoje.

## Documentos canónicos e operacionais

| Documento | Função / estado |
| --- | --- |
| [Cérebro V5 — como cruza odds, mercados e resultados](lab/CEREBRO-ODDS.md) | **Guia principal do cérebro**, distingue pesquisa de apostas H1 |
| [Arquitetura canónica](lab/ARCHITECTURE.md) | **Mapa atual** H1, V4, V5, fornecedores, agendamentos, dashboard |
| [Motor V5 — especificação](lab/PATTERN-ENGINE.md) | Padrões, hipóteses, estatística, OOS, registo append-only |
| [FT de todos os jogos](lab/ALL-OBSERVED-FT.md) | Ledger de resultados do LAB, identidade, estados, fontes e ponte com H1 |
| [Cronologia por jogo](lab/TIMELINE.md) | Alertas, episódios, direções e movimentos não observados |
| [Golden Set V4](lab/GOLDEN-REVIEW.md) | Validação humana e regras de certificação; ainda não certificado |
| [Dimensões de qualidade V4](lab/QUALITY-DIMENSIONS.md) | Gates e separação de exatidão, cobertura e concordância |
| [Auditoria BSD Europa 30](../reports/README.md) | Registo histórico de 27/10/2026; 26/30 no ensaio; workflow apenas manual |
| [Agendamento Cloudflare](../scheduler/README.md) | Configuração do cron H1 e limites de confirmação em produção |

## Relatórios públicos (gerados automaticamente)

| Relatório | Leitura |
| --- | --- |
| [H1 — singles, triplas e ROI](data.json) | Fonte do dashboard de produção, inclui só liquidados no ROI |
| [V4 vs H1](lab/v4-audit.json) | Gates de auditoria; PENDING até evidência de certificação |
| [Golden Set](lab/golden-report.json) | Revisões, conflitos e estado NOT_CERTIFIED |
| [Cronologia](lab/match-trajectories.json) | Trajetórias agrupadas por jogo |
| [Todos os resultados FT do LAB](lab/ft-results.json) | Cobertura FT por jogo, fontes, futuros e atrasados |
| [Cérebro V5 — hipóteses e testes](lab/pattern-research.json) | Estados EXPLORATORIO/CANDIDATO/etc., combinações, FT e similaridade |
| [Auditoria histórica BSD](../reports/bsd-europa-audit.json) | Amostra da cobertura BSD, não dados de jogo em tempo real |

## Históricos e documentos de fases anteriores

Conservam evidência, desenho original e decisões anteriores, mas **não devem ser interpretados como o estado corrente**. Ver os cabeçalhos de atualização:

- [Market Intelligence V1/V2](MARKET-INTELLIGENCE.md) — protótipos desativados, não o V5;
- [Handoff de 27/10/2026](lab/CLAUDE-HANDOFF-2026-10-27.md) — instantâneo anterior à ponte FT e ao V5 consolidado;
- [Prioridade cobertura FT V3](lab/FT-COVERAGE-PRIORITY.md) — baseline anterior à recuperação de outubro;
- [Prontidão Outcome](lab/OUTCOME-READINESS.md) — estudo preparatório anterior ao V5 com ligação FT;
- [Repetição das odds — estudo descritivo](lab/REPEATED-ODDS-EMPIRICAL.md) — não é backtest com resultados;
- [API-Football V10](lab/API-FOOTBALL-V10.md), [GOAL/OpenFoot V11](lab/GOAL-OPENFOOT-FT-V11.md), [FotMob V9](lab/FOTMOB-FT-V9.md), [BSD por data](lab/BSD-DATE-SEARCH.md), [SportScore FT](lab/SPORTSCORE-FT.md), [identidade e fontes](lab/SOURCE-ORDER-INTEGRITY.md) — decisões técnicas de integração, sujeitas ao código atual.

**Princípio comum:** o LAB investiga e valida; não substitui a regra H1 nem passa hipóteses ao Telegram. A única transferência LAB → H1 é o **resultado FT FINAL verificável** de jogos já registados. Nenhum relatório isolado prova vantagem estatística ou ROI real.
