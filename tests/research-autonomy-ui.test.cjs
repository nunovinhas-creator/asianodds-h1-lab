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
  schema_version: 1, status: "EXPLORATORY_RESEARCH_NOT_VALIDATION", generated_at: "2026-11-05T12:00:00+00:00",
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

test("unknown schema is rejected, not shown as empty results", () => {
  const { doc } = fakeDoc();
  assert.throws(() => ui.render(doc, { schema_version: 2 }));
});

test("published panel JSON, if present, matches the contract", () => {
  const p = path.join(__dirname, "../docs/research/autonomous-research.json");
  if (!fs.existsSync(p)) return;
  const data = JSON.parse(fs.readFileSync(p, "utf8"));
  assert.strictEqual(data.status, "EXPLORATORY_RESEARCH_NOT_VALIDATION");
  assert.deepStrictEqual(data.validated, []);
  for (const c of [...data.discovered, ...data.rejected, ...data.needs_more_data]) {
    assert.strictEqual(c.scientific_status, "EXPLORATORY_NOT_VALIDATED");
  }
  const { doc } = fakeDoc();
  ui.render(doc, data);
});
