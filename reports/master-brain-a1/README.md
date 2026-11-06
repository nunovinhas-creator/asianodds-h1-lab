# MASTER BRAIN — A1: relatório para revisão independente

Relacionada com a issue [#256](https://github.com/nunovinhas-creator/asianodds-h1-lab/issues/256) e PR Draft [#257](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/257). Sem merge. Apenas diagnóstico de leitura; sem alteração de produção, gates, fontes, históricos, alertas ou autonomia.

## Correções obrigatórias da revisão da PR #257

Esta entrega responde aos [dois bloqueadores da revisão independente](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/257#issuecomment-6684517832). Código e testes corrigidos no commit `be67062ba113c280de6abbf0c0d3a26446fabe34`. As provas novas estão em `validation.json`, na chave `pr257_review_corrections`; as provas anteriores abaixo são preservadas como histórico.

**Origem Git, prioridade alta:** a auditoria exige um checkout Git local correto. Lê o objeto commit, percorre as árvores, recalcula os IDs dos objetos e compara o inventário e os bytes de todos os inputs com os blobs originais. São verificados os quatro ficheiros fixos, todas as partições dos quatro streams consumidos e todos os recibos de incidente. No commit original são **13 inputs, 17 845 028 bytes**, ancorados na árvore `afa73947f4f509ec6e0b63e7d309cf025cfd6df7`. O inventário e os conteúdos são verificados novamente antes do retorno. Só depois destas verificações pode existir `source_commit_verified=true`.

A verificação ignora overrides Git do chamador e objetos de substituição, desativa locks opcionais e lazy fetch, não usa o index/mtime como prova e não consulta serviços de rede. Commits inexistentes, commits cujo inventário/conteúdo difere, inputs modificados/ausentes/adicionais, symlinks e objetos necessários indisponíveis ou corrompidos bloqueiam a execução. Um commit diferente que contenha exatamente os mesmos inputs continua a ser uma origem válida desses bytes; a prova é de pertença ao commit declarado, não de identidade entre HEAD e esse commit. Objetos sem checkout correto ou um snapshot JSON isolado não substituem esta prova.

**Cronologia FT, prioridade média:** a função `ft_chronology` é reproduzida ao relógio publicado do P0 (`2026-11-06T10:42:04+00:00`). Qualquer diferença levanta `ValueError` antes de criar o diretório de saída ou escrever relatório. `--as-of` pode alterar o relógio da análise solicitada, mas não contorna a reconciliação independente ao relógio publicado, registado em `ft_published_replay_clock`.

**Testes adversariais:** 29 testes A1 direcionados passaram. Os testes usam repositórios Git locais reais e adulteram cada input, retiram objetos commit/árvore/blob, corrompem um blob, introduzem inputs adicionais, objetos de substituição, symlink e um clone parcial com blob disponível no remoto: a verificação recusa esse blob ausente sem o buscar. Há testes distintos para uma publicação FT divergente mas legitimamente commitada e para divergência deliberada na função de replay, também com `--as-of`. Todas as rejeições verificam ausência de escrita/criação da saída. O replay real testa ainda um recibo introduzido durante a auditoria, bloqueado pela segunda verificação do inventário.

**Reprodução positiva e negativa real:** o novo CLI executou sobre um checkout descartável integral do commit `9d52a5bbf03d9301a6a3479b0e9c95e01945388c` e confirmou **992/1030 (96,3106796%), 38 lacunas e 420 FT: 360 consistentes não certificados / 60 inválidos**. Todos os campos do snapshot histórico coincidem; só foram acrescentados quatro campos de prova. O JSON novo tem SHA-256 `8bcacfe09f74f5921b67e1147b07fb3fa12a2b42a0b7c1657cbffffadf5c915d`. O gzip original mantém SHA-256 `950a8e095fe03823ab416e72850d46842b8ef58236855e4167ac6d14c021133a`.

Oito rejeições adicionais foram reproduzidas sobre essa cópia real: commit inexistente, commit existente errado (`bd3cdecd94069574c7bc4de08bff2ae74863871a`), estado modificado, estado ausente, mês adicional, recibo adicional, checkout Git ausente e divergência FT simulada. Nenhum caso criou diretório/relatório de saída. Os inputs originais foram repostos e novamente verificados no fim. As mutações adversariais ocorreram apenas em cópias temporárias.

## Validação das correções

Suite integral local: **1932 testes OK, um skip, 363,135 s**. A descoberta dessa execução ocorreu antes de acrescentar o último teste de clone parcial; a versão final tem **29 testes A1 direcionados OK**, sem skips, e foi integralmente descoberta na CI abaixo. Compilação Python, três testes UI e um teste cron também passaram.

| Execução no código `be67062ba113` | Resultado confirmado |
| --- | --- |
| [H1 push 42217183910](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42217183910) | **1933 testes OK, quatro skips, 464,035 s**; checkout do próprio commit |
| [H1 PR 42217191103](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42217191103) | **1933 testes OK, quatro skips, 348,785 s**; merge de teste `d3e46cc341c0b83ca7fd0b774adf54a21236e793` |
| [UI 42217191064](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42217191064) | success |
| [V6 offline 42217191115](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42217191115) | gate/evaluate success, publish skipped |

São **cinco checks success e um publish skipped**, todos completed. Os dois H1 passaram igualmente os passos dry-run E5, paridade Telegram, replay P0/archives/memórias/FT e cron, sem notificações ou promoção. Os hashes SHA-256 dos logs UTF-8 e as conclusões de cada passo constam do JSON de validação.

Os quatro skips da CI são explícitos: root público já paginado, replay A1 sem objeto Git original no checkout raso, e dois testes históricos sem os respetivos commits. O skip A1 não é contado como aprovação do replay original: este passou no clone integral local, tanto nos testes como no CLI separado com prova dos objetos Git. Nenhum skip foi ocultado ou convertido em prova.

**Recomendação atual:** submeter esta correção à **nova verificação independente do Work**. As duas falhas têm testes de rejeição e a reprodução histórica foi preservada; isto fundamenta a nova revisão técnica. A aprovação do Work continua pendente e o merge permanece bloqueado nesta entrega. PR em Draft, sem merge, B1 não iniciada. Nenhum gate científico, dado histórico ou componente de produção foi alterado; nenhum FT foi certificado. Zero chamadas LLM/fornecedor, zero serviços pagos e nenhum fluxo de dinheiro.

## Fotografia auditada e conclusão

Fonte `9d52a5bbf03d9301a6a3479b0e9c95e01945388c`, relógio `2026-11-06T10:42:04+00:00`. O snapshot original comprimido permanece byte a byte intacto (SHA-256 `950a8e095fe03823ab416e72850d46842b8ef58236855e4167ac6d14c021133a`).

**992/1030 = 96,3106796%**, 38 lacunas: 34 primeiros registos no kickoff ou depois e quatro registos pré-jogo sem freeze canónico. Nenhuma percentagem foi corrigida artificialmente. Fonte observável não equivale a ingestão atempada nem a todas as fixtures.

Todas as 38 lacunas foram cruzadas por SHA de revisão com commits/recibos ou com o lote recuperado. A exclusão temporal é demonstrada em 34 casos; a causa anterior do atraso continua **INCONCLUSIVO**. Para dois jogos das 08:30 está demonstrada a recusa do lote e publicação só às 08:49:52. Nos outros dois casos, há falha/supersessão LAB comprovada, mas o vínculo ao forecast não publicado de cada jogo é **INCONCLUSIVO**.

A investigação A1 está documentada para revisão; a aceitação científica e certificação temporal independente **não estão concluídas**. CI técnica não transforma dados em provas científicas.

## Provas anteriores — checks e suite completa em checkout integral

| Run | Ref efetiva | Suite / conclusão |
| --- | --- | --- |
| [H1 push 42209625665](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42209625665) | `f7dee41833d3` | 1919 testes, OK, 3 skips, 403,889 s; replay A1 real passou |
| [H1 PR 42209703327](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42209703327) | merge de teste `a46bd961959d` | 1919 testes, OK, 4 skips, 476,473 s; snapshot A1 avançado foi explicitamente ignorado |
| [UI 42209703349](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42209703349) | PR | success |
| [V6 offline 42209703348](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42209703348) | PR | gate/evaluate success; publish skipped, sem publicação |

GitHub Actions executou checkout integral, instalou `Telethon==1.45.0`, `PyYAML==6.0.2` e dependências transitivas já declaradas, compilou e executou a suite completa. Cinco checks success e um publish skipped no head de código auditado; nenhum check falhou. Os logs têm hashes e links no JSON de recibos. São execuções reais de CI, não a cópia local parcial.

A CI também passou E5 dry-run, recusa dos emissores retirados, paridade Telegram, integridade de archives, replay das cinco memórias, FT, cronologia, radar, monitorização e testes de interface. Não foi enviada notificação experimental. Não se afirma garantia universal de zero regressões: não foram observadas regressões nesses testes e nenhuma superfície protegida foi alterada.

### Três falhas e 30 erros locais — preservados

A1 local: 1903 testes, três falhas, 30 erros, quatro skips. Baseline local sem A1: 1888 testes, mesmas três falhas/30 erros/quatro skips. Os 15 testes novos passaram e o multiconjunto dos cabeçalhos de falhas/erros é idêntico. Isto caracteriza limitações do checkout/ambiente comparado, não bugs demonstrados de produção.

- 24 erros e três asserções: inputs ausentes no checkout parcial. Os 23 métodos afetados passaram em replays após repor 16 ficheiros exatos do SHA fonte, só numa cópia descartável, sem mudar código ou limiares.
- Quatro erros: sockets localhost bloqueados pela sandbox; dois erros: Telethon não instalado no Python local. O runner integral instalou as dependências e executou esses testes.
- 48 testes direcionados passaram localmente. Isolamento: 353 ficheiros protegidos presentes byte a byte iguais após a auditoria. O diff remoto permanece restrito aos seis ficheiros A1.

## Reconciliação por jogo — 38 lacunas

Tabela: **T** = primeiro registo no/após kickoff, exclusão pré-jogo comprovada, causa do atraso INCONCLUSIVO; **R** = lote recusado/recuperado depois do kickoff; **I** = causa do freeze por jogo INCONCLUSIVO. Tempos UTC. O JSON contém os SHAs de revisão, publicações, logs e limitações de cada linha.

| Match key / jogo | Kickoff | Primeiro registo | Publicação comprovada | Classe |
| --- | --- | --- | --- | --- |
| `2026-10-31,10004939,10004944` Panathinaikos FC U19 vs AEK Athens FC U19 | 2026-10-31T13:00:00+00:00 | 2026-10-31T13:01:05+00:00 | [run 41203624027](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41203624027) 2026-10-31T13:01:10.9743211Z | T |
| `2026-10-31,10049204,10059948` Shijiazhuang Gongfu vs Guangdong GZ-Power FC | 2026-10-31T06:30:00+00:00 | 2026-10-31T06:31:08+00:00 | [run 41176920937](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41176920937) 2026-10-31T06:31:12.8291251Z | T |
| `2026-10-31,10071606,10060048` Guangzhou Dandelion Alpha FC vs Changchun Xidu | 2026-10-31T06:30:00+00:00 | 2026-10-31T06:31:08+00:00 | [run 41176920937](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41176920937) 2026-10-31T06:31:12.8291251Z | T |
| `2026-10-31,10071607,10071617` Wenzhou FC vs Shanghai Second | 2026-10-31T06:30:00+00:00 | 2026-10-31T06:31:08+00:00 | [run 41176920937](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41176920937) 2026-10-31T06:31:12.8291251Z | T |
| `2026-10-31,10094123,10071611` Dalian Yingbo II vs Guangdong Mingtu | 2026-10-31T06:30:00+00:00 | 2026-10-31T06:31:08+00:00 | [run 41176920937](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41176920937) 2026-10-31T06:31:12.8291251Z | T |
| `2026-10-31,1047,193` Augsburg vs SC Freiburg | 2026-10-31T14:30:00+00:00 | 2026-10-31T14:36:05+00:00 | [run 41210876872](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41210876872) 2026-10-31T14:36:11.1140734Z | T |
| `2026-10-31,1402,30632` Stord Sunnhordland FK vs Sogndal IL II | 2026-10-31T13:00:00+00:00 | 2026-10-31T13:01:05+00:00 | [run 41203624027](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41203624027) 2026-10-31T13:01:10.9743211Z | T |
| `2026-10-31,23677,28374` Gyeongnam FC vs Hwasung Shinwoo Electronics FC | 2026-10-31T05:00:00+00:00 | 2026-10-31T05:01:04+00:00 | [run 41170848722](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41170848722) 2026-10-31T05:01:10.2099975Z | T |
| `2026-10-31,30201,27516` CA Acassuso vs Club Ferro Carril Oeste | 2026-10-31T18:00:00+00:00 | 2026-10-31T18:06:05+00:00 | [run 41227708980](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41227708980) 2026-10-31T18:06:09.8896617Z | T |
| `2026-10-31,36607,10022956` CD Morón vs Club Ciudad de Bolivar | 2026-10-31T19:00:00+00:00 | 2026-10-31T19:01:07+00:00 | [run 41232154427](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41232154427) 2026-10-31T19:01:12.1852202Z | T |
| `2026-10-31,50488,10004041` Polokwane City FC vs TS Galaxy FC | 2026-10-31T16:00:00+00:00 | 2026-10-31T16:01:05+00:00 | [run 41217576476](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41217576476) 2026-10-31T16:01:09.0421800Z | T |
| `2026-10-31,554,30207` Colón de Santa Fe vs CA Defensores Belgrano | 2026-10-31T21:00:00+00:00 | 2026-10-31T21:01:10+00:00 | [run 41241561021](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41241561021) 2026-10-31T21:01:13.0841762Z | T |
| `2026-10-31,679,30679` Skeid Fotball vs Stjørdals-Blink | 2026-10-31T12:00:00+00:00 | 2026-10-31T12:01:07+00:00 | [run 41199217274](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41199217274) 2026-10-31T12:01:14.8027994Z | T |
| `2026-11-01,101449,10105973` UD Logrones U19 vs Arratia U19 | 2026-11-01T15:30:00+00:00 | 2026-11-01T15:31:04+00:00 | [run 41321600076](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41321600076) 2026-11-01T15:31:07.4962683Z | T |
| `2026-11-01,24581,27678` FC Zenit Caslav vs SK Slovan Varnsdorf | 2026-11-01T13:00:00+00:00 | 2026-11-01T13:06:06+00:00 | [run 41309592043](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41309592043) 2026-11-01T13:06:08.8867577Z | T |
| `2026-11-01,27452,66595` Inter Club d'Escaldes vs Penya Encarnada d'Andorra | 2026-11-01T16:00:00+00:00 | 2026-11-01T16:01:06+00:00 | [run 41324102092](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41324102092) 2026-11-01T16:01:09.0268182Z | T |
| `2026-11-01,37949,1617` Guabira vs Club Bolívar | 2026-11-01T21:15:00+00:00 | 2026-11-01T20:51:05+00:00 | [run 41348939587](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41348939587) 2026-11-01T20:51:07.8714793Z | I |
| `2026-11-01,48538,1623` Montego Bay United vs Portmore United FC | 2026-11-01T20:00:00+00:00 | 2026-11-01T20:01:10+00:00 | [run 41344630176](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41344630176) 2026-11-01T20:01:12.9669474Z | T |
| `2026-11-01,93884,28736` FC Spartak Velka Bites vs FC Dosta Bystrc-Knínicky | 2026-11-01T13:00:00+00:00 | 2026-11-01T13:06:06+00:00 | [run 41309592043](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41309592043) 2026-11-01T13:06:08.8867577Z | T |
| `2026-11-02,30205,30219` Club Comunicaciones vs CA Talleres Remedios Escalada | 2026-11-02T18:00:00+00:00 | 2026-11-02T18:01:10+00:00 | [run 41496514049](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41496514049) 2026-11-02T18:01:15.3201292Z | T |
| `2026-11-02,85974,85692` Coleraine FC U20 vs Ballymena United FC U20 | 2026-11-02T20:00:00+00:00 | 2026-11-02T20:01:08+00:00 | [run 41515246843](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41515246843) 2026-11-02T20:01:12.8368242Z | T |
| `2026-11-03,10062187,26745` Dejan FC vs PSM Makassar | 2026-11-03T09:00:00+00:00 | 2026-11-03T09:01:07+00:00 | [run 41607574976](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41607574976) 2026-11-03T09:01:11.6770867Z | T |
| `2026-11-03,49893,27612` Atletico Madrid U19 vs FC Bayern München U19 | 2026-11-03T15:00:00+00:00 | 2026-11-03T15:01:22+00:00 | [run 41659418767](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41659418767) 2026-11-03T15:01:28.2822456Z | T |
| `2026-11-04,49032,40541` Aberdeen FC Women vs Spartans FC Women | 2026-11-04T19:45:00+00:00 | 2026-11-04T19:46:13+00:00 | [run 41900082376](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41900082376) 2026-11-04T19:46:18.3483544Z | T |
| `2026-11-04,51135,67154` FK Crvena Zvezda U19 vs NK Bravo U19 | 2026-11-04T13:00:00+00:00 | 2026-11-04T13:21:11+00:00 | [run 41837261309](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41837261309) 2026-11-04T13:21:16.8191120Z | T |
| `2026-11-04,86126,33801` Kataka FC vs Uganda Revenue Authority SC | 2026-11-04T13:00:00+00:00 | 2026-11-04T13:21:11+00:00 | [run 41837261309](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41837261309) 2026-11-04T13:21:16.8191120Z | T |
| `2026-11-05,10038271,29842` Genesis Huracan vs Real CD España | 2026-11-05T21:00:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | T |
| `2026-11-05,10103324,97238` Atlante Women vs Tigres UANL Women | 2026-11-05T21:45:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | T |
| `2026-11-05,540,1626` Celta Vigo vs Royale Union Saint-Gilloise | 2026-11-05T20:00:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | T |
| `2026-11-05,66859,33773` NAPSA Stars vs Power Dynamos FC | 2026-11-05T13:00:00+00:00 | 2026-11-05T13:01:12+00:00 | [run 42031996309](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42031996309) 2026-11-05T13:01:18.4490675Z | T |
| `2026-11-05,709,25971` SE Palmeiras (SP) vs CD Remo (PA) | 2026-11-05T22:30:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | T |
| `2026-11-06,10018602,58010` Hapoel Ironi Karmiel vs Hapoel Ironi Baka El Garbiya | 2026-11-06T08:30:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | R |
| `2026-11-06,10074327,10009985` USM Alger Women vs FC Bejaia Women | 2026-11-06T09:00:00+00:00 | 2026-11-06T08:50:54+00:00 | [run 42190570403](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42190570403) 2026-11-06T08:50:59.9649138Z | I |
| `2026-11-06,10077319,53546` Libertad de San Carlos vs CA Torque | 2026-11-06T00:00:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | T |
| `2026-11-06,26730,10041436` PSIM Yogyakarta vs Dewa United | 2026-11-06T08:30:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | R |
| `2026-11-06,29839,29841` CD Marathón vs CD Platense | 2026-11-06T01:30:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | T |
| `2026-11-06,32264,10047372` Adelaide United Women vs Wellington Phoenix Women | 2026-11-06T08:00:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | T |
| `2026-11-06,32837,10006605` Arnett Gardens FC vs Mount Pleasant FA | 2026-11-06T00:00:00+00:00 | 2026-11-06T08:09:19+00:00 | [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) 06/11 08:49:52 | T |

### Quatro registos pré-jogo sem freeze

- **Hapoel Ironi Karmiel e PSIM Yogyakarta:** coleta no [run 42181923012, attempt 2](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42181923012/attempts/2), checkpoint 53130, 61 mensagens; publicação REFUSED por identidade contraditória de outro jogo do lote. Comparação entre blobs `238fada…` e `e78528e…`: 1063 → 1124 linhas, 61 acrescentadas e todas as anteriores mantidas. [PR #254](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/254) merged em 08:49:52; ambos tinham kickoff 08:30. `known_at` retido não prova disponibilidade anterior em main.
- **Guabirá–Bolívar:** revisão publicada às 20:51:07, kickoff 21:15. Cinco runs LAB entre 20:51 e 21:11 falharam `trajectory`; o primeiro mostra `AssertionError: 970 != 974` no teste de coerência da cronologia e o guard recusou publicar. Primeiro LAB publicado às 21:16:49, já após kickoff. Os logs só contam forecasts, não listam o jogo: vínculo por jogo **INCONCLUSIVO**.
- **USM Alger Women–FC Bejaia Women:** revisão publicada pelo [coletor 42190570403](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42190570403) às 08:50:59, kickoff 09:00. [LAB 42190831669](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42190831669) e [42190982027](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42190982027) terminaram `SUPERSEDED_BY_NEWER_INPUTS`, `published_commit=null`; primeiro LAB publicado às 09:02:23. Não há artefactos retornados pela API para os dois runs superseded: forecast por jogo **INCONCLUSIVO**.

## Auditoria FT — 420 eventos, sem certificação automática

**360 consistentes sem certificação temporal independente; 60 inválidos em 59 jogos.** Os 52 eventos `NOT_REGISTERED_PREKICKOFF` têm efetivamente freeze anterior ao registo formal da hipótese em `2026-10-28T14:41:35+00:00`; a falha é anterioridade ao registo, não prova de freeze posterior ao kickoff.

Nove eventos provêm de `H1_RESULTS_CSV` e não têm `ft_checked_at`. Os códigos originais `NO_POST_90MIN_FT_CHECK` e `FT_INGEST_BEFORE_CHECK_OR_FREEZE` disparam por timestamp ausente: **não demonstram uma inversão temporal real**. Um desses nove também pertence aos 52: união 52 + 9 − 1 = 60. Os nove têm eventos posteriores, mas isso não altera nem certifica retroativamente a evidência original. No último evento por jogo: 360 consistentes não certificados e 51 inválidos (411 jogos).

`independently_proven_provider_checked_at` mantém-se null em todos os 420. Não há treino, scoring, promoção ou correção do histórico. Cada evento inválido, fonte, tempos, motivo e sucessor estão no JSON de recibos; o snapshot original conserva os 420.

| Evento inválido | Match key | Motivo factual |
| --- | --- | --- |
| `FT:3fb1d83b0be616ffa4139a89` | `2026-10-28,32833,1641` | freeze anterior ao registo |
| `FT:73a9b3051993f479a7d01be4` | `2026-10-28,84840,39079` | freeze anterior ao registo |
| `FT:be4ec5681912ee5868848b7e` | `2026-10-28,1077,1048` | freeze anterior ao registo |
| `FT:b32ff96a1c3d29e91a768aa5` | `2026-10-28,1136,24479` | freeze anterior ao registo |
| `FT:38824ad88c21f7b96798348d` | `2026-10-28,1509,239` | freeze anterior ao registo |
| `FT:d183d0bc1201d7d9842674db` | `2026-10-28,26233,26232` | freeze anterior ao registo |
| `FT:dcf5ea867eef6407e6844029` | `2026-10-28,33662,36187` | freeze anterior ao registo |
| `FT:9b9376e5305523fe79f00682` | `2026-10-28,610,520` | freeze anterior ao registo |
| `FT:b5709f972648dd2bd4560b09` | `2026-10-28,34927,10104437` | freeze anterior ao registo |
| `FT:31a761f3118ee78eca7dcd14` | `2026-10-28,1517,31985` | freeze anterior ao registo |
| `FT:19f19772d630907cf8d8b020` | `2026-10-28,31987,1515` | freeze anterior ao registo |
| `FT:f71a9d095bbd01bbb00255fc` | `2026-10-28,649,744` | freeze anterior ao registo |
| `FT:ebe485d90cbec9fcca3ce425` | `2026-10-28,29474,38367` | freeze anterior ao registo |
| `FT:ba4b2d630a981152a658bda0` | `2026-10-28,143,127` | freeze anterior ao registo |
| `FT:7ba323040c1e68e5224eb9e0` | `2026-10-28,10048051,26818` | freeze anterior ao registo |
| `FT:2dfc97e8ca6200dce33427e5` | `2026-10-29,38271,605` | freeze anterior ao registo |
| `FT:ffb1e5c893b1d71980a2d92a` | `2026-10-29,30895,30899` | freeze anterior ao registo |
| `FT:425215070f8e7d1b03a15e83` | `2026-10-28,23066,87309` | freeze anterior ao registo |
| `FT:9eef608622ea43cd5f14462f` | `2026-10-28,23670,30838` | freeze anterior ao registo |
| `FT:f3933b7216ec0395765486a0` | `2026-10-28,27460,27466` | freeze anterior ao registo |
| `FT:4c8b97756b968546ef22d65f` | `2026-10-28,27461,908` | freeze anterior ao registo |
| `FT:2994de058e7a1594743113c2` | `2026-10-28,36998,58673` | freeze anterior ao registo |
| `FT:8b2f6e3729d26650c4a1322d` | `2026-10-29,918,1180` | freeze anterior ao registo |
| `FT:f44a362a95eaae4f94178d7f` | `2026-10-30,1585,27385` | freeze anterior ao registo |
| `FT:fb1fd012586bee1b53bfe04c` | `2026-10-30,21672,903` | freeze anterior ao registo |
| `FT:f1a95d1b6234c042d1f87bc4` | `2026-10-30,332,1058` | freeze anterior ao registo |
| `FT:99fbec5ef4a03233a08d1ce0` | `2026-10-31,23449,23456` | freeze anterior ao registo |
| `FT:0984042b8f95c9f8f516134c` | `2026-10-31,26745,79724` | freeze anterior ao registo |
| `FT:eaba17e9dfc1d59127b9c2da` | `2026-10-31,47,18` | freeze anterior ao registo |
| `FT:37dca878cfe6f159ffc48f98` | `2026-10-28,28162,10042394` | freeze anterior ao registo |
| `FT:2e490b556e3283f7830162b6` | `2026-10-31,24188,15` | freeze anterior ao registo; CSV sem checked_at |
| `FT:1d11f9944f373852f6602ce2` | `2026-10-31,54,63` | CSV sem checked_at |
| `FT:644a26054d1f5bbedc12029a` | `2026-10-31,66,50` | freeze anterior ao registo |
| `FT:e1906087acf3c26b1bbe7e86` | `2026-10-31,24188,15` | freeze anterior ao registo |
| `FT:102502f7ed0669b8d88aaa56` | `2026-10-31,24270,39` | freeze anterior ao registo |
| `FT:407bbccacd85669f322c17dc` | `2026-10-31,80,36` | freeze anterior ao registo |
| `FT:4113ae776880f5338d913b47` | `2026-10-30,26235,35124` | freeze anterior ao registo |
| `FT:07a48b64858e52facc982fd7` | `2026-10-31,26,91` | freeze anterior ao registo |
| `FT:5fbcd8cba5d748507dbe8ccc` | `2026-10-31,513,510` | freeze anterior ao registo |
| `FT:2c839787c9a77d57627f4c15` | `2026-10-31,242,240` | CSV sem checked_at |
| `FT:7cc80bac04c2cdbd799a7114` | `2026-10-31,277,22804` | freeze anterior ao registo |
| `FT:72ae494bff09e5be43bf4ee3` | `2026-10-31,188,23811` | freeze anterior ao registo |
| `FT:29b86cc041bc2c8043efca73` | `2026-10-31,26243,39771` | freeze anterior ao registo |
| `FT:be17b307a46122673bbd551b` | `2026-11-01,205,214` | freeze anterior ao registo |
| `FT:1aad49867a5c5c91b700df54` | `2026-11-01,1512,1568` | freeze anterior ao registo |
| `FT:dac699e42062921c7f841239` | `2026-11-01,23165,37488` | freeze anterior ao registo |
| `FT:a0b5025c1b7b945805ea4efe` | `2026-11-01,1103,803` | freeze anterior ao registo |
| `FT:d6236cfc15cac9a1839ff9d8` | `2026-11-01,1625,30945` | freeze anterior ao registo |
| `FT:b46bce6f818752d7ef9c6539` | `2026-11-01,822,913` | freeze anterior ao registo |
| `FT:bc71c614c8e2c3057d4f2860` | `2026-11-02,174,177` | CSV sem checked_at |
| `FT:d9ac44cc7aae42ca0094fda3` | `2026-11-03,27890,25153` | freeze anterior ao registo |
| `FT:ec70dbf6c4581a468dfebcd7` | `2026-11-02,38475,70985` | freeze anterior ao registo |
| `FT:6f54aa27cccb95ca11c1e3f4` | `2026-11-03,27518,371` | freeze anterior ao registo |
| `FT:5b2dcd752a1bdac7f3bae8c1` | `2026-11-03,35829,35831` | CSV sem checked_at |
| `FT:4ac47cf0dd6f2e8dcb3545ef` | `2026-11-03,35833,10058979` | CSV sem checked_at |
| `FT:11e94d8f8d0fbd06b85ef108` | `2026-11-03,70,78` | CSV sem checked_at |
| `FT:fe7c5119f3c860168c456173` | `2026-11-03,5,57` | CSV sem checked_at |
| `FT:5d482dae28e81fa499df6580` | `2026-11-04,194,184` | freeze anterior ao registo |
| `FT:e26e5b4c68a597e3b35bfff7` | `2026-11-05,36932,1597` | CSV sem checked_at |
| `FT:345656529f65a328dfa6aa29` | `2026-11-05,111,1049` | freeze anterior ao registo |

## Limitações e recomendação de merge

Falta prova independente de entrega/receção Telegram para atribuir a causa anterior dos 34 atrasos; os timestamps publicados pelo canal não a substituem. Para Guabirá e USM, faltam os bundles/artefactos não publicados com registo por jogo e SHA; a API não devolveu artefactos nos runs consultados. Não reconstruir forecasts para preencher essas lacunas.

Para FT falta o recibo/resposta original do fornecedor, com identidade do jogo, assertion FT e timestamp verificável independente ligado ao evento. Um checked_at de ledger mutável ou written_at do journal não o substitui. Os 52 eventos anteriores ao registo não podem ser tornados prospectivos retroativamente. Falta ainda uma auditoria Git commit a commit fora das publicações aqui cruzadas e os dois ciclos operacionais reais pós-merge; estes não podem ser alegados antes de merge autorizado.

**Recomendação atualizada:** repetir a verificação independente do Work sobre as duas correções. A aprovação técnica e o merge continuam pendentes dessa revisão e de autorização explícita do utilizador. Não recomendar merge como sinal de aceitação científica, cobertura ≥99% ou certificação FT. Sem merge nesta tarefa. B1 não foi iniciada.

## Reprodução e integridade

Num clone integral, selecionar o commit de código `be67062ba113c280de6abbf0c0d3a26446fabe34`, instalar `requirements-test.txt` e executar os comandos abaixo. A cópia da fonte é criada a partir de objetos já locais, sem rede; o CLI executado é o código corrigido. Usar caminhos temporários novos, sem sobrescrever provas.

```sh
python -m unittest discover -s tests -v
git clone --shared --no-checkout . /tmp/a1-source-257
git -C /tmp/a1-source-257 checkout --detach 9d52a5bbf03d9301a6a3479b0e9c95e01945388c
python -m scripts.master_brain_a1_audit --root /tmp/a1-source-257 --source-sha 9d52a5bbf03d9301a6a3479b0e9c95e01945388c --output /tmp/a1-257-novo.json
```

A auditoria falha se os objetos Git necessários não existirem; não faz fetch nem aceita o snapshot comprimido como substituto. O teste real pode ser explicitamente skipped num clone raso, pelo que a reprodução acima em clone integral continua obrigatória para a revisão independente.

Para verificar uma linha: obter o log do job referenciado, confirmar recibo push/PUBLISHED e SHA do commit; ler o diff da revisão correspondente e comparar o `sha256` com o journal do snapshot. No lote recuperado, comparar os dois blobs documentados e o merged_at de #254. Verificar os SHA-256 dos logs decodificados em UTF-8 e dos artefactos no JSON de validação. O snapshot inicial permanece imutável; os factos adicionais são anexados ao ficheiro de recibos.

`llm_calls=0`, neurons=0, provider_calls=0; apenas recursos gratuitos e leitura GitHub/offline. Nenhum coletor, H1, E5, Telegram, publicador, ledger, resultado, Pages, gate ou configuração de autonomia foi alterado. Nenhum alerta foi enviado.
