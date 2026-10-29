/* MASTER BRAIN: conservative, offline matcher for fields actually exposed in pattern-watch.json.
   NO missing market is interpreted as false. No odds or results are fabricated.
   Three-valued logic: true = observed; false = definitively absent; null = unknown. */
(function(root,factory){
 const api=factory();
 if(typeof module==="object"&&module.exports)module.exports=api;
 else root.MBPatternMatcher=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
 "use strict";
 const EPS=0.05, INTENSITY_EPS=0.03, BIG_NET=0.20;
 const valid=n=>typeof n==="number"&&Number.isFinite(n);
 const parse=s=>typeof s==="string"&&s.trim()?Date.parse(s):NaN;
 function observations(match){
   const rows=match?.observations;
   if(!Array.isArray(rows)||!rows.length)return null;
   const out=rows.map(o=>({at:parse(o?.observed_at),d:o?.delta_lambda,
     ep:o?.episode,event:o?.event_id,origin:o?.total_origin}));
   if(out.some(o=>!Number.isFinite(o.at)||!o.event))return null;
   out.sort((a,b)=>a.at-b.at || String(a.event).localeCompare(String(b.event)));
   if(out.some((o,i)=>i&&o.event===out[i-1].event))return null;
   return out;
 }
 function factMap(match){
   const f=Object.create(null);
   if(!match||typeof match!=="object"||!match.strict_condition)return f;
   const rows=observations(match),ko=parse(match.kickoff_utc),first=parse(match.first_alert_at),
     last=parse(match.last_alert_at);
   if(!Number.isFinite(ko)||!rows||rows.some(x=>x.at>=ko))return f;
   if(valid(match.messages)&&match.messages===rows.length){
     f.G_MULTI_ALERT=rows.length>=2;f.G_SINGLE_ALERT=rows.length===1;
   }
   // Episode representatives use the first observation per episode, as the V5 feature engine does.
   if(rows.every(o=>o.ep!==null&&o.ep!==undefined)){
     const seen=new Set(), reps=[];
     for(const o of rows)if(!seen.has(String(o.ep))){seen.add(String(o.ep));reps.push(o)}
     if(valid(match.episodes)&&match.episodes===reps.length){
       f.G_MULTI_EPISODE=reps.length>=2;
       if(reps.every(o=>valid(o.d))){
         const dirs=reps.map(o=>o.d>=EPS?"UP":o.d<=-EPS?"DOWN":"FLAT");
         const nonflat=dirs.filter(d=>d!=="FLAT");
         f.G_REPEAT_SAME_DIRECTION=nonflat.length>=2&&new Set(nonflat).size===1;
         f.G_OPPOSING_DIRECTIONS=nonflat.includes("UP")&&nonflat.includes("DOWN");
         if(reps.length>=2){
           f.G_INTENSIFYING=Math.abs(reps[reps.length-1].d)>Math.abs(reps[0].d)+INTENSITY_EPS;
           f.G_WEAKENING=Math.abs(reps[reps.length-1].d)<Math.abs(reps[0].d)-INTENSITY_EPS;
         }
       }
       if(reps.length>=2){
         const gaps=reps.slice(1).map((o,i)=>(o.at-reps[i].at)/60000);
         if(gaps.every(g=>g>=0)){f.G_SHORT_INTERVAL=gaps.some(g=>g<30);f.G_LONG_INTERVAL=gaps.some(g=>g>360)}
       }
     }
   }
   // Historical V5 uses the first message, not a later reclassification.
   if(Number.isFinite(first)&&first<ko&&first<=last&&rows[0].at===first){
     const lead=(ko-first)/60000;
     f.G_FIRST_LEAD_LT_6H=lead<360;
     f.G_FIRST_LEAD_6_24H=lead>=360&&lead<=1440;
     f.G_FIRST_LEAD_GT_24H=lead>1440;
     f.M_EARLY=lead>1440;
   }
   if(Number.isFinite(last)&&last<ko&&rows[rows.length-1].at===last)
     f.M_LATE=(ko-last)/60000<60;
   const line=match.total_line_after;
   if(valid(line)&&match.total_line_origin==="V4_EXPLICIT"){
     f.G_LAST_LINE_LOW=line<=2.25;
     f.G_LAST_LINE_MID=line>2.25&&line<3.25; // V5 implementation, not label rounded to 2.5..3
     f.G_LAST_LINE_HIGH=line>=3.25;
   }
   if(rows.every(o=>valid(o.d))&&match.valid_total_messages===rows.length){
     f.M_IMPLIED_GOALS_UP=rows.some(o=>o.d>=EPS);
     f.M_IMPLIED_GOALS_DOWN=rows.some(o=>o.d<=-EPS);
     f.M_IMPLIED_GOALS_FLAT=rows.some(o=>Math.abs(o.d)<EPS);
   }
   // A last-message line change proves a positive HAS, but cannot prove that an
   // earlier message did not change. Hence no false fact for absent Total moves.
   if(valid(match.total_line_before)&&valid(match.total_line_after)&&
      match.total_line_origin==="V4_EXPLICIT"){
     const change=match.total_line_after-match.total_line_before;
     if(change>1e-9)f.M_TOTAL_LINE_UP=true;
     if(change< -1e-9)f.M_TOTAL_LINE_DOWN=true;
     if(Math.abs(change)<1e-9)f.M_TOTAL_LINE_SAME=true;
     if(Math.abs(change)>=0.5-1e-9)f.M_LINE_JUMP_HALF=true;
   }
   // Deliberately unknown: 1X2, Asian Handicap, alert trigger, inter-message
   // lambda net (NOT the sum of within-message deltas), gaps and price direction.
   // Absence from this object is UNKNOWN, not false.
   void BIG_NET;
   return f;
 }
 function condition(def,facts){
   if(!def||typeof def!=="object")return null;
   const positives=def.op==="HAS"?[def.a]:def.op==="AND"||def.op==="AND_NOT"?def.all:null;
   const negatives=def.op==="AND_NOT"?def.none:[];
   if(!Array.isArray(positives)||!positives.length||!Array.isArray(negatives))return null;
   // A false positive condition is a definite mismatch; unknown cannot match.
   if(positives.some(x=>facts[x]===false)||negatives.some(x=>facts[x]===true))return false;
   if(positives.some(x=>facts[x]!==true)||negatives.some(x=>facts[x]!==false))return null;
   return true;
 }
 function linked(match,research,options={}){
   if(!match?.strict_condition||!research||!Array.isArray(research.patterns))return[];
   const minN=options.minN??12,minDiff=options.minDiff??0.08;
   const patterns=[...research.patterns,...(Array.isArray(research.combinations_top)?research.combinations_top:[])];
   const facts=factMap(match),found=[],seen=new Set();
   for(const h of patterns){
     if(condition(h.definition,facts)!==true)continue;
     for(const target of ["OVER_2_5","BTTS_YES"]){
       const o=h.outcomes?.[target],id=h.id+"|"+target;
       if(seen.has(id)||!o||!valid(o.diff)||!valid(o.rate)||!valid(o.reference_rate)||
          !valid(o.known)||!valid(o.reference_known)||o.known<minN||o.reference_known<minN||o.diff<minDiff)continue;
       seen.add(id);found.push({id:h.id,label:h.label,target,
         state:h.state||"EXPLORATORIO",hits:o.hits,known:o.known,reference_known:o.reference_known,
         rate:o.rate,reference_rate:o.reference_rate,diff:o.diff,q:o.q_bh,definition:h.definition});
     }
   }
   found.sort((a,b)=>b.diff-a.diff||b.known-a.known||a.id.localeCompare(b.id));
   return found;
 }
 return {factMap,condition,linked};
});