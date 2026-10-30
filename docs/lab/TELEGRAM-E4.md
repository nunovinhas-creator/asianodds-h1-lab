# MASTER BRAIN — Telegram E4, isolada e combinada (30/10/2026)

## Âmbito da alteração

Apenas as **notificações do Telegram** foram alteradas. O coletor H1, todas as cinco regras de deteção, análises, dashboard, LAB e liquidação FT continuam intactos.

O único emissor automático ativo no workflow de recolha é `python -m h1lab.e4_notify`. São silenciadas, para novos envios, as estratégias E1, E2, E3 e E5 quando não existe E4; os antigos emissores de Pattern Watch, H1, triplas e cinco estratégias V5 não são executados automaticamente.

## Dois grupos exclusivos

- **🟢 E4 ISOLADA — Over 2,5:** E4 (P5-d92fc19ce8) é a única regra V5 válida no jogo. Linha Total última ≥3,25 e ausência comprovável de enfraquecimento do último episódio.
- **🟣 E4 COMBINADA — Over 2,5:** E4 é válida e pelo menos uma de E1, E2, E3 ou E5 também é válida. Identifica os números das outras regras apenas como contexto; **não emite apostas ou mensagens de E1/E2/E3/E5**.

A classificação depende de `candidate_matches` e de evidência V4 explícita, exatamente como antes, não de resultados finais. Quando E4 se mantém ativa mas passa de isolada a combinada (ou inverso), envia uma mensagem `🔄 AGORA` uma única vez por mudança. Se nova evidência V4 provar que E4 deixou de valer, avisa `❌ SAIU DA E4`; a falta de dados não constitui uma saída confirmada.

## Início imediato e continuidade

O novo ledger `data/e4-notifications.json` é separado de `data/strategy-notifications.json`, que fica preservado para auditoria e deixa de gerar envios. A **primeira execução real do novo emissor** envia todos os jogos E4 elegíveis ainda por começar nas próximas 12 horas, mesmo que já tenham recebido uma mensagem do antigo emissor; um recibo novo impede repetições futuras. Não há limite rígido de seis jogos. A ordem é por hora de início e existe pausa de 1,2 s entre mensagens.

Só os jogos futuros entram. Um envio incerto não é repetido automaticamente, para evitar duplicação. Sem `TG_BOT_TOKEN` e `TG_CHAT_ID`, não há envio nem recibo consumido. Os outros workflows técnicos continuam em funcionamento, incluindo recolha, H1 results e FT.

A mensagem mostra jogo, hora de Portugal, categoria E4, outras estratégias detectadas (apenas na combinada), histórico geral E4 e amostra de 29/10/2026. **A amostra de 29/10 é descritiva, pequena e não prova rentabilidade**. Não há odds de entrada nem EV comprovado.

## Verificação

```bash
python -m h1lab.e4_notify --dry-run
python -m unittest tests.test_e4_notify -v
python -m unittest discover -s tests -v
```

O `--dry-run` não envia nem guarda recibos. A alteração ao `.github/workflows/collect.yml` gera um `push` em `main` quando a PR é integrada, disparando de imediato o workflow de recolha; os novos alertas dependem da conclusão da etapa de recolha e da disponibilidade do Telegram.
