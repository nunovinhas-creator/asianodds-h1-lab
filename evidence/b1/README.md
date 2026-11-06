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

