# MASTER BRAIN — PR de ativação produtiva FT em modo duplo

**ESTADO: SNAPSHOT INICIAL PREPARADO NA PR, MAS NÃO INTEGRAR NEM ATIVAR AINDA.** O commit `3324f0dafe12c8aa78c69d382ffa8475f482811b` reuniu no mesmo conjunto atómico a alteração do workflow FT, `CURRENT.json`, sete shards, manifesto e arquivo de recuperação, a partir da main `9f21e4dd6b8ba0cc84099ec50819d293274674d1`. Os 331 registos FINAL foram congelados individualmente em `reports/FT_CUTOVER_FROZEN_FINALS.json`. **Este snapshot está apenas na branch da PR e pode ficar desatualizado se a main produtiva avançar.** Os restantes bloqueios de integração são independentes da presença dos ficheiros; CI verde, por si só, não autoriza o corte.

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

1. **Snapshot existente mas pin congelado:** a primeira geração e o workflow estão juntos na branch da PR, **não na produção**. Antes de qualquer integração é obrigatório comparar de novo o commit de origem com a main efetiva, incluindo os blobs de `discovery-state.json` e `ft-ledger.json`, reconstituir a geração se necessário e repetir integralmente os testes. `CURRENT.json` continua ausente da main produtiva. É proibido integrar um snapshot antigo contra um estado FT mais recente.
2. **Leitores:** `scripts/lab_discovery_consumer_audit.py` percorre **todos os ficheiros de código rastreados pelo Git** nos diretórios produtivos e exige classificação explícita das referências literais ao estado. Não confundir isto com prova exaustiva dos caminhos construídos dinamicamente: continuam necessários revisão manual de imports dinâmicos, concorrência entre workflows e ensaio ponta-a-ponta dos consumidores. A leitura do espelho no produtor dual passa obrigatoriamente por `dual.load` com igualdade byte-a-byte; a API pública lê o manifesto paginado, não a mirror privada.
3. **Rollback Git remoto:** verificar que a preparação local de rollback apenas pode chegar a `main` através de commit com ambos mirror/CURRENT/PREVIOUS e selo completo; testar conflito de ref no rollback e impossibilidade de regressão de FT certificado.
4. **Congelamento de prova:** já existem 331 FINAL individualmente identificados no snapshot inicial e teste que recusa qualquer alteração às suas equipas, data, resultado ou certificação; **revalidar e atualizar todos os FINAL** no verdadeiro instante do cutover e conferir SHA, eventos/arquivos, manifesto público e páginas. Não afirmar comparação produtiva antes/depois: a produção continua em legacy.
5. **Aceitação operacional:** CI verde, zero conflitos, validação de origem/competição FT, uma execução real agendada com todos os limites e watchdog/Pages estáveis, prova de integridade 24h/48h/7 dias sem perdas. Interromper em caso de divergência, sem forçar.
6. **Permissões e corte:** autorização **expressa adicional** para o primeiro commit de bootstrap e a integração produtiva da PR. O merge não será feito automaticamente.

## Limite de capacidade

A fase dual preserva o mirror obrigatório com o limite **2.000.000 bytes**. Portanto, mesmo após esta mudança, a falta de capacidade histórica ainda não fica resolvida. O corte posterior para armazenamento segmentado autoritativo sem mirror corrente exige outra PR de transição, testes e autorização específicos.

**Separação imutável:** não tocar no H1, `results.yml`, alertas Telegram, estratégias, CORE_NAME, quotas ou certificados FT antigos. Relacionado com issue #107 e PRs #162, #164–#168.
