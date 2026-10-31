# MASTER BRAIN — Plano de ativação controlada do estado segmentado

**Estado: preparação técnica, sem ativação, sem autorização de corte produtivo.** A PR de preparação acrescenta uma ferramenta explícita de libertação e testes com remotos Git locais. A automação FT e o `state_backend legacy` mantêm-se inalterados.

## Problema de segurança identificado após a #167

Publicar `data/lab/discovery-segmented/CURRENT.json` **sozinho** é perigoso: o workflow FT atual continuaria a executar o produtor em modo `legacy` e poderia escrever uma nova versão de `discovery-state.json` sem atualizar os shards. O selo #167 recusaria essa divergência, bloqueando publicações. **O primeiro commit produtivo tem de alterar simultaneamente o workflow, o armazenamento segmentado e todas as proteções de staging.**

## Barreiras implementadas nesta PR (ainda sem integração)

`scripts/lab_discovery_cutover_release.py` disponibiliza quatro comandos explícitos:

- `prepare --expected-head SHA`: valida o SHA atual e o SHA remoto de `main`, exige inputs limpos, cria o primeiro snapshot segmentado a partir do legado e **apenas coloca no índice Git** os membros relevantes verificados. Não faz commit nem push.
- `stage`: para o futuro produtor dual, coloca no índice a mirror legacy e todos os objetos CURRENT/PREVIOUS (manifesto, shards e arquivo gzip). Exclui temporários e ficheiros de bloqueio. Revalida os hashes e a igualdade exata do histórico.
- `verify`: verifica o conjunto publicado no HEAD local; não altera o Git.
- `publish --expected-parent SHA`: apenas para um **commit de transição integral e autorizado**. Exige parent SHA fixo, HEAD e remote alinhados, mudanças confinadas aos objetos segmentados e ao workflow FT, e um workflow que execute `lab_discoveries --state-backend dual`, o comando de staging e uma barreira `DISCOVERY_SEGMENTED_NO_REBASE`. Verifica o HEAD e usa apenas `git push` normal, **nunca força/rebaseia** uma produção FT desatualizada. Se outro job ganhar a corrida, falha e exige novo cálculo a partir da main mais recente.

Os testes instanciam repositórios Git temporários e remotos bare locais e verificam publicação de um commit integral, ausência de push na preparação, conflito concorrente, commit parcial, sujidade do estado, alteração de ficheiros fora do âmbito e impossibilidade de publicar ponteiros sem mudança simultânea do workflow. **Nada é executado no repositório produtivo.**

## Passos ainda necessários para a PR de ativação real

1. **Congelamento:** fixar SHA da main, SHA do histórico e do ft-ledger, lista de cada resultado FINAL com o mesmo match_key, resultado e origem. Confirmar margem do limite de 2 MB e integridade dos arquivos de eventos.
2. **Inventário de consumidores:** todas as leituras diretas do histórico nos scripts, testes, monitores, workflows, processos de replay e publicação. A lista gerada pelo pré-ensaio #164 é apenas heurística. Converter ou provar compatibilidade e ausência de fallback silencioso.
3. **Commit único de cutover:** modificar efetivamente o workflow FT para executar o dual sem auto-bootstrap e para chamar `stage` antes de `publication_guard seal`. Na fase segmentada, substituir o rebase/retry tradicional por **abortar perante alteração da main remota e reexecutar todo o produtor sobre o novo estado**. No mesmo commit adicionar todos os objetos segmentados e o espelho legado. Não ativar a rotina antiga num commit anterior.
4. **Recuperação:** definir o rollback da mirror e de CURRENT/PREVIOUS como **um único commit Git completo**, com prova da identidade do estado e proteção do ft-ledger. Nunca voltar automaticamente a uma geração anterior se a atual estiver corrompida.
5. **Ensaios de falha:** dois FT writers concorrentes, cancelamento antes de CURRENT, falta do último shard, conflito remoto após estágio, rebase/retry indevido, corrupção e rollback. Se algum ensaio falhar, não integrar a ativação.
6. **Pós-ativação:** primeiro ciclo FT natural e página pública/manifesto, contagem e comparação por jogo de todos os FINAL antigos, observação 24h/48h/7 dias. Manter o H1, estratégias e Telegram inalterados.

## Limite de capacidade não resolvido nesta fase

O `write_dual` ainda mantém um espelho obrigatório de 2 000 000 bytes. Logo, **um cutover dual bem-sucedido não aumenta a capacidade produtiva**. Para realmente deixar de depender do limite, uma PR posterior deve ativar armazenamento **segmentado como fonte autoritativa**, com todos os leitores atualizados e uma recuperação histórica comprovada. Essa mudança tem risco e autorização próprios.

**Não autorizado nesta PR:** executar bootstrap, alterar `.github/workflows/lab-ft-results.yml`, fazer push para main, mudar a certificação FT, consultar fornecedores, modificar H1/Telegram ou remover limites. Issue #107.
