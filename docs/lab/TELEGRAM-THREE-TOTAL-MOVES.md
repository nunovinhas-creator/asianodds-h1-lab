# Telegram MASTER BRAIN — três movimentos Total (31/10/2026)

## Regra ativa

O `collect.yml` executa apenas `python -m h1lab.three_moves_notify` como emissor Telegram. As rotinas E4 (isolada/combinada), T05, cinco estratégias V5, H1/triplas e Pattern Watch continuam no repositório para auditoria e testes, mas **não são chamadas para enviar mensagens pelo workflow produtivo**. Os ledgers antigos são mantidos como registos históricos, nunca apagados.

Envia **uma mensagem por jogo** quando existem pelo menos **três movimentos distintos e diretamente observados** da linha de Total, em mensagens V4 explícitas `before→after`, recolhidas antes do início. São aceites sequências de subida, descida e inversões; não se exige um sentido ou um resultado de futebol específico. Só jogos cujo KO UTC ainda esteja no futuro. Sem limite de 12 horas, nem máximo de seis mensagens. O envio ordena pelos KO mais próximos e tem intervalo de 1,2 s entre mensagens.

## Interpretação rigorosa

O rótulo `3 alertas` apresentado no dashboard não demonstra três movimentos independentes. O motor rejeita os seguintes casos:

- Mercado Total não explicitamente registado no V4, alterações de preço sem mudança de linha ou movimento `FLAT`.
- Várias mensagens suspeitas do mesmo episódio; `SAME_MOVEMENT_REPEAT` e `AMBIGUOUS_REPEAT_OR_REVERSAL` não contam como novos movimentos.
- Mudanças entre mensagens sem observação direta, mensagens depois do KO ou posteriores ao instante de decisão.
- Identidades ou horários de início incoerentes.

O algoritmo utiliza a cronologia `h1lab.timeline` e as suas relações de episódios. O número de inversões é contado apenas entre as direções dos **movimentos V4 elegíveis**, não entre linhas interpoladas. O último preço observado não é uma odd de mercado continuamente atualizada; não se infere um resultado futuro.

## Entrega e evidência

`data/three-total-moves-notifications.json` tem um registo específico, com versão de regra, `match_key`, IDs dos movimentos e o `telegram_message_id`. O mesmo jogo não é reenviado em ciclos seguintes. Uma entrega incerta bloqueia repetição automática e exige verificação manual; a aplicação **não garante exatamente uma vez** se a execução falhar entre envio e publicação do ledger Git.

`python -m h1lab.three_moves_notify --dry-run` lista todos os candidatos futuros e pendentes sem tocar no Telegram nem criar recibos. Os testes unitários cobrem duplicações, ausência de V4, ambiguidade, temporalidade, deduplicação e contrato do único emissor.

**Corte produtivo:** este código não revoga nem apaga retroativamente mensagens antigas dentro do chat Telegram. Apenas substitui os envios futuros do workflow assim que a alteração integrar `main`. A confirmação do envio real requer o log do primeiro `collect.yml` em produção e os recibos resultantes.
