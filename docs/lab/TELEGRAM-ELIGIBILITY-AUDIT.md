# MASTER BRAIN — Transparência de exclusões Telegram (01/11/2026)

## Âmbito e garantias

O separador **Mercados e jogos** em `docs/h1.html#market` passa a apresentar, por jogo publicado, a elegibilidade observada das duas regras produtivas: três alterações independentes V4 da linha Total e duas subidas independentes com Δ de pelo menos 0,50 e nenhuma descida V4. O histórico visual não representa automaticamente o universo de notificações.

A classificação é calculada em `h1lab.telegram_eligibility` sobre os mesmos `collect_timelines` e validada, jogo a jogo, com `three_moves_notify.candidates` e `two_up_notify.candidates`. Qualquer divergência bloqueia o relatório e o bundle LAB, **sem** alterar os emissores ou o coletor H1. A auditoria não tem acesso aos segredos do bot, não envia mensagens, não toca em resultados FT, tickets, picks ou ledgers.

`docs/lab/telegram-eligibility.json` é um derivado pequeno (máximo 512 KB), separado da cronologia de quase 2 MB. Inclui contagem de movimentos não planos V4, movimentos aceites em cada regra, exclusões por origem legada, linha estável, repetições, ambiguidades, mesmo episódio e observações fora do intervalo pré-jogo. Contém ainda os recibos oficiais dos dois ledgers; a ausência de recibo não prova falha de entrega. Recibos de entrega incerta exigem verificação manual, sem reenvio automático.

## Falsos negativos: o que significa "possível"

O indicador `review_possible_false_negative` apenas sinaliza jogos para inspeção **quando há movimentos V4 brutos suficientes mas a independência é insuficiente**. Repetições podem ser mensagens duplicadas do mesmo movimento; uma ida e volta entre alertas sem prova temporal não pode ser inferida. **Nenhuma suspeita é promovida automaticamente a movimento válido.**

Para cada jogo cuja hora de início já passou, a auditoria não faz backtesting retroativo dos critérios como se fosse uma aposta pré-jogo. Os envios passados só são apresentados se existirem recibos históricos.

A auditoria usa os mesmos primeiros 400 jogos com vários alertas incluídos na página; o total global de candidatos é calculado sobre todas as cronologias lidas. As duas vistas são consistentes apenas quando os respetivos `source_commit` coincidem; caso contrário, a interface apresenta «aguardar auditoria».

## Operação

O workflow existente `lab-v4-audit.yml` executa `python -m unittest discover -s tests -p 'test_telegram_eligibility.py' -v` e `python -m scripts.lab_telegram_eligibility`, selando e publicando o relatório no mesmo bundle atómico. A rotina falha explicitamente por alteração de semântica das regras, ledger inválido ou relatório acima de 250 KB.

Validação local, sem envio Telegram:

```bash
python -m unittest tests.test_telegram_eligibility -v
python -m scripts.lab_telegram_eligibility
node --test tests/dashboard-ui.test.cjs
```

A geração acima só escreve o ficheiro público derivado; não deve ser executada em produção fora do workflow de publicação autorizado.
