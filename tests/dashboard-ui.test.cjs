"use strict";
// Read-only dashboard calculations, no network or browser needed.
const assert=require("node:assert/strict");
const test=require("node:test");
const fs=require("node:fs");
const path=require("node:path");
const model=require("../docs/dashboard.js");
const root=path.resolve(__dirname,"..");
const signals=[
  {home:"SC Braga",away:"Famalicão",competition:"Taça",kickoff_utc:"2026-11-02T20:00:00Z",profit:null},
  {home:"Blackpool",away:"Aston Villa U21",competition:"Trophy",kickoff_utc:"2026-10-25T20:00:00Z",profit:1},
  {home:"Dortmund",away:"Werder",competition:"DFB Pokal",kickoff_utc:"2026-10-29T20:00:00Z",profit:null},
];
test("H1: singles and ROI count only settled observations",()=>{
  const d={alert_count:160,signals,singles:{total:3,pending:2,settled:1,roi_pct:25,profit_units:.25},
    tickets:[{ticket_id:"T-1"}],triples:{total:1,pending:1,settled:0,roi_pct:null}};
  assert.deepEqual(model.h1Metrics(d),{alerts:160,signals:3,triples:1,pending:2,settled:1,roi:25,profit:.25,
    triplePending:1,tripleSettled:0,tripleRoi:null});
  assert.equal(model.roi(null,0),"Sem resultados");
  assert.equal(model.roi(25,1),"+25,0%");
});
test("Singles: upcoming first; no settled game counted as upcoming",()=>{
  const now=Date.parse("2026-10-27T21:00:00Z");
  assert.deepEqual(model.sortedSignals(signals,now).map(x=>x.home),["Dortmund","SC Braga","Blackpool"]);
  assert.deepEqual(model.filteredSignals(signals,"DOR","upcoming",now).map(x=>x.home),["Dortmund"]);
  assert.deepEqual(model.filteredSignals(signals,"","settled",now).map(x=>x.home),["Blackpool"]);
  assert.deepEqual(model.filteredSignals(signals,"","pending",now).map(x=>x.home),["Dortmund","SC Braga"]);
});
test("Freshness: invalid or future data is not shown as healthy",()=>{
  const now=Date.parse("2026-10-27T21:00:00Z");
  assert.equal(model.ageState("2026-10-27T20:51:00Z",now,20),"ok");
  assert.equal(model.ageState("2026-10-27T20:35:00Z",now,20),"stale");
  assert.equal(model.ageState("2026-10-27T21:05:00Z",now,20),"unknown");
  assert.equal(model.ageState("not-a-timestamp",now,20),"unknown");
});
test("LAB: counts by match rather than pretending alerts are independent",()=>{
  const tl={summary:{messages:142,matches:107,repeated_matches:30,related_message_pairs:6,possibly_redundant_snapshots:4}};
  const v4={phase_coverage:{first_24h:{captured:66,eligible:66}}};
  const gold={human_review_totals:{messages_with_human_review:4,fields_matching_v4:52,fields_compared:52},pending_reference_count:4};
  const m=model.labMetrics(tl,v4,gold);
  assert.deepEqual([m.messages,m.matches,m.repeated,m.related,m.duplicates],[142,107,30,6,4]);
  assert.deepEqual([m.reviewed,m.agreed,m.compared,m.pending],[4,52,52,4]);
});
test("LAB: search and related/reversal/V4 filters do not fabricate records",()=>{
  const tl=[{match_label:"Dortmund – Werder",related_messages:[{}],trajectory:{total:{reversals:[]}},
      events:[{snapshots:{total:{origin:"V4_EXPLICIT"}}}]},
     {match_label:"Blackpool – Aston Villa",related_messages:[],trajectory:{total:{reversals:[{}]}},
      events:[{snapshots:{total:{origin:"H1_LEGACY_ONLY"}}}]}];
  assert.equal(model.filteredTimelines(tl,"dort","all").length,1);
  assert.equal(model.filteredTimelines(tl,"","related").length,1);
  assert.equal(model.filteredTimelines(tl,"","reversals").length,1);
  assert.equal(model.filteredTimelines(tl,"","v4").length,1);
  assert.equal(model.filteredTimelines(tl,"unknown","all").length,0);
});
test("Static page: IDs exist, dedicated LAB entry and data endpoints are reachable by relative path",()=>{
  // Legacy H1 remains fully functional but is no longer the main entry.\n  const html=fs.readFileSync(path.join(root,"docs/h1.html"),"utf8");\n  const master=fs.readFileSync(path.join(root,"docs/index.html"),"utf8");\n  assert.match(master,/<title>MASTER BRAIN/);\n  assert.match(master,/id="page-radar"/);\n  assert.match(master,/id="page-futuros"/);\n  assert.match(master,/href="\.\/h1\.html#h1"/);
  const js=fs.readFileSync(path.join(root,"docs/dashboard.js"),"utf8");
  const css=fs.readFileSync(path.join(root,"docs/dashboard.css"),"utf8");
  for(const name of ["overview","h1","triples","market","quality"]){
    assert.match(html,new RegExp('id="view-'+name+'"'));
    assert.match(html,new RegExp('data-view="'+name+'"'));
  }
  for(const id of ["h1-list","triple-list","market-list","quality-gates","quality-families"]){
    assert.match(html,new RegExp('id="'+id+'"'));
  }
  for(const rel of ["./lab.html","./golden-review.html","./dashboard.css","./dashboard.js"])assert.ok(html.includes(rel));
  for(const key of ["./data.json","./lab/v4-audit.json","./lab/golden-report.json","./lab/match-trajectories.json"])assert.ok(js.includes(key));
  assert.match(css,/@media\(max-width:620px\)/);
  assert.doesNotMatch(html,/<script[^>]*src="https?:\/\//);
  assert.ok(!html.includes("fetch('https://"));
});
test("Tracked JSON sample is consistent with the read-only dashboard (real data not a synthetic market)",()=>{
  const d=JSON.parse(fs.readFileSync(path.join(root,"docs/data.json"),"utf8"));
  const tl=JSON.parse(fs.readFileSync(path.join(root,"docs/lab/match-trajectories.json"),"utf8"));
  const g=JSON.parse(fs.readFileSync(path.join(root,"docs/lab/golden-report.json"),"utf8"));
  const h=model.h1Metrics(d),m=model.labMetrics(tl,null,g);
  assert.ok(h.signals>=0 && h.triples>=0);
  assert.ok(m.messages>=m.matches && m.matches>=m.repeated);
  assert.equal(m.reviewed,g.human_review_totals.messages_with_human_review);
  for(const game of tl.timelines){
    for(const row of game.trajectory?.total?.points||[]){
      assert.ok(Number.isFinite(row.before)&&Number.isFinite(row.after));
    }
  }
});
