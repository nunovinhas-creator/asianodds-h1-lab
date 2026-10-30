# Incidente: Investigador LLM / Cloudflare Workers AI — 30/10/2026

## Evidência da primeira chamada real

O utilizador forneceu o ZIP de logs da execução GitHub Actions `cloudflare_once` de 30/10/2026 às 10:04 UTC. O job fez checkout de `main` no commit `c3b597ae2b4b8bc615a54e74547bf3360afdf4e5`, concluiu 8/8 testes Python e executou uma única chamada à Cloudflare com os secrets presentes no ambiente e a confirmação explícita `CONSUMIR_IA_UMA_VEZ`.

A chamada devolveu resposta HTTP utilizável e conteúdo JSON que foi interpretado, mas a validação interna `validate_proposals` rejeitou o formato com `ValueError: Unexpected model response schema` em `h1lab/v6_llm_investigator.py:178`. O workflow terminou com código 1 e não publicou `investigation.json`. As mensagens `error:` nos testes de segurança eram intencionais. **Não foi possível ver a estrutura efetivamente devolvida pelo modelo**, porque a saída era redirecionada e o erro não registava diagnósticos de formato. A quota de neurons consumida também não está evidenciada nos logs.

## Causa e correção de baixo risco

O cliente solicitava apenas `response_format: {"type":"json_object"}`: isso restringe a sintaxe a JSON mas **não impõe** as chaves, arrays e campos de `schema_version=1` exigidos pelo contrato da aplicação. Não se pode afirmar qual foi exatamente a divergência do modelo.

Esta PR:
- Especifica que o modelo deve devolver **exatamente uma proposta DRAFT**, com duas chaves no topo (`schema_version` e `proposals`).
- Inclui um exemplo de JSON completo, com nomes de campos exatos e referência a uma fonte existente no dossier. Não adiciona dados reais, odds ou resultados.
- Mantém `json_object` para não mudar a compatibilidade do modelo Cloudflare durante uma correção conservadora. Não aceita silenciosamente um formato diferente.
- Adiciona códigos e flags de erro *sem incluir texto do modelo*, para distinguir versão errada, campo ausente, chaves extra e truncamento (`finish_reason`), sem divulgar conteúdo gerado.
- Acrescenta regressões para respostas com estruturas inválidas e tipos não previstos.

Não altera H1, Telegram, ROI, FIFO, FT, cron, secrets nem regras de publicação. **Não executa outro pedido** à Cloudflare. Não foi possível validar a correção contra uma nova resposta real, portanto a integração permanece **não comprovada**, não `OK`.

## Aceitação

- CI e testes unitários relevantes aprovados.
- Validar resposta `DRAFT_UNVALIDATED_HUMAN_REVIEW_REQUIRED` num **único novo pedido manual**, somente após revisão da PR e medição/aceitação da quota disponível.
- Se voltar a falhar, usar apenas os diagnósticos de estrutura, sem persistir a resposta bruta. Não ativar retries ou agendamento.
- O estado científico V6 continua `INCONCLUSIVO`; propostas LLM nunca ativam estratégias.
