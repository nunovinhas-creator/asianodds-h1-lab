# Snapshot segmentado atualizado — revisão, NÃO ativado

- Main de origem: `28315deb716c6df1d3af45221743777ec3c7c55d`; fontes protegidas pelos blobs (independentes de atualizações não relacionadas em main).
- Legado Git blob: `776cbb82681414e483ba2db7d6f2aa27b51cf155` (1670410 bytes)
- FT ledger Git blob: `a6f18cd198ef65800500435c02e593994033b97e` (1488064 bytes)
- Geração SHA-256: `ecf8e6596caf14bd1af2d844b1e4ce2fd65888f7ff5cb1c1897d4d6d980e441c`
- Manifesto SHA-256: `99bc1048b60a699fb31ac924697d2cf97ec429d1dd41d1651f1f9fa094dc1099`
- Segmentos: 7 até 256000 bytes.
- FT FINAL congelados individualmente: 349; todos os 331 FINAL da baseline anterior preservados.
- Arquivo gzip: validado por formato DEFLATE armazenado (sem compressão efetiva, tamanho 1670558 bytes); otimizar a compressão antes de qualquer promoção definitiva.

**NÃO MERGE.** Revalidar blobs atuais no instante de integração, CI, leitores dinâmicos, rollback, Pages, FT e watchdog. Qualquer alteração posterior de `discovery-state.json` ou `ft-ledger.json` exige nova geração e baseline.
