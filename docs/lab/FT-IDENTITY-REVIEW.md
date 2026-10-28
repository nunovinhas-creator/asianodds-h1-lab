# MASTER BRAIN — Fila automática de revisão de identidades FT

**Escopo:** exclusivamente observacional; não modifica H1, picks, triplas, notificações, previsões, aliases aprovados ou marcadores FT.

## O que implementa

Em cada reconciliação FT regular, depois de consultar até 30 jogos com os mesmos limites de cada fornecedor, o sistema percorre **apenas os caches de resposta dessa execução**: API-Football, GOAL, OpenFoot, BSD (somente páginas completas) e SportScore (índices de consulta potencialmente parciais).

O módulo \`h1lab/lab_identity_review.py\` recebe o ledger FT já reconciliado e os caches na memória. Seleciona os jogos não confirmados que passaram KO+3h, identifica correspondências candidatas na janela temporal de ±90 minutos e armazena, no máximo, **2 candidatos por fornecedor / 6 por jogo**. Guarda apenas nomes de equipas, KO, competição, identificador público, URL de referência permitida, orientação casa/fora e métrica de similaridade diagnóstica, **nunca os marcadores, o payload integral da API ou as credenciais**.

A fila incorpora também colisões internas do AsianOdds quando dois \`match_key\` têm a mesma equipa no mesmo horário, sem fundir entradas. Inclui códigos de revisão para conflitos e para falta de prova dos 90 minutos.

O ficheiro \`docs/lab/ft-identity-review.json\` é uma **projeção mutável para revisão humana**, guardada entre ciclos. Mantém candidatos antigos apenas se \`home\`, \`away\` e \`kickoff_utc\` forem exatamente os mesmos; tais candidatos são marcados como \`observed_this_run=false\`, não como confirmação atual. Elimina jogos quando já têm FT ou deixam de ser elegíveis. A lista limita-se a 500 entradas, com contagem explícita de omissões.

## Proteções essenciais

- \`name_similarity_diagnostic\` **nunca** entra na validação ou liquidação. Não há novos aliases, cruzamentos automáticos, alterações de \`lab_identity.py\`, previsões retroativas ou resultados presumidos.
- Os dados dos caches são utilizados **depois** da reconciliação; nenhuma API é chamada para criar a fila.
- A razão \`NO_MATCH_FOUND_IN_AVAILABLE_CACHES\` não prova a ausência real do encontro; resultados podem faltar ou as listagens ser parciais.
- Candidatos preservados de execuções anteriores **não são observações atuais**.
- O pipeline FT pode publicar os FT mesmo que a construção não crítica da fila falhe: o erro não modifica o ledger.
- O dashboard em \`docs/ft-identity-review.html\` apresenta estados de revisão e os motivos da última tentativa, mas não valores de golos nem resultados inventados.

## Validação e operação

Testes sintéticos em \`tests/test_lab_identity_review.py\` verificam coincidências, inversões, qualificadores U19/U21, duplicados, persistência, invalidação por mudança de identidade, separação futuros/tolerância de 3h, falhas de paginação e ausência de marcadores/segredos.

Depois do merge, esperar uma execução real de \`Lab - Reconcile FT for all observed matches\` e confirmar: \`LAB_FT_IDENTITY_REVIEW\` nos logs, publicação do JSON, \`total_eligible\` consistente com a fila de atrasados e zero mudanças no resultado dos testes/ledger por efeito da fila. Os valores do snapshot só são reais após essa execução.

**Links:** [Painel de revisão](../ft-identity-review.html) · [JSON da fila](ft-identity-review.json) · [FT atrasados](ft-backlog.json).

## Revisão documental adicional, 28/10/2026 (seis jogos, sem aliases globais)

Comparadas fontes públicas independentes e a identidade ORIGINAL do jogo (equipa casa, fora, data e KO UTC). As seis correspondências com prova por duas fontes são adicionadas **apenas ao registo de revisão explícita por `match_key`** em `h1lab/lab_ft_reviewed_evidence.py`; não são adicionadas como normalização global:

| Jogo (identidade AsianOdds) | FT 90m | Fontes | Nota |
|---|---|---|---|
| Alianza FC (SLV) – CD Marathón | 0–0 | CONCACAF; Fútbol Centroamérica | KO 02:00 UTC, 28/10 |
| Silivrispor – Beyoglu Yeni Carsiz | 3–2 | Federação turca TFF; Kamu1 | KO 10:30 UTC |
| Menemen Belediyespor – Karacabey Belediyespor | 0–1 | TFF; Canlı Gaste | KO 10:30 UTC |
| FK Teleoptik Zemun – FK Mladost Lučani | 1–1 | Tanjug; HotSport | **5–4 nas grandes penalidades não é FT** |
| Adana 1954 FK – Kutahyaspor | 1–1 | TFF; Kütahya'nın Sesi | **2–1 após prolongamento não é FT**; Adana 1954 foi renomeado Adana 01 em 2024 |
| Balikesirspor – Arnavutkoy Genclik Spor | 1–0 | TFF; Canlı Gaste | KO 12:00 UTC |

**Não promover:** `2026-10-28,29823,1748` (Karsspor vs Antalyaspor): fontes oficiais dizem Kars 36 Spor e há evidência de que **Karsspor e Kars 36 são entidades distintas**. O calendário coincidente não autoriza fundir as identidades. `2026-10-28,10088406,95346` e `2026-10-28,10055350,95346` identificam duas entradas concorrentes para Eskisehir Anadolu/Anadolu Universitesi vs Aksaray. Não atribuir o resultado a ambos sem reconciliação explícita dos IDs.

Apenas os seis registos originais `PENDING` podem receber resultado nesta recuperação, depois dos testes, se não houver qualquer contradição de outro fornecedor. O FT é gravado com `checked_at` real da execução, sem retrodatação. Não são previsões prospetivas nem ROI.

## Lote documental de 28/10/2026 — 10 revisões, só aos 90 minutos

Os dez jogos abaixo foram observados no LAB e estavam `PENDING` à hora da preparação da PR. O catálogo preserva os nomes e o KO UTC originais de cada `match_key` (não são aliases automáticos). Cada registo tem dois URLs HTTPS de domínios diferentes com o resultado validado:

| Jogo | FT aos 90 min | Prova e cautelas |
|---|---|---|
| FK Viagem Pribram B – SK Benešov | **2–3** | [Fonte 1](https://www.eurofotbal.cz/souteze/cesko/cfl-a/2026-2027/reportaz/fk-pribram-b-sk-benesov-1092965/) · [Fonte 2](https://futebolmax.org/football/match/pribram-b-vs-benesov-2582090) |
| FC Slovan Liberec II – FC Zenit Caslav | **0–0** | [Fonte 1](https://www.fcslovanliberec.cz/cz/match/5784-Svatecni-dohravka-branky-nenabidla-B-tym-remizoval-s-Caslavi) · [Fonte 2](https://www.eurofotbal.cz/souteze/cesko/cfl-b/2026-2027/reportaz/slovan-liberec-b-fk-caslav-1093061/) |
| Nagoya Grampus Eight – Urawa Red Diamonds | **1–1** | [Fonte 1](https://www.urawa-reds.co.jp/topteamtopics/9029897.html) · [Fonte 2](https://www.redspress.jp/index/reds_report/ARTICLE1/2026102800003) |
| Cigánd SE – Paksi SE | **1–2** | [Fonte 1](https://nb1.hu/hir/magyar-kupa-4-fordulo-eredmenyek/) · [Fonte 2](https://hatsofuves.nemzetisport.hu/labdarugo-nb-i/2026/10/a-loki-es-a-paks-a-hajraban-a-szpari-a-hosszabbitasban-harcolta-ki-a-tovabbjutast-a-mol-magyar-kupaban) |
| Muranga Seal – Nairobi United | **3–2** | [Fonte 1](https://www.kovascore.com/football/match/sportpesa-premier-league/murang-a-seal-nairobi-united-4883398) · [Fonte 2](https://www.oddsgpt.com/asian-handicap/1629093/murang-a-seal-vs-nairobi-united/en) |
| OFK Vrsac – Omladinski FK Beograd | **0–1** | [Fonte 1](https://meridiansport.rs/fudbal/zvezdina-filijala-srusila-superligasa-romanticari-preziveli-odlazak-u-vrsac/) · [Fonte 2](https://www.dnevnik.rs/lat/sport/fudbal/suboticane-eliminisao-srpskoligas-kraj-za-spartak-kupu-superligasi-polozili-koplja-pred-teleoptikom-graficarom-2026-10-28) |
| Marko – Olympiakos | **0–2** | [Fonte 1](https://www.epo.gr/el/arthra/marko-olympiakos-0-2) · [Fonte 2](https://www.sport24.gr/football/marko-olimpiakos-0-2-me-saliaka-kai-karmo-oi-erithrolefkoi-exoun-to-apolito-sto-superbet-kipello-elladas/) |
| ACF Fiorentina U19 – FC Septemvri Sofia U19 | **5–0** | [Fonte 1](https://ng.soccerway.com/match/fiorentina-2TBysB6k/septemvri-sofia-80w3wjhQ/?mid=W8kExAdJ) · [Fonte 2](https://www.nove.firenze.it/primavera-goleada-europea-5-0-al-septemviri-sofia.htm) |
| MKS Znicz Pruszków – Ruch Chorzow | **0–1** | [Fonte 1](https://pilkanozna.pl/ruch-zwycieski-w-pruszkowie-niebiescy-z-awansem-do-kolejnej-rundy/) · [Fonte 2](https://www.sporx.com/znicz-pruszkow-player1-bu-kulvarda-bu-sezonki-5-maci-anlatim-6280516) |
| Puszcza Niepolomice – Wisła Płock | **1–1** | [Fonte 1](https://www.scorebat.com/puszcza-n-vs-wisla-plock-live-stream/) · [Fonte 2](https://kanalsportowy.pl/relacja/puszcza-niepolomice-wisla-plock-2026-10-28/sklady/) |

**Duas exceções críticas:** Nagoya–Urawa foi **1–1 aos 90 min**, apesar de terminar 1–2 após golo aos 117'; Puszcza–Wisła Płock foi igualmente **1–1 aos 90 min**, apesar do 1–2 após golo aos 109'. A preservação do FT é testada expressamente. A verificação histórica de identidade não altera cronologia V6 nem valida ROI.

Esta intervenção foi deliberadamente **apenas documental e por `match_key`**. É necessária a reconciliação GitHub pós-merge para confirmar quantos resultados foram efetivamente gravados com o timestamp real. Os restantes, incluindo `Mayak Sarny` com KO do fornecedor desfasado 60 minutos, as colisões `Karsspor/Kars 36`, `Eskisehir/Anadolu` e os eventos sem segundo FT final credível permanecem por verificar.
