# FT 24h, fonte única e descoberta com segmentos autoritativos

## Política FT (nova)

- Janela operacional: desde o final do período de segurança após o início até **24 horas contadas desde o kickoff UTC**, inclusive.
- Mais de 24h sem FT inequívoco: `EXPIRED_UNVERIFIED`. Os detalhes de tentativas/probes são descartados e o jogo deixa de ser elegível para APIs, recuperação antiga ou pesquisa por ID.
- A lápide mínima `match_key` + identidade + kickoff permanece para deduplicação e para não enviesar a cobertura; não é uma aposta perdida nem um FT.
- `FINAL` já certificado nunca é apagado nem rebaixado por idade.
- **Uma única fonte com identidade exata/justificada e resultado dos 90 minutos é suficiente**. Se houver conflito entre fontes, é obrigatório recusar até à expiração; não selecionar arbitrariamente a mais conveniente.
- A validação estatística permanece separada da existência de um FT: amostra observada, confirmação efetiva e dados em falta são indicadores diferentes.

## Limite de 2 MB

O backend `segmented` funciona sem um espelho `discovery-state.json` corrente. O estado é dividido em shards imutáveis, com manifesto SHA-256, ponteiro `CURRENT`, `PREVIOUS` para recuperação explícita e arquivo gzip byte-exato. O teste cobre estados acima de 2 MB. Há um limite **de segurança independente de 20 MB** no código atual, que terá de ser revisto muito antes de atingido; isto não representa capacidade ilimitada.

**Não está ativado na produção.** O workflow atual usa `legacy`; a PR de preparação é Draft. Nunca fazer apenas o merge de um workflow que exija `segmented` sem a geração inicial no mesmo commit.

## Corte produtivo obrigatório (não executado)

1. Congelar as versões atuais de `main`, do estado de descobertas e do ledger FT.
2. Num checkout seguro, executar `python -m scripts.lab_discovery_authoritative_release bootstrap`; o processo gera `CURRENT`, manifesto, shards e gzip, e verifica os objetos do índice Git.
3. No **mesmo commit de ativação**, modificar o workflow FT para `python -m scripts.lab_discoveries --state-backend segmented`, substituir a leitura do histórico no teste por `dual.load(...,format="segmented")`, chamar `python -m scripts.lab_discovery_authoritative_release stage` antes de selar resultados e trocar o rebase após reconciliação por push único não forçado e protegido por SHA do pai.
4. Alterar o corte para preservar histórico e FT FINAL. Fazer teste do selo `INDEX` e do `HEAD`, do rollback e da concorrência Git sem APIs. Confirmar que o legacy fica arquivado mas nunca mais é atualizado.
5. Reexecutar CI completa, tests de consumidores de estado, páginas, watchdog, H1 e Telegram; recusar em caso de qualquer divergência.
6. Só com autorização de merge e sem `main` alterada nos dois blobs, permitir ativação. Fazer observação operacional de 24h/48h/7d sem mexer nos FT certificados.

**Este documento não autoriza merge, cutover nem execução de fornecedores.**
