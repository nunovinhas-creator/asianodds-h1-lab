/* Research-only view: rendering never invokes a model, API provider or betting service. */
(() => {
  'use strict';
  const root = document.getElementById('python-statistics');
  if (!root) return;
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  };
  const num = v => typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('pt-PT', {maximumFractionDigits: 4}) : 'Não calculável';
  const date = v => v ? new Date(v).toLocaleString('pt-PT', {timeZone: 'Europe/Lisbon'}) : '—';
  const labels = {
    MISSING_OR_SUSPECT_FEATURE_MARKETS: 'Faltam cotações válidas para uma ou mais variáveis',
    VERIFIED_FT_MISSING_FOR_MATCHED_GAMES: 'Há jogos sem FT verificado',
    CLEAN_TWO_SIDED_TOTAL_BASELINE_MISSING: 'Falta baseline Total com os dois preços válidos',
    INSUFFICIENT_CHRONOLOGICALLY_AVAILABLE_TRAINING_FT: 'Treino insuficiente com FT conhecido antes do teste',
    INSUFFICIENT_TEMPORAL_HOLDOUT_N: 'Amostra temporal de teste insuficiente',
    INSUFFICIENT_INDEPENDENT_CALENDAR_DAYS: 'Menos de cinco dias com resultados',
    UNBALANCED_FT_COVERAGE_MATCHED_GROUPS: 'Cobertura FT desequilibrada entre grupo e controlos',
    NO_PREREGISTERED_CONFIRMATORY_PROTOCOL: 'Protocolo confirmatório ainda não pré-registado',
    COMPETITION_CONFOUNDING_NOT_CONTROLLED: 'Efeito da competição ainda não controlado'
  };
  function table(headers, rows) {
    const wrap = el('div', undefined, 'llm-table-wrap');
    const t = el('table'), head = el('thead'), tr = el('tr');
    headers.forEach(h => tr.append(el('th', h)));
    head.append(tr); t.append(head);
    const body = el('tbody');
    rows.forEach(values => { const r = el('tr'); values.forEach(v => r.append(el('td', v))); body.append(r); });
    if (!rows.length) {const r=el('tr'),td=el('td','Ainda sem casos elegíveis.');td.colSpan=headers.length;r.append(td);body.append(r);}
    t.append(body);wrap.append(t);return wrap;
  }
  function metric(label,value,sub) {
    const n=el('article',undefined,'llm-card'); n.append(el('div',label),el('strong',value),el('small',sub));return n;
  }
  function render(d) {
    if (d.schema_version !== 1 || d.status !== 'LLM_OFFLINE_EXPLORATORY_NO_PROMOTION' || !Array.isArray(d.hypotheses)) throw Error('Contrato estatístico inválido');
    root.replaceChildren();
    root.append(el('div','PYTHON · DADOS REAIS · ZERO CHAMADAS IA','eyebrow'),el('h2','O que já foi testado com jogos reais'));
    const age = Date.now()-new Date(d.generated_at).getTime();
    root.append(el('p',`Fotografia de ${date(d.generated_at)} (Portugal continental). ${age>18*3600000?'ATENÇÃO: relatório com mais de 18 horas; os dados podem ter mudado.':'Análise exploratória, sem aprovação científica.'}`, age>18*3600000?'llm-warning':'llm-muted'));
    root.append(el('p','IA: formula cruzamentos. Python: conta casos, verifica FT e calcula métricas. Comprovação: nenhuma hipótese aprovada; requer protocolo independente e amostras adequadas.'));
    const metrics=el('div',undefined,'llm-metrics');
    const ft=d.coverage.ft;
    metrics.append(metric('Hipóteses arquivadas',num(d.hypotheses.length),'Propostas distintas'),
      metric('Jogos com FT aceite',num(ft.ft),`${num(ft.matches)} com observações utilizáveis; ${num(ft.pending)} sem FT aceite`),
      metric('FT com baseline limpo',num(ft.baseline.n),'Probabilidade derivada do Total por Poisson'),
      metric('Comprovações científicas','0','Exploração e monitorização independentes'));
    root.append(metrics);
    const cov=d.catalogue_support.counts;
    root.append(el('p',`${num(cov.with_at_least_30_ft_and_baseline)} de ${num(cov.crossings)} cruzamentos têm pelo menos 30 FT e baseline. É cobertura de dados: não significa ${num(cov.crossings)} testes nem vantagens encontradas. Histórico FT: ${num(ft.days)} dias.`));
    const states=el('p',undefined,'llm-muted');
    const counts={};d.hypotheses.forEach(h=>{counts[h.state]=(counts[h.state]||0)+1;});
    states.textContent=Object.entries(counts).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v}`).join(' · ');root.append(states);
    for (const h of d.hypotheses) {
      const detail=el('details',undefined,'stats-hypothesis');detail.open=true;
      const title=el('summary',`${h.state.replaceAll('_',' ')} · ${h.feature_codes.join(' + ')}`);detail.append(title);
      detail.append(el('p',`Proposta: ${date(h.registered_at)} · ${h.archive} · ${h.candidate_id.slice(0,12)}`,'llm-muted'));
      const a=h.historical,p=h.prospective;
      detail.append(table(['Âmbito','Casos','FT','Sem FT aceite','Baseline n','Brier baseline','Log Loss baseline'],[
        ['Histórico exploratório',a.group.matches,a.group.ft,a.group.pending,a.group.baseline.n,num(a.group.baseline.brier),num(a.group.baseline.log_loss)],
        ['Controlo emparelhado',a.matched_control.matches,a.matched_control.ft,a.matched_control.pending,a.matched_control.baseline.n,num(a.matched_control.baseline.brier),num(a.matched_control.baseline.log_loss)],
        ['Monitorização prospetiva',p.group.matches,p.group.ft,p.group.pending,p.group.baseline.n,num(p.group.baseline.brier),num(p.group.baseline.log_loss)]]));
      detail.append(el('p',`Comparação com ambos os FT conhecidos: ${a.complete_pairs.group.ft} pares. Sem controlo compatível: ${a.unmatched_group} casos. Critérios: probabilidade ±5 pp, mesma antecedência, até 7 dias, sem reutilizar controlos nem consultar FT na seleção.`));
      const ci=a.group.rate_ci95;
      detail.append(el('p',ci?`Frequência histórica Over 2,5: ${num(100*a.group.rate)}% (${a.group.hits}/${a.group.ft}); intervalo 95%: ${num(100*ci[0])}%–${num(100*ci[1])}%. Não demonstra vantagem.`:'Ainda sem FT suficiente para estimar frequência.'));
      detail.append(el('h3','Teste temporal e modelo'));
      const t=a.temporal;
      detail.append(el('p',`Corte por dia: ${t.split_day}. Treino elegível: ${t.train_n}; teste com baseline: ${t.test_baseline.n}. Offset treinado: ${num(t.offset)}. Log Loss do modelo: ${num(t.test_model?.log_loss)}; Brier do modelo: ${num(t.test_model?.brier)}. p corrigido no universo completo: ${num(h.p_bonferroni_search_space)}.`));
      detail.append(el('p','Sem treino cronologicamente válido, o modelo não produz previsões. As métricas do baseline descrevem o mercado nos jogos encontrados; não são métricas de uma previsão da LLM.','llm-warning'));
      detail.append(el('h3','Dados em falta e limitações'));
      const missing=el('ul'); h.blockers.forEach(b=>missing.append(el('li',labels[b]||b))); detail.append(missing);
      detail.append(table(['Variável','Jogos com valor desconhecido'],Object.entries(a.unknown_by_code).map(([c,n])=>[c,n])));
      detail.append(el('p',`Exclusões prospetivas: ${Object.entries(h.prospective_exclusions).map(([k,n])=>`${k}: ${n}`).join(' · ')||'Nenhuma'}. Não são convertidas em resultados negativos.`));
      detail.append(el('h3','Jogos que cumprem o cruzamento'));
      detail.append(table(['Jogo','Início (Portugal)','FT','Probabilidade mercado','Captura'],a.games.map(g=>[g.match_label,date(g.kickoff_utc),g.score?g.score.join('–'):`${g.ft_status} · pendente de aceitação`,g.market_probability==null?'Ausente':`${num(100*g.market_probability)}%`,date(g.decision_at)])));
      const raw=el('a','Consultar dados e proveniência completos');raw.href='./lab/llm-statistics.json';detail.append(raw);
      root.append(detail);
    }
    const limits=el('details');limits.append(el('summary','Método, cobertura e histórico auditável'));
    limits.append(table(['Estado FT','Jogos'],Object.entries(d.coverage.ft_states)));
    const ul=el('ul');d.limitations.forEach(s=>ul.append(el('li',s)));limits.append(ul);
    const method=el('a','Protocolo e execução real documentada');method.href='https://github.com/nunovinhas-creator/asianodds-h1-lab/blob/main/docs/audit/LLM-OFFLINE-STATISTICS.md';limits.append(method);
    const history=el('a','Histórico de execuções offline');history.href='https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/workflows/v6-offline-statistics.yml';limits.append(el('p'),history);root.append(limits);
  }
  async function load() {
    try {
      const r=await fetch('./lab/llm-statistics.json',{cache:'no-store'});
      if(!r.ok)throw Error(`HTTP ${r.status}`);
      render(await r.json());
    } catch(e) {
      root.replaceChildren(el('h2','Análise Python indisponível'),el('p',`Não foi possível obter um relatório estatístico válido (${e.message}). Não equivale a zero jogos ou hipótese rejeitada.`, 'llm-warning'));
    }
  }
  document.getElementById('refresh-llm')?.addEventListener('click',load);
  load();
})();
