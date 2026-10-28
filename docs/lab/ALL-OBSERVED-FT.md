> **Atualização 28/10/2026:** o LAB já utiliza BSD, TheSportsDB e fornecedores complementares (ESPN, SportScore com salvaguardas, API-Football, GOAL, OpenFoot e evidência documental específica), com quotas e verificações por jogo; `FINAL` não equivale a certificação estatística. FotMob só sob autorização apropriada. Na fotografia do ficheiro [ft-results.json](ft-results.json) às 11:15 UTC: 267 jogos observados, **63 FT**, 204 sem FT (169 futuros, 24 ainda na margem de 3 h, 11 no cooldown). **A ponte [lab_promotion.py](../../h1lab/lab_promotion.py) foi integrada na PR #53** e importa FT FINAL com identidade/proveniência estrita para liquidar H1 já existente, sem tocar na seleção H1. Este documento nasceu na fase inicial de dois fornecedores; as listas antigas abaixo são históricas. Ver [arquitetura canónica](ARCHITECTURE.md) e [cérebro V5](CEREBRO-ODDS.md).

# LAB — resultados FT de TODOS os jogos observados

**Objetivo:** desligar a cobertura de resultados FT da seleção de sinais H1, sem modificar o H1 nem criar prognósticos/apostas.

## Fontes e universo
- `data/state.json → alerts` **todos** os alertas, incluindo `h1=false`. A chave primária é `match_key`, um jogo = uma observação estatística, por mais mensagens que existam.
- `data/lab/markets-AAAA-MM.jsonl` acrescenta eventuais jogos V4 que não estejam no H1. Como o registo V4 não contém nomes de equipas, esses casos ficam `INSUFFICIENT_IDENTITY` até existir correspondência verificável. **Não deduzir equipas pelos IDs.**
- A hora de início e as equipas têm de ser coerentes entre os alertas. Se discordarem, `IDENTITY_CONFLICT` e sem consulta automática.
- **Nenhum jogo é excluído por não ter sinal H1.** Jogos repetidos continuam um único `match_key`.

## Provedores e liquidação
- O LAB chama as funções de validação existentes `h1lab.bsd.find_result` e `h1lab.results.api_events / choose_result` apenas como funções de leitura: não executa `sync()`, `save()`, `write_rows()` ou envio Telegram.
- Reutiliza `BSD_API_KEY` já configurado em Secrets, se disponível. Sem a chave, a BSD fica marcada como indisponível por configuração e a TheSportsDB continua a ser tentada.
- Cada fornecedor valida nomes ordenados casa/fora, hora, jogo terminado, resultado regulamentar 90'+descontos, marcador inteiro e ausência de prolongamento/penáltis ambíguos. Não basta encontrar um jogo com nome parecido.
- Duas fontes válidas e mesmo marcador → `bsd_and_thesportsdb`. Uma fonte válida apenas → `bsd_only` ou `thesportsdb_only`. **Duas fontes com marcadores diferentes → `SCORE_CONFLICT`, nunca FINAL.**
- Sem resultado, identidade ambígua ou resposta inválida → pendente/erro; **nunca derrota ou ausência de golos**.

## Execução autónoma
- Workflow: `Lab - Reconcile FT for all observed matches` em `.github/workflows/lab-ft-results.yml`, com cron `23 */2 * * *` (de duas em duas horas, sujeito a atrasos GitHub), botão manual `Run workflow` e execução após merge de código na `main`.
- Só após início + 3 horas, e até + 30 dias. Tentativas espaçadas pelo menos 4 horas por jogo.
- Máximo 20 jogos consultados por run por omissão (variável opcional `LAB_RESULTS_MAX_CHECKS`, máximo absoluto 30). Ordem por menor `checked_at`, com desempate pelo início do jogo e chave. Duas fontes, sendo a BSD opcional. Não assume cobertura integral num único run.
- Mutex exclusivo `asianodds-lab-ft-results` — não utiliza `asianodds-h1-write` nem `asianodds-lab-v4-audit`.
- Saídas: `data/lab/ft-ledger.json` (persistência individual, estados e proveniência) e `docs/lab/ft-results.json` (resumo + no máximo 500 jogos recentes); UI `docs/lab-results.html`. Tudo apenas no LAB.
- Commits somente se os ficheiros mudarem; rebase/push com cinco tentativas. Não imprime URLs de consultas, exceções remotas nem tokens em logs.
- A página pública lê unicamente `docs/lab/ft-results.json`, **não** a conta Telegram. Não guarda mensagens integrais nem credenciais.

## Testes e estados
`python -m unittest discover -s tests -p 'test_lab_results.py' -v` testa não-H1, V4 sem identidade, janela temporal, duas fontes, conflitos, segurança dos erros, dados inválidos, repetição, retry, limite por execução, expiração e universo real sem consultas HTTP.

`FINAL` significa apenas *resultado FT registado com uma ou duas fontes*, não certificação estatística do parser V4. `PENDING`, `PROVIDER_ERROR`, `SCORE_CONFLICT`, `IDENTITY_CONFLICT`, `INSUFFICIENT_IDENTITY` e `EXPIRED_UNVERIFIED` não entram como resultados apurados.

**Sem EV, ROI, GREEN/RED, apostas ou verificação de estratégias nesta fase.** A análise de reversões vs resultados requer pré-registo, cobertura suficiente, identidade robusta, limites de confiança e amostra fora do período de descoberta. A recolha do canal é seletiva (não contínua).

## Separação do H1 e exceção controlada — atualização 28/10/2026

Os módulos de **seleção H1** (`core.py`, `cli.py`, `bot.py`, `notify.py`, `session.py`), os alertas existentes e o cron continuam independentes do laboratório. **A integração de FT não é uma alteração de estratégias**.

A partir da PR #53, `results.yml` executa `h1lab/lab_promotion.py` após a sua procura direta de FT. Este adaptador importa para `data/results.csv` **apenas** resultados `FINAL` do LAB que coincidam rigorosamente com um sinal H1 (identidade, hora, marcador e fonte válida), preservando sem alterações quaisquer resultados previamente confirmados pelo H1. `data/result_audit.json` recebe a proveniência; `docs/data.json` volta a calcular o ROI H1 original. Portanto, os documentos de versões antigas que dizem que `results.yml` e `data/results.csv` «não são tocados» descrevem uma fase anterior e não o estado atual.

Consultar [arquitetura](ARCHITECTURE.md), [motor V5](CEREBRO-ODDS.md) e [relatório FT](ft-results.json); os resultados e as hipóteses de padrões têm níveis de validação distintos.
