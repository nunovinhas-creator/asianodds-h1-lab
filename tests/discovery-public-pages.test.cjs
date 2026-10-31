"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const crypto = require("node:crypto");
const {TextDecoder} = require("node:util");

const source = fs.readFileSync("docs/master-brain.js","utf8");
assert.ok(source.includes("module.exports={validateData,renderPatternsMeta"));
const injectable = source.replace("module.exports={validateData,renderPatternsMeta",
                                  "module.exports={fetchDiscovery,validateData,renderPatternsMeta");

function page(raw) {
  const bytes = Buffer.from(JSON.stringify(raw));
  const sha256 = crypto.createHash("sha256").update(bytes).digest("hex");
  return { bytes, sha256, descriptor: {
    path: "discovery-pages/" + sha256 + ".json",
    sha256, bytes: bytes.byteLength, patterns: Object.keys(raw.patterns).length
  }};
}

function runner(root, pageFiles) {
  const fetch = async (url) => {
    if(url === "./lab/discoveries.json") return {ok:true,json:async()=>root};
    const name = url.replace("./lab/", "");
    if(!pageFiles.has(name))return {ok:false,status:404};
    const bytes=pageFiles.get(name);
    return {ok:true,arrayBuffer:async()=>Uint8Array.from(bytes).buffer};
  };
  const module={exports:{}};
  const sandbox={module,fetch,crypto:crypto.webcrypto,TextDecoder,AbortController,
                 setTimeout,clearTimeout};
  vm.runInNewContext(injectable,sandbox);
  return module.exports.fetchDiscovery("lab/discoveries.json");
}

test("loads and verifies a paginated discovery with full pattern evidence", async()=>{
  const p=page({patterns:{"A|OVER_2_5":{latest:{known:5},points:[{at_utc:"t1"}]},
                          "B|BTTS_YES":{latest:{known:3},points:[{at_utc:"t2"}]}}});
  const root={schema_version:1, patterns:{},pattern_count:2,pattern_pages:[p.descriptor],
              timeline:[],prospective:{},baseline_at:"2026-10-30T22:00:00Z"};
  const hydrated=await runner(root,new Map([[p.descriptor.path,p.bytes]]));
  assert.equal(hydrated.patterns["A|OVER_2_5"].latest.known,5);
  assert.deepEqual(JSON.parse(JSON.stringify(hydrated.patterns["B|BTTS_YES"].points)),[{at_utc:"t2"}]);
  assert.equal(hydrated.pattern_count,2);
});

test("fails closed when page bytes are changed or missing",async()=>{
  const p=page({patterns:{"A":{latest:{known:1}}}});
  const root={schema_version:1,patterns:{},pattern_count:1,pattern_pages:[p.descriptor]};
  await assert.rejects(runner(root,new Map()),/HTTP/);
  await assert.rejects(runner(root,new Map([[p.descriptor.path,Buffer.from("{}")]])),/integrity mismatch/);
  await assert.rejects(runner({...root,pattern_count:2},new Map([[p.descriptor.path,p.bytes]])),
                       /Incomplete discovery page coverage/);
});

test("legacy unpaged discovery remains readable",async()=>{
  const old={schema_version:1,patterns:{"x":{latest:{known:1}}}};
  const hydrated=await runner(old,new Map());
  assert.deepEqual(JSON.parse(JSON.stringify(hydrated)),old);
});
