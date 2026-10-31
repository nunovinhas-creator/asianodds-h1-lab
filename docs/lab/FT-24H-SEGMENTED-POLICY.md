# MASTER BRAIN — FT verificável em 24 horas e armazenamento segmentado

## Política vigente
- Confirmação FT **até 24h após kickoff UTC**. Passado esse limite, um jogo não verificado fica `EXPIRED_UNVERIFIED`, sem novas chamadas às APIs. Conserva-se apenas o identificador mínimo para não o recuperar indevidamente e para medir cobertura.
- **Uma única fonte credível** é suficiente se os nomes/identidade/competição e o resultado de 90 minutos forem corretamente validados. Resultados incompatíveis não são selecionados arbitrariamente.
- Cada `FINAL` certificado mantém a pontuação e identidade imutáveis: o job regista um baseline antes de reconciliar e verifica-o antes de publicar.
- `segmented` substitui a escrita no mirror legado de 2 MB. `CURRENT`/`PREVIOUS`, shards de até 256 kB, SHA-256 e gzip recuperável são selados numa transação. Mantém-se um limite defensivo de **20 MB por estado**, não armazenamento ilimitado.

## O que já foi ativado e o problema confirmado
A PR #172 foi integrada em 31/10/2026 e o workflow produtivo já chama `--state-backend segmented`. No entanto, os ciclos FT de 21h56 e 22h31 **não publicaram** porque commits H1/V4 chegaram durante a reconciliação. Os logs das 22h31 confirmam 363 `FINAL` originais, dois novos FT candidatos, zero revisões, integridade dos shards preservada e bloqueio de commit remoto com `FT_REMOTE_CONFLICT_RERUN_WHOLE_RECONCILIATION`.

## Correção de publicação proposta — PR #174
O comando `python -m scripts.lab_ft_publish_safe --base "$FT_BASE_HEAD" --manifest "$RUNNER_TEMP/publication-seal.json" --baseline "$RUNNER_TEMP/ft-certified-baseline.json"` substitui o bloqueio por ref absoluto.

1. Congela o **commit FT original já certificado** e verifica o selo integral, as pontuações FINAL e o conjunto exato de alterações.
2. Faz `fetch` do `main` atual. Recusa alterações concorrentes a qualquer artefacto FT ou selado, ficheiro de código/workflow, segmentação, identidade existente de jogos H1 ou journal histórico reescrito. Reconhece apenas mudanças H1/V4 comprovadamente independentes, incluindo arquivos V4 estritamente append-only.
3. Num índice Git temporário, constrói uma árvore do `main` mais recente, aplicando **apenas** os ficheiros originais FT, byte a byte. Preserva integralmente os novos dados H1/V4; não invoca fornecedores nem recalcula FT.
4. Cria um commit novo com pai `main` atualizado via `git commit-tree`, sem `git rebase`. Repete a prova de publicação, o baseline FT e a selagem da segmentação antes de permitir o push normal, sem `--force`.
5. Uma corrida `non-fast-forward` durante o push desencadeia no máximo mais cinco novas verificações e reconstruções sobre o remoto atual. Qualquer alteração relevante ou erro não relacionado com concorrência aborta imediatamente.

As estatísticas publicadas refletem o instante de recolha original; novos jogos observados durante a reconciliação entram no ciclo seguinte, e não são apresentados como FT resolvidos.

O sistema pode remover gerações segmentadas antigas já inacessíveis a partir dos ponteiros `CURRENT/PREVIOUS`. Os objetos antigos continuam recuperáveis na história Git; a prova de publicação só exige os membros atualmente alcançáveis.

## Critérios de conclusão em produção
CI verde e ausência de conflitos; depois, a primeira publicação real deve registar `FT_ATOMIC_PUBLISHED` e aumento de `FINAL` só por resultados comprovados, com zero FT anteriores alterados. Conferir `docs/lab/ft-results.json`, `CURRENT/PREVIOUS`, páginas públicas, watchdog, H1 e Telegram. Validar comportamento em 24h/48h/7d.

**A implementação da PR #174 não é por si só evidência de recuperação produtiva. Não publicar nem integrar uma PR com testes falhados.**
