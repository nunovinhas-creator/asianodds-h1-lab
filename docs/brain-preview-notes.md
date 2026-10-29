# MASTER BRAIN — Interface clara em seis áreas (pré-visualização)

Estado: **PR em rascunho; produção não alterada**. Ficheiro de entrada: `docs/brain-preview.html`. Não modifica `index.html`, H1, recolha, autenticação, crons ou resultados.

## O que mostra

1. **Hoje:** observações pré-jogo do relatório `pattern-watch.json`, inclusive jogos já iniciados na fotografia antiga (identificados como tal, sem fingir dados live). Padrões históricos associados por **definição V5 verificável**, com amostras e taxas, e rótulo de associação retrospetiva.
2. **Passado:** hipóteses individuais e combinações do relatório V5, sem transformar frequências em probabilidade de vitória futura.
3. **Sinais positivos:** padrões individuais com pelo menos 12 FT em ambos os grupos e diferença observada ≥ 8 pontos percentuais. Limiar **editorial de triagem**, não critério científico ou estatístico de promoção.
4. **Estratégias:** cruzamentos históricos distintos das hipóteses formalmente registadas no V6.2 e das regras V5 congeladas. Não promover hipóteses pós-hoc a prospetivas.
5. **Comprovadas:** apresenta estado V5 e requisitos científicos V6.2; não considera um sinal exploratório uma estratégia comprovada.
6. **Histórico e métodos:** cronologia, FT associados a deteções, ligações aos registos e comprovativos.

## Associação conservadora por `match_key`

`brain-pattern-link.js` é uma biblioteca JavaScript testável com `node:test`. Lê apenas observações realmente presentes no relatório **pré-jogo**, e compara `definition` (`HAS`, `AND`, `AND_NOT`) das hipóteses do V5. Usa **lógica trivalorada**: verdadeiro, falso ou desconhecido. Um `AND_NOT` só corresponde quando o facto negativo é comprovadamente falso; um dado de mercado em falta não é contado como ausência do movimento.

São avaliáveis, quando completos: número de mensagens, episódios distintos, direções e ritmos de episódios, horário do primeiro/último alerta, linha Total explicitamente V4 e movimentos de lambda que constem das mensagens. Um movimento de linha na última mensagem só prova a sua presença, **não prova a ausência anterior**. Os limites usam constantes fixas do `h1lab/pattern_features.py` em vez de um novo modelo estatístico.

Permanecem **desconhecidos** quando não constam dos dados: handicap asiático, direção das probabilidades 1X2, gatilho do alerta, preços completos, transições não observadas e o lambda líquido entre a primeira e última fotografia do jogo. Este último **não** equivale à soma dos deltas `Was→Now` de cada mensagem. O algoritmo omite padrões não verificáveis; não completa campos por nome da equipa, campeonato ou probabilidade inventada.

O catálogo apresentado (`patterns` + `combinations_top`) é apenas o **subconjunto publicado** do V5, não a totalidade dos 800 testes. A ausência de correspondências não é uma conclusão negativa sobre todo o catálogo. Uma associação publicada depois da primeira deteção do jogo é sempre marcada como **retrospetiva**, nunca uma previsão congelada.

## Proveniência e observabilidade

O painel consome diretamente os JSON publicados: V5, jogos futuros, descobertas, FT, auditoria V4, V6.2 readiness/shadow/gates. Não consulta APIs pagas nem usa chaves. Em vez de um sucesso enganador, distingue:
- fonte indisponível, HTTP não-200, formato inesperado ou timeout (20 s);
- data declarada em cada fonte e idade do relatório;
- FT confirmados na fila versus FT já usados pela pesquisa (fotografias/âmbitos distintos);
- pendências de FT, gates de qualidade e de cronologia científica;
- hipóteses científicas em `INCONCLUSIVO` / `WARMUP`.

**Limite essencial:** publicar JSON e passar CI *não provam* que o coletor recebeu todos os alertas, que a publicação foi completa ou que a liquidação FT está certificada. Para transformar o estado operacional em `OK`, a auditoria integral #107 terá de cruzar logs e run IDs, commits, horários de captura e dados servidos; este painel indica expressamente a ausência dessa prova.

## Testes e aceitação antes de integrar

- `python -m unittest tests/test_brain_preview.py -v` (ou descoberta via `python -m unittest discover -s tests -v`).
- `node --test tests/brain-pattern-link.test.cjs` com fixtures de faltas de mercados, negações trivaloradas, pós-kickoff, valores de corte e auditoria contra JSON reais.
- Verificação visual em desktop e Android, links, estados de falha/desatualização e compatibilidade com GitHub Pages, **ainda não certificada por navegador real**.
- Não fazer merge ou alterar o ponto de entrada público sem autorização; a correção independente dos placeholders está na PR #108.

### Próximo contrato de dados desejável

Gerar em pipeline já existente, sem acrescentar chamadas API, um resumo compacto de *última recolha verificada → publicação confirmada → análise concluída → reconciliação FT*. Cada fonte deve expor `run_id`, `source_sha`, `published_sha`, `generated_at`, `records_seen`, `records_valid`, `records_written` e `status`, com timestamps reais e códigos de falha. Até haver esse contrato, o dashboard não afirma robustez operacional total.
