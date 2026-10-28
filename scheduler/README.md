# Cron de 5 minutos — Cloudflare Workers + GitHub Actions

**Documentação revista em 28/10/2026.** Ver também [arquitetura canónica](../docs/lab/ARCHITECTURE.md) e [README raiz](../README.md).

## Porque existe

O workflow GitHub `.github/workflows/collect.yml` mantém `on.schedule` com
intervalo de 5 minutos, mas o GitHub pode atrasar ou omitir execuções (documentado
oficialmente). Na fotografia de 27-10-2026, a recolha via Cloudflare foi comprovada por
commits e logs, e foi também observada pelo menos uma execução
`event=schedule` do cron GitHub por volta das 18:12 UTC. A afirmação anterior
de ausência total de execuções agendadas ficou ultrapassada. Nenhuma das
duas plataformas garante disparos pontuais 24/7; confirmar o histórico
atual em Actions e o `collector.trigger_source` em `data/state.json`.

Este Worker usa o cron gratuito da Cloudflare para disparar o **mesmo**
workflow, com as mesmas credenciais Telegram guardadas **apenas no GitHub**.
A Cloudflare nunca recebe `TG_SESSION`, `TG_BOT_TOKEN` ou a API BSD.

A fonte fica identificada no log: `COLLECT_TRIGGER: cloudflare-cron`.
Quando o GitHub disparar o seu cron nativo, o log apresenta
`COLLECT_TRIGGER: github-schedule`.

## Configuração inicial (uma única vez)

1. **GitHub → Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token.** Selecionar exclusivamente
   `nunovinhas-creator/asianodds-h1-lab` em *Repository access* e atribuir
   **Actions: Read and write** (Metadata: Read automático). O token servirá
   **apenas para ler as últimas recolhas e despachar collect.yml**. Não
   utilizar um token com permissões totais ou acesso a todos os repositórios.
   É aconselhável uma expiração curta e rotação periódica.
2. **Cloudflare → Workers & Pages → Create → Worker.** Criar um Worker
   `asianodds-h1-cron` e, no editor, substituir o código inicial pelo
   conteúdo de [scheduler/worker.mjs](worker.mjs). Clicar em **Deploy**.
   Se utilizar Wrangler, este diretório já contém `wrangler.toml`, com
   `crons = ["*/5 * * * *"]`; executar `npx wrangler deploy` na
   diretoria `scheduler/`.
3. **Cloudflare Worker → Settings → Variables and Secrets.** Adicionar
   variável de tipo **Secret** com nome `GITHUB_DISPATCH_TOKEN` e valor
   do token fine-grained criado no passo 1. Nunca guardá-lo como variável
   de texto público nem o colocar no GitHub.
4. **Cloudflare Worker → Settings → Triggers → Cron Triggers.** Adicionar
   `*/5 * * * *`, em UTC. Confirmar que o cron aparece na lista.
   O Worker usa o evento `scheduled()`, não uma URL pública.
5. Consultar os logs da Cloudflare (observabilidade do Worker).
   O resultado normal será `H1_CRON_DISPATCH_ACCEPTED` se o GitHub
   não recolheu recentemente, ou `H1_CRON_SKIPPED_RECENT_RUN` se já
   houve recolha há menos de 4 minutos e 30 segundos.
6. Validar no GitHub:
   [Workflow H1](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/workflows/collect.yml).
   Procurar dois runs distintos `event=workflow_dispatch` iniciados
   aproximadamente com 5 minutos de intervalo, com o log
   `COLLECT_TRIGGER: cloudflare-cron` e conclusão `success`.
   Validar `data/state.json → collector → trigger_source` depois de uma
   recolha que cause atualização do checkpoint.

## Regras de segurança e duplicações

- O Worker responde **404 a HTTP público**. Só o agendamento interno Cloudflare
  executa o pedido ao GitHub.
- Cada tick lê as últimas execuções do workflow `collect.yml`; se existir
  uma com menos de 4m30s, **não dispara outra**.
- O collector e o reconciliador de resultados partilham o grupo de concorrência
  `asianodds-h1-write` com `cancel-in-progress: false`.
- O checkpoint de Telegram e a deduplicação por ID do alerta impedem
  registos repetidos mesmo se dois eventos forem disparados.
- O Worker não recebe a sessão do Telegram, não envia odds e não
  modifica os dados do repositório. Só pede ao GitHub para executar.
- Caso o token expire, o Worker passará a registar
  `GITHUB_RUNS_CHECK_FAILED: HTTP 401/403`; o cron nativo continuará
  disponível como fallback.
- Uma aceitação HTTP 204 **não é comprovação de recolha concluída**.
  É necessário observar no GitHub a execução sucessiva, o sucesso e
  a atualização do checkpoint. Nem Cloudflare nem GitHub oferecem garantia
  absoluta de execução pontual.

## Diagnóstico GitHub nativo

- [Runs do agendamento](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/workflows/collect.yml?query=event%3Aschedule)
- [Runs em geral](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/workflows/collect.yml)
- Agendamento: `2-57/5 * * * *` em UTC, registado em `main`.
- Documentação: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

### Testes locais

```bash
node --test scheduler/worker.test.mjs
```

São testes com respostas **sintéticas** da API GitHub. Não substituem
a comprovação de runs reais criados pelo Worker.
