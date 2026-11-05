"use strict";
// Offline UI contract for docs/research-autonomy.js: no network, no innerHTML,
// exploratory results never counted as validated.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const js = fs.readFileSync(path.join(__dirname, "../docs/research-autonomy.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../docs/research-autonomy.html"), "utf8");
const ui = require("../docs/research-autonomy.js");

function fakeDoc() {
  const nodes = {};
  function make(tag) {
    return {
      tag, className: "", children: [], _text: "",
      set textContent(v) { this._text = String(v); this.children = []; },
      get textContent() { return this._text + this.children.map(c => c.textContent).join(""); },
      appendChild(c) { this.children.push(c); return c; },
      replaceChildren() { this.children = []; this._text = ""; },
    };
  }
  const doc = {
    createElement: make,
    createTextNode: t => ({ textContent: String(t) }),
    getElementById(id) { if (!nodes[id]) nodes[id] = make("div"); return nodes[id]; },
  };
  return { doc, nodes };
}

const sample = {
  schema_version: 2, status: "EXPLORATORY_RESEARCH_NOT_VALIDATION", generated_at: "2026-11-05T12:00:00+00:00",
  provenance: { kind: "DEMONSTRATION", note: "DEMONSTRAÇÃO", reference_time: "2026-11-05T16:00:00+00:00",
    cycle_origins: ["SIMULATED_LLM"], real_llm_calls: 0, is_current_autonomous_research: false },
  gates: { exploration: "EXPLORATION_ALLOWED", scientific_validation: "SCIENTIFICALLY_BLOCKED", limitations: ["7_days BELOW_99_PERCENT"] },
  memory: { records: 5, experiments: 3, distinct_questions: 3, cycles: 1 },
  last_cycle: { recorded_at: "2026-11-05T12:00:00+00:00", llm_calls: 0 },
  investigating: [{ kind: "NEEDS_PREREGISTRATION", ready: false, question: "Pré-registar" }],
  discovered: [{ state: "PROMISING_EXPLORATORY", question: "<img src=x onerror=alert(1)>", market: "TOTAL_GOALS",
    outcome: "OVER_2_5", variables: ["lambda_net"], new_indicators: [{ name: "X_A" }], group_n: 40, control_n: 90,
    effect: 0.2, effect_ci95: [0.1, 0.3], p_value: 0.001, q_value: 0.01, primary_statistic: "DIFFERENCE_IN_MEAN_RESIDUAL_VS_MARKET",
    checks: { F1_PERMUTATION: "PASS" }, missing: [], limitations: [], next_question: "Pré-registar", version: 1, origin: "LLM" }],
  rejected: [], rejected_plans: [], needs_more_data: [], validated: [{ fake: true }],
  validated_note: "Nenhuma estratégia validada.",
};

test("panel never uses innerHTML or network calls to models", () => {
  assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|eval\(|new Function/.test(js));
  assert.ok(!/cloudflare|api\.|chat\/completions/i.test(js));
  assert.match(html, /research-autonomy\.js\?v=/);
});

test("model text is rendered as text and validated stays zero", () => {
  const { doc, nodes } = fakeDoc();
  ui.render(doc, sample);
  assert.strictEqual(nodes["ra-validated"].textContent, "0");
  const disc = nodes["ra-discovered"].textContent;
  assert.ok(disc.includes("<img src=x onerror=alert(1)>"), "kept as literal text");
  assert.ok(disc.includes("Promissor (exploratório)"));
  assert.ok(nodes["ra-gates"].textContent.includes("bloqueada"));
});

test("demonstration is labelled with origin, reference date and no real LLM calls", () => {
  const { doc, nodes } = fakeDoc();
  ui.render(doc, sample);
  const t = nodes["ra-provenance"].textContent;
  assert.ok(t.includes("DEMONSTRAÇÃO — NÃO É INVESTIGAÇÃO AUTÓNOMA ATUAL"));
  assert.ok(t.includes("2026-11-05T16:00:00+00:00"));
  assert.ok(t.includes("SIMULATED_LLM"));
  assert.ok(t.includes("Sem chamadas reais ao LLM"));
  assert.ok(nodes["ra-provenance"].className.includes("DEMONSTRATION"));
});

test("missing provenance or schema 1 is rejected", () => {
  const { doc } = fakeDoc();
  assert.throws(() => ui.render(doc, Object.assign({}, sample, { provenance: undefined })));
  assert.throws(() => ui.render(doc, Object.assign({}, sample, { schema_version: 1 })));
});

function fetchWith(map) {
  return url => {
    const key = Object.keys(map).find(k => url.startsWith(k));
    const v = map[key];
    return Promise.resolve(typeof v === "number" ? { ok: false, status: v } : { ok: true, status: 200, json: () => Promise.resolve(v) });
  };
}

test("only a 404 on the operational report falls back to the labelled demo", async () => {
  let f = fakeDoc();
  await ui.load(f.doc, fetchWith({ "./research/autonomous-research.json": 404, "./research/demo/panel.json": sample }));
  assert.ok(f.nodes["ra-state"].textContent.startsWith("Ainda não existe investigação operacional publicada"));
  assert.ok(f.nodes["ra-provenance"].textContent.includes("DEMONSTRAÇÃO"));
  f = fakeDoc();
  await ui.load(f.doc, fetchWith({ "./research/autonomous-research.json": 500, "./research/demo/panel.json": sample }));
  assert.ok(f.nodes["ra-state"].textContent.startsWith("Dados indisponíveis"));
  assert.ok(!(f.nodes["ra-provenance"] || { textContent: "" }).textContent.includes("DEMONSTRAÇÃO"),
            "a server error never shows the demo");
  f = fakeDoc();
  const fakeDemo = Object.assign({}, sample, { provenance: Object.assign({}, sample.provenance, { kind: "OPERATIONAL" }) });
  await ui.load(f.doc, fetchWith({ "./research/autonomous-research.json": 404, "./research/demo/panel.json": fakeDemo }));
  assert.ok(f.nodes["ra-state"].textContent.startsWith("Dados indisponíveis"), "demo file must be labelled DEMONSTRATION");
});

test("unknown schema is rejected, not shown as empty results", () => {
  const { doc } = fakeDoc();
  assert.throws(() => ui.render(doc, { schema_version: 2 }));
});

test("tracked operational report, once published, is OPERATIONAL, exploratory and splits LLM from offline", () => {
  // The first live cycle (run 42021728675) published this file; before that it did not exist.
  const p = path.join(__dirname, "../docs/research/autonomous-research.json");
  if (!fs.existsSync(p)) return;
  const data = JSON.parse(fs.readFileSync(p, "utf8"));
  assert.strictEqual(data.provenance.kind, "OPERATIONAL");
  assert.strictEqual(data.status, "EXPLORATORY_RESEARCH_NOT_VALIDATION");
  assert.deepStrictEqual(data.validated, []);
  for (const c of [...data.discovered, ...data.rejected, ...data.needs_more_data]) {
    assert.strictEqual(c.scientific_status, "EXPLORATORY_NOT_VALIDATED");
  }
  // Published by the workflow only; reports from before provenance v3 are split client-side.
  const split = data.research_split || ui.deriveSplit(data);
  assert.ok(split && split.autonomous && split.deterministic, "LLM and offline research are reported separately");
  const llmCards = [...data.discovered, ...data.rejected, ...data.needs_more_data].filter(c => c.origin === "LLM_LIVE").length;
  assert.ok(split.autonomous.experiments_executed >= llmCards);
  if (data.research_split) {
    assert.strictEqual(data.provenance.is_current_autonomous_research, split.autonomous.experiments_executed > 0);
  }
  const { doc, nodes } = fakeDoc();
  ui.render(doc, data);
  assert.ok(nodes["ra-autonomous"].textContent.includes("Experiências executadas a partir de planos do LLM: " + split.autonomous.experiments_executed));
  assert.ok(nodes["ra-deterministic"].textContent.includes("Experiências do proponente offline: " + split.deterministic.experiments_executed));
});

test("historical live cycle reads 3 proposed, 0 accepted, 0 executed by the LLM and 40 offline", () => {
  const { doc, nodes } = fakeDoc();
  ui.renderSplit(doc, {
    autonomous: { models: ["NAO_REGISTADO_CICLO_ANTERIOR_A_PROVENIENCIA_V3"], real_llm_calls: 1, plans_received: 3,
      plans_accepted: 0, plans_rejected: 3, plans_duplicate_skipped: 0, experiments_executed: 0,
      cycles: [{ recorded_at: "2026-11-05T11:49:58+00:00", model: "NAO_REGISTADO_CICLO_ANTERIOR_A_PROVENIENCIA_V3",
        model_inferred_from_code: { model: "@cf/meta/llama-3.1-8b-instruct-fast" }, plans_received: 3, plans_accepted: 0,
        experiments_from_llm: 0, experiments_from_offline: 40,
        rejection_reasons: { "DSL:INVALID_INDICATOR_NAME": 1, INDICATOR_DEFINED_BUT_UNUSED: 2 } }] },
    deterministic: { experiments_executed: 40, distinct_questions: 40, states: { NO_SUPPORT_IN_DATA: 34, INSUFFICIENT_DATA: 6 }, limitations: ["grelha fixa"] }
  });
  const a = nodes["ra-autonomous"].textContent;
  assert.ok(a.includes("LLM: 3 propostas, 0 aceites, 0 experiências executadas"));
  assert.ok(a.includes("offline: 40 experiências"));
  assert.ok(a.includes("inferido do código: @cf/meta/llama-3.1-8b-instruct-fast"));
  assert.ok(a.includes("Experiências executadas a partir de planos do LLM: 0"));
  assert.ok(nodes["ra-deterministic"].textContent.includes("Experiências do proponente offline: 40"));
});

test("published pre-v3 report (first live cycle) is split as 3 proposed / 0 accepted / 0 LLM / 40 offline", () => {
  const p = path.join(__dirname, "../docs/research/autonomous-research.json");
  if (!fs.existsSync(p)) return;
  const data = JSON.parse(fs.readFileSync(p, "utf8"));
  if (data.research_split || data.last_cycle.cycle_id !== "Ceede16a74f0ae09") return;
  const s = ui.deriveSplit(data);
  assert.deepStrictEqual([s.autonomous.plans_received, s.autonomous.plans_accepted, s.autonomous.experiments_executed,
                          s.deterministic.experiments_executed], [3, 0, 0, 40]);
  const { doc, nodes } = fakeDoc();
  ui.render(doc, data);
  assert.ok(nodes["ra-autonomous"].textContent.includes("LLM: 3 propostas, 0 aceites, 0 experiências executadas"));
  assert.ok(nodes["ra-autonomous"].textContent.includes("offline: 40 experiências"));
  assert.ok(nodes["ra-provenance"].textContent.includes("Chamadas reais ao LLM: 1"));
});

test("reports with nothing to split are labelled, not shown as LLM research", () => {
  const { doc, nodes } = fakeDoc();
  ui.render(doc, Object.assign({}, sample, { discovered: [], rejected_plans: [] }));
  assert.ok(nodes["ra-autonomous"].textContent.includes("formato anterior"));
});

test("tracked demo panel is a labelled DEMONSTRATION", () => {
  const p = path.join(__dirname, "../docs/research/demo/panel.json");
  const data = JSON.parse(fs.readFileSync(p, "utf8"));
  assert.strictEqual(data.provenance.kind, "DEMONSTRATION");
  assert.strictEqual(data.provenance.real_llm_calls, 0);
  assert.strictEqual(data.provenance.is_current_autonomous_research, false);
  assert.strictEqual(data.status, "EXPLORATORY_RESEARCH_NOT_VALIDATION");
  assert.deepStrictEqual(data.validated, []);
  for (const c of [...data.discovered, ...data.rejected, ...data.needs_more_data]) {
    assert.strictEqual(c.scientific_status, "EXPLORATORY_NOT_VALIDATED");
  }
  const { doc } = fakeDoc();
  ui.render(doc, data);
});
