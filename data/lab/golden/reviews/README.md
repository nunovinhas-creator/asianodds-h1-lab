# Revisões humanas do Golden Set

**Estado inicial: nenhum evento validado manualmente.**

Esta pasta recebe apenas ficheiros JSON de valores transcritos diretamente das mensagens originais do canal Telegram AsianOdds Dropping Odds, **nunca** exportações do H1 ou do V4.

## Passos no Android

1. Abre [Golden Set — revisão](https://nunovinhas-creator.github.io/asianodds-h1-lab/golden-review.html) (após a integração e publicação).
2. Escolhe um evento candidato, localiza-o no canal Telegram pelo número da mensagem e confirma a equipa/data/hora.
3. Escolhe **R1**, cola o texto original (ou seleciona uma captura de ecrã) para calcular localmente a sua impressão digital SHA-256; o texto e a imagem **não** entram no JSON gerado.
4. Transcreve manualmente cada valor Was/Now, sem consultar os preços do V4 e do legado. Indica o início em UTC.
5. Exporta um único ficheiro JSON com nome `<canal>_<mensagem>__R1.json`. Propõe-o por uma PR separada, ou partilha comigo apenas o JSON para o integrar.
6. **Um segundo revisor** (ou segunda leitura cega, explicitamente assinalada como não independente) repete o processo como R2, sem consultar os valores da primeira revisão. Não usar os preços do V4 como referência.
7. A validação automática compara as duas transcrições entre si e só depois contra o V4; as divergências ficam visíveis em `docs/lab/golden-report.json`. Uma dupla concordância não equivale a certificação da autenticidade da origem.

## Segurança

Não guardar nesta pasta: texto integral do Telegram, ficheiros de imagem, URL com token, sessões, credenciais, nomes pessoais dos revisores ou identificadores privados. O identificador do evento, odds e hash da fonte são suficientes para fazer comparações não sensíveis — mas **não provam autenticidade por si só**.

Os ficheiros que não obedeçam exatamente ao esquema são rejeitados. O revisor usa um pseudónimo `R1` ou `R2`; só uma aprovação humana de evidência de acesso à fonte pode atestar a independência dos revisores.

## Exemplo do formato

A página HTML cria o JSON completo automaticamente. Para um alerta Total, o objeto `markets` inclui:
```json
{
  "total": {
    "before": {"line": 2.25, "over_price": 1.83, "under_price": 2.02},
    "after": {"line": 2.50, "over_price": 1.83, "under_price": 1.81}
  }
}
```

**Os números acima são apenas um exemplo didático, não uma mensagem verificada nem um resultado Golden.**

Em 1X2 são obrigatórias também as três seleções `1/X/2` e a tabela `asian_handicap` com linha, preço casa e preço fora; tudo antes/depois.

A publicação `golden_set_verified` permanece `false` por construção. Para passar essa barreira será necessário um conjunto realmente independente de mensagens originais, uma revisão formal aprovada e cobertura estatística adequada. Não alterar automaticamente essa proteção.
