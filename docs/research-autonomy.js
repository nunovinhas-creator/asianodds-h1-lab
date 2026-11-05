/* MASTER BRAIN autonomous research panel: presentation only, zero model/API calls.
 * All text from the research memory (including model-written questions) is inserted
 * with textContent, never as HTML. */
(function (root) {
  "use strict";
  const SOURCE = "./research/autonomous-research.json";
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
    box.appendChild(el(doc, "p", (MARKET_LABEL[c.market] || "Mercado") + " · " + (c.outcome || "—") + " · origem " + (c.origin || "—") + " · versão " + (c.version || 1)));
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
  function render(doc, data) {
    if (!data || data.schema_version !== 1 || data.status !== "EXPLORATORY_RESEARCH_NOT_VALIDATION") {
      throw new Error("Formato de relatório não reconhecido");
    }
    const m = data.memory || {};
    doc.getElementById("ra-experiments").textContent = m.experiments ?? "—";
    doc.getElementById("ra-questions").textContent = m.distinct_questions ?? "—";
    doc.getElementById("ra-cycles").textContent = m.cycles ?? "—";
    const last = data.last_cycle;
    doc.getElementById("ra-last-cycle").textContent = last ? "Último: " + last.recorded_at + " · chamadas IA " + last.llm_calls : "Sem ciclos";
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
    (data.rejected_plans || []).forEach(r => rp.appendChild(el(doc, "li", r.recorded_at + " · " + r.origin + " · " + r.reason)));
    if (!rp.children.length) rp.appendChild(el(doc, "li", "Nenhum plano recusado."));
    doc.getElementById("ra-validated-note").textContent = data.validated_note || "Nenhuma estratégia validada.";
    doc.getElementById("ra-state").textContent = "Memória com " + (m.records ?? 0) + " registos · gerado em " + data.generated_at;
  }
  function load(doc, fetchFn) {
    const s = doc.getElementById("ra-state");
    s.textContent = "A carregar a memória de investigação…";
    return fetchFn(SOURCE + "?t=" + Date.now(), { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(d => render(doc, d))
      .catch(e => { s.textContent = "Dados indisponíveis (" + e.message + "). Não significa ausência de investigação."; });
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { render, card, STATE_LABEL };
  } else {
    root.document.addEventListener("DOMContentLoaded", () => {
      load(root.document, root.fetch.bind(root));
      root.document.getElementById("ra-refresh").addEventListener("click", () => load(root.document, root.fetch.bind(root)));
    });
  }
})(typeof window !== "undefined" ? window : globalThis);
