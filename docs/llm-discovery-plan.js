/* Read-only offline planner snapshot. Never calls an AI endpoint. */
(async () => {
  "use strict";
  const status = document.getElementById("offline-state");
  const queue = document.getElementById("offline-queue");
  try {
    const response = await fetch("./lab/llm-discovery-plan.json", {cache: "no-store"});
    if (!response.ok) throw new Error("Unavailable");
    const p = await response.json();
    if (p.schema_version !== 1 || p.state !== "OFFLINE_QUEUE_NOT_SCIENTIFIC_EVIDENCE" ||
        p.llm_calls !== 0 || p.empirical_tests_performed !== 0 || !Array.isArray(p.queue)) {
      throw new Error("Invalid plan");
    }
    status.textContent = "Fotografia offline · pares: " + p.distinct_family_space["2"] +
      " · triplos com três famílias: " + p.distinct_family_space["3"] +
      " · por propor: " + p.remaining + " · já propostos: " + p.previously_proposed_unique +
      " · 0 chamadas IA · 0 testes empíricos. Atualização manual; não acompanha novas execuções automaticamente.";
    queue.replaceChildren();
    p.queue.forEach(c => {
      const li = document.createElement("li");
      li.textContent = c.feature_codes.join(" + ") + " · por propor · ID " + c.candidate_id.slice(0, 12);
      queue.appendChild(li);
    });
    const li = document.createElement("li");
    li.textContent = "Bloqueios: " + p.blocked_on.join("; ");
    queue.appendChild(li);
  } catch (_) {
    status.textContent = "Fila offline indisponível ou inválida; consultar os ficheiros e hashes no GitHub.";
    queue.replaceChildren();
  }
})();
