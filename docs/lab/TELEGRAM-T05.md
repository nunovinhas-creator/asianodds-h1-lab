# Telegram — T05 (Over 2,5 experimental) · 30/10/2026

## Regra congelada, sem olhar para resultados

**T05 / candidato `7d7275b4a862...`**, da execução [41046486099](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41046486099):

1. `G_FIRST_LEAD_LT_6H`: primeira mensagem da cronologia de odds chegou a menos de 6 horas do KO.
2. `M_1X2_HOME_PROB_UP`: a probabilidade 1X2 sem margem da equipa da casa aumentou num movimento Was→Now realmente observado.
3. `M_TOTAL_LINE_UP`: a linha Total asiática de golos subiu num movimento Was→Now realmente observado.

As duas condições positivas exigem `V4_EXPLICIT`, mercados utilizáveis no contrato estatístico e identidade/horário consistente. `make_row(...,known_at=agora)` aplica o mesmo filtro por instante de conhecimento que o motor estatístico. Nenhum FT ou resultado participa na deteção. O padrão de três jogos do painel **não é uma taxa de sucesso cientificamente aceite**.

### Exemplos históricos, fora da previsão

- Anadolu Üniversitesi – 68 Aksaray, 28/10/2026, **3–1**. Evidência pública de resultado: [Zerozero / Turkish Cup](https://www.zerozero.tr/competition/turkish-cup); [Kamu1](https://www.kamu1.net/mac/anadolu-universitesi-68-aksaray-belediyespor-28-ekim-2026). O FT ainda consta como PENDING no motor.
- CD Olimpia – CS Cartaginés, 29/10/2026, **2–2**. Fonte de competição: [CONCACAF](https://www.concacaf.com/competitions/central-american-cup/matches/4f7c306b1b734987a33602ae95659215/olimpia-vs-cs-cartagines/events). O motor arquivou resultado provisório por cronologia não certificada.
- Kasımpaşa – Çorluspor 1947, 29/10/2026, **3–1**. [beIN Sports](https://www.beinsports.com.tr/haber/kasimpasa-3-golle-turu-gecti). O motor arquivou resultado provisório por cronologia não certificada.

Os três têm **quatro golos**: 3/3 Over 2,5 observados *a posteriori*, com 0 FT aceites na amostra congelada do relatório de 12:00 UTC. Não atribuir garantia, ROI, EV nem validação científica a estes três resultados.

## Emissão

- **Primeira execução autorizada**: envia um único resumo etiquetado *HISTÓRICO (NÃO É ALERTA PRÉ-JOGO)*; nunca transforma jogos terminados em apostas futuras.
- **Novas deteções**: envia uma mensagem por jogo futuro com início nos próximos **12 horas**, ordenada por KO, mesmo se o jogo tiver sido observado antes no dia. Sem teto arbitrário de seis jogos. Hora Europe/Lisbon.
- O histórico é **apenas apresentado** no texto; não entra na seleção. A hipótese segue o estado `EXPLORATÓRIO`.
- **Recibos em `data/t05-notifications.json`**, independentes de `data/e4-notifications.json`; uma entrega incerta bloqueia reenvio automático. Se Telegram não estiver configurado, não consome recibos.
- E4 mantém-se inteiramente ativa; E1/E2/E3/E5, H1 singles/triplas e Pattern Watch continuam silenciadas.
- O notifier T05 não faz pedidos à Cloudflare IA nem aos fornecedores de resultados.

## Recuperação FT e Zerozero — decisão de integração

O Zerozero lançou a API oficial em 14/10/2026: [api.zerozero.pt](https://api.zerozero.pt/). O plano **Club Free** permite 250 pedidos/mês e até duas equipas de um único clube; não oferece uma autorização genérica para cobrir todos os jogos observados pelo MASTER BRAIN. Planos Developers ainda aparecem como *coming soon*, e a API está em pré-lançamento. O [RSS Jogos Realizados](https://www.zerozero.pt/rss.php) refere principalmente ligas europeias importantes, sem cobertura garantida para Türkiye Kupası ou CONCACAF.

**Não implementar scraping não documentado das fichas HTML** como fonte de liquidação: pode dar HTTP 403, a identidade de um jogo pesquisado não basta, e um 2–2 após prolongamento não é automaticamente 2–2 nos 90 minutos. Futuramente, um adaptador oficial deverá:
- operar **apenas depois de obter acesso e autorização de cobertura à API Zerozero**, com quota própria e cache diária;
- procurar jogo por data, competição, duas equipas e IDs/crosswalk imutáveis;
- exigir `status FT` explícito aos 90 minutos, sem penalties/prolongamento, e corroborar quando possível;
- registar URL/ID da fonte, `observed_at`, `checked_at` e hora real de conhecimento para avaliação da cronologia;
- falhar fechado em conflito/indisponibilidade, sem transformar resultado visualmente conhecido num FT estatisticamente válido.

**Prioridade imediata para casos sem evidência FT:** manter o reconciliador BSD/API-Football/GOAL/OpenFoot/ESPN/SportScore e os respetivos cooldowns e testes de cobertura, sem depender de introdução manual pelo utilizador. Um pedido de acesso Zerozero futuro não condiciona os alertas T05.

## Testes

```bash
python -m h1lab.t05_notify --dry-run
python -m unittest tests.test_t05_notify -v
python -m unittest discover -s tests -v
```
