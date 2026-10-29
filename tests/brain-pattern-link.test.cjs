"use strict";
const assert=require("node:assert/strict");
const test=require("node:test");
const m=require("../docs/brain-pattern-link.js");
function game(){
 return {match_key:"game:A",match_label:"Casa vs Fora",strict_condition:true,
  kickoff_utc:"2026-10-29T18:00:00+00:00",first_alert_at:"2026-10-29T15:00:00+00:00",
  last_alert_at:"2026-10-29T16:00:00+00:00",messages:3,episodes:2,
  valid_total_messages:3,total_line_origin:"V4_EXPLICIT",
  total_line_before:2.5,total_line_after:2.75,
  observations:[
   {event_id:"e1",episode:"0",observed_at:"2026-10-29T15:00:00+00:00",delta_lambda:0.12},
   {event_id:"e2",episode:"0",observed_at:"2026-10-29T15:00:04+00:00",delta_lambda:0.12},
   {event_id:"e3",episode:"1",observed_at:"2026-10-29T16:00:00+00:00",delta_lambda:0.17},
  ]};
}
function row(id,def,diff=0.25,known=30){
 return {id,label:id,definition:def,state:"EXPLORATORIO",
  outcomes:{OVER_2_5:{diff,rate:0.73,reference_rate:0.48,known,reference_known:95,hits:22,q_bh:0.991}}};
}
test("observed, absent and unknown are distinct: historical combination must be fully verifiable",()=>{
 const facts=m.factMap(game());
 assert.equal(facts.G_MULTI_EPISODE,true);
 assert.equal(facts.G_FIRST_LEAD_LT_6H,true);
 assert.equal(facts.G_LAST_LINE_MID,true);
 assert.equal(facts.G_FIRST_LEAD_GT_24H,false);
 assert.equal(facts.M_IMPLIED_GOALS_DOWN,false);
 assert.equal(facts.G_NET_IMPLIED_SMALL,undefined); // cannot sum intra-message deltas
 assert.equal(facts.M_AH_TOWARD_HOME,undefined); // missing market is NOT 'false'
 assert.equal(m.condition({op:"AND_NOT",all:["G_LAST_LINE_MID"],none:["G_FIRST_LEAD_GT_24H"]},facts),true);
 assert.equal(m.condition({op:"AND_NOT",all:["G_LAST_LINE_MID"],none:["M_AH_TOWARD_HOME"]},facts),null);
 assert.equal(m.condition({op:"HAS",a:"M_1X2_AWAY_PROB_UP"},facts),null);
 assert.equal(m.condition({op:"HAS",a:"M_IMPLIED_GOALS_DOWN"},facts),false);
});
test("same match links to historical pattern definitions, not just similar names",()=>{
 const r={patterns:[
  row("real",{op:"HAS",a:"G_MULTI_EPISODE"}),
  row("unknown-exclusion",{op:"AND_NOT",all:["G_LAST_LINE_MID"],none:["M_AH_TOWARD_HOME"]}),
  row("known-exclusion",{op:"AND_NOT",all:["G_LAST_LINE_MID"],none:["G_FIRST_LEAD_GT_24H"]}),
  row("incomplete",{op:"HAS",a:"G_NET_IMPLIED_SMALL"}),
  row("not-favorable",{op:"HAS",a:"G_FIRST_LEAD_LT_6H"},-0.10),
  row("few-results",{op:"HAS",a:"G_FIRST_LEAD_LT_6H"},0.2,5),
 ],combinations_top:[]};
 assert.deepEqual(m.linked(game(),r).map(x=>x.id).sort(),["known-exclusion","real"]);
});
test("future observations and incomplete totals must never prove a pattern",()=>{
 const g=game();
 g.observations[2].observed_at="2026-10-29T18:01:00+00:00";
 assert.equal(Object.keys(m.factMap(g)).length,0);
 assert.deepEqual(m.linked(g,{patterns:[row("real",{op:"HAS",a:"G_MULTI_EPISODE"})]}),[]);
 const bad=game();bad.valid_total_messages=2;
 assert.equal(m.factMap(bad).M_IMPLIED_GOALS_UP,undefined);
 const uncertain=game();uncertain.strict_condition=false;
 assert.deepEqual(m.linked(uncertain,{patterns:[row("real",{op:"HAS",a:"G_MULTI_EPISODE"})]}),[]);
});
test("only last Total line move visible; no invented historical absence",()=>{
 const g=game(),f=m.factMap(g);
 assert.equal(f.M_TOTAL_LINE_UP,true);
 assert.equal(f.M_TOTAL_LINE_DOWN,undefined);
 assert.equal(m.condition({op:"AND_NOT",all:["G_MULTI_EPISODE"],none:["M_TOTAL_LINE_DOWN"]},f),null);
});
test("unknown schema and skipped markets cannot be converted into matches",()=>{
 const facts=m.factMap(game());
 for(const def of [{op:"ORDER",a:"G_MULTI_EPISODE"},{op:"HAS",a:"M_TRIGGER_1X2"},{op:"AND",all:["G_MULTI_EPISODE","M_AH_TOWARD_AWAY"]}])
  assert.notEqual(m.condition(def,facts),true);
 assert.deepEqual(m.linked(game(),{patterns:[]}),[]);
 assert.deepEqual(m.linked(game(),null),[]);
});
test("real V5 snapshot: each displayed association has an exact definition and independently recorded sample",()=>{
 const fs=require("node:fs"),path=require("node:path"),root=path.resolve(__dirname,"..");
 const w=JSON.parse(fs.readFileSync(path.join(root,"docs/lab/pattern-watch.json"),"utf8"));
 const r=JSON.parse(fs.readFileSync(path.join(root,"docs/lab/pattern-research.json"),"utf8"));
 const definitions=new Map([...(r.patterns||[]),...(r.combinations_top||[])].map(x=>[x.id,x]));
 const seen=new Set();
 for(const game of w.future_strict||[]){
  assert.equal(game.strict_condition,true);
  assert.equal(seen.has(game.match_key),false,"No fixture may be counted twice");
  seen.add(game.match_key);
  const ko=Date.parse(game.kickoff_utc);
  assert.ok((game.observations||[]).every(e=>Date.parse(e.observed_at)<ko));
  for(const hit of m.linked(game,r)){
   const definition=definitions.get(hit.id);
   assert.ok(definition,hit.id);
   assert.equal(m.condition(definition.definition,m.factMap(game)),true);
   assert.ok(hit.known>=12&&hit.reference_known>=12&&hit.diff>=0.08);
   assert.equal(definition.outcomes[hit.target].hits,hit.hits);
   assert.equal(definition.outcomes[hit.target].known,hit.known);
  }
 }
});
