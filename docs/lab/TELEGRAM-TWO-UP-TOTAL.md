# Telegram MASTER BRAIN — segundo alerta independente: duas subidas Total V4

**Aditivo à regra anterior** `h1lab.three_moves_notify`. Esta implementação **não altera** a elegibilidade, a mensagem, a versão da regra nem o ficheiro de recibos da regra original. Também não ativa E4, T05, H1, triplas nem outras estratégias.

## Nova regra

Um jogo do dia ainda não iniciado ou futuro é candidato quando o respetivo histórico V4 contém:
1. **Duas ou mais subidas distintas e explícitas** da linha Total (`before → after`, `origin == V4_EXPLICIT`).
2. **Subida líquida mínima de 0,50** entre o primeiro valor anterior e o último valor posterior das subidas V4 aceites.
3. **Nenhuma descida V4 explícita** antes do início e observada até ao instante de seleção.
4. **Identidade e KO consistentes**; todas as mensagens usadas precedem o jogo.
5. **Sem duplicações**: uma mensagem repetida ou movimento ambíguo não pode somar episódios. As mudanças entre mensagens não observadas não contam.

São admissíveis outras mensagens sem movimento de linha (ex.: 3 alertas, mas só 2 subidas); a quantidade de mensagens do dashboard não é o número de subidas. Não se usam resultados FT nem inferências futuras. Ausência de uma descida observada **não demonstra** que o mercado nunca desceu entre consultas.

Os exemplos ilustrativos de 31/10 são:
- LKS Łomża – Mazovia Mińsk Mazowiecki: 3,25 → 3,75 em dois movimentos ascendentes no gráfico;
- CSyD Merlo – Arsenal de Sarandí: 1,75 → 2,25, com dois movimentos ascendentes e um terceiro alerta sem mudança de linha.

Estes exemplos não têm garantia de disponibilidade atual: um jogo já iniciado nunca gera novo aviso.

## Emissão e auditoria

`python -m h1lab.two_up_notify` corre **depois** de `python -m h1lab.three_moves_notify` no mesmo `collect.yml`, com separação de títulos:

- Regra original: `🔄 3+ MOVIMENTOS CONFIRMADOS · TOTAL`
- Nova regra: `📈 2+ SUBIDAS SEGUIDAS · TOTAL (SEM INVERSÃO V4)`

A nova rotina usa exclusivamente `data/two-up-total-notifications.json`, guarda os IDs de mensagens de origem e a ID confirmada da mensagem Telegram. Nunca lê nem altera `data/three-total-moves-notifications.json`.

Sem limite de 12 horas nem máximo de 6 jogos. O envio é único por jogo **por regra**; se um jogo cumprir ambas as regras, as duas mensagens são possíveis e explicitamente identificadas. Entregas ambíguas ficam marcadas para verificação manual, sem repetição automática.

Teste apenas de leitura:
```bash
python -m h1lab.three_moves_notify --dry-run
python -m h1lab.two_up_notify --dry-run
```

Não apagar mensagens antigas do Telegram; só acrescentar notificações de jogos futuros. Históricos H1, FT e estados de estratégias não são modificados pela nova rotina.
