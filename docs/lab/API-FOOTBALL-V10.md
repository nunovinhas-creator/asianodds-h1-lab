# LAB FT — transição para fontes de acesso autorizado

## O que foi demonstrado em produção

A PR #44 recuperou **9 FT adicionais** por correspondência da listagem FotMob, passando de 28 para 37 FT em 179 jogos observados (28/10/2026, 09h56 UTC). Os 4 conflitos `SOURCE_ORDER_CONFLICT` permaneceram bloqueados; a indicação `Pen` não foi tomada como resultado dos 90 minutos.

Fonte: https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40668127647

## Restrição de utilização do FotMob

Após a integração foi verificado que a página oficial FotMob diz que a recolha automática regular não é permitida, e `robots.txt` exclui `/api/*` para o utilizador genérico. Portanto o agendador **não deve prosseguir consultas automáticas regulares sem autorização explícita do fornecedor**.

- V10: `LAB_FOTMOB_LICENSED=0` **por defeito**. `FotMobResults` mantém-se disponível para testes sintéticos ou utilização com permissão adquirida e configurada pelo operador.
- As nove observações anteriormente liquidadas preservam o URL de proveniência; a desativação não as regrava nem as apaga.
- O workflow de diagnóstico FotMob é apenas manual: não executar consultas sem autorização adequada.

## Solução alternativa implementada — API-Football (API-Sports, oficial)

API e documentação do fornecedor: https://www.api-football.com/documentation_v3

Existe plano gratuito do fornecedor, até 100 pedidos/dia, com limites por minuto. A cobertura anunciada é superior a 1200 competições; *não assumir* que cada jogo AsianOdds existe nem que FT é sempre disponibilizado.

- `h1lab/lab_api_football.py`: `GET https://v3.football.api-sports.io/fixtures?date=YYYY-MM-DD&timezone=UTC`; cabeçalho `x-apisports-key`. Consulta no máximo **3 dias diferentes por ciclo** com cache por data, sem pedidos repetidos por jogo.
- Requer o **Secret** `API_FOOTBALL_KEY` do GitHub. Sem ele: zero pedidos, nenhuma falha no pipeline FT.
- Identidade `EXACT` ou `CORE_NAME`, jogos únicos na janela ±90 min, casa/fora estritamente orientados, rejeição de duplicados e colisões.
- Só liquida o estado `fixture.status.short == "FT"`, com marcador `score.fulltime.home/away` inteiro e idêntico ao `goals.home/away`. AET e PEN permanecem pendentes até existir prova adicional dos 90 minutos.
- Confronta sempre resultados dos restantes fornecedores: qualquer divergência ⇒ `SCORE_CONFLICT` sem gravar FT.
- O relatório adiciona `api_football_search`, incluindo `configured`, número de pedidos e FT validados. Dados H1 e cron Cloudflare permanecem intocados.

### Ativar sem expor credenciais

1. Registar uma chave gratuita no painel oficial API-Sports.
2. Em GitHub → repositório → Settings → Secrets and variables → Actions → New repository secret, criar **`API_FOOTBALL_KEY`** com o valor da chave. Não colocar a chave em `vars`, commits, relatórios ou no chat.
3. O LAB passará a usar a nova fonte no ciclo seguinte. O workflow mantém 30 jogos analisados por execução; não é necessário novo cron nem criar branches de trabalho.

**Validação necessária:** após inserir o secret, confirmar em `docs/lab/ft-results.json` que `api_football_search.configured=true` e contabilizar apenas os `verified_in_run` que entram de facto em `FINAL`. Uma integração sem chave continua funcional, mas não pode reivindicar recuperação empírica por esta fonte.
