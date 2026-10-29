# BSD FT — Descoberta persistente de IDs por catálogo completo (V10)

Implementação: `h1lab/lab_bsd_id_registry.py`, `scripts/lab_results.py`.
Persistência: `data/lab/ft-bsd-event-ids.json`.

## Porque era necessário

O Monte-Carlos tem IDs da BSD guardados **desde a recolha**; o LAB do
MASTER BRAIN recebe IDs próprios do AsianOdds, que não identificam eventos
BSD. Mesmo consultando a BSD, uma pesquisa por `team_name` pode falhar por
designadores, exónimos e nomes abreviados. Sem ID guardado, cada nova
verificação repete o problema.

**Não existe uma correspondência automática segura apenas entre dois IDs
de espaços diferentes.** A descoberta inicial usa uma lista BSD completa de
jogos de uma data e associa um evento apenas se ambos os clubes,
categorias (U19/reservas/feminino), orientação casa/fora e horário UTC
(±5 minutos) forem rigorosamente compatíveis, com unicidade de origem
e destino. A dependência inicial de nomes é limitada a este passo de
identificação e **não se repete após registo do ID**. Nomes muito diferentes
continuam a precisar de revisão, sem inferir uma correspondência.

## Operação automática

1. Em execuções FT normais com BSD configurada, selecionar até **três
   dias** com jogos vencidos e ainda sem ID guardado **independentemente
   dos 30 jogos escolhidos pela fila de reconciliação**. A seleção analisa
   todo o ledger pendente, começa pelos dias ainda nunca tentados e,
   posteriormente, usa a data mais antiga da tentativa (rotação justa).
   Continua a funcionar quando a fila FT normal seleciona **zero** jogos.
2. Consultar `/api/v2/events/?date_from=...&date_to=...&status=finished`,
   com limite de 200 e até três páginas por dia. Exigir o `count` total
   documentado e todas as páginas até `next=null`. Qualquer erro,
   discrepância de contagem ou paginação incompleta impede a descoberta.
3. A partir de **cada lista completa**, identificar IDs BSD para todos
   os jogos observados nesse dia, e não apenas para o jogo escolhido
   para a consulta. Identidades ambíguas ou colisões ficam excluídas.
4. Persistir `match_key`, `event_id`, identidade original AsianOdds,
   identidade BSD do mesmo evento, horário e primeira observação.
   **Não** guardar marcadores, quotas, chaves, palpites ou payloads.
5. Em verificações futuras, dar prioridade ao `/api/v2/events/{id}/`
   guardado, com confirmação independente do detalhe BSD: ID, nomes
   originais do fornecedor, posição casa/fora, KO e **90 minutos**.
   O caminho usa o mesmo limite de 12 consultas de detalhe já reservado
   ao Monte-Carlos; não cria orçamento paralelo.
6. Se não há ID fiável, continuar a usar o arquivo Monte-Carlos.
   Como última alternativa, consultar a lista BSD por data: **sem**
   pedido preliminar `team_name`, e reutilizar a lista de dia em cache
   durante toda a execução.

### Segurança e cadência

- Nova tentativa de descobrir o mesmo dia apenas após **quatro horas**,
  seja a consulta anterior completa ou falhada; o histórico persiste.
  A V10.1 elimina a dependência da fila FT individual e favorece dias
  nunca tentados, prevenindo a repetição dos mesmos três dias.
- Os jogos com conflito de marcador documentado `HOLD_FOR_OFFICIAL`
  nunca são liquidados pelo atalho BSD, mesmo que haja um único FT.
- Não é permitida recuperação por odds, igualdade aproximada isolada
  nem identificação baseada no mesmo horário sem equipas verificadas.
- Uma revisão posterior que associe outro ID, nomes ou horário ao jogo
  entra em quarentena e não altera silenciosamente a correspondência.
- Nenhuma fonte de resultado pode ser inferida a partir do catálogo de
  identidades. O FT só nasce do detalhe real validado.
- Um ID já reclamado por outro jogo, incluindo um FT confirmado, é
  rejeitado; uma observação duplicada no AsianOdds não duplica um FT.
- Caminho apenas do LAB: H1, o Telegram e o Motor V6 não são alterados.
  O V6 consome o resultado apenas através do ledger FT.
- Pushes e merges não desencadeiam consultas autenticadas. A recolha
  real acontece exclusivamente em execuções FT normais autorizadas.

## Como medir

Consultar `docs/lab/ft-results.json`:

- `ft_queue.bsd_identity_registry.overdue_without_id`: jogos vencidos sem ID;
- `ft_queue.bsd_identity_registry.independent_of_ft_queue`: plano separado;
- `ft_queue.bsd_identity_registry.planned_days`: datas selecionadas;
- `pre_reconcile.new_ids` e `post_reconcile.new_ids`: novas associações
  de IDs, não liquidações;
- `bindings_total`: IDs existentes no registro;
- `binding_conflicts`: associações em quarentena;
- `direct_lookup.reasons.verified_bsd_from_persisted_id`: FT recuperados
  diretamente a partir de ID guardado;
- `ft_queue.newly_confirmed`: **novos FT reais** no ledger.

A primeira execução pode apenas construir o índice, sem recuperar um FT.
Um sucesso de CI com dados sintéticos não prova recuperação efetiva.

Documentação oficial: https://sports.bzzoiro.com/docs/ — `count`
indica o número **total** de itens, `next` a próxima página,
`limit` máximo 200, e `finished` o estado de jogo concluído.

## V10.1 — correção do fallback (29/10/2026)

Causa comprovada na base `8503f5f`: `plan_days` (linhas 293–328,
`lab_bsd_id_registry.py`) filtrava as quatro horas, mas `_date_index`
(linhas 53–62, `lab_bsd_search.py`) verificava apenas cache e orçamento.
O fallback de `lookup_bsd_monte_first` podia consultar um dia excluído
pelo plano. `discover` voltava então a gravar uma tentativa real.

Agora `date_in_cooldown` é a única política, usada no plano e na fronteira
HTTP. O adaptador recebe os `probes` persistidos e o relógio da execução.
A cache da execução tem prioridade; um catálogo completo pode ser reutilizado.
Recusas ficam em `deferred_days`, nunca em `days`; `discover` também ignora
explicitamente tuples de cooldown/orçamento. Assim recusas não alteram
`attempted_at_utc`, nem consomem orçamento, nem prolongam a espera.
Tentativas falhadas continuam a esperar quatro horas. Os jobs permanecem
serializados pelo grupo de concorrência existente; é necessário publicar
com sucesso o estado para proteger a execução seguinte.

Não foram alargadas regras de identidade. A contagem BSD também tem de ser
estável entre páginas. Comparações compactas persistem em `comparisons`
(até 3000 entradas, retenção de 45 dias), sem scores ou payloads. Distinguem
horário incompatível, inversão, categoria, ambiguidade e colisões verificáveis.
`no_verified_match_unknown_coverage_or_names` significa exatamente que não
se pode distinguir ausência de cobertura de nomes incompatíveis. O catálogo
filtrado por `finished` tampouco prova ausência do evento na BSD inteira.

Novos campos em `ft_queue.bsd_identity_registry`, gerados pelo próximo job:

- `overdue_without_id_after`, `overdue_compared_with_complete_catalogue` e
  `comparison_reason_counts`: população ainda pendente e evidência persistida.
- `coverage_absence_confirmed`: zero sem prova independente; não é estimativa.
- `cooldown_blocked_games`, `eligible_days_before`, `eligible_days_after` e
  `deferred_days`: elegibilidade temporal e recusas efetivas do adaptador.
- `new_ids`, `direct_lookup.ids_reused`, `direct_lookup.http_requests`:
  associações novas, invocações com ID validado e pedidos efetivos desse caminho.
- `persisted_id_new_finals`: transições novas a FINAL com evidência BSD por ID;
  diferente de detalhe validado que venha a colidir com outro fornecedor.
- `date_http_by_path`, `fallback_detail_requests`, `monte_only_detail_requests`
  e `http_total`: pedidos reais, incluindo falhas/retries, sem contar cache.

### Evidência e aceitação operacional

Snapshot lido: Porto–Académico, ID 599528, PENDING, `attempts=0`,
`queue_visited_at=2026-10-29T10:11:42+00:00`. A fila exige quatro horas
após essa visita: não era elegível às 12:56. Sem nova visita ou outro bloqueio,
a barreira termina às 14:11:42 UTC; a seleção continua sujeita à capacidade
e à ordenação normais. Não foi executado pedido real, nem alterado o ledger.
Os 141 eventos dos três dias anteriores não estão guardados no registo;
não permitem reconstruir retrospectivamente as razões dos 103 não associados.

Testes locais usam respostas simuladas e relógio controlado, incluindo
três jobs, falha HTTP, contador de páginas inconsistente, cache, fila vazia,
ID → fila → detalhe → FT, quarentena e HOLD_FOR_OFFICIAL. Zero FT reais
recuperados nesta intervenção. O relatório histórico não foi regenerado.

Depois do merge autorizado, verificar apenas jobs normais:

1. Antes de quatro horas: zero novos HTTP para cada data bloqueada,
   motivo `bsd_date_cooldown_deferred` se invocada pelo fallback e timestamp
   de tentativa inalterado, mesmo após vários jobs.
2. Após quatro horas: datas novamente elegíveis; nunca tentadas e mais
   antigas servidas primeiro, mantendo três dias/três páginas por defeito.
3. IDs persistidos consultados pela fila quando elegíveis, no orçamento
   partilhado de 12 pedidos; nenhum catálogo exigido por esse caminho.
4. Somar os caminhos HTTP e conferir `http_total`; comparar novos IDs,
   detalhes validados e novas transições FINAL separadamente.
5. Exigir detalhe real de 90 minutos e ausência de conflitos para provar
   recuperação; sucesso dos testes ou do workflow não constitui essa prova.
