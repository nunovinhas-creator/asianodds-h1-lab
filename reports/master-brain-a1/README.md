# MASTER BRAIN — P1 A1, diagnóstico somente de leitura

Estado: **incompleto para aceitação científica**. O diagnóstico reproduz a cobertura publicada e os 420 eventos FT, mas a reconciliação independente de todos os recibos por jogo e o histórico commit a commit continuam pendentes. Não desbloqueia C/D, gates, treino, resultados ou promoção. B1 permanece uma fase separada.

Fonte: commit `9d52a5bbf03d9301a6a3479b0e9c95e01945388c`, árvore `afa73947f4f509ec6e0b63e7d309cf025cfd6df7`. Relógio P0: `2026-11-06T10:42:04+00:00`; readiness publicada às `10:41:41+00:00`. A janela é móvel de sete dias, conforme o cálculo existente, e atravessa oito datas UTC.

## Evidência reproduzida

- **992/1030 = 96,3106796%**, 38 lacunas. O enunciado anterior tinha 991/1029; não foi usado como constante nem corrigido artificialmente. Gate permanece abaixo de 99%.
- **34** jogos: primeiro registo do coletor no kickoff ou depois. Isso não distingue atraso de transmissão, indisponibilidade do coletor, ou observação/publicação tardia; não atribuir causa sem recibos.
- **4** jogos: registo do coletor pré-kickoff, sem freeze canónico. Não contar como capturados nem reconstruir valores.
- **420 eventos FT**: 360 consistentes sem certificação independente, 60 inválidos. Auditoria adicional usa o SHA exato referenciado pelo evento, preservando revisões e distinguindo eventos de jogos.
- Falhas FT: 52 `NOT_REGISTERED_PREKICKOFF`, 9 `NO_POST_90MIN_FT_CHECK`, 9 `FT_INGEST_BEFORE_CHECK_OR_FREEZE`. Os dois últimos códigos pertencem aos mesmos nove eventos; um desses também está nos 52. União: 60, não 70.
- Observadas 2010 forecasts, 420 eventos de evidência e **2491 revisões V4**; o P0 publicado declara 2490 revisões. Esta diferença de frescura é exposta, não apagada. O bloco FT publicado reproduz integralmente.

| Mercado observado pré-jogo | Cobertura da fonte | Percentagem |
| --- | ---: | ---: |
| Total | 992/1030 | 96,31% |
| AH | 433/449 | 96,44% |
| 1X2 | 418/434 | 96,31% |

Os denominadores por mercado sobrepõem-se: cada jogo conta uma vez em cada mercado observado. Não são cobertura de todas as fixtures, nem garantia de preço utilizável, freeze específico do mercado ou chegada atempada. As percentagens por competição e todas as entradas bloqueadas estão no JSON.

## Ficheiros de prova

- `snapshot-9d52a5bb.json.gz`: manifesto SHA-256 de cada input, 1030 jogos da janela, 38 lacunas com recibos de revisão, exclusões de identidade, percentagens por mercado/competição, todos os 420 eventos FT com tempos e razões.
- `run-receipt-excerpts.json`: excertos independentes dos jobs GitHub, IDs, URLs e recibos de publicação. Evidência parcial, sem certificação automática por jogo.
- `validation.json`: comandos, resultados e isolamento, registados separadamente do snapshot imutável.

Os 360 eventos consistentes mantêm `independently_proven_provider_checked_at=null`. O `ft_checked_at` copiado do ledger e o `written_at` do journal aparecem em campos distintos. Todos os jogos/eventos têm `training_or_result_eligible=false`; nenhuma quarentena é exportada para treino ou scoring. Zero chamadas LLM, zero neurons, zero chamadas a fornecedores, zero promoções.

## Reconciliação parcial dos runs

Para Guabirá–Bolívar (`2026-11-01,37949,1617`), a revisão fixa o primeiro registo às 20:51:05, antes do kickoff 21:15. O [LAB 41348970219](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41348970219) gerou cinco forecasts localmente às 20:51:26 e falhou a publicação: `Publication blocked; producers not successful: trajectory`. O run não lista os cinco jogos; isto prova a falha do ciclo, **não** que esse jogo específico foi um dos cinco. Mantém-se a lacuna e a causa por jogo pendente.

Nos casos de 6 de novembro, a presença de `known_at` pré-kickoff no journal final não comprova disponibilidade desse registo em main naquele instante. O [coletor 42185835029](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42185835029) recusou publicar por `Fixture identity rewritten in collector state`; `published_commit=null`. O [LAB 42185669354](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42185669354) publicou a partir de um checkpoint anterior. O [LAB 42190831669](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42190831669), embora verde, terminou com `SUPERSEDED_BY_NEWER_INPUTS`, sem publicação. **Conclusão do workflow não equivale a recibo de publicação.** Não extrapolar estes runs para todas as lacunas.

## Reprodução offline

Num checkout do SHA fonte, aplicar apenas o script e os testes desta PR:

```sh
python -m unittest tests.test_master_brain_a1_audit tests.test_v6_readiness tests.test_v6_p0_gates tests.test_v6_shadow tests.test_v4_revisions -v
python -m scripts.master_brain_a1_audit --root . \
  --source-sha 9d52a5bbf03d9301a6a3479b0e9c95e01945388c \
  --output /tmp/master-brain-a1-new.json
python -m unittest discover -s tests -v
git diff --exit-code -- h1lab/ data/ docs/ config/ .github/ scheduler/
```

O script não cria registos de hipóteses, não faz append e recusa sobrescrever outputs existentes. Dentro do repositório aceita output apenas em `reports/master-brain-a1/`. Falha fechado se faltarem streams, se uma cadeia estiver alterada, se houver erros de identidade/tempo na montagem das timelines, se a readiness publicada não reproduzir ou se os inputs mudarem durante a execução. A origem SHA dos bytes hidratados foi verificada contra os blobs GitHub.

## Trabalho ainda necessário

Reconciliar os 38 jogos com os respetivos checkpoints publicados e os runs anteriores/posteriores, incluindo commits e recibos originais; atribuir causas apenas onde demonstráveis. Completar a auditoria histórica de todas as cadeias e a prova temporal independente FT. O script conserva categorias distintas para ausência de recibo, ausência de evidência pré-jogo, conflitos de identidade/kickoff, desalinhamento e registo tardio; categorias com zero casos não são preenchidas artificialmente.

Merge só com autorização explícita. Os dois ciclos reais H1/E5 com recibos e verificação de duplicações/regressões são uma obrigação **pós-merge** e permanecem pendentes. B1 deve adicionar o quality gate científico separadamente, mantendo os três planos antigos; C depende de B1 e da auditoria, D de evidência OOS. Esta A1 não modifica os motores, as fontes, as regras E5, Telegram, FT, cursor, Pages ou workflows.

## Lista das 38 lacunas

`TARDIO` = primeiro registo do coletor no kickoff ou depois; `SEM_FREEZE` = registo pré-kickoff sem freeze. São classificações de evidência, não causas certificadas. Timestamps em UTC.

| Match key | Jogo | Kickoff | Primeiro registo do coletor | Classe |
| --- | --- | --- | --- | --- |
| 2026-10-31,10004939,10004944 | Panathinaikos FC U19 vs AEK Athens FC U19 | 2026-10-31T13:00:00+00:00 | 2026-10-31T13:01:05+00:00 | TARDIO |
| 2026-10-31,10049204,10059948 | Shijiazhuang Gongfu vs Guangdong GZ-Power FC | 2026-10-31T06:30:00+00:00 | 2026-10-31T06:31:08+00:00 | TARDIO |
| 2026-10-31,10071606,10060048 | Guangzhou Dandelion Alpha FC vs Changchun Xidu | 2026-10-31T06:30:00+00:00 | 2026-10-31T06:31:08+00:00 | TARDIO |
| 2026-10-31,10071607,10071617 | Wenzhou FC vs Shanghai Second | 2026-10-31T06:30:00+00:00 | 2026-10-31T06:31:08+00:00 | TARDIO |
| 2026-10-31,10094123,10071611 | Dalian Yingbo II vs Guangdong Mingtu | 2026-10-31T06:30:00+00:00 | 2026-10-31T06:31:08+00:00 | TARDIO |
| 2026-10-31,1047,193 | Augsburg vs SC Freiburg | 2026-10-31T14:30:00+00:00 | 2026-10-31T14:36:05+00:00 | TARDIO |
| 2026-10-31,1402,30632 | Stord Sunnhordland FK vs Sogndal IL II | 2026-10-31T13:00:00+00:00 | 2026-10-31T13:01:05+00:00 | TARDIO |
| 2026-10-31,23677,28374 | Gyeongnam FC vs Hwasung Shinwoo Electronics FC | 2026-10-31T05:00:00+00:00 | 2026-10-31T05:01:04+00:00 | TARDIO |
| 2026-10-31,30201,27516 | CA Acassuso vs Club Ferro Carril Oeste | 2026-10-31T18:00:00+00:00 | 2026-10-31T18:06:05+00:00 | TARDIO |
| 2026-10-31,36607,10022956 | CD Morón vs Club Ciudad de Bolivar | 2026-10-31T19:00:00+00:00 | 2026-10-31T19:01:07+00:00 | TARDIO |
| 2026-10-31,50488,10004041 | Polokwane City FC vs TS Galaxy FC | 2026-10-31T16:00:00+00:00 | 2026-10-31T16:01:05+00:00 | TARDIO |
| 2026-10-31,554,30207 | Colón de Santa Fe vs CA Defensores Belgrano | 2026-10-31T21:00:00+00:00 | 2026-10-31T21:01:10+00:00 | TARDIO |
| 2026-10-31,679,30679 | Skeid Fotball vs Stjørdals-Blink | 2026-10-31T12:00:00+00:00 | 2026-10-31T12:01:07+00:00 | TARDIO |
| 2026-11-01,101449,10105973 | UD Logrones U19 vs Arratia U19 | 2026-11-01T15:30:00+00:00 | 2026-11-01T15:31:04+00:00 | TARDIO |
| 2026-11-01,24581,27678 | FC Zenit Caslav vs SK Slovan Varnsdorf | 2026-11-01T13:00:00+00:00 | 2026-11-01T13:06:06+00:00 | TARDIO |
| 2026-11-01,27452,66595 | Inter Club d'Escaldes vs Penya Encarnada d'Andorra | 2026-11-01T16:00:00+00:00 | 2026-11-01T16:01:06+00:00 | TARDIO |
| 2026-11-01,37949,1617 | Guabira vs Club Bolívar | 2026-11-01T21:15:00+00:00 | 2026-11-01T20:51:05+00:00 | SEM_FREEZE |
| 2026-11-01,48538,1623 | Montego Bay United vs Portmore United FC | 2026-11-01T20:00:00+00:00 | 2026-11-01T20:01:10+00:00 | TARDIO |
| 2026-11-01,93884,28736 | FC Spartak Velka Bites vs FC Dosta Bystrc-Knínicky | 2026-11-01T13:00:00+00:00 | 2026-11-01T13:06:06+00:00 | TARDIO |
| 2026-11-02,30205,30219 | Club Comunicaciones vs CA Talleres Remedios Escalada | 2026-11-02T18:00:00+00:00 | 2026-11-02T18:01:10+00:00 | TARDIO |
| 2026-11-02,85974,85692 | Coleraine FC U20 vs Ballymena United FC U20 | 2026-11-02T20:00:00+00:00 | 2026-11-02T20:01:08+00:00 | TARDIO |
| 2026-11-03,10062187,26745 | Dejan FC vs PSM Makassar | 2026-11-03T09:00:00+00:00 | 2026-11-03T09:01:07+00:00 | TARDIO |
| 2026-11-03,49893,27612 | Atletico Madrid U19 vs FC Bayern München U19 | 2026-11-03T15:00:00+00:00 | 2026-11-03T15:01:22+00:00 | TARDIO |
| 2026-11-04,49032,40541 | Aberdeen FC Women vs Spartans FC Women | 2026-11-04T19:45:00+00:00 | 2026-11-04T19:46:13+00:00 | TARDIO |
| 2026-11-04,51135,67154 | FK Crvena Zvezda U19 vs NK Bravo U19 | 2026-11-04T13:00:00+00:00 | 2026-11-04T13:21:11+00:00 | TARDIO |
| 2026-11-04,86126,33801 | Kataka FC vs Uganda Revenue Authority SC | 2026-11-04T13:00:00+00:00 | 2026-11-04T13:21:11+00:00 | TARDIO |
| 2026-11-05,10038271,29842 | Genesis Huracan vs Real CD España | 2026-11-05T21:00:00+00:00 | 2026-11-06T08:09:19+00:00 | TARDIO |
| 2026-11-05,10103324,97238 | Atlante Women vs Tigres UANL Women | 2026-11-05T21:45:00+00:00 | 2026-11-06T08:09:19+00:00 | TARDIO |
| 2026-11-05,540,1626 | Celta Vigo vs Royale Union Saint-Gilloise | 2026-11-05T20:00:00+00:00 | 2026-11-06T08:09:19+00:00 | TARDIO |
| 2026-11-05,66859,33773 | NAPSA Stars vs Power Dynamos FC | 2026-11-05T13:00:00+00:00 | 2026-11-05T13:01:12+00:00 | TARDIO |
| 2026-11-05,709,25971 | SE Palmeiras (SP) vs CD Remo (PA) | 2026-11-05T22:30:00+00:00 | 2026-11-06T08:09:19+00:00 | TARDIO |
| 2026-11-06,10018602,58010 | Hapoel Ironi Karmiel vs Hapoel Ironi Baka El Garbiya | 2026-11-06T08:30:00+00:00 | 2026-11-06T08:09:19+00:00 | SEM_FREEZE |
| 2026-11-06,10074327,10009985 | USM Alger Women vs FC Bejaia Women | 2026-11-06T09:00:00+00:00 | 2026-11-06T08:50:54+00:00 | SEM_FREEZE |
| 2026-11-06,10077319,53546 | Libertad de San Carlos vs CA Torque | 2026-11-06T00:00:00+00:00 | 2026-11-06T08:09:19+00:00 | TARDIO |
| 2026-11-06,26730,10041436 | PSIM Yogyakarta vs Dewa United | 2026-11-06T08:30:00+00:00 | 2026-11-06T08:09:19+00:00 | SEM_FREEZE |
| 2026-11-06,29839,29841 | CD Marathón vs CD Platense | 2026-11-06T01:30:00+00:00 | 2026-11-06T08:09:19+00:00 | TARDIO |
| 2026-11-06,32264,10047372 | Adelaide United Women vs Wellington Phoenix Women | 2026-11-06T08:00:00+00:00 | 2026-11-06T08:09:19+00:00 | TARDIO |
| 2026-11-06,32837,10006605 | Arnett Gardens FC vs Mount Pleasant FA | 2026-11-06T00:00:00+00:00 | 2026-11-06T08:09:19+00:00 | TARDIO |

## Validação local final

48 testes direcionados passaram. A suite completa executou 1903 testes em 372,712 s: 3 falhas, 30 erros, 4 skips. Há fixtures ainda ausentes, Telethon indisponível e quatro testes HTTP locais impedidos de criar sockets; três asserções de integração existentes também falharam. Não foi estabelecida equivalência dessas falhas com a baseline. CI permanece por executar. O teste de isolamento verificou 353 ficheiros protegidos byte a byte e passou.

O upload para GitHub foi rejeitado pela revisão automática por exigir autorização explícita para publicar o novo código nesse repositório público. O branch existe no SHA fonte; não há código enviado, PR criada ou merge.
