> **Documento histórico.** Descreve os protótipos V1 (`intelligence.py`) e V2 (`market_v2.py`). A arquitetura atual (V4, Golden Set, cronologia por jogo) está em [`docs/lab/ARCHITECTURE.md`](lab/ARCHITECTURE.md).

# Market Intelligence V1 — investigação separada
Esta área é **observacional**. Não altera o H1, a FIFO de triplas, a liquidação, nem as notificações.
O módulo `h1lab/intelligence.py` transforma alertas *já estruturados* em eventos deduplicados,
delta e direção de preços 1X2, totais e handicap. Resultados FT são uma tabela separada.
Não é um backtest, não cria apostas e não reivindica poder preditivo.

**Limites:** o parser legado pode omitir formatos e não normaliza BTTS nem todas as odds do canal.
O feed de Telegram é selecionado (não existe universo negativo de jogos sem alerta).
Não inferir causalidade, ROI ou probabilidade calibrada a partir das contagens.

**Próximos gates:** catálogo de formatos reais/redigidos; parser V2 testado por mercado;
persistência incremental que não aumenta indefinidamente o JSON público; cobertura BSD;
desduplicação por jogo; train/test cronológico, custos e correção por múltiplas hipóteses.

## Estado de integração Fase 1 (schema 2)
O componente ativo nesta fase é apenas `shadow_formats.py`, chamado em modo não bloqueante a partir de `cli.py`. Regista apenas classes de linhas e impressões digitais, sem texto da mensagem. `intelligence.py` e `market-intelligence.html` são **protótipos desativados** e não devem ser usados para inferir probabilidades, eficácia ou ROI; a vista de laboratório não foi ativada no menu H1. A geração de `market-intelligence.json` permanece desligada. Os ficheiros temporários `data/lab/*.tmp` não devem ser commitados.
