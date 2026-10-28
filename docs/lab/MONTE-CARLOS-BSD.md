# LAB — integração do reconciliador BSD do Monte-Carlos

**Repositório original do utilizador:** https://github.com/nunovinhas-creator/Monte-Carlos

**Código lido:** `settlement.py`, `main.py`, `database.py`, `README.md` em 28/10/2026.

## Porque funciona melhor no Monte-Carlos
O Monte-Carlos obtém os eventos diretamente da **BSD**, guarda o `match_id` que é o ID do próprio evento BSD e, para liquidar, faz **`GET /api/v2/events/{id}/`**. Não depende de repetidas pesquisas textuais. O `settlement.py` tem ainda:
- Extração de status tanto no topo como em dicionários aninhados (`_extrair_status`).
- Extração de golos em vários formatos (`_extrair_golos`).
- Encaminhamento **`replaced_by`** para novos IDs (até cinco saltos).
- Resposta a 429 com backoff 2, 4, 8 segundos.
- Diagnósticos de motivos para não liquidação e estados não jogado, não iniciado ou sem dados.

## Diferença crucial face ao AsianOdds
As chaves `match_key` dos alertas AsianOdds **não são necessariamente IDs da BSD**. Não podem ser usadas automaticamente para consultar `/events/{id}/`. Tentar fazê-lo criaria correspondências falsas e resultados atribuídos ao jogo errado.

## Como integramos SEM comprometer a integridade
1. A partir da base de dados **pública** e já existente do Monte-Carlos, `predictions.db`, criar em memória uma tabela de correspondência entre ID real BSD e **nome casa + nome fora + início UTC**. Ficheiro temporário com `SQLite mode=ro`, limite de 4 MB, sem escritas na BD nem publicação de linhas brutas.
2. Usar primeiro a pesquisa BSD existente do LAB (nome e pesquisa por data, mais as fontes independentes). **Se falhar a correspondência**, consultar a tabela Monte-Carlos apenas para encontrar um ID candidato. Exige nomes ordenados normalizados exatamente e kickoff ±90 minutos; múltiplos IDs para o mesmo encontro ficam pendentes.
3. Com ID verificado, consultar o próprio evento diretamente à BSD, **nunca tomar o resultado SQLite como verdade**. O evento devolvido deve voltar a confirmar as equipas, o início, o estado de tempo regulamentar e `home_score/away_score`. Quando a BSD substituiu o evento, seguir `replaced_by` até cinco saltos, revalidando a identidade.
4. Aplicar a tolerância de payload que torna o Monte-Carlos robusto, mas restringindo a aceitação a **marcadores explicitamente regulamentares**. Não usar golos de `score` genérico se puder incluir prolongamento/penáltis. Numa prova de taça incerta o jogo permanece pendente.
5. Respeitar os pedidos: até **12 consultas diretas BSD por ciclo**, backoff 2/4/8 após 429 e interrupção se persistir; nunca imprimir token, erros completos nem URLs de pedidos com parâmetros.
6. Registrar no relatório `monte_carlos_bsd`: estado da leitura da BD, prefixo do SHA-256, grupos de equipas/datas indexados, jogos com ID candidato, requests BSD diretos, e FT obtidos neste ciclo.
7. Recolha de todas as fontes mantém-se separada dos H1. A versão do motor `LOOKUP_SOURCE_VERSION=6` permite **uma nova tentativa por jogo pendente** para testar esta fonte, retornando depois ao cooldown normal.

## Cobertura adicional sem perder segurança
O lote geral de SportScore pode truncar-se a 200 jogos/dia. Portamos também a melhoria de procura específica da antiga PR #36: **20 pesquisas dirigidas de equipas e 45 pedidos SportScore por ciclo**, sempre por slug devolvido pelo fornecedor e com limite superior declarado. Esta melhoria substitui a PR #36 caso seja integrada nesta branch, evitando dois merges concorrentes.

## Resultado e limites
A integração só será considerada empiricamente útil depois de um run real mostrar `monte_carlos_bsd.verified_in_run > 0`. Caso não existam jogos comuns aos dois projetos, o contador pode ser zero: o método de liquidação fica disponível, mas a cobertura não melhora automaticamente. Não se inventam IDs nem se copia um marcador não confirmado de outra base.

**Permanecem intocáveis:** `h1lab/bsd.py`, `results.py`, H1 collector e cron Cloudflare, `data/state.json`, resultados oficiais H1, Telegram, picks, triplas e FIFO.

## Atualização V8 — identificação por CORE_NAME (28/10/2026)

A auditoria oficial confirma que `/api/v2/events/` suporta `date_from`, `date_to`, `status=finished`, `team_name`, `limit` até 200 e `offset`; detalhes em `/api/v2/events/{id}/`. O ID é sempre obtido da resposta BSD ou do arquivo de eventos BSD do Monte-Carlos, **nunca de um identificador AsianOdds**.

Na ausência de correspondência estritamente normalizada no SQLite público, o LAB V8 examina eventos do arquivo dentro de ±90 minutos (incluindo dias UTC adjacentes) e permite somente equivalência `CORE_NAME` para **ambas** as equipas na ordem casa/fora. Rejeita automaticamente: nomes genéricos ou inválidos, duplicados, inversões, coincidência com outra partida do mesmo clube, alteração de U21/reservas/feminino e discrepâncias de horário.

O ID encontrado é **um candidato**: exige consulta fresca de `GET /events/{id}/`, com ID do detalhe, nomes originais do arquivo, kickoff, estado e marcador regulamentar validados. Em provas de taça usa somente `home_score`/`away_score` ou blocos explicitamente regulamentares; prolongamento e penáltis não são somados. A resposta de origem fica em `result.source`. Identidades V8 aceites incluem `identity_match=CORE_NAME`.

Contadores novos: `core_name_event_id_candidates` e `verified_core_name_in_run`. Os limites de **12 consultas diretas por ciclo** e 30 jogos consultados não aumentam. `LOOKUP_SOURCE_VERSION=8` permite uma única reconsulta aos jogos pendentes, respeitando depois o intervalo de 4 horas.

A documentação BSD comunica uma quota gratuita diária e limites de pico que podem mudar; portanto a implementação mantém orçamentos conservadores e não assume acesso ilimitado.

**Critério de êxito:** confirmar num workflow FT real um `verified_core_name_in_run > 0` e aumento de FT sem conflitos; zero mantém a integração funcional mas sem ganho empírico demonstrado. A PR só altera módulos e documentos LAB.
