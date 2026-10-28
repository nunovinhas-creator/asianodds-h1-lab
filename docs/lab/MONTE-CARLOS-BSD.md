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
