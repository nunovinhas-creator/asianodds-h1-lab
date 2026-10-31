# MASTER BRAIN — PR de ativação produtiva FT em modo duplo

**ESTADO: CANDIDATA / NÃO INTEGRAR NEM ATIVAR AINDA.** Esta PR altera de verdade o workflow `.github/workflows/lab-ft-results.yml`, mas NÃO pode ser integrada até que o primeiro snapshot segmentado (CURRENT, manifestos, shards e recuperação histórica) seja preparado no mesmo commit de ativação e a revisão de leitores esteja completa. O GitHub CI verde por si só não autoriza esse primeiro arranque.

## O que a PR altera

- O produtor de descobertas usa `python -m scripts.lab_discoveries --state-backend dual`, sem fallback silencioso.
- Antes de cada ciclo, exige o CURRENT segmentado íntegro e **byte a byte igual** ao mirror `data/lab/discovery-state.json`. Não cria CURRENT automaticamente. Uma ativação incompleta bloqueia o job FT em vez de escrever fora do formato.
- Congela uma baseline temporária dos registos FINAL do `data/lab/ft-ledger.json` com `match_key`, `status`, `home`, `away`, `kickoff_utc` e conteúdo completo do `result`. Antes da publicação, o guard recusa a perda, mudança de identidade ou alteração de qualquer resultado FINAL anterior; novos FINAL são permitidos.
- Coloca no índice Git cada objeto CURRENT/PREVIOUS relevante, manifesto, shard e arquivo de recuperação binário, antes de adicionar os resultados FT normais. O `publication_guard` #167 sela o conjunto completo antes de commit e verifica-o depois.
- **DISCOVERY_SEGMENTED_NO_REBASE**: elimina o ciclo de `git fetch/rebase/retry` *após* produzir FT. Fixado o SHA de entrada, depois de confirmar o commit local e o selo Git, verifica a `main` remota e faz um único `git push` normal. Se outro job atualizar `main`, falha sem force e sem rebase de observações antigas. O próximo ciclo normal terá de recolher e recomputar os dados sobre o estado atualizado.
- Acrescenta um mecanismo local de **rollback conjunto**: requer CAS do CURRENT, valida a geração atual e a anterior, substitui o mirror e inverte CURRENT/PREVIOUS sob o mesmo lock local e obriga à preparação/publicação manual conjunta. Se houver interrupção a meio, os leitores duplos falham explicitamente; não recuperam por fallback implícito.
- Mantém os limites das APIs e o número de consultas FT, sem mudanças H1, Telegram, estratégias ou regras de admissão.

## Ensaios incluídos

Os testes usam ficheiros temporários e remotos Git bare: ausência/corrupção do CURRENT; concorrência entre dois writers; recusas de perda, rebaixamento e alteração de identidade/resultado FINAL; atualização remota concorrente; publicação não-forçada; rollback conjunto; interrupção simulada após substituir o mirror; revisão do workflow contra rebase de FT antigo.

## BLOQUEIOS DE INTEGRAÇÃO (não dispensáveis)

1. **Primeiro snapshot em falta:** produzir a partir da `main` atualizada, com `prepare --expected-head <SHA>`, e acrescentar ao **mesmo commit de ativação** o workflow alterado e todos os ficheiros `data/lab/discovery-segmented/` alcançáveis. A main normal não tem `CURRENT.json`. Esta PR de código isolada NÃO está preparada para merge.
2. **Leitores:** inventário definitivo (não apenas heurístico) dos scripts, monitores, publicadores e qualquer processo que leia `discovery-state.json`. Todos os leitores que mantenham acesso ao espelho legado deverão ter igualdade verificada antes da sua execução ou ser transferidos para o loader duplo. Testes de leitores em conjunto e simulador offline ainda necessários.
3. **Rollback Git remoto:** verificar que a preparação local de rollback apenas pode chegar a `main` através de commit com ambos mirror/CURRENT/PREVIOUS e selo completo; testar conflito de ref no rollback e impossibilidade de regressão de FT certificado.
4. **Congelamento de prova:** comparar TODOS os registos FINAL atuais por match_key antes/depois do primeiro cutover; guardar SHA e contagem de eventos/arquivos e verificar manifesto público e páginas de padrões.
5. **Aceitação operacional:** CI verde, zero conflitos, validação de origem/competição FT, uma execução real agendada com todos os limites e watchdog/Pages estáveis, prova de integridade 24h/48h/7 dias sem perdas. Interromper em caso de divergência, sem forçar.
6. **Permissões e corte:** autorização **expressa adicional** para o primeiro commit de bootstrap e a integração produtiva da PR. O merge não será feito automaticamente.

## Limite de capacidade

A fase dual preserva o mirror obrigatório com o limite **2.000.000 bytes**. Portanto, mesmo após esta mudança, a falta de capacidade histórica ainda não fica resolvida. O corte posterior para armazenamento segmentado autoritativo sem mirror corrente exige outra PR de transição, testes e autorização específicos.

**Separação imutável:** não tocar no H1, `results.yml`, alertas Telegram, estratégias, CORE_NAME, quotas ou certificados FT antigos. Relacionado com issue #107 e PRs #162, #164–#168.
