# MASTER BRAIN — Fase 2: cronologia auditável de descobertas

**Âmbito:** investigação V5 observacional; não gera apostas, ordens, picks, EV nem ROI. O H1 e as triplas mantêm-se separados.

## Fontes e produtos

- Fonte: `docs/lab/pattern-research.json` (V5), `data/lab/pattern-watch-first-seen.json` (primeira deteção pré-jogo), `data/lab/ft-ledger.json` (FT confirmado).
- Motor: `h1lab/discovery_timeline.py`; publicação: `scripts/lab_discoveries.py`.
- Estado incremental: `data/lab/discovery-state.json`.
- **Histórico completo imutável**: `data/lab/discovery-events-YYYY-MM.jsonl` — acrescenta apenas novos eventos. Nenhum registo antigo é reescrito ou apagado.
- Dashboard estático: `docs/lab/discoveries.json` e `docs/master-brain.js` no Radar.
- Executado no `lab-ft-results.yml` depois da pesquisa e do observatório prospetivo. Sem novo workflow/cron ou chamadas a APIs de futebol.

## Baseline e diferença determinística

A primeira execução **não fabrica história anterior**. Guarda a fotografia real das hipóteses publicadas e regista `baseline_at` (hora UTC do relatório V5). A partir da segunda, compara por chave **ID estável V5 + mercado de resultado** (`OVER_2_5` ou `BTTS_YES`), nunca por posição no ranking.

A base publicada do V5 contém os padrões individuais, as 40 combinações do relatório e hipóteses congeladas. **O índice de evolução ainda não contém as 800 hipóteses avaliadas internamente**: as restantes não são inventadas nem consideradas rejeitadas por não aparecerem na tabela. A saída indica este limite de cobertura.

Classificações:

| Classe | Interpretação |
|---|---|
| `NEW_PATTERN` | Primeira aparição depois da baseline, não uma descoberta validada |
| `NEW_EVIDENCE` | Aumentou o número de FT conhecidos no padrão ou na amostra independente |
| `IMPROVED` | Com novos FT, o valor absoluto da diferença entre grupos aumentou ≥ 5 pontos percentuais **sem inversão de sinal** |
| `DEGRADED` | Com novos FT, o valor absoluto da diferença entre grupos diminuiu ≥ 5 pontos percentuais |
| `SIGN_REVERSAL` | Diferença entre grupos mudou de sinal, com magnitude mínima de 3 pp em ambos |
| `RECALCULATED` | Mudança estatística de referência sem novos FT no grupo |
| `DATA_REVISION` | Redução de FT/hits; alerta para auditoria, não melhoria |
| `CANDIDATE`, `VALIDATED`, `REJECTED` | Mudanças de estado **apenas** segundo o motor V5 e o registo congelado |
| `NO_CHANGE` | Nenhum acontecimento novo é persistido |

Taxas, p, q, IC de 95%, FT, estados e estabilidade mantêm-se descritivos. Um efeito maior ou valor-q menor **não** significa lucro ou validação. A amostra descoberta de uma hipótese congelada é copiada do registo imutável; os FT posteriores entram em `out_of_sample` separado.

As mudanças são eventos duráveis, com ID determinístico, hora UTC, valores anteriores/novos, critérios e proveniência. O JSON público retém os 90 eventos recentes e 24 pontos temporais por padrão; as entradas anteriores permanecem nos arquivos mensais Git (sem perda do histórico completo).

## Prospetiva e FT posteriores

A classificação original é lida apenas de `pattern-watch-first-seen.json`, com `first_detected_at` e `observed_through` **anteriores** ao início. Um resultado só é associado se o ledger o tiver confirmado como `FINAL`, com golos inteiros válidos e `checked_at` pelo menos 90 minutos depois do início. Assim, um jogo sem FT **não** entra no denominador, nem conta como red.

Resultados associados são congelados pelo par `match_key + score` e por categoria original. Qualquer remoção/alteração de primeira deteção ou divergência do resultado já publicado provoca erro explícito, para auditoria manual, em vez de reescrita silenciosa.

Greens/reds no Radar significam apenas **sim/não** no desfecho desportivo Over 2,5 ou BTTS. Não houve aposta real; não se calcula lucro, odds executáveis nem EV.

## Repetição, testes e limites

```bash
python -m unittest discover -s tests -p 'test_discovery_timeline.py' -v
python -m scripts.lab_discoveries
python -m unittest discover -s tests -v
node --check docs/master-brain.js
```

Testes sintéticos cobrem baseline, reexecução sem mudanças, aumento de FT, efeito crescente/decrescente, inversão de sinal, estados, correções de resultados e persistência dos arquivos. Não são provas empíricas de capacidade preditiva.

O trabalho LAB é isolado dos scripts de apostas H1. Se a pesquisa ou a observação prospetiva falhar, a etapa de descobertas não corre; a reconciliação FT continua independente.

**Estado científico:** a validação depende de hipóteses V5 congeladas e de resultados OOS suficientes, posteriores à hora de congelamento. O Radar não promove padrões exploratórios a apostas.
