# MASTER BRAIN — bloqueios da PR #170

**ESTADO: snapshot segmentado regenerado apenas na branch da PR — NÃO MERGE NEM ATIVAR.** O workflow FT em modo dual, `CURRENT.json`, manifesto, shards, mirror legacy e baseline FT estão na mesma árvore Git. A geração usa os blobs `776cbb82681414e483ba2db7d6f2aa27b51cf155` (discovery) e `a6f18cd198ef65800500435c02e593994033b97e` (FT) observados em `28315deb716c6df1d3af45221743777ec3c7c55d`. Testar novamente antes de uma integração devido a avanços constantes da main.

## Implementado na PR

- Modo dual estrito, preflight sem fallback e publicação FT com um único push sem rebase antigo.
- Selagem da árvore Git (mirror, CURRENT/PREVIOUS, shards, manifesto, arquivo gzip) e rollback CAS do par.
- Baseline de 349 FT FINAL por chave/identidade/resultado; os 331 existentes anteriormente permanecem inalterados.
- Inventário estático de leitores conhecidos: não comprova caminhos dinâmicos.
- Limite do mirror legacy de 2 MB continua em vigor.

## Critérios obrigatórios antes de eventual merge

1. Confirmar novamente que `main` contém exatamente os blobs do relatório `DISCOVERY_CUTOVER_PINNED_SNAPSHOT.md`; se mudar um, regenerar snapshot e baseline.
2. Auditoria manual de todos os leitores, incluindo imports e paths dinâmicos, compatibilidade Pages e workflows concorrentes.
3. CI completa verde, prova da integridade byte-a-byte e de todos os FT FINAL, com rollback Git remoto ensaiado contra corrida e sem regressão.
4. Otimizar ou aceitar explicitamente o tamanho do gzip; validação da capacidade do repositório e de todos os limites.
5. Aceitação após execução real agendada, watchdog e Pages 24h/48h/7d. Não antecipar estabilidade.
6. Autorização expressa adicional antes de integrar ou ativar.

**Produção H1, estratégias, Telegram, quotas e providers intocados.** Nenhum workflow de produção foi iniciado por esta preparação.
