import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { checkAndDispatch } from "./worker.mjs";

const T = Date.parse("2026-10-27T13:30:00Z");
const env = { GITHUB_DISPATCH_TOKEN: "synthetic_token_for_unit_tests" };
function response(body, status=200) {
  return {ok:status>=200&&status<300,status,async json(){return body;}};
}
function stub(createdAt, extraStatus=204) {
  const calls=[];
  const fetchImpl=async(url,opts)=>{
    calls.push({url,method:opts.method,body:opts.body});
    if(opts.method==="GET")return response({workflow_runs:createdAt?[{created_at:createdAt}]:[]});
    return response({},extraStatus);
  };
  return {calls,fetchImpl};
}

test("never dispatches if latest GitHub collector is fresh", async()=>{
  const s=stub("2026-10-27T13:27:00Z");
  const result=await checkAndDispatch(env,{now:T,fetchImpl:s.fetchImpl});
  assert.equal(result.dispatched,false);
  assert.equal(s.calls.length,1);
});

test("dispatches stale collector using explicit cloudflare-cron source",async()=>{
  const s=stub("2026-10-27T13:20:00Z");
  const result=await checkAndDispatch(env,{now:T,fetchImpl:s.fetchImpl});
  assert.equal(result.dispatched,true);
  assert.equal(s.calls.length,2);
  assert.equal(s.calls[1].method,"POST");
  assert.deepEqual(JSON.parse(s.calls[1].body),{
    ref:"main",inputs:{trigger_source:"cloudflare-cron"}
  });
  assert.match(s.calls[1].url,/\/actions\/workflows\/collect.yml\/dispatches$/);
});

test("initial collector run is dispatched when there are no runs",async()=>{
  const s=stub();
  assert.equal((await checkAndDispatch(env,{now:T,fetchImpl:s.fetchImpl})).dispatched,true);
});

test("GET failure blocks dispatch instead of sending blind duplicate",async()=>{
  let count=0;
  await assert.rejects(
    checkAndDispatch(env,{now:T,fetchImpl:async()=>{count++;return response({},403)}}),
    /GITHUB_RUNS_CHECK_FAILED/
  );
  assert.equal(count,1);
});

test("dispatch failure produces safe error without echoing token",async()=>{
  const s=stub("2026-10-27T13:10:00Z",422);
  await assert.rejects(checkAndDispatch(env,{now:T,fetchImpl:s.fetchImpl}),
    /GITHUB_DISPATCH_FAILED: HTTP 422/);
});

test("without the Cloudflare secret never calls GitHub",async()=>{
  await assert.rejects(checkAndDispatch({},{
    now:T,fetchImpl:async()=>{throw new Error("network must not be called");}
  }),/DISPATCH_SETUP_REQUIRED/);
});

test("public Worker HTTP entrypoint cannot dispatch",async()=>{
  const r=await worker.fetch();
  assert.equal(r.status,404);
});
