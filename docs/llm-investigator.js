/* MASTER BRAIN LLM viewer: presentation only, zero model/API calls. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const state = $("runtime-state");
  const latest = $("latest-detail");
  const history = $("llm-history");

  function text(el, value) {
    el.textContent = value === null || value === undefined ? "—" : String(value);
  }
  function elt(tag, content, cls) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (content !== undefined) text(node, content);
    return node;
  }
  function block(parent, label, content) {
    parent.appendChild(elt("h3", label));
    parent.appendChild(elt("p", content));
  }
  function safeList(xs) {
    return Array.isArray(xs) ? xs.filter(x => typeof x === "string").join(" · ") : "Não disponível";
  }
  function renderProposal(p) {
    latest.replaceChildren();
    if (!p || typeof p !== "object" || p.status !== "DRAFT") {
      latest.appendChild(elt("p", "A investigação ainda não tem uma proposta válida publicada."));
      return;
    }
    latest.appendChild(elt("h3", "Cruzamento de variáveis V5"));
    const tags = elt("div", undefined, "llm-codes");
    (Array.isArray(p.feature_codes) ? p.feature_codes : []).forEach(code => {
      if (typeof code === "string" && /^[A-Z][A-Z0-9_]{1,60}$/.test(code)) {
        tags.appendChild(elt("code", code));
      }
    });
    latest.appendChild(tags);
    block(latest, "Hipótese a testar", p.hypothesis);
    block(latest, "Hipótese nula", p.null_hypothesis);
    block(latest, "Métrica / referência", String(p.metric || "—") + " · " + String(p.baseline || "—") + " (modelo Poisson, não odd negociável)");
    block(latest, "Grupo de controlo", p.control_group);
    block(latest, "Plano experimental", p.test_design);
    block(latest, "Como refutar", p.falsification);
    block(latest, "Dados ainda necessários", safeList(p.data_needed));
    block(latest, "Possíveis confundidores", safeList(p.confounders));
    block(latest, "Proveniência das definições (não prova de eficácia)", safeList(p.source_refs));
  }

  function renderLegacy(legacy) {
    latest.replaceChildren();
    latest.appendChild(elt("h3", "T02 — Primeiro ensaio real (contrato anterior)"));
    block(latest, "O que a IA efetivamente propôs",
      legacy.description);
    block(latest, "Limite desta investigação",
      "Não foram identificados códigos cruzados, um desempenho OOS, nem vantagem estatística. Esta execução não é uma descoberta ou estratégia validada.");
    const link = elt("a", "Consultar execução original no GitHub Actions");
    const id = legacy.run_id;
    if (Number.isSafeInteger(id) && id > 0) {
      link.href = "https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/" + id;
      link.rel = "noopener noreferrer";
      latest.appendChild(link);
    }
  }

  function row(entry) {
    const tr = document.createElement("tr");
    tr.appendChild(elt("td", entry.recorded_at_utc));
    tr.appendChild(elt("td", safeList(entry.feature_codes)));
    tr.appendChild(elt("td", entry.metric));
    const td = document.createElement("td");
    const id = entry.run_id;
    if (Number.isSafeInteger(id) && id > 0) {
      const a = elt("a", "#" + id);
      a.href = "https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/" + id;
      a.rel = "noopener noreferrer";
      td.appendChild(a);
    } else {
      text(td, "—");
    }
    tr.appendChild(td);
    return tr;
  }
  async function load() {
    text(state, "A consultar o último relatório publicado…");
    try {
      const res = await fetch("./lab/llm-investigator-index.json?nocache=" + Date.now(), {cache: "no-store"});
      if (res.status === 404) {
        text(state, "Nenhuma investigação publicada neste painel. O modo dossier não usa IA; as execuções manuais de Cloudflare passarão a surgir aqui.");
        return;
      }
      if (!res.ok) throw new Error("HTTP " + res.status);
      const v = await res.json();
      if (!v || v.schema_version !== 1 || v.state !== "SHADOW_DRAFT_NOT_EMPIRICALLY_VALIDATED" || !v.search_space || !Array.isArray(v.history) || (v.latest === null && v.history.length !== 0)) {
        throw new Error("Relatório publicado com formato inválido");
      }
      const s = v.search_space;
      text($("features-count"), s.features_in_catalogue);
      if (Number.isSafeInteger(s.possible_pairs_distinct_families) && Number.isSafeInteger(s.possible_triples_distinct_families)) {
        text($("combos-count"), (s.possible_pairs_distinct_families + s.possible_triples_distinct_families).toLocaleString("pt-PT"));
      }
      text($("runs-count"), v.llm_executions_recorded);
      text($("validated-count"), 0);
      history.replaceChildren();
      if (v.latest === null && v.history.length === 0) {
        const legacy = v.legacy_successful_manual_run;
        if (!legacy || legacy.run_id !== 41039239732 || legacy.status !== "LEGACY_DRAFT_NOT_SCIENTIFICALLY_VALIDATED") {
          throw new Error("Ensaio histórico sem proveniência verificável");
        }
        text(state, "1 ensaio real anterior · 0 propostas com novo contrato · IA não está a correr automaticamente.");
        text($("latest-meta"), "Execução histórica #" + legacy.run_id + " · " + legacy.date_utc + " · Formato anterior · Sem novos cruzamentos publicados");
        renderLegacy(legacy);
        history.appendChild(row({
          recorded_at_utc: legacy.date_utc,
          feature_codes: ["T02 — alertas repetidos (formato anterior)"],
          metric: "Não definida",
          run_id: legacy.run_id
        }));
        return;
      }
      const run = v.latest;
      if (!run || !Number.isSafeInteger(run.run_id) || !v.history.length || v.history[0].run_id !== run.run_id) {
        throw new Error("Índice e última execução não coincidem");
      }
      text(state, "Modo manual · último cruzamento publicado · sem investigação em segundo plano.");
      text($("latest-meta"), "Run #" + run.run_id + " · " + run.recorded_at_utc + " · Modelo " + run.model + " · Neurons: não medidos no relatório");
      if (run.provider_usage) {
        const u = run.provider_usage;
        text($("latest-meta"), "Run #" + run.run_id + " · " + run.recorded_at_utc +
          " · Modelo " + run.model + " · Tokens: " + JSON.stringify(u.tokens || {}) +
          " · Neurons: não medidos · quota da conta não verificada");
      }
      renderProposal(Array.isArray(run.proposals) ? run.proposals[0] : null);
      v.history.forEach(e => history.appendChild(row(e)));
    } catch (err) {
      text(state, "Erro na leitura do relatório. Consultar GitHub Actions; não é possível confirmar o estado atual.");
      text($("latest-meta"), "Relatório indisponível ou inválido.");
      text($("features-count"), "—");
      text($("combos-count"), "—");
      text($("runs-count"), "—");
      latest.replaceChildren(elt("p", "Não foi possível verificar os dados publicados."));
      history.replaceChildren();
      const tr = document.createElement("tr"), td = elt("td", "Histórico indisponível.");
      td.colSpan = 4;
      tr.appendChild(td);
      history.appendChild(tr);
    }
  }
  $("refresh-llm").addEventListener("click", load);
  load();
})();
