> **Atualização de contexto (28/10/2026):** este catálogo de equivalências revisto por jogo é **evidência histórica restrita a jogos identificados**. Não é uma normalização automática universal. A recuperação posterior integrou fontes adicionais e controlo `SOURCE_ORDER_CONFLICT`, e [ft-results.json](ft-results.json) tornou-se a fonte da cobertura corrente. Ver [integridade casa/fora](SOURCE-ORDER-INTEGRITY.md) e [arquitetura](ARCHITECTURE.md).

# LAB — Recuperação de FT por nomes de equipas revistos (28/10/2026)

## Evidência real e problema identificado
O run de diagnóstico `Lab - FT identity and regulation forensic probe` (08:04 UTC, 28/10/2026) consultou 200 jogos SportScore de 27/10. Para 60 jogos sem FT, encontrou **7 pares com nomes idênticos** e **16 pares com nomes diferentes mas forte correspondência de equipas e horário**. O LAB anterior só aceitava igualdade dos nomes normalizados e ignorava estes candidatos.

Alguns exemplos confirmados na análise dos alertas e da lista do fornecedor:
- Dinamo Zagreb – HNK Rijeka ↔ Dinamo Zagreb – Rijeka.
- Bristol City U21 – Millwall FC U21 ↔ Bristol City U21 – Millwall U21.
- FK Ludogorets Razgrad B – PFC Dobrudzha Dobrich ↔ Ludogorets Razgrad II – FC Dobrudzha Dobrich.
- FC Koper – NK Maribor ↔ FC Koper – Maribor.

## Solução implementada
- O arquivo puro `h1lab/lab_reviewed_aliases.py` conserva 16 pares explícitos observados no relatório forense. A chave é o `match_key` original, com os nomes casa/fora **e** a hora de início UTC exatos.
- A SportScore compara nomes exatos como sempre. Se não coincidirem, só aceita um par presente nesse mapa e apenas se os nomes originais e hora do alerta permanecerem idênticos ao registo analisado. Os nomes da SportScore têm de corresponder exatamente ao par autorizado. **Não há fuzzy matching dinâmico, pesquisa de equipas similares ou apelidos globais.**
- Todos os candidatos continuam sujeitos à regra de identidade por hora ±90 minutos, unicidade do evento, confirmação de terminado, hora regulamentar e marcador inteiro. A origem do marcador é sempre identificada como `sportscore_only` se não existir corroborante independente.
- As competições `Cupa` da Roménia foram incluídas explicitamente na regra de taças. Um marcador com `status_text=Finished` não comprova 90 minutos em taças. Permanece por verificar, mesmo com equipas idênticas.
- Os 16 jogos analisados passam à frente da fila normal **uma única vez**, mesmo que a tentativa anterior ainda estivesse no período de cooldown. Depois, continua a vigorar a espera normal de quatro horas; não há bypass recorrente.
- O relatório regista `reviewed_alias_catalog_matches` e `sportscore_search.reviewed_alias_ft_in_run`. Esses contadores não são ROI nem provam vantagem estatística.

## Limitações e auditoria
O facto de dois nomes e uma hora coincidirem num lote de um fornecedor não constitui verificação independente do resultado. Os jogos de taça continuam sem FT quando o fornecedor só indica que terminou, sem identificar os 90 minutos. O run forense tentou abrir páginas de detalhe para quatro jogos de taça, mas essas consultas não devolveram conteúdo utilizável. Nenhum resultado foi inferido.

Verificações: `python -m unittest discover -s tests -p 'test_lab_reviewed_aliases.py' -v` + regressões completas. O workflow LAB FT recolhe e publica apenas `data/lab/ft-ledger.json` e `docs/lab/ft-results.json`.

**H1 mantido inalterado**, incluindo cron de cinco minutos, ficheiros de sinais, picks, triplas, Telegram e resultados oficiais H1.
