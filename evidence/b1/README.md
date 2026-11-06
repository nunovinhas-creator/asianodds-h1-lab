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
