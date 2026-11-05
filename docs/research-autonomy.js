/* MASTER BRAIN autonomous research panel: presentation only, zero model/API calls.
 * All text from the research memory (including model-written questions) is inserted
 * with textContent, never as HTML. */
(function (root) {
  "use strict";
  const SOURCE = "./research/autonomous-research.json";
  const DEMO_SOURCE = "./research/demo/panel.json";
  const STATE_LABEL = {
    PROMISING_EXPLORATORY: "Promissor (exploratório)",
    NO_SUPPORT_IN_DATA: "Sem suporte nos dados",
    FALSIFIED_EXPLORATORY: "Falhou a falsificação",
    INSUFFICIENT_DATA: "Dados insuficientes",
    INCONCLUSIVE: "Inconclusivo"
  };
  const CHECK_LABEL = {
    F1_PERMUTATION: "Teste de permutação",
    F2_OUT_OF_SAMPLE_SIGN: "Fora da amostra",
    F3_PERIOD_STABILITY: "Estabilidade entre períodos",
    F4_CONFOUNDING: "Controlo de confusões",
    F5_MULTIPLICITY: "Correção de testes múltiplos"
  };
  const MARKET_LABEL = { TOTAL_GOALS: "Total de golos", BTTS: "Ambas marcam", "1X2": "1X2", ASIAN_HANDICAP: "Handicap asiático" };

  const ORIGIN_LABEL = {
    LLM_LIVE: "LLM real",
    OFFLINE_PROPOSER: "proponente offline determinístico",
    SIMULATED_LLM: "LLM SIMULADO (sem chamadas reais)",
    RESPONSE_FILE_NOT_LIVE_LLM: "ficheiro de resposta (não é LLM real)"
  };
  const REASON_HINT = {
    INDICATOR_DEFINED_BUT_UNUSED: "indicador definido mas não usado na condição",
    "DSL:INVALID_INDICATOR_NAME": "nome de indicador inválido (tem de ser X_ em MAIÚSCULAS)",
    COPIED_RESPONSE_EXAMPLE: "cópia do exemplo do pedido",
    OVER_PLAN_BUDGET: "acima do limite de planos"
  };
  function fmt(x, nd) {
    return typeof x === "number" && isFinite(x) ? x.toFixed(nd === undefined ? 3 : nd) : "—";
  }
  function el(doc, tag, text, cls) {
    const n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function card(doc, c) {
    const box = el(doc, "article", undefined, "ra-card");
    const head = el(doc, "h3");
    head.appendChild(el(doc, "span", STATE_LABEL[c.state] || "Estado desconhecido", "ra-state " + (STATE_LABEL[c.state] ? c.state : "")));
    head.appendChild(doc.createTextNode(c.question || "Pergunta não disponível"));
    box.appendChild(head);
    box.appendChild(el(doc, "p", (MARKET_LABEL[c.market] || "Mercado") + " · " + (c.outcome || "—") + " · origem " + (ORIGIN_LABEL[c.origin] || c.origin || "—") + " · versão " + (c.version || 1)));
    const tags = el(doc, "div", undefined, "ra-tags");
    (Array.isArray(c.variables) ? c.variables : []).forEach(v => tags.appendChild(el(doc, "code", v)));
    (Array.isArray(c.new_indicators) ? c.new_indicators : []).forEach(i => tags.appendChild(el(doc, "code", "novo: " + i.name)));
    box.appendChild(tags);
    const sample = "Amostra: grupo " + (c.group_n ?? "—") + " jogos, controlo " + (c.control_n ?? "—") + " jogos com resultado verificado.";
    box.appendChild(el(doc, "p", sample));
    if (typeof c.effect === "number") {
      const ci = Array.isArray(c.effect_ci95) ? " (intervalo 95%: " + fmt(c.effect_ci95[0]) + " a " + fmt(c.effect_ci95[1]) + ")" : "";
      const what = c.primary_statistic === "DIFFERENCE_IN_MEAN_RESIDUAL_VS_MARKET"
        ? "Diferença face ao esperado pelo mercado: " : "Diferença de frequência (sem preço de mercado): ";
      box.appendChild(el(doc, "p", what + fmt(c.effect) + ci + " · p=" + fmt(c.p_value, 4) + " · q=" + fmt(c.q_value, 4)));
    }
    if (c.checks && typeof c.checks === "object") {
      const ch = el(doc, "div", undefined, "ra-checks");
      Object.keys(CHECK_LABEL).forEach(k => {
        if (c.checks[k]) ch.appendChild(el(doc, "span", CHECK_LABEL[k] + ": " + ({ PASS: "passou", FAIL: "falhou", NOT_APPLICABLE: "não aplicável" }[c.checks[k]] || "—")));
      });
      box.appendChild(ch);
    }
    (Array.isArray(c.missing) ? c.missing : []).forEach(m => box.appendChild(el(doc, "p", "Em falta: " + m)));
    (Array.isArray(c.limitations) ? c.limitations : []).slice(0, 3).forEach(m => box.appendChild(el(doc, "p", "Limitação: " + m)));
    if (c.next_question) box.appendChild(el(doc, "p", "Próxima pergunta: " + c.next_question));
    return box;
  }
  function fill(doc, id, items, empty) {
    const host = doc.getElementById(id);
    host.replaceChildren();
    if (!items.length) { host.appendChild(el(doc, "p", empty, "llm-muted")); return; }
    items.forEach(c => host.appendChild(card(doc, c)));
  }
  const KIND_LABEL = {
    OPERATIONAL: "INVESTIGAÇÃO OPERACIONAL",
    DEMONSTRATION: "DEMONSTRAÇÃO — NÃO É INVESTIGAÇÃO AUTÓNOMA ATUAL",
    TEST: "TESTE AUTOMÁTICO — NÃO É INVESTIGAÇÃO PUBLICADA"
  };
  function provenanceText(p) {
    const parts = [KIND_LABEL[p.kind]];
    parts.push("Data de referência: " + (p.reference_time || "—"));
    parts.push("Origem das hipóteses: " + (Array.isArray(p.cycle_origins) ? p.cycle_origins.join(", ") : "—"));
    parts.push(p.real_llm_calls > 0 ? "Chamadas reais ao LLM: " + p.real_llm_calls
                                    : "Sem chamadas reais ao LLM");
    if (typeof p.experiments_from_live_llm === "number") {
      parts.push("Experiências de planos do LLM real: " + p.experiments_from_live_llm
                 + " · do proponente offline: " + (p.experiments_from_offline ?? "—"));
    }
    return parts.join(" · ");
  }
  function li(doc, host, text) { host.appendChild(el(doc, "li", text)); }
  const LLM_ORIGINS = ["LLM_LIVE", "SIMULATED_LLM", "RESPONSE_FILE_NOT_LIVE_LLM"];
  // Reports published before provenance v3 have no research_split: derive it from what the
  // report does contain (card origins and refused plans), clearly marked as derived.
  function deriveSplit(data) {
    const cards = [].concat(data.discovered || [], data.rejected || [], data.needs_more_data || []);
    if (!cards.length && !(data.rejected_plans || []).length) return null;
    const llm = cards.filter(c => LLM_ORIGINS.includes(c.origin));
    const off = cards.filter(c => c.origin === "OFFLINE_PROPOSER");
    const refused = (data.rejected_plans || []).filter(r => LLM_ORIGINS.includes(r.origin));
    const reasons = {};
    refused.forEach(r => { reasons[r.reason] = (reasons[r.reason] || 0) + 1; });
    const states = {};
    off.forEach(c => { states[c.state] = (states[c.state] || 0) + 1; });
    const calls = data.provenance ? data.provenance.real_llm_calls || 0 : 0;
    const exps = data.memory && typeof data.memory.experiments === "number" ? data.memory.experiments : cards.length;
    return {
      derived: true,
      autonomous: { models: [], real_llm_calls: calls, plans_received: refused.length + llm.length,
        plans_accepted: llm.length, plans_rejected: refused.length, plans_duplicate_skipped: 0,
        experiments_executed: llm.length, rejection_reasons: reasons, cycles: [] },
      deterministic: { experiments_executed: Math.max(off.length, exps - llm.length), distinct_questions: off.length,
        states, limitations: ["Hipóteses de uma grelha fixa de tercis, sem IA e sem uso de resultados."] }
    };
  }
  function renderSplit(doc, split) {
    const a = doc.getElementById("ra-autonomous");
    const d = doc.getElementById("ra-deterministic");
    a.replaceChildren(); d.replaceChildren();
    if (!split || !split.autonomous || !split.deterministic) {
      li(doc, a, "Este relatório não separa a origem das experiências (formato anterior).");
      li(doc, d, "Este relatório não separa a origem das experiências (formato anterior).");
      return;
    }
    if (split.derived) {
      li(doc, a, "Relatório anterior à proveniência v3: valores derivados dos cartões e planos recusados; modelo não registado.");
      const r = split.autonomous.rejection_reasons || {};
      const txt = Object.keys(r).map(k => (REASON_HINT[k] || k) + " ×" + r[k]).join("; ");
      li(doc, a, "LLM: " + split.autonomous.plans_received + " propostas, " + split.autonomous.plans_accepted + " aceites, "
                + split.autonomous.experiments_executed + " experiências executadas" + (txt ? " · motivos: " + txt : "")
                + " · offline: " + split.deterministic.experiments_executed + " experiências");
    }
    const s = split.autonomous;
    li(doc, a, "Modelo utilizado: " + (s.models && s.models.length ? s.models.join(", ") : "nenhum"));
    li(doc, a, "Chamadas reais: " + (s.real_llm_calls ?? 0));
    li(doc, a, "Planos propostos: " + (s.plans_received ?? 0) + " · aceites pela DSL: " + (s.plans_accepted ?? 0)
              + " · rejeitados: " + (s.plans_rejected ?? 0) + " · repetidos na memória: " + (s.plans_duplicate_skipped ?? 0));
    li(doc, a, "Experiências executadas a partir de planos do LLM: " + (s.experiments_executed ?? 0));
    (Array.isArray(s.cycles) ? s.cycles : []).slice().reverse().forEach(c => {
      const reasons = Object.keys(c.rejection_reasons || {}).map(k => (REASON_HINT[k] || k) + " ×" + c.rejection_reasons[k]).join("; ");
      const inferred = c.model_inferred_from_code ? " (não registado no ciclo; inferido do código: " + c.model_inferred_from_code.model + ")" : "";
      li(doc, a, "Ciclo " + c.recorded_at + " · modelo " + (c.model || "—") + inferred + " · LLM: " + c.plans_received
                + " propostas, " + c.plans_accepted + " aceites, " + c.experiments_from_llm + " experiências executadas"
                + (reasons ? " · motivos: " + reasons : "") + " · offline: " + c.experiments_from_offline + " experiências");
    });
    if (s.note) li(doc, a, s.note);
    const o = split.deterministic;
    li(doc, d, "Experiências do proponente offline: " + (o.experiments_executed ?? 0) + " (perguntas distintas: " + (o.distinct_questions ?? 0) + ")");
    const st = o.states || {};
    li(doc, d, "Resultados: " + (Object.keys(st).map(k => (STATE_LABEL[k] || k) + " " + st[k]).join(" · ") || "—"));
    (Array.isArray(o.limitations) ? o.limitations : []).forEach(x => li(doc, d, "Limitação: " + x));
  }
  function render(doc, data) {
    if (!data || data.schema_version !== 2 || data.status !== "EXPLORATORY_RESEARCH_NOT_VALIDATION"
        || !data.provenance || !KIND_LABEL[data.provenance.kind]) {
      throw new Error("Formato de relatório não reconhecido");
    }
    const pv = doc.getElementById("ra-provenance");
    pv.textContent = provenanceText(data.provenance);
    pv.className = "ra-provenance ra-kind-" + data.provenance.kind;
    doc.getElementById("ra-provenance-note").textContent = data.provenance.note || "";
    const m = data.memory || {};
    doc.getElementById("ra-experiments").textContent = m.experiments ?? "—";
    doc.getElementById("ra-questions").textContent = m.distinct_questions ?? "—";
    doc.getElementById("ra-cycles").textContent = m.cycles ?? "—";
    const last = data.last_cycle;
    const fu = last && last.funnel;
    doc.getElementById("ra-last-cycle").textContent = last ? "Último: " + last.recorded_at + " · chamadas IA " + last.llm_calls
      + (fu ? " · LLM " + fu.experiments_from_llm + " / offline " + fu.experiments_from_offline + " experiências" : "") : "Sem ciclos";
    renderSplit(doc, data.research_split || deriveSplit(data));
    // Exploratory output never feeds the validated count.
    doc.getElementById("ra-validated").textContent = "0";
    const g = doc.getElementById("ra-gates");
    g.replaceChildren();
    g.appendChild(el(doc, "li", "Exploração: " + (data.gates && data.gates.exploration === "EXPLORATION_ALLOWED" ? "permitida (dados tecnicamente íntegros)" : "bloqueada")));
    g.appendChild(el(doc, "li", "Validação científica: " + (data.gates && data.gates.scientific_validation === "AUTHORISED" ? "critérios técnicos cumpridos, sem promoção automática" : "bloqueada — critérios de cobertura e amostra ainda não cumpridos")));
    ((data.gates && data.gates.limitations) || []).forEach(x => g.appendChild(el(doc, "li", x)));
    const inv = doc.getElementById("ra-investigating");
    inv.replaceChildren();
    const kinds = { RETEST_WHEN_DATA_GROWS: "Repetir com mais dados", NEEDS_PREREGISTRATION: "Pré-registar", EXPLORE_ALTERNATIVE: "Explicação alternativa" };
    (data.investigating || []).forEach(a => inv.appendChild(el(doc, "li", (kinds[a.kind] || "Pergunta") + (a.ready ? " (pronto)" : "") + ": " + a.question)));
    if (!inv.children.length) inv.appendChild(el(doc, "li", "Ainda sem agenda."));
    fill(doc, "ra-discovered", data.discovered || [], "Nenhuma relação passou todas as verificações nesta amostra.");
    fill(doc, "ra-rejected", data.rejected || [], "Nada rejeitado ainda.");
    fill(doc, "ra-more", data.needs_more_data || [], "Nada pendente.");
    const rp = doc.getElementById("ra-rejected-plans");
    rp.replaceChildren();
    (data.rejected_plans || []).forEach(r => rp.appendChild(el(doc, "li", r.recorded_at + " · " + (ORIGIN_LABEL[r.origin] || r.origin)
      + " · " + r.reason + (REASON_HINT[r.reason] ? " (" + REASON_HINT[r.reason] + ")" : "") + (r.field ? " · campo " + r.field : ""))));
    if (!rp.children.length) rp.appendChild(el(doc, "li", "Nenhum plano recusado."));
    doc.getElementById("ra-validated-note").textContent = data.validated_note || "Nenhuma estratégia validada.";
    doc.getElementById("ra-state").textContent = "Memória com " + (m.records ?? 0) + " registos · gerado em " + data.generated_at;
  }
  function get(fetchFn, url) {
    return fetchFn(url + "?t=" + Date.now(), { cache: "no-store" })
      .then(r => { if (!r.ok) { const e = new Error("HTTP " + r.status); e.status = r.status; throw e; } return r.json(); });
  }
  function load(doc, fetchFn) {
    const s = doc.getElementById("ra-state");
    s.textContent = "A carregar a memória de investigação…";
    // Operational report first. Only a 404 (never published) falls back to the
    // clearly labelled demonstration; other failures are shown as failures.
    return get(fetchFn, SOURCE)
      .then(d => render(doc, d))
      .catch(e => {
        if (e.status !== 404) throw e;
        return get(fetchFn, DEMO_SOURCE).then(d => {
          if (!d || !d.provenance || d.provenance.kind !== "DEMONSTRATION") throw new Error("demonstração inválida");
          render(doc, d);
          s.textContent = "Ainda não existe investigação operacional publicada. A mostrar a DEMONSTRAÇÃO. " + s.textContent;
        });
      })
      .catch(e => { s.textContent = "Dados indisponíveis (" + e.message + "). Não significa ausência de investigação."; });
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { render, card, load, STATE_LABEL, provenanceText, renderSplit, deriveSplit };
  } else {
    root.document.addEventListener("DOMContentLoaded", () => {
      load(root.document, root.fetch.bind(root));
      root.document.getElementById("ra-refresh").addEventListener("click", () => load(root.document, root.fetch.bind(root)));
    });
  }
})(typeof window !== "undefined" ? window : globalThis);
