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
