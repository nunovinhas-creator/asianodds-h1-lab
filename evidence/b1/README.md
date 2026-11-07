# B1 — correções Work; nova auditoria requerida

PR #259 continua Draft, sem merge, integração operacional ou promoção.
Auditoria: issuecomment-6686213052, head original 80462a48a.

| Problema Work | Correção | Prova automatizada (test_research_quality.py) |
| --- | --- | --- |
| 1. Escrita | CLI aceita apenas basename JSON, ancorado ao root real em work/b1-diagnostics; diretórios via descritores O_DIRECTORY/O_NOFOLLOW; destino O_CREAT/O_EXCL/O_NOFOLLOW, sem substituir | test_secure_exclusive_output: absolutos, traversal, destino existente e symlinks |
| 2. Histórico | Input ede8b771cc20a9236a0163df47ce2f6e7e915b25 e publicação 58c928893f0ba95df361b3ae43c17a3ecdba53e3 fixados no código; verificação de objetos Git, memória integral/hash chain, identidade exata dos 3 registos, hashes de blobs de input, ancestralidade e mensagem de publicação que identifica run 42202804803 | test_history_tampering_fails_before_dataset: source_commit, run_id, memory_sha256 e registo alterados recusados |
| 3. Controlo | Mesmas verificações dimensionais/materialidade em ambos os braços; todas as células conjuntas dos estratos pré-especificados exigem >=2 observações de cada braço | test_work_controls_and_support; test_work_182_418_and_182_43 |
| 4. Lógica | Expansão limitada de caminhos AND/OR, interseção de limites simples por variável; cada caminho deve demonstrar materialidade; equivalência complexa adiada | test_logic_paths: AND redundante aceite como desenho, OR contextual bloqueado, OR material aceite |
| 5. Cronologia | Observação <= freeze <= decisão < kickoff; IDs/flags JSON nunca bastam para autorização; elegibilidade bloqueada até existir adaptador confiável | test_freeze_order_and_untrusted_flags; test_positive_and_boolean_context |
| 6. Isolamento | Removida exceção sem consumidor verification.json de ambas as matrizes | test_evidence_is_manual_review_owned e suite de ownership/isolation |

## Proveniência e limites

`real-plans.json` não foi alterado. O campo legado `source_commit` nesse ficheiro
refere-se à PUBLICAÇÃO, não ao input. O relatório novo usa `input_commit` e
`publication_commit` separados e verificados. Não aceita identificadores fornecidos
pelo utilizador como autoridade. Objetos Git ausentes, memória divergente ou input
incompatível falham antes de qualquer relatório. O vínculo offline deste replay
fixo é o commit de publicação que nomeia o run, os objetos de input fixados e os
blobs registados; não constitui um adaptador genérico de recibos GitHub.

O futuro adaptador deve autenticar eventos e valores, fontes e identidade dos jogos,
observação, congelamento de cada feature, baseline, origem FT e pré-registo/desenho.
Não existe tal adaptador nesta B1. `design_quality_status` avalia somente o desenho;
`quality_status` nunca fica SCIENTIFICALLY_TESTABLE com flags/IDs declarados.
Sem prova confiável: INSUFFICIENT_DATA (ou REJECTED quando há falha objetiva).
Os testes positivos demonstram aceitação do desenho suficiente; não burlam este
bloqueio nem autorizam experiências. Suporte comum é estrutural, não prova causal.

Pisos candidatos a priori: 5 pp (.05 em fração), .10 golos implícitos, .25 linha
Total/AH. Não são resultados comprovados. Álgebra complexa exige revisão. Os
estratos conjuntos sem suporte comum adiam a comparação; não se descartam células
para obter artificialmente comparabilidade.

## Replay offline

Os três planos continuam REJECTED por IMMATERIAL_MOVEMENT; zero experiências novas,
zero promoção, memória/históricos intactos. Contagens brutas 78/65, 58/52, 51/36;
FT histórico 17/20, 11/15, 8/12. 12/17 (70,6%) continua apenas exploratório.
`replay.json` contém hashes de input/output e as razões adicionais de bloqueio.
`output_sha256` cobre o relatório sem esse próprio campo.

```sh
mkdir -p /tmp/b1-frozen
git archive ede8b771cc20a9236a0163df47ce2f6e7e915b25 data docs/lab | tar -x -C /tmp/b1-frozen
python -m scripts.lab_research_quality --source-root /tmp/b1-frozen --output novo-replay.json
```

A saída será criada exclusivamente em `<repo>/work/b1-diagnostics/novo-replay.json`,
independentemente do CWD. Nomes já existentes são recusados. A regeneração das
provas versionadas é revisão manual, não uma capacidade de escrita do CLI.

19 testes B1 passam. Resultados da suite integral, isolamento e CI do head corrigido
serão registados na PR. Nada altera H1/E5/Telegram/FT/Pages, workflows de produção,
gates, memória, quotas ou agendamento. Zero LLM real, fornecedores, serviços pagos
ou fluxos monetários. Requer nova auditoria independente Work; não está aprovada.

## B1 P0 — controlo neutro e alternativas OR

A validação dimensional abrange o sinal e o controlo. A exigência de movimento
material aplica-se ao sinal, por caminho lógico. O controlo neutro de −0,02 a
0,02 tem 100 observações face a 182 no sinal e, nesta amostra, dá os mesmos
estados, razões e métricas que o complemento. Unidades incompatíveis,
sobreposição e falta de suporte comum continuam a impedir a aceitação.

O OR entre pelo menos 0,10 golos implícitos e pelo menos 0,25 na linha Total
passa a verificação do desenho. Alternativas imateriais ou contraditórias são
rejeitadas. Caminhos sem materialidade demonstrável ficam pendentes. Limites
AND redundantes continuam a ser combinados. A aceitação do desenho mantém
`TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE` e zero elegibilidade operacional.

O replay histórico autenticado produziu exatamente o relatório versionado
(`output_sha256` 334731885529019ee3a2e0a453c435c76474e8533d554993bf6f9304427f0617).
Os três planos permanecem rejeitados por `IMMATERIAL_MOVEMENT`, com
`MIN_N_NOT_MET` e `COMMON_STRATUM_SUPPORT_MISSING` entre as limitações.
Zero experiências executadas. Os 21 testes direcionados B1 passaram.

PR em Draft. Nova auditoria independente requerida antes de qualquer merge.

## B1 P0/P1 — auditoria independente de 58e3c1fd

Correção limitada a `h1lab/research_quality.py` e testes adversariais independentes.
A PR permanece Draft e requer nova auditoria; não autoriza merge, experiências,
ativação operacional ou promoção científica.

- P0: cada alternativa explícita AND/OR é verificada, incluindo negação e
  complementos booleanos, igualdade/desigualdade (tolerância real de 1e-9 da DSL),
  operandos invertidos e intervalos. Um ramo comprovadamente contraditório rejeita
  o desenho mesmo com outro ramo OR válido. Álgebra sem prova de satisfatibilidade
  recebe `SATISFIABILITY_UNPROVEN` e revisão manual. OR materiais válidos, AND
  redundantes e controlo neutro mantêm aceitação do desenho.
- P1: a janela temporal inclui as dependências dos estratos selecionados:
  `lead_first_min`, `total_line_last` e os três contextos de competição.
  Observação, freeze, decisão e kickoff são confrontados separadamente; uma
  fronteira desconhecida não oculta uma violação demonstrada noutra fronteira.
  Linhas tardias ou de cronologia desconhecida continuam nas contagens brutas,
  mas não fornecem suporte comum, elegibilidade nem OOS. As células selecionadas
  são preservadas, sem descartar células deficientes para obter suporte artificial.
- Os dois contraexemplos OR e o controlo com `total_line_last` um segundo tardio
  foram reproduzidos no código rejeitado: os três eram SCIENTIFICALLY_TESTABLE.
  A versão corrigida rejeita os três.
- 30 testes direcionados passaram sem skips: 21 existentes e 9 novos métodos
  adversariais, com permutações e variações de operadores e braços, testemunhas
  concretas pela DSL e 900 pares de predicados para procurar falsos positivos.
- Replay autenticado dos três planos: igualdade estrutural e byte a byte com
  `evidence/b1/replay.json`, sem diferenças de estados, razões ou métricas.
  `output_sha256=334731885529019ee3a2e0a453c435c76474e8533d554993bf6f9304427f0617`.
  Prova original intacta; zero experiências, zero promoções e zero chamadas pagas.

Reprodução em checkout com objetos históricos disponíveis:

```sh
python -m unittest discover -s tests -p 'test_research_quality*.py' -v
mkdir -p /tmp/b1-frozen
git archive ede8b771cc20a9236a0163df47ce2f6e7e915b25 data docs/lab | tar -x -C /tmp/b1-frozen
python -m scripts.lab_research_quality --source-root /tmp/b1-frozen --output novo-p0-p1-replay.json
cmp evidence/b1/replay.json work/b1-diagnostics/novo-p0-p1-replay.json
python -m unittest discover -s tests -v
node --test tests/dashboard-ui.test.cjs tests/master-brain-contract.test.cjs tests/discovery-public-pages.test.cjs tests/research-autonomy-ui.test.cjs scheduler/worker.test.mjs
python -m unittest discover -s tests -p 'test_v6_offline*.py' -v
python -m scripts.v6_scientific_gate --verify-blocked
python -m scripts.research_isolation_check --base 58e3c1fd10a40746cf16296432a81444b30fa8c5
```

Os resultados integrais, falhas/skips e checks remotos finais são registados na
conversa da PR. Neste ambiente, o proxy Git estava inacessível; a recuperação pelo
conector GitHub foi conferida contra hashes Git originais, incluindo árvores,
commits, memória de publicação e os onze blobs do replay. Não se desativou TLS nem
se contornou o proxy. A recuperação parcial não constitui prova de suite integral.

Mantém-se `TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE`, LLM autónomo desligado e zero
custos. H1, E5, Telegram, FT, Pages, históricos, ledgers, gates e workflows
operacionais não são alterados por esta correção.

**Nova auditoria independente solicitada: procurar contraexemplos não antecipados
pelos testes, especialmente negações/OR aninhados, tolerância das igualdades,
dependências temporais dos estratos e suporte comum nos dois braços.**

## Segunda auditoria Claude — correção do head c7914dcffd2a96be9a17ab3edf1d34b22393b656

PR #259 permanece **Draft**, sem merge, ativação operacional ou promoção científica.
Esta secção substitui as afirmações anteriores sobre cobertura dos ramos falsos e
dos valores de estratificação. O head rejeitado passou os 30 testes anteriores,
mas admitiu todos os oito contraexemplos obrigatórios desta auditoria.

### Matriz reproduzida antes/depois

Os estados abaixo são de **desenho**, não autorização científica. Em todos os
casos mantém-se `TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE` e `promotion_eligible=false`.
Os quatro casos P1 usam 600 linhas, com 300 em cada braço.

| Contraexemplo | Head rejeitado | Esperado e corrigido |
| --- | --- | --- |
| `OR(lambda_net >= .10, false)` | Aceite | REJECTED / `CONTRADICTORY_SIGNAL_PATH` |
| `OR(lambda_net >= .10, NOT true)` | Aceite | REJECTED / `CONTRADICTORY_SIGNAL_PATH` |
| `AND(lambda_net >= .10, OR(total_line_net >= .25, false))` | Aceite | REJECTED / `CONTRADICTORY_SIGNAL_PATH` |
| Controlo `OR(between(lambda_net, -.02, .02), false)` | Aceite | REJECTED / `CONTRADICTORY_SIGNAL_PATH` |
| Três contextos `False` | Aceite, 600 elegíveis | REJECTED / `CONFOUNDER_COMPETITION_CONTRADICTION`, zero elegíveis/OOS |
| `ctx_cup=True`, `ctx_league_other=True` | Aceite, 600 elegíveis | REJECTED / `CONFOUNDER_COMPETITION_CONTRADICTION`, zero elegíveis/OOS |
| `lead_first_min=-30` | Aceite, 600 elegíveis | REJECTED / `CONFOUNDER_VALUE_OUT_OF_DOMAIN`, zero elegíveis/OOS |
| `total_line_last=NaN` | Aceite como MID, 600 elegíveis | REJECTED / `CONFOUNDER_VALUE_NONFINITE`, zero elegíveis/OOS |
| Estrato ausente ou `None` | Adiado | INSUFFICIENT_DATA / `CONFOUNDER_DATA_MISSING`, zero suporte/elegibilidade/OOS dessa linha |
| Estrato numérico infinito ou de tipo incorreto | Podia ser categorizado ou abortar a avaliação | REJECTED / `CONFOUNDER_VALUE_NONFINITE` ou `CONFOUNDER_VALUE_TYPE_INVALID`, exclusão rastreável |
| `lambda_abs_path <= -.2` (P2) | Aceite pela análise do desenho | REJECTED / `CONTRADICTORY_SIGNAL_PATH`, domínio não negativo |
| `p_home_net >= 5` (P2) | Aceite pela análise do desenho | REJECTED / `CONTRADICTORY_SIGNAL_PATH`, domínio [-1, 1] |
| `lead_first_min=5000`, observação final a 10 min (P2) | Aceite | Aceite se a primeira mensagem foi a 5000 min: trajetória legítima, sem inferir incoerência |
| Comparar `lambda_net/lambda_first` com `p_home_net/p_home_last` (P2) | Rejeição dimensional indevida | Unidades cancelam; adiado por `COMPOUND_UNITS_REVIEW` / `SATISFIABILITY_UNPROVEN` |
| OR com duas alternativas materiais, AND redundante e controlo neutro 182/100 | Aceite | Aceite, preservando bloqueio de proveniência |

### Implementação e fronteiras

- `_logic_paths` representa um caminho verdadeiro por conjunção vazia e um
  caminho falso por átomo `false` explícito. Nenhum OR descarta esse ramo.
  Mantêm-se os limites da expansão, a lógica ternária e a prova por caminho em
  ambos os braços. Identidades verdadeiras e De Morgan têm controlos positivos.
- `_stratum_cell` é exclusivo do B1; `research_executor._bins` e todos os seus
  consumidores permanecem inalterados. Só categoriza dependências dos estratos
  pré-especificados após validação. Numéricos têm de ser `int`/`float` finitos,
  excluindo booleanos; lead e linha Total não podem ser negativos. Não se inventam
  máximos nem se exige uma grelha de quartos sem prova do contrato da fonte.
  Contextos têm de ser booleanos estritos e exatamente um verdadeiro. Dois
  verdadeiros rejeitam mesmo quando o terceiro está em falta; um contexto
  desconhecido não se transforma numa competição conhecida.
- Linhas excluídas mantêm `rows`, atribuições brutas, disponibilidade FT/baseline
  e os dados de origem intactos. Quando a própria atribuição não é avaliável,
  conta como `unknown` sem interromper as linhas seguintes. `strata_excluded`,
  contadores por braço e `strata_exclusions` identificam `match_key`, variável e
  motivo. Não entram em células válidas, elegibilidade ou split OOS. Não se
  declara suporte comum quando o estrato de uma linha selecionada é desconhecido.
  Os novos campos só aparecem havendo exclusões, preservando o replay histórico.
- Os limites P2 decorrem diretamente de `trajectory_variables`: soma de valores
  absolutos >= 0 e diferença de probabilidades em [-1, 1]. Estes limites provam
  viabilidade, sem alterar os limiares submetidos usados na materialidade.
- O caso lead 5000/10 foi reconstruído por `trajectory_variables` com duas
  mensagens: primeira a 5000 min, última a 10 min, span 4990 min. O timestamp de
  disponibilidade de uma feature agregada não identifica a primeira mensagem.
  **P2 separado para futura auditoria:** coerência completa entre lead, span,
  eventos e horários exige um adaptador autenticado que distinga primeiro evento,
  último evento e freeze. Não se impõe igualdade com `feature_observed_at` nem um
  teto arbitrário de lead. A álgebra dimensional geral (produtos, recíprocos,
  conversões de minutos/horas) também fica fora desta correção; apenas se prova
  cancelamento de dimensões iguais, mantendo revisão manual da álgebra composta.

### Verificação desta revisão

42 testes B1: 30 anteriores (uma expectativa antiga incompatível com o contrato
foi corrigida) e 12 novos métodos com casos parametrizados. Incluem os oito
contraexemplos Claude, ordens e braços, negações aninhadas, desconhecidos versus
inválidos, os oito estados booleanos de competição, fronteiras dos bins, valores
finitos/não finitos, tipos, exclusão de uma linha e de um braço inteiro, estrato
usado no sinal e os P2. Preservam os 900 pares de predicados com testemunhas DSL,
cronologia, sobreposição, proveniência e controlo neutro 182/100.

Replay autenticado byte a byte idêntico a `evidence/b1/replay.json`:
SHA-256 `1dd93bc1fee284f2efaed7a58e287f77f2fd9b524b39fea25fbf260e568061c5`.
Prova original intacta:
`6280ff9aacce4f9987bfee8aea02c79e968f6f7ded9268c996f823c3c18938f0`.
Os três planos continuam REJECTED, sem experiências novas ou promoção.

UI: 30 testes; scheduler: 7; V6 offline: 35, sem skips. Gate:
`SCIENTIFICALLY_BLOCKED`, sem avaliação/publicação. A suite integral, smoke,
preflight e isolamento finais, com eventuais falhas/skips e links CI, serão
registados na conversa da PR. Comandos reproduzíveis são os da secção anterior,
usando `--base c7914dcffd2a96be9a17ab3edf1d34b22393b656` para esta correção.
Usar nomes de output novos, porque o CLI recusa sobrescrita.

**Solicita-se nova auditoria independente Claude/Work do novo head**, incluindo
erros adicionais não antecipados: caminhos DNF aninhados, constantes sob negação,
fronteiras físicas/tolerância de igualdade, tipos malformados em ambos os braços,
combinações incompletas e contraditórias de estratos e elegibilidade/OOS.
Testes verdes não constituem aprovação científica. Zero LLM real, custos,
alterações históricas, workflows, gates ou integração operacional.

## Terceira auditoria — bloqueadores do head 0b8045f6a4d6e392c621b2c00706d54c842338fb

Esta revisão substitui os limites anteriores sobre coerência de lead, validação
apenas dos estratos e suporte agregado. PR #259 continua **Draft**. Não autoriza
merge, experiências B1, LLM real, promoção ou qualquer alteração operacional.
Somente o avaliador B1, três ficheiros de testes e este README são alterados.
`research_dsl`, `research_executor`, H1, E5, Telegram, FT, Pages, históricos,
ledgers, quotas, workflows e gates permanecem intactos.

### Contrato e provas lógicas

Cada alternativa explícita continua auditada, incluindo alternativas mortas em
OR, em ambos os braços. A seleção de `competition_type` acrescenta o contrato de
exatamente um contexto verdadeiro. Não se pressupõe esse contrato quando o
estrato não está selecionado. Negação, De Morgan e ordem das alternativas não
alteram a classificação.

O fragmento de prova verifica constantes com o próprio intérprete DSL,
comparações reflexivas, exigências de disponibilidade de expressões e ciclos de
ordenação estrita. A ordenação não usa epsilon. `EQ`/`NE` continuam com a tolerância
**real da DSL, 1e-9**; igualdade aproximada não é tratada como transitiva. Os
intervalos escalares usam os mesmos domínios da admissão das linhas (incluindo
contagens inteiras e direções discretas), continuam arredondados para fora e só demonstram
satisfatibilidade após uma testemunha concreta da DSL. A disponibilidade de
aritmética que pode transbordar ou dividir por zero não é inferida só pela
disponibilidade dos operandos. A lógica de três valores do intérprete não mudou.

Nas linhas abaixo, `A = lambda_net >= .10`, `x = lambda_first`, `y = lambda_last`;
cada `C` é usado em `OR(A, AND(A, C))`, no sinal **e** no controlo. O estado
anterior refere-se à análise lógica: ausência de rejeição da contradição não é
aprovação científica.

| C / família | Head rejeitado | Revisão |
| --- | --- | --- |
| `AND(ctx_cup, ctx_league_other)`, competição selecionada | Não identificava contradição; sinal podia passar o desenho | REJECTED / `CONTRADICTORY_SIGNAL_PATH` |
| Três flags falsas; exclusão das três por NOT/OR; ordens e aninhamentos | Não identificava o domínio exclusivo | Mesma rejeição; os três estados one-hot válidos preservados |
| `EQ(1, 2)` | `SATISFIABILITY_UNPROVEN` | REJECTED / `CONTRADICTORY_SIGNAL_PATH` |
| `LT(ADD(1, 2), 3)` | `SATISFIABILITY_UNPROVEN` | Mesma rejeição |
| `GT(x, x)` | `SATISFIABILITY_UNPROVEN` | Mesma rejeição |
| `NE(x, x)` | `SATISFIABILITY_UNPROVEN` | Mesma rejeição |
| `AND(NOT IS_KNOWN(GT(x, 1)), GT(x, 1))` | `SATISFIABILITY_UNPROVEN` | Mesma rejeição |
| `AND(GT(x, y), GE(y, x))` | `SATISFIABILITY_UNPROVEN` | Mesma rejeição, por ciclo estrito |
| Níveis lambda negativos, probabilidade >1, contagem fracionária e direção fora de {-1,0,1} nas condições | Podia usar testemunhas fora do contrato de admissão | REJECTED / `CONTRADICTORY_SIGNAL_PATH`; domínio lógico e de dados partilhado |
| Expressões satisfazíveis, incluindo EQ aproximada não transitiva e AND conhecido por operando dominante | Regressões positivas | Não rejeitadas como contraditórias; testemunhas independentes na DSL |
| Álgebra geral, razões compostas, aritmética indefinida | Revisão manual | INSUFFICIENT_DATA quando não há prova; nunca aprovação por suposição |
| OR com `false`, `NOT true`, falso aninhado, complementos opacos e booleanos; intervalos incompatíveis; controlo OR morto | Já corrigidos na auditoria anterior | Regressões preservadas |
| OR material, AND redundante, controlo neutro 182/100; domínio de caminho absoluto e diferenças de probabilidades | Controlos positivos/negativos anteriores | Regressões preservadas, mesma diferença de materialidade entre sinal e controlo |

### Validação antes da atribuição e contabilização completa

Todas as variáveis transitivas do sinal e controlo são validadas **antes** de
`membership`: tipos exatos (bool não é número), finitude, domínios provenientes do
catálogo e disponibilidade. Não há conversão de strings. Indicadores derivados e
subexpressões indefinidas são verificados antes da atribuição. Dados ausentes
adiam; valores objetivamente inválidos rejeitam. Um valor inválido num ramo
booleano dominado não é autorizado a entrar pela alternativa/complemento.

Cada linha conserva a contagem bruta e recebe motivos por jogo e variável. Uma
linha inválida nas dependências de atribuição é `unknown`, nunca controlo. Uma
linha com atribuição calculável e defeito de cronologia/estrato conserva o braço
bruto, mas não entra no suporte pré-jogo, elegibilidade ou OOS. FT e baseline só
são consultados **depois** da atribuição. Os contadores de elegibilidade são
apenas diagnósticos; o funil científico continua bloqueado e `executed=0`.

A amostra base tem 600 linhas, 300 por braço. Nas substituições de uma variável
do sinal, a linha afetada era do grupo. G/C significa grupo/controlo.

| Caso | Antes | Bruto após validação (G/C/desconhecido) | Excluídas | Pré-jogo G/C | Elegíveis G/C | OOS total |
| --- | --- | --- | --- | --- | --- | --- |
| Controlo positivo | 300/300 | 300/300/0 | 0 | 300/300 | 300/300 | 600 |
| `lambda_net=NaN` | Migrava para controlo: 299/301 | 299/300/1 | 1 | 299/300 | 299/300 | 599 |
| `lambda_net=Infinity`, `True`, `"0.2"` (um por execução) | Aceitava/coagia a observação | 299/300/1 | 1 | 299/300 | 299/300 | 599 |
| Mesmo defeito no controlo explícito, complemento e indicador derivado | Fronteira não validada integralmente | Mesma exclusão sem contaminação do outro braço | 1 | 299/300 | 299/300 | 599 |
| Lead 0; decisão a -31 minutos | Não confrontava o lead com a decisão | 300/300/0 | 1 | 299/300 | 299/300 | 599 |
| HIGH com 2 G/2 C; os 2 G sem FT certificado | Suporte agregado aparentemente suficiente | 300/300/0 | 2 | 300/300 | 298/300 | 598 |
| `total_line_last=NaN` numa linha do grupo | `shadow_report` lançava ValueError ao criar hash | 300/300/0 | 1 | 299/300 | 299/300 | 599 |
| `feature_observed_at=None` numa linha do grupo | Relatório parcialmente contabilizado / QUALITY_INPUT_INVALID | 300/300/0 | 1 | 299/300 | 299/300 | 599 |
| Timestamp `0001-01-01T00:00:00+01:00` | OverflowError na conversão UTC | 300/300/0 | 1 | 299/300 | 299/300 | 599 |
| Tipos errados em variables, timestamps, baseline/FT ou IDs de proveniência | Podia aprovar ou interromper a contabilização | 600 linhas contabilizadas; atribuição desconhecida se variables/identidade inválidas | 1 | Só 599 contribuem | Só 599 contribuem | 599 |
| NaN + linha sem timestamps + linha não objeto, simultaneamente | Primeiro erro podia esconder os seguintes | 600 linhas contabilizadas | 3, todas identificadas | 597 no total | 597 no total | 597 |
| Todos os contextos falsos/duplicados, lead negativo, linha Total não finita, tipos e domínios inválidos dos estratos | Exemplos da segunda auditoria | REJECTED; regressões anteriores preservadas | Todas as afetadas | Não contribuem | Não contribuem | Não contribuem |

A indisponibilidade de dependências é uma regra de admissão B1; não altera o
resultado ternário do intérprete DSL nem o executor partilhado. Duplicados são
excluídos em **todas** as suas ocorrências, sem escolher a primeira linha. As
exclusões identificadas são ordenadas deterministicamente por identidade e
motivos; `row_index` conserva intencionalmente a posição original quando não há
identificador auditável.

`shadow_report` verifica a identidade JSON sem converter tuplos, chaves numéricas,
objetos Python ou valores não finitos. Quando não há representação canónica
exata, devolve `report_status=REJECTED`, `input_sha256=null` e
`INPUT_IDENTITY_UNAVAILABLE`, com diagnósticos das linhas ainda contabilizáveis.
Não inventa hashes, não substitui NaN, não perde o resto da amostra e não escreve.

### Cronologia de lead

`lead_first_min` é arredondado na origem a 0,1 minuto. A tolerância explícita é
**3 segundos**, metade dessa unidade; só se aplica à primeira observação
inferida. Observações de features continuam sem tolerância de atraso:
`observação <= freeze <= decisão < kickoff`. A primeira observação inferida deve
preceder observação de disponibilidade do próprio lead, freeze, decisão e kickoff.
Os motivos `LEAD_FIRST_AFTER_*` identificam a fronteira violada. Overflow de data
ou timedelta é contabilizado, sem interromper as restantes linhas.

Com decisão a -31 min: lead 30,95 é compatível com o arredondamento; 30,94 já não
é. Lead 31 e lead 5000 são válidos se as restantes fronteiras forem compatíveis.
A disponibilidade de uma feature agregada não é confundida com a primeira
mensagem: não se exige igualdade entre esses horários.

### Suporte comum e possível viés por exclusão

`common_support` apresenta separadamente os contadores pré-jogo, elegíveis e por
período de cada célula. A célula HIGH do contraexemplo continua **2/2 pré-jogo**,
mas fica **0/2 elegível**, causando `COMMON_STRATUM_SUPPORT_MISSING`. As células
que perdem todos os elegíveis são conservadas; não se escolhem estratos depois
de conhecer a disponibilidade de FT.

A decisão P2 é exigir **>=2 observações de cada braço em cada célula no treino e
no teste**, além do mínimo global OOS já existente. O desenho declara comparação
estratificada fora da amostra; suporte agregado não a demonstra. HIGH com grupo
só no treino e controlo só no teste tem suporte global, mas recebe
`COMMON_STRATUM_PERIOD_SUPPORT_MISSING`. O dia de corte é fixado com as atribuições
pré-jogo cronologicamente válidas, antes da exclusão por FT/baseline. Excluir FT
de dias inteiros não pode mover esse dia ou redefinir os braços.

`attrition` apresenta atribuições, pré-jogo, elegíveis, exclusões após atribuição
e FT sem origem verificada, por braço; as células permitem localizar perdas
assimétricas. No contraexemplo perdem-se 2/300 do grupo e 0/300 do controlo, com
a perda concentrada em HIGH. Isso torna visível seleção potencialmente informativa.
Sem resultados certificados para os ausentes, estes metadados não provam ausência
de viés por missing-not-at-random, nem justificam imputação, ponderação ou nova
atribuição. A comparação fica bloqueada, sem conclusões de efeito preditivo.

### Replay autenticado e diferenças exclusivamente diagnósticas

Os ficheiros históricos `real-plans.json` e `replay.json` não são alterados.
A regressão reconstrói os 11 blobs autenticados num diretório temporário e executa
o replay duas vezes, exigindo determinismo. Confere igualdade integral de
`provenance`, `input_sha256`, `before`, `costs`, `limits`, `funnel`, fingerprints,
estados, contagens de braços, disponibilidade histórica FT/baseline e OOS.
Os três planos continuam REJECTED e os seis braços têm zero elegibilidade B1.

A versão diagnóstica passa a `B1_SHADOW_2`. Acrescenta métricas de exclusão, atrito,
suporte e três razões: `SIGNAL_DATA_MISSING`, `BASELINE_MISSING` (agora também
registada nas linhas sem atribuição) e `COMMON_STRATUM_PERIOD_SUPPORT_MISSING`.
A validação prévia das dependências reclassifica linhas antigas não atribuídas
como desconhecidas; a soma das duas categorias é exatamente preservada:

| Plano (prefixo) | G/C históricos intactos | Desconhecidas antes/depois | Não atribuídas antes/depois | Pré-jogo G/C | Elegíveis G/C |
| --- | --- | --- | --- | --- | --- |
| `676a5e49` | 78/65 | 868/955 | 607/520 | 0/0 | 0/0 |
| `b2c9b2b7` | 58/52 | 921/922 | 587/586 | 0/0 | 0/0 |
| `a362ed8a` | 51/36 | 868/955 | 663/576 | 0/0 | 0/0 |

| Identidade | SHA-256 |
| --- | --- |
| Prova original, bytes | `6280ff9aacce4f9987bfee8aea02c79e968f6f7ded9268c996f823c3c18938f0` |
| Replay histórico, bytes intactos | `1dd93bc1fee284f2efaed7a58e287f77f2fd9b524b39fea25fbf260e568061c5` |
| Replay histórico, output_sha256 | `334731885529019ee3a2e0a453c435c76474e8533d554993bf6f9304427f0617` |
| Input do replay, intacto | `398d66b985c441c905daa4eb0ddf83d7713fddb8898f77022b5976ced2115077` |
| Dataset original/reconstruído, intacto | `ba45b40bad2fda1380265c8afd2e1265dc720d596746cd0366415b8119743f4a` |
| Replay B1_SHADOW_2, bytes | `25ba8a1f44eb4a5296ec127c251e341be6fb4698053e5c83fdd92b0bbcd7582d` |
| Replay B1_SHADOW_2, output_sha256 | `15788d58012e806fe62f12ac98229a642cf71211ebf715cf7a70a3933b7aa16f` |

Para reproduzir, usar o comando anterior com um basename novo de diagnóstico.
A diferença de bytes é esperada e limitada às alterações diagnósticas acima;
não se apresenta uma identidade integral que não existe.

### Regressões, isolamento e limites remanescentes

São 55 testes B1: os 42 anteriores, com fixtures cronologicamente válidos e uma
expectativa de suporte por período explicitada, mais 13 novos métodos. Incluem
permutações de OR, AND, linhas e duplicados; estados booleanos completos;
testemunhas finitas e fronteiras float; entradas inválidas monotónicas;
contaminação de sinal/controlo; disponibilidade derivada; erro simultâneo em
várias linhas; proveniência e replay autenticado. O oráculo anterior de 900 pares
conserva os valores negativos numa variável de movimento assinada
(`lambda_unobserved_net`); níveis `lambda_first` passam a respeitar o domínio não
negativo também nas provas lógicas. Não há dependências novas.

A suite integral, Research, preflight sem PyYAML, 30 testes UI, 7 scheduler,
isolamento e os quatro workflows CI são reportados no comentário de entrega da
PR, associados ao SHA completo. Falhas de sandbox/loopback e skips são reportados
separadamente dos resultados finais, sem os apresentar como verdes.

Limites mantidos: fragmento lógico deliberadamente incompleto (máximo 64 caminhos;
álgebra não demonstrada adia), álgebra dimensional geral ainda sujeita a revisão,
lead inferido não autentica eventos e metadados não demonstram ignorabilidade da
perda de FT. Não existe adaptador genérico confiável:
**`TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE`**, **`promotion_eligible=false`**.
Zero experiências B1, zero promoções, zero LLM real e zero custos. Os testes do
sistema existente usam apenas fixtures, mocks e memórias TEST temporárias.

**Solicita-se nova auditoria independente Claude/Work**, especialmente para falsos
positivos de satisfatibilidade, combinações de knownness/overflow/tolerância,
células elegíveis contaminadas, efeitos de exclusão no split, determinismo e
relatórios malformados. Procurar contraexemplos além dos testes. Não fazer merge.

## Correção estrutural após a auditoria de fbab0d53

A referência é o relatório independente `MASTER-BRAIN-auditoria-B1-PR259.md`
(SHA-256 `21325d17befbd1412d382aafa8450ba4b55009f29364603633abd3ce899d3cd1`).
A sonda original foi executada no head rejeitado e no avaliador corrigido.
A PR permanece em Draft e requer nova auditoria independente.

| Caso | Antes | Depois |
|---|---|---|
| Net positivo e extremos iguais num ramo de OR | Desenho testável | `CONTRADICTORY_SIGNAL_PATH` |
| Contagens incompatíveis e direção sem movimentos | Desenho testável | Ramo rejeitado |
| Flags one-hot sem estrato de competição | Desenho testável | Ramo rejeitado |
| Intervalo sem ponto na grelha do produtor ou dependência obrigatória desconhecida | Desenho testável | Ramo rejeitado |
| Interseção explícita a 0,27 ausente da amostra | Desenho testável | `LOGICAL_GROUP_CONTROL_OVERLAP` |
| Interseção com álgebra fora do fragmento | Podia depender da amostra | `CONTROL_DISJOINTNESS_UNPROVEN` |
| Lead final e hora de kickoff incompatíveis | 600 elegíveis | Zero elegíveis nas duas mutações integrais |
| Timestamp com sete casas | A diferença desaparecia | Linha excluída com `TIMESTAMP_PRECISION_UNSUPPORTED` |
| Plano prévio duplicado | Mesmo hash com parecer diferente | SHA-256 de input distinto |
| NaN numa chave adicional | API direta aprovava e shadow retinha contagens elegíveis | Ambas rejeitam, preservam contabilidade e devolvem zero elegíveis |
| Fingerprint adulterado | APIs divergentes | Ambas rejeitam |
| Restrição tautológica do domínio | Falso negativo de materialidade | Sinal material preservado |
| Controlo neutro 182/100 | Válido | Válido, com disjunção demonstrada |

O fragmento usa limites necessários do produtor, grelhas e uma testemunha
conjunta reavaliada no intérprete DSL. Verifica também as relações entre
contagens, extremos, movimentos, direções e leads nas dependências presentes.
As grelhas estreitas são verificadas exaustivamente. Um oráculo independente
enumera todas as sequências de sinais de uma a três mensagens e verifica
as contagens e os sentidos nos extremos. As implicações de uma única
mensagem também vinculam os leads, os intervalos e o movimento Total. Uma interseção sem
contradição demonstrada nem testemunha fica por provar. A expansão continua
limitada a 64 ramos, e a análise explícita admite até 64 pares de caminhos e
4 096 vetores de testemunhas por análise. O modelo cobre os invariantes
codificados do catálogo. A proveniência e a possibilidade de reconstruir uma
sequência real de cotações continuam fora do alcance do diagnóstico. Os leads
declarados são comparados com os timestamps com a tolerância existente de
três segundos. A comparação direta entre os dois leads usa a monotonicidade
do arredondamento do produtor.

O contrato `B1_SHADOW_3` identifica planos submetidos, metadados, desenho e
freeze e a representação canónica dos campos de planos prévios que influem
na decisão. As contagens brutas de linhas e atribuições descrevem o input.
Quando falta uma identidade JSON válida, a elegibilidade e o suporte
admissíveis são zero. As contagens de linhas restantes ficam em
`unidentified_diagnostics` para diagnóstico, incluindo as exclusões por jogo
na contabilidade geral. A decisão continua independente de evidência FT para
a atribuição bruta. `TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE` e
`promotion_eligible=false` continuam obrigatórios.

O replay histórico versionado conserva SHA-256
`1dd93bc1fee284f2efaed7a58e287f77f2fd9b524b39fea25fbf260e568061c5`.
O replay autenticado preserva o dataset
`ba45b40bad2fda1380265c8afd2e1265dc720d596746cd0366415b8119743f4a`,
os registos originais, os braços 78/65, 58/52 e 51/36 e três rejeições.
O diagnóstico novo tem input
`6a1e7cc60baf4c3a07ae7a92ebfd6fac21e912acba52dbc3c11ea42fb9d402da`
e `output_sha256`
`1efcaab0f611c123fdcb35431e4584592e833fb599eb4666f033cc71c16d4bfe`.
A adulteração do registo e do blob de entrada falha fechada. Não há
execuções B1, promoção, memória escrita ou chamadas a fornecedores.

A próxima auditoria deve procurar caminhos conjuntamente impossíveis
que o fragmento ainda aceite, sobreposição latente fora das regiões da
amostra, fronteiras de precisão e pedidos com a mesma identidade mas
decisões diferentes.

## Contrato de existência após rejeição de 198bdf1c — F01–F08

Correção `B1_SHADOW_4`, contrato `B1_PRODUCER_1`. A PR #259 continua **Draft**.
Os produtores `research_dataset.py`, `market_math.py`, `research_dsl.py` e o
executor partilhado mantêm os bytes do commit rejeitado. A correção fica no
avaliador B1, no novo `research_contract.py`, nos testes e no diagnóstico offline.

**Documentos em falta.** Não estão no workspace, na árvore da PR ou nos
comentários acessíveis os ficheiros `MASTER-BRAIN-auditoria-B1-PR259-198bdf1c.md`,
`ADENDA-52-SONDAS-ORIGINAIS.md` ou o relatório anterior com os scripts originais.
Foi pedida a sua localização. Os testes abaixo são **reconstruídos a partir do
pedido**, não uma reprodução literal dos 52/43/10/601 inputs do auditor. Em
particular, não é possível identificar individualmente os **553** casos desse
relatório sem os respetivos inputs. Esse requisito da auditoria permanece aberto.
O histórico da secção anterior conserva as alegações e hashes dessa entrega;
a presente correção não os apresenta como evidência suficiente de existência.

### Fonte única e significado das provas

`h1lab/research_contract.py` contém os domínios, grelhas, unidades, dependências,
restrições de subconjuntos, modelo de sequências, intervalos temporais e o
verificador de certificados. O avaliador lógico e a admissão usam esse contrato.

- **SAT:** há um certificado com mensagens pré-jogo completas. O certificado é
  validado contra a gramática das fontes, passado pelo produtor original e pelo
  cálculo original de episódios; todos os operandos necessários são conhecidos,
  todos os átomos do caminho avaliam a `True` na DSL e o resumo passa o contrato.
  Os valores de lambda resultam de cotações válidas e da inversão original de
  `market_math`, incluindo o seu arredondamento. Um vetor de valores numéricos
  que apenas passe desigualdades nunca prova SAT.
- **UNSAT:** uma contradição lógica, escalar ou uma condição necessária do
  produtor demonstra impossibilidade. A ausência de candidatos numa busca
  limitada não é uma prova UNSAT. Na política de desenho existente, qualquer
  alternativa explicitamente impossível recebe `CONTRADICTORY_SIGNAL_PATH`.
- **UNKNOWN:** falta prova num dos sentidos. Emite `SATISFIABILITY_UNPROVEN` e
  impede `SCIENTIFICALLY_TESTABLE`. Álgebra fora do fragmento e limites de
  complexidade mantêm esse resultado. O relatório expõe `logical_proof`, com
  estados, contrato, tipo de prova e testemunhas por caminho/interseção.

A construção é deliberadamente incompleta: DNF e pares de caminhos limitados a
64; busca construtiva até 12 mensagens, 32 modelos de sinais por configuração,
512 passos de geração de pontos/cotações e 256 certificados completos por
análise. O verificador admite certificados explícitos até 64 mensagens. Uma
observação maior sem certificado suportado fica excluída, com ausência de prova;
não é declarada fisicamente impossível por exceder o limite. A enumeração de
sequências pode provar impossibilidade fora da busca construtiva, mas não
certifica preços, duração ou dispersão. Estes exigem sempre replay concreto.

### Relações do produtor e arredondamento

| Família | Contrato usado nas duas fronteiras |
|---|---|
| Domínios/unidades | Contagens inteiras; direções em `{-1,0,1}`; hora UTC inteira `0..23`; booleans sem coerção; lambda `0.05..12`, variação `-11.95..11.95`; unidades em `VARIABLE_UNITS`. |
| Grelhas | Leads/span/gap a **0,1 minuto**; resumos lambda/probabilidade/variações/share a quatro casas; overround a cinco casas. Linhas brutas respeitam a grelha de quartos e a tolerância explícita do parser; linhas Total inválidas para Poisson não produzem lambda conhecida. |
| Disponibilidade | O replay original determina a disponibilidade conjunta; features necessárias não podem ser `None`. Metadados omissos não são inventados. `None` em metadados de admissão significa falta de evidência e não é usado como prova de inexistência. |
| Subconjuntos | Cada mercado é subconjunto das mensagens; interseções têm limites superior e de inclusão-exclusão; episódios `1..n`; movimentos não excedem mensagens do mercado. |
| Sinais/runs | O sinal usa o teste original estrito `>0.05`/`<-0.05`; zeros são removidos antes de contar runs e reversals. Enumeram-se contagens e comprimentos de runs alternadas, incluindo a paridade entre direções inicial/final. Diferenças binárias próximas de 0,05 não recebem uma fronteira artificial de 0,0501 na prova de impossibilidade. |
| Observado/não observado | Extremos e net referem todos os pontos; path soma apenas movimentos dentro das mensagens. `net - unobserved_net` é a soma assinada observada. Nenhuma mudança de cotação não observada implica drift não observado nulo; cada gap tem amplitude máxima 11,95 em lambda. |
| Dispersão/extremos | `sd <= (12-.05)/2 = 5.975`; path e diferença de extremos respeitam limites derivados do mesmo conjunto de `2m` pontos. Com um Total: `path=abs(net)` e `sd=abs(net)/2`, com intervalos de arredondamento. O replay verifica as relações completas mesmo quando as condições necessárias não decidem. |
| Tempo | Cada resumo temporal arredondado `x` representa um intervalo exterior `[max(0,x-.05),x+.05]` minutos; os extremos de empate são incluídos conservadoramente. Esses intervalos têm de permitir `lead_first-lead_last=span`, `max_gap<=span` e `span<= (n-1)*max_gap`. Um evento tem span/gap zero. |
| Velocidade | Usa o **net já arredondado**, dividido pela duração positiva entre a primeira e última mensagem **Total**, em horas; essa duração não excede o span global. O valor final tem intervalo de meia unidade na quarta casa. Accel exige pelo menos três mensagens e duas durações positivas. |

Os intervalos exteriores só são usados para provar impossibilidade. O certificado
SAT percorre o arredondamento real e os timestamps reais, em segundos como nas
fontes normalizadas. A tolerância de **três segundos** continua a aplicar-se à
comparação de um lead inferido com uma fronteira cronológica; não torna
`lead_first_min=120.01` um valor admissível.

### Admissão de observações

A B1 exige agora `producer_witness` nos metadados de admissão: objeto com
`contract`, `kickoff_utc`, `competition` e `events`; cada evento contém
`event_id`, `observed_at`, `trigger_market`, `snapshots`. O replay deve reproduzir
**todos os valores fornecidos e conhecidos**, a disponibilidade das features
necessárias, o kickoff e a decisão. Não há alteração do produtor operacional
para fornecer ou adaptar esse certificado. Uma fonte sem certificado recebe
`OBSERVATION_PRODUCIBILITY_UNPROVEN`; uma incompatibilidade demonstrada recebe
`PRODUCER_WITNESS_MISMATCH` e/ou `TRAJECTORY_INVARIANTS_VIOLATED`.

Esta é uma prova matemática de produzibilidade, não uma autenticação de eventos.
Continua em falta o adaptador de proveniência de confiança. Valores inválidos,
incluindo os fornecidos em campos que o plano não utiliza, são verificados.
Nenhuma linha excluída entra no suporte pré-jogo, elegibilidade, suporte por
período ou OOS. Contagens brutas, braços computáveis e razões de exclusão ficam
preservados; FT e baseline são consultados depois da atribuição pré-jogo.

Os positivos antigos usavam resumos escalares aleatórios que não representavam
trajetórias: por exemplo, alteravam net sem os extremos e deixavam leads/span/gap
independentes. As permutações puramente lógicas usam quatro linhas válidas e continuam a
exercitar a prova antes da admissão; os testes de contabilidade mantêm as
amostras completas de 600/200 linhas. Os positivos B1 foram substituídos por mensagens que o produtor
real transforma em resumos. Alterações intencionadas de um positivo (linha,
competição, janela) regeneram as mensagens; as mutações adversariais continuam
a adulterar apenas o campo em teste. A antiga expectativa de que
`p_home_net=1` fosse SAT também foi retirada: preços válidos e normalização de
três probabilidades tornam esse extremo impossível.

### Matriz reproduzível F01–F08

Os resultados abaixo exercitam diretamente `_path_constraints`/`prove_path` e
`_arm_separation`; não dependem de o desenho ultrapassar materialidade, suporte
ou outro ramo exterior. O teste `test_f01_to_f07_direct_both_arms_orders_and_or_paths`
repete cada caso no sinal, controlo, OR e permutações de AND.

| Caso | `198bdf1c` | Correção | Prova/testemunha | Teste reproduzível | Elegibilidade na amostra de 200 linhas |
|---|---|---|---|---|---|
| F01: up=1 e max_run=0 | SAT | UNSAT | Um movimento não nulo exige um run de comprimento >=1. | `test_f01_to_f07_direct_both_arms_orders_and_or_paths`; oráculo de sequências | Uma linha adulterada: G 100→99, C 100; excluída também do pré-jogo e OOS. |
| F02: sd>6 | SAT | UNSAT | Popoviciu sobre pontos em `[.05,12]`: sd<=5.975. | Mesmo teste; amostragem independente de cotações | G 100→99; C intacto. |
| F03: changes=0 e unobserved_net=1 | SAT | UNSAT | Cotações iguais em todos os gaps implicam lambdas iguais nesses gaps. | Mesmo teste; mutações do certificado | G 100→99; C intacto. |
| F04: n=2 e share=.3333 | SAT | UNSAT | O quociente arredondado vem de um numerador inteiro: somente 0, .5 ou 1. | Mesmo teste; enumeração dos numeradores | Share adulterado numa linha n=2: G 100→99. |
| F05: net>=.1, velocity=0, span<=60 | SAT | UNSAT | Zero arredondado exige magnitude da velocidade <=.00005/h; duração <=60.05 min não permite net>=.1. | Mesmo teste; limites de duração | G 100→99; C intacto. |
| F06: leads 120/60, span=1 | SAT lógico; observação admitida | UNSAT; observação excluída | Intervalos de arredondamento das três grandezas não se intersectam na identidade temporal. | `test_admission_quantization_time_and_full_certificate` | G 100→99, pré-jogo 100→99, OOS total 200→199. `120.01` também excluído. |
| F07: n=3, span=60, max_gap=10 | SAT lógico; observação admitida | UNSAT; observação excluída | Dois gaps de até 10.05 min não cobrem um span mínimo de 59.95 min. | Mesmo teste | G 100→99; total bruto continua 200; uma exclusão detalhada. |
| F08: net>=.1, total_msgs=2, up=2; controlo reversals=1 | `LOGICAL_GROUP_CONTROL_OVERLAP` com falsa testemunha | Interseção UNSAT; braços separados | Dois movimentos positivos ocupam as duas mensagens Total; nenhum negativo permite uma reversão. | `test_f08_separation_uses_joint_proof_and_overlap_certificate` | Remove apenas a falsa rejeição lógica por sobreposição; suporte/FT/OOS continuam independentes e obrigatórios. |

Limites de cada linha: estas provas resolvem os casos explicitados, não afirmam
completude do fragmento. Uma interseção geral não resolvida produz
`CONTROL_DISJOINTNESS_UNPROVEN`, sem afirmar sobreposição. Um controlo neutro
válido conserva SAT e separação demonstrada. A propriedade de sobreposição
verifica que a testemunha satisfaz ambos os braços e todos os invariantes.

### Oráculos, regressões e comandos

`tests/test_research_quality_joint.py` enumera strings de sinais com um oráculo
independente do algoritmo de runs. A seleção reconstruída tem **601 conjunções:
54 possíveis e 547 impossíveis**. Não é a seleção original do auditor com 553
impossíveis. São verificadas as duas direções: impossíveis nunca recebem SAT;
nenhuma das 54 possíveis recebe UNSAT, e todas as 54 obtêm SAT com certificado.
O mesmo conjunto foi executado nos dois commits históricos:

| Código avaliado | Impossíveis com SAT / 547 | Possíveis com SAT / 54 | Possíveis com UNSAT |
|---|---:|---:|---:|
| `fbab0d53f7298c215f56fc5b7db27c02a2770c47` | 547 | 54 | 0 |
| `198bdf1c480b8d3e1938f26f5268451499264400` | 44 | 54 | 0 |
| Contrato corrigido | 0 | 54 | 0 |

O script `scripts/lab_research_b1_oracle.py` emite cada uma das 601 entradas,
a classificação do oráculo e a classificação obtida; permite investigar cada
falso positivo, incluindo os 44 observados diretamente no ramo auditado de
`198bdf1c`. Acrescenta **43 cenários reconstruídos**, **10 verificações
suplementares reconstruídas**, F08 e hashes dos ficheiros de implementação.
As 52 sondas originais e a comparação individual dos 553 casos permanecem
pendentes de receção dos documentos/inputs originais.

Há ainda 250 casos gerados com cotações e timestamps aleatórios independentes
do solver, confrontados com o produtor original, a admissão e a prova lógica;
e uma execução exploratória adicional de 1 500 trajetórias multimercado sem
falsas rejeições nas condições necessárias. As propriedades cobrem AND/OR,
controlos neutros, monotonicidade da exclusão, OOS, limites UNKNOWN e a
independência dos braços face à disponibilidade de FT/baseline.

```sh
python -m unittest discover -s tests -p 'test_research_quality*.py' -v
python -m unittest discover -s tests -p 'test_research_*.py' -v
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p 'test_v6_offline*.py' -v
python scripts/lab_research_b1_oracle.py --repo /tmp/b1-rejected-198 --output /tmp/b1-before.json
python scripts/lab_research_b1_oracle.py --repo /tmp/b1-historical-fbab --output /tmp/b1-historical.json
python scripts/lab_research_b1_oracle.py --repo . --output work/b1-diagnostics/joint-oracle.json
python -m scripts.lab_research_quality --source-root /tmp/b1-source-ede8 --output joint-replay.json
python -m scripts.research_isolation_check --base 198bdf1c480b8d3e1938f26f5268451499264400
```

Os três worktrees de reprodução usam, respetivamente, `198bdf1c`, `fbab0d53`
e `ede8b771cc20a9236a0163df47ce2f6e7e915b25`. O script recusa sobrescrever
outputs existentes. A UI deve executar também os cinco ficheiros diretamente
com `node`, para expor os 30 testes UI e sete scheduler; neste runtime Node 24,
o comando agregado `node --test` apresentou apenas cinco resultados por ficheiro.

**Segurança preservada:** `TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE`,
`promotion_eligible=false`, zero experiências B1, zero promoções e zero LLM real.
Sem alterações H1, E5, Telegram, FT, Pages, históricos, memória, ledgers, gates,
quotas ou workflows. As suites do sistema existente usam apenas mocks, repositórios
temporários e ciclos TEST. Nova auditoria independente necessária; **não fazer
merge sem autorização expressa**. A reprodução literal dos documentos ausentes
não está concluída e não deve ser inferida dos testes reconstruídos verdes.
