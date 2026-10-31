# Snapshot autoritativo FT e descoberta (somente PR)

- Histórico congelado em blob Git: `4f5888c0938fb5d1123f5ed277cbd3139914f987`
- FT ledger congelado em blob Git: `9ece1de88a782a89271bc8724fa0b6b177470f05` (FINAL existentes: 363)
- Geração: `d27b3f295bfb58135dbd2d5fa55af4b1b9ab6b3aa9776ba0fbded09352096d3e`
- SHA manifesto: `22e52b4247d3316aa9ec7d304663d556f88669472c9d4f211a9f1b5dfa35ef65`
- Segmentos: 7 (até 256000 bytes cada)
- Arquivo gzip: blob `e7f6e500aa785f7cdc1d7e7be583032140768f0b` (DEFLATE sem compressão de conteúdo, recuperação exata)
- Backend pretendido após cutover: `segmented` sem mirror corrente; o antigo `data/lab/discovery-state.json` fica apenas como snapshot histórico.

**Não ativado.** Só integrar após validar que os blobs fonte atuais ainda coincidem e CI, rollback, Pages, H1, Telegram e FT FINAL continuam íntegros. Mudança no workflow e primeiro snapshot têm de estar no mesmo commit.
