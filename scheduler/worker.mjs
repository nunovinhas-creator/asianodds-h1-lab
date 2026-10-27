/**
 * AsianOdds H1 external fallback cron.
 *
 * Cloudflare Workers Free: cron every 5 minutes, calls GitHub workflow_dispatch
 * only when collector runs have not started recently.
 *
 * GITHUB_DISPATCH_TOKEN is a Cloudflare Worker secret, never an HTTP parameter.
 */
const OWNER = "nunovinhas-creator";
const REPO = "asianodds-h1-lab";
const WORKFLOW = "collect.yml";
const BASE = "https://api.github.com/repos/" + OWNER + "/" + REPO;
const MAX_FRESH_AGE_MS = 4 * 60 * 1000 + 30 * 1000;

function headers(token) {
  return {
    Accept: "application/vnd.github+json",
    Authorization: "Bearer " + token,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "asianodds-h1-external-cron",
  };
}

export async function checkAndDispatch(env, options = {}) {
  const request = options.fetchImpl || fetch;
  const now = options.now ?? Date.now();
  const token = env.GITHUB_DISPATCH_TOKEN;
  if (!token || typeof token !== "string") {
    throw new Error("DISPATCH_SETUP_REQUIRED: Cloudflare Worker secret GITHUB_DISPATCH_TOKEN");
  }

  // Use the workflow-scoped endpoint: don't mistake Pages deployments for
  // successful Telegram collection. Inspect started runs, not only successes.
  const response = await request(
    BASE + "/actions/workflows/" + WORKFLOW + "/runs?per_page=5",
    { method: "GET", headers: headers(token) }
  );
  if (!response.ok) {
    throw new Error("GITHUB_RUNS_CHECK_FAILED: HTTP " + response.status);
  }
  const payload = await response.json();
  if (!payload || !Array.isArray(payload.workflow_runs)) {
    throw new Error("GITHUB_RUNS_CHECK_FAILED: malformed response");
  }

  const newestTimestamp = payload.workflow_runs
    .map((run) => Date.parse(run.created_at))
    .filter(Number.isFinite)
    .sort((a, b) => b - a)[0];

  if (newestTimestamp !== undefined &&
      now - newestTimestamp >= 0 &&
      now - newestTimestamp < MAX_FRESH_AGE_MS) {
    console.log("H1_CRON_SKIPPED_RECENT_RUN");
    return { status: "recent_run", dispatched: false };
  }

  const dispatchResponse = await request(
    BASE + "/actions/workflows/" + WORKFLOW + "/dispatches",
    {
      method: "POST",
      headers: { ...headers(token), "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main", inputs: { trigger_source: "cloudflare-cron" } }),
    }
  );
  if (dispatchResponse.status !== 204) {
    // GitHub may return a text body with secrets/paths; don't print it.
    throw new Error("GITHUB_DISPATCH_FAILED: HTTP " + dispatchResponse.status);
  }
  console.log("H1_CRON_DISPATCH_ACCEPTED");
  return { status: "accepted", dispatched: true };
}

export default {
  async fetch() {
    // No public HTTP trigger: only Cloudflare cron may dispatch the workflow.
    return new Response("Not found", { status: 404 });
  },
  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(checkAndDispatch(env));
  },
};
