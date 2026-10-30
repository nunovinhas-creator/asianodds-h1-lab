/* MASTER BRAIN — read-only research-first data rendering, no betting actions. */
(function () {
 "use strict";
 const ROOT="./";
 const SOURCES={
   research:"lab/pattern-research.json", watch:"lab/pattern-watch.json",
   discovery:"lab/discoveries.json",
   ft:"lab/ft-results.json", quality:"lab/v4-audit.json", h1:"data.json"
 };
 const PAGE_NAMES={radar:"Radar do Cérebro",futuros:"Jogos futuros",padroes:"Padrões e cruzamentos",validacao:"Validação e evolução",dados:"Dados e qualidade"};
 const CATEGORY={
   RISING_EACH_EPISODE:["Subidas consistentes","rise"],
   RISING_WITH_FLAT:["Subidas + estável","flat"],
   FLAT_EACH_EPISODE:["Estável","flat"],
   OPPOSING_DIRECTIONS:["Sentidos opostos","alert"],
   POSSIBLE_DUPLICATE:["Possível repetição","warn"],
   INCOMPLETE_TOTAL:["Total incompleto","warn"],
   FALLING:["Desce significativamente","alert"]
 };
 const GATE_LABELS={
   coverage_99:"Cobertura de mensagens ≥ 99%",
   data_integrity:"Integridade do registo",
   field_agreement_100:"Concordância por campo com proveniência",
   golden_set_verified:"Golden Set revisto e certificado",
   independent_identity:"Identidade verificada independentemente",
   logs_clean_24h:"Logs da janela auditados",
   minimum_evidence:"Amostra mínima de evidência",
   window_elapsed:"Período mínimo decorrido"
 };
 const state={data:{},page:"radar",futureFilter:"strict"};
 const $=id=>document.getElementById(id);
 const create=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined&&text!==null)e.textContent=String(text);if(cls)e.className=cls;return e};
 const put=(id,value)=>{const n=$(id);if(n)n.textContent=value==null?"—":String(value)};
 const num=v=>v!==null&&v!==undefined&&v!==""&&typeof v!=="boolean"&&Number.isFinite(Number(v))?Number(v).toLocaleString("pt-PT"):"—";
 const perc=v=>typeof v==="number"&&Number.isFinite(v)?(v*100).toLocaleString("pt-PT",{maximumFractionDigits:1})+"%":"—";
 const nDec=(v,places=3)=>typeof v==="number"&&Number.isFinite(v)?v.toLocaleString("pt-PT",{maximumFractionDigits:places}):"—";
 const sign=v=>typeof v==="number"&&Number.isFinite(v)?(v>0?"+":"")+v.toLocaleString("pt-PT",{minimumFractionDigits:3,maximumFractionDigits:4}):"sem Total";
 const dt=v=>{const n=Date.parse(v||"");return Number.isFinite(n)?n:null};
 const formatDate=(v,opts={day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"})=>{
   const t=dt(v);return t==null?"—":new Intl.DateTimeFormat("pt-PT",{timeZone:"Europe/Lisbon",...opts}).format(t);
 };
 const present=t=>dt(t)!=null;
 const clear=(id)=>{const n=$(id);if(n)n.replaceChildren();return n};
 function empty(where,text){const n=create("div",text,"empty");where.append(n)}
 function tag(text,style){return create("span",text,"tag"+(style?" "+style:""))}
 function category(value){return CATEGORY[value]||[value||"Não classificado","warn"]}
 function data(key){return state.data[key]||null}
 function bar(label,value,max,reference=false){
   const row=create("div",null,"bar-row");
   row.append(create("span",label));
   const track=create("div",null,"track"),fill=create("div",null,"fill"+(reference?" reference":""));
   fill.style.width=Math.max(0,Math.min(100,max?100*value/max:0))+"%";track.append(fill);row.append(track);
   row.append(create("strong",perc(value)));return row;
 }
 function gate(parent,label,on,ok="Sim",no="Por comprovar"){
   const row=create("div",null,"gate");row.append(create("span",label));
   row.append(create("strong",on?ok:no,"state "+(on?"pass":"fail")));parent.append(row);
 }
 function move(page,history=true){
   if(!(page in PAGE_NAMES))page="radar";
   state.page=page;
   for(const id of Object.keys(PAGE_NAMES)){
     const el=$("page-"+id);if(el)el.hidden=id!==page;
   }
   document.querySelectorAll("[data-page]").forEach(btn=>{
     const active=btn.dataset.page===page;
     btn.classList.toggle("active",active);
     if(active)btn.setAttribute("aria-current","page");else btn.removeAttribute("aria-current");
   });
   put("breadcrumb-page",PAGE_NAMES[page]);
   if(history&&location.hash!=="#"+page)historyPush("#"+page);
   document.title=PAGE_NAMES[page]+" | MASTER BRAIN";
   if(page==="futuros")futureRows();
   if(page==="padroes")patterns();
   window.scrollTo({top:0,behavior:"auto"});
 }
 function historyPush(hash){try{history.replaceState(null,"",hash)}catch(_){location.hash=hash}}
 function legacyRedirect(){
   const h=decodeURIComponent(location.hash.slice(1)).toLowerCase();
   if(["h1","triples","market","quality","overview"].includes(h)){
     location.replace("./h1.html#"+h);return true;
   }return false;
 }
 function setupNav(){
   if(legacyRedirect())return;
   const h=location.hash.slice(1);
   move(h in PAGE_NAMES?h:"radar",false);
   document.querySelectorAll("[data-page]").forEach(btn=>btn.addEventListener("click",()=>move(btn.dataset.page)));
   document.querySelectorAll("[data-go]").forEach(btn=>btn.addEventListener("click",()=>move(btn.dataset.go)));
   window.addEventListener("hashchange",()=>{if(legacyRedirect())return;const page=location.hash.slice(1);if(page in PAGE_NAMES)move(page,false)});
   $("refresh").addEventListener("click",()=>load(true));
   $("discovery-filter").addEventListener("change",renderChronology);
   $("f-query").addEventListener("input",futureRows);
   document.querySelectorAll("[data-cat]").forEach(btn=>btn.addEventListener("click",()=>{
     state.futureFilter=btn.dataset.cat;
     document.querySelectorAll("[data-cat]").forEach(b=>{const active=b===btn;b.classList.toggle("active",active);b.setAttribute("aria-pressed",active?"true":"false")});
     futureRows();
   }));
   for(const id of ["p-query","p-target","p-type","p-sort"])$(id).addEventListener(id==="p-query"?"input":"change",patterns);
 }
 function validateData(key,body){
   const object=v=>v!==null&&typeof v==="object"&&!Array.isArray(v);
   const count=v=>Number.isSafeInteger(v)&&v>=0;
   const fail=()=>{throw Error("Contrato de dados inválido: "+key)};
   if(!object(body))fail();
   if(key!=="h1"&&body.schema_version!==1)fail();
   const arrays={research:["patterns","combinations_top","frozen"],watch:["future_strict","future_other_original","future_opposing"],discovery:["timeline"],ft:["games"],h1:["signals","tickets"]};
   for(const field of arrays[key]||[])if(!Array.isArray(body[field])||body[field].some(v=>!object(v)))fail();
   const objects={research:["scope","generation","state_counts"],watch:["summary"],discovery:["patterns","prospective"],ft:["timing_counts","coverage_diagnostics"],quality:["acceptance_gates"],h1:["singles","triples"]};
   for(const field of objects[key]||[])if(!object(body[field]))fail();
   if(!Object.hasOwn(objects,key))fail();
   const timestamp=key==="ft"?body.last_updated_at:key==="discovery"?body.baseline_at:body.generated_at;
   if(typeof timestamp!=="string"||!Number.isFinite(Date.parse(timestamp)))fail();
   if(key==="ft"){
     if(![body.matches,body.final_recorded,body.unverified].every(count)||body.final_recorded+body.unverified!==body.matches)fail();
     if(!Object.values(body.timing_counts).every(count)||Object.values(body.timing_counts).reduce((a,b)=>a+b,0)!==body.matches)fail();
   }
   if(key==="research"){
     if(![body.scope.ft_confirmed,body.scope.research_eligible,body.generation.hypotheses_evaluated].every(count)||!Object.values(body.state_counts).every(count))fail();
   }
   if(key==="watch"){
     if(!count(body.summary.strict_eligible)||body.summary.strict_eligible!==body.future_strict.length)fail();
     // Objects alone are not sufficient: futureRows sorts by kickoff and
     // renders observation arrays. Fail closed before any partial rendering.
     for(const row of [...body.future_strict,...body.future_other_original,...body.future_opposing]){
       if(typeof row.match_label!=="string"||!row.match_label.trim()||
          typeof row.kickoff_utc!=="string"||!Number.isFinite(Date.parse(row.kickoff_utc))||
          typeof row.category!=="string"||!count(row.episodes)||
          !Array.isArray(row.observations)||row.observations.some(v=>!object(v)))fail();
     }
   }
   if(key==="research"){
     // A malformed nested outcome must not crash radar/pattern sorting later.
     for(const row of [...body.patterns,...body.combinations_top]){
       if(typeof row.label!=="string"||!object(row.outcomes)||
          !object(row.outcomes.OVER_2_5)||!object(row.outcomes.BTTS_YES))fail();
     }
   }
   if(key==="quality"&&(!Object.keys(body.acceptance_gates).length||Object.values(body.acceptance_gates).some(v=>typeof v!=="boolean")))fail();
   if(key==="h1")for(const metric of [body.singles,body.triples]){
     if(![metric.total,metric.pending,metric.settled].every(count)||metric.pending+metric.settled!==metric.total)fail();
   }
   if(key==="ft"){
     if(!["future","grace","blocked_review","past_unverified_eligible","ft_confirmed"].every(k=>count(body.coverage_diagnostics[k])))fail();
     if(body.coverage_diagnostics.ft_confirmed!==body.final_recorded)fail();
   }
   return body;
 }
 async function fetchData(path){
   const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
   try{
     const res=await fetch(ROOT+path,{cache:"no-store",signal:controller.signal});
     if(!res.ok)throw Error(path+": HTTP "+res.status);
     return await res.json();
   }finally{clearTimeout(timer)}
 }
 async function load(force=false){
   const button=$("refresh");button.disabled=true;button.textContent="↻";
   const attempts=await Promise.allSettled(Object.entries(SOURCES).map(async ([key,path])=>({key,body:await fetchData(path)})));
   const failed=[],stale=[];let got=0;
   for(let i=0;i<attempts.length;i++){
     const item=attempts[i],key=Object.keys(SOURCES)[i];
     if(item.status==="fulfilled"){
       const body=item.value.body;
       try{
         state.data[key]=validateData(key,body);got++;
         if(key==="ft"&&body.execution_health?.status==="DEGRADED")failed.push("FT: erros de execução registados");
         const timestamp=key==="ft"?body.last_updated_at:body.generated_at;
         if(timestamp&&(Date.now()-Date.parse(timestamp)>2*60*60*1000||Date.parse(timestamp)>Date.now()+120000))stale.push(key);
       }
       catch(_){delete state.data[key];failed.push(key+" (formato)")}
     }else{delete state.data[key];failed.push(key)}
   }
   const banner=$("error-box");
   banner.hidden=failed.length===0&&stale.length===0;
   banner.textContent="";
   if(failed.length)banner.textContent="Dados parciais: não foi possível atualizar "+failed.join(", ")+". Os valores existentes podem estar desatualizados.";
   if(stale.length)banner.textContent+=" Dados desatualizados ou com relógio inválido: "+stale.join(", ")+". Última atualização superior a 2 horas ou no futuro.";
   put("last-sync",got?(data("research")?.generated_at?"Cérebro: "+formatDate(data("research").generated_at)+" · relatórios publicados":"Relatórios parcialmente disponíveis"):"Sem ligação aos relatórios");
   try{render()}catch(_){banner.hidden=false;banner.textContent="Erro ao apresentar os relatórios. Os valores não puderam ser validados."}
   finally{button.disabled=false;button.textContent="↻"}
 }
 function originalFuture(){
   const watch=data("watch");if(!watch)return {strict:[],other:[],opposite:[],original:[]};
   const today=Date.now();
   const future=a=>Array.isArray(a)?a.filter(r=>dt(r.kickoff_utc)>today):[];
   const strict=future(watch.future_strict),other=future(watch.future_other_original),opposite=future(watch.future_opposing);
   return{strict,other,opposite,original:[...strict,...other]};
 }
 function metric(id,value){put(id,value)}
 function renderRadar(){
   const r=data("research"),ft=data("ft"),w=originalFuture();
   metric("r-future",data("watch")?num(w.strict.length):"—");
   metric("r-hyp",r?num(r.generation?.hypotheses_evaluated):"—");
   metric("r-valid",r?num(r.state_counts?.VALIDADO||0):"—");
   metric("r-ft",r?num(r.scope?.ft_confirmed):"—");
   put("r-ft-sub",ft?"No LAB: "+num(ft.final_recorded)+" FT em "+num(ft.matches)+" jogos":"Uma observação por partida");

   const container=clear("r-insights");
   if(!r){empty(container,"Relatório do cérebro indisponível.");}
   else{
     const found=(r.combinations_top||[]).filter(h=>{
       const o=h.outcomes?.OVER_2_5;return o&&o.known>=8&&o.reference_known>=8&&Number.isFinite(o.p_two_sided);
     }).sort((a,b)=>a.outcomes.OVER_2_5.p_two_sided-b.outcomes.OVER_2_5.p_two_sided).slice(0,3);
     if(!found.length)empty(container,"Ainda não há cruzamentos com amostra e resultados suficientes para acompanhar.");
     for(const h of found){
       const o=h.outcomes.OVER_2_5,card=create("article",null,"insight-card");
       const head=create("div",null,"insight-head");
       head.append(create("span","HIPÓTESE · OVER 2,5","small-label"),create("span",h.state||"EXPLORATÓRIO","tiny-state"));
       card.append(head,create("h3",h.label));
       const row=create("div",null,"insight-metrics");
       const a=create("span");a.append(create("b",num(o.hits)+"/"+num(o.known),"highlight")," Over · "+perc(o.rate));
       const b=create("span");b.append(create("b",perc(o.reference_rate))," restantes jogos");
       const c=create("span");c.append(create("b","q "+nDec(o.q_bh))," corrigido");
       row.append(a,b,c);card.append(row);
       const bars=create("div",null,"bar-compare");bars.append(bar("Com padrão",o.rate,1),bar("Sem padrão",o.reference_rate,1,true));card.append(bars);
       card.append(create("p","P nominal "+nDec(o.p_two_sided,4)+" · não significativo após correção por testes múltiplos."));
       container.append(card);
     }
   }
   const watchBox=clear("r-watch");
   if(!data("watch"))empty(watchBox,"Relatório de jogos futuros indisponível.");
   else if(!w.strict.length)empty(watchBox,"Não há jogos rigorosos por começar nesta fotografia.");
   else {
     for(const match of w.strict.slice(0,6)){
       const n=create("div",null,"list-row"),left=create("div"),right=create("div",null,"right");
       left.append(create("div",match.match_label,"name"),create("div",formatDate(match.kickoff_utc)+" · "+match.episodes+" episódios","meta"));
       const [label,style]=category(match.category);right.append(tag(label,style));
       const net=(match.observations||[]).reduce((n,e)=>n+(Number.isFinite(e.delta_lambda)?e.delta_lambda:0),0);
       right.append(create("div","ΣΔλ "+sign(net),"meta"));
       n.append(left,right);watchBox.append(n);
     }
   }
   const proof=clear("r-proof");
   if(!r)empty(proof,"Sem relatório V5.");
   else {
     gate(proof,"Hipóteses com FT e métricas",(r.scope?.ft_confirmed||0)>0,"Em investigação");
     gate(proof,"Hipóteses congeladas",(r.frozen||[]).length>0,(r.frozen||[]).length+" congeladas");
     gate(proof,"Validação fora da amostra",(r.state_counts?.VALIDADO||0)>0,(r.state_counts?.VALIDADO||0)+" validadas");
   }
   const feeds=clear("r-feeds");
   if(!r&&!data("ft")&&!data("watch"))empty(feeds,"A aguardar dados das fontes.");
   else {
     if(r)rowKeyVal(feeds,"Pesquisa V5",formatDate(r.generated_at));
     if(ft)rowKeyVal(feeds,"Resultados FT",num(ft.final_recorded)+" / "+num(ft.matches));
     if(data("watch"))rowKeyVal(feeds,"Radar de futuros",formatDate(data("watch").generated_at));
     const v=data("quality");if(v)rowKeyVal(feeds,"Certificação V4",v.status==="PENDING"?"Pendente":v.status);
     const first=data("watch")?.summary?.total_historical_first_detections;
     if(first!=null)rowKeyVal(feeds,"Primeiras deteções congeladas",num(first));
   }
 }

 const DISCOVERY_TYPES={
   NEW_PATTERN:["Novo padrão publicado","flat"],
   NEW_EVIDENCE:["Novos resultados FT","flat"],
   IMPROVED:["Efeito observado aumentou","rise"],
   DEGRADED:["Efeito observado diminuiu","alert"],
   SIGN_REVERSAL:["Inversão do sinal observado","alert"],
   DATA_REVISION:["Revisão de dados · auditoria","warn"],
   RECALCULATED:["Recalculado, sem novos FT no grupo","warn"],
   CANDIDATE:["Candidata congelada","rise"],
   VALIDATED:["Validada fora da amostra","rise"],
   REJECTED:["Rejeitada na validação","alert"],
   STATE_CHANGE:["Mudança de estado V5","warn"]
 };
 const nameTarget=v=>v==="BTTS_YES"?"BTTS Sim":"Over 2,5";
 function renderChronology(){
   const where=clear("r-discovery"),d=data("discovery");
   // Detail panels refer to an earlier snapshot. Never keep one after reload/filter.
   const detail=clear("r-detail");if(detail)detail.hidden=true;
   if(!d){
     empty(where,"Cronologia indisponível: o relatório não foi carregado. Consulte o aviso no topo e tente atualizar.");
     put("discovery-count","Indisponível");return;
   }
   if(d.status==="AWAITING_FIRST_BASELINE"){
     empty(where,"A primeira execução ainda vai fixar a baseline. Não existem descobertas históricas inventadas.");
     put("discovery-count","Baseline pendente");return;
   }
   if(!Array.isArray(d.timeline)){
     empty(where,"Cronologia inválida: o relatório não contém uma lista de acontecimentos.");
     put("discovery-count","Dados inválidos");return;
   }
   const current=$("discovery-filter").value;
   const all=d.timeline||[];
   const filtered=all.filter(x=>current==="all" ||
     (current==="states"&&["CANDIDATE","VALIDATED","REJECTED","STATE_CHANGE"].includes(x.kind)) ||
     (current==="NEW_EVIDENCE"&&(x.ft_delta>0||x.oos_ft_delta>0)) ||
     x.kind===current);
   put("discovery-count",num(filtered.length)+" de "+num(all.length)+" acontecimentos recentes");
   if(!filtered.length){
     empty(where,"Sem mudanças desta categoria desde a baseline de "+
       formatDate(d.baseline_at,{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"})+
       ". A ausência de eventos também é informação.");
     return;
   }
   for(const ev of filtered.slice(0,24)){
     const card=create("article",null,"discovery-item "+String(ev.kind||"").toLowerCase());
     const when=create("div",null,"discovery-time");
     when.append(create("strong",formatDate(ev.at_utc,{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit",timeZone:"UTC"})),
       create("div","UTC"));
     const main=create("div"),typ=DISCOVERY_TYPES[ev.kind]||[ev.kind,"warn"];
     main.append(tag(typ[0],typ[1]),create("h3",ev.label+" · "+nameTarget(ev.target)));
     main.append(create("p",ev.explanation));
     const vals=create("div",null,"discovery-values");
     if(ev.ft_delta!==null&&ev.ft_delta!==undefined&&ev.ft_delta!==0)vals.append(create("span",(ev.ft_delta>0?"+":"")+num(ev.ft_delta)+" FT no grupo"));
     if(ev.oos_ft_delta)vals.append(create("span","OOS: +"+num(ev.oos_ft_delta)+" FT, separado"));
     vals.append(create("span","FT: "+num(ev.previous?.known)+" → "+num(ev.current?.known)),
       create("span","Δ: "+perc(ev.previous?.diff)+" → "+perc(ev.current?.diff)),
       create("span","q: "+nDec(ev.previous?.q_bh)+" → "+nDec(ev.current?.q_bh)));
     main.append(vals);
     const actions=create("div",null,"discovery-actions"),btn=create("button","Examinar evidência");
     btn.type="button";btn.addEventListener("click",()=>showEvidence(ev.id,ev.target));
     actions.append(btn,create("small",ev.id+" · "+(ev.state||"EXPLORATORIO")));
     main.append(actions);card.append(when,main);where.append(card);
   }
   if(filtered.length>24)where.append(create("p","São mostrados os 24 eventos mais recentes do filtro; os históricos completos ficam nos arquivos mensais versionados.","muted"));
 }
 function showEvidence(id,target){
   const d=data("discovery"),record=d?.patterns?.[id+"|"+target];
   const el=clear("r-detail");
   if(!record){el.hidden=false;empty(el,"Este padrão saiu do conjunto publicado ou ainda não tem histórico.");return}
   el.hidden=false;
   const current=record.latest||{},pts=record.points||[];
   el.append(create("div","EVOLUÇÃO INDIVIDUAL · "+id,"small-label"),create("h3",current.label+" · "+nameTarget(target)));
   el.append(create("p","Amostra de descoberta: taxas descritivas, não sinais executados. Os dados OOS, quando existem, são apresentados separadamente.","muted"));
   const grid=create("div",null,"detail-grid");
   const metrics=[
     ["Jogos com padrão",num(current.matches)],
     ["FT conhecidos",num(current.known)],
     ["Sim / Não",num(current.hits)+" / "+num(current.misses)],
     ["Taxa observada",perc(current.rate)],
     ["Sem padrão",perc(current.reference_rate)],
     ["Diferença",perc(current.diff)],
     ["IC 95% taxa",Array.isArray(current.ci95)?current.ci95.map(perc).join(" — "):"—"],
     ["IC 95% diferença",Array.isArray(current.diff_ci95)?current.diff_ci95.map(perc).join(" — "):"—"],
     ["p / q",nDec(current.p_two_sided,4)+" / "+nDec(current.q_bh,4)],
     ["Estabilidade",current.temporal_stability||"Por avaliar"],
     ["Estado V5",current.state||"EXPLORATORIO"]
   ];
   for(const [label,value] of metrics){const cell=create("div");cell.append(create("strong",value),create("span",label));grid.append(cell)}
   el.append(grid);
   if(current.frozen_at){
     const oos=current.out_of_sample||{};
     const panel=create("p","Congelada: "+formatDate(current.frozen_at)+
       " · FT fora da amostra: "+num(oos.known)+" · Taxa OOS: "+perc(oos.rate)+
       " · Referência OOS: "+perc(oos.reference_rate)+
       " · efeito OOS: "+perc(oos.diff),"note");
     el.append(panel);
   } else {
     el.append(create("p","Sem amostra independente congelada. Os FT acima pertencem à investigação exploratória.","note"));
   }
   const usable=pts.filter(p=>typeof p.rate==="number"&&Number.isFinite(p.rate));
   if(usable.length){
     const graph=document.createElementNS("http://www.w3.org/2000/svg","svg");
     graph.setAttribute("class","discovery-graph");graph.setAttribute("viewBox","0 0 650 150");
     graph.setAttribute("role","img");graph.setAttribute("aria-label","Taxa observada por atualização, com datas UTC reais");
     const coords=usable.map((p,i)=>{
       const x=25+(usable.length===1?0:i*600/(usable.length-1));
       return [x,135-120*Math.min(1,Math.max(0,p.rate)),p];
     });
     const line=document.createElementNS("http://www.w3.org/2000/svg","polyline");
     line.setAttribute("points",coords.map(p=>p[0]+","+p[1]).join(" "));graph.append(line);
     for(const [x,y,p] of coords){
       const dot=document.createElementNS("http://www.w3.org/2000/svg","circle");
       dot.setAttribute("cx",x);dot.setAttribute("cy",y);dot.setAttribute("r","3.5");
       const tooltip=document.createElementNS("http://www.w3.org/2000/svg","title");
       tooltip.textContent=p.at_utc+" · "+perc(p.rate)+" · "+num(p.known)+" FT";dot.append(tooltip);graph.append(dot);
     }
     el.append(create("h4","Evolução da taxa observada (datas UTC reais)"),graph);
     const dates=create("div",null,"discovery-point-list");
     for(const p of usable.slice(-6))dates.append(create("small",formatDate(p.at_utc,{day:"2-digit",month:"short",year:"numeric"})+" · "+num(p.known)+" FT · "+perc(p.rate)));
     el.append(dates);
   }else empty(el,"Ainda não há FT suficientes para desenhar uma evolução.");
   const note=create("p","O gráfico conserva apenas os últimos 24 pontos por padrão. Os eventos históricos completos estão arquivados mensalmente no GitHub.","muted");
   el.append(note);
   const link=create("a","Abrir relatório V5 e respetiva evidência →");link.href="./lab-research.html";el.append(link);
   move("radar");
   el.scrollIntoView({block:"start",behavior:"smooth"});
 }
 function renderProspective(){
   const container=clear("r-prospective"),d=data("discovery");
   if(!d){empty(container,"Histórico prospetivo indisponível: o relatório não foi carregado.");return;}
   if(d.status==="AWAITING_FIRST_BASELINE"){
     empty(container,"Sem baseline e resultados históricos associados ainda.");return;
   }
   const p=d.prospective||{},head=create("div",null,"prospective-summary");
   head.append(tag(num(p.detected_total||0)+" primeiras deteções","flat"),
     tag(num(p.settled_total||0)+" FT confirmados","rise"));
   container.append(head);
   const groups=Object.entries(p.by_first_detection_category||{});
   if(!groups.length){empty(container,"Ainda não há FT elegíveis após uma primeira deteção pré-jogo. Jogos pendentes não são reds.");return}
   for(const [key,s] of groups){
     const row=create("div",null,"prospective-row");
     row.append(create("strong",category(key)[0]+" · "+num(s.known_ft)+" FT"),
       create("small","Over 2,5: "+num(s.over_2_5)+" sim / "+num(s.known_ft-s.over_2_5)+" não · BTTS: "+
         num(s.btts_yes)+" sim / "+num(s.known_ft-s.btts_yes)+" não"));
     container.append(row);
   }
   for(const m of (p.settled||[]).slice(0,4)){
     const row=create("div",null,"list-row");
     const left=create("div");left.append(create("div",m.match_label+" · "+m.score,"name"),
       create("div","Deteção: "+formatDate(m.first_detected_at)+" · "+category(m.category_at_first_detection)[0],"meta"));
     const right=create("div",null,"right");right.append(tag(m.over_2_5?"Over Sim":"Over Não",m.over_2_5?"rise":"warn"),
       create("div",m.btts_yes?"BTTS Sim":"BTTS Não","meta"));
     row.append(left,right);container.append(row);
   }
   container.append(create("p","Resultados desportivos descritivos; não representam apostas nem demonstram ROI ou EV. Categorias posteriores não substituem a classificação original.","muted"));
 }

 function rowKeyVal(parent,key,val){const r=create("div",null,"gate");r.append(create("span",key),create("strong",val,"state"));parent.append(r)}
 function renderFuture(){
   const w=data("watch"),f=originalFuture();metric("f-original",w?num(f.original.length):"—");metric("f-strict",w?num(f.strict.length):"—");
   metric("f-other",w?num(f.other.length):"—");metric("f-opposite",w?num(f.opposite.length):"—");metric("nav-future",w?num(f.strict.length):"—");
   futureRows();
 }
 function futureRows(){
   const tbody=clear("f-rows"),w=data("watch"),f=originalFuture();
   if(!w){const tr=create("tr"),cell=create("td","A aguardar relatório prospectivo…");cell.colSpan=6;tr.append(cell);tbody.append(tr);put("f-count","—");return}
   const mode=state.futureFilter;
   let rows=mode==="strict"?f.strict:mode==="other"?f.other:mode==="opposite"?f.opposite:
     f.strict.filter(x=>mode==="rise"?x.category==="RISING_EACH_EPISODE":
       mode==="mixed"?x.category==="RISING_WITH_FLAT":x.category==="FLAT_EACH_EPISODE");
   const query=$("f-query").value.trim().toLocaleLowerCase("pt-PT");
   if(query)rows=rows.filter(x=>(x.match_label||"").toLocaleLowerCase("pt-PT").includes(query));
   rows=rows.slice().sort((a,b)=>a.kickoff_utc.localeCompare(b.kickoff_utc));
   put("f-count",num(rows.length)+" jogos ainda futuros · "+formatDate(w.generated_at));
   if(!rows.length){const tr=create("tr"),cell=create("td","Sem jogos que correspondam ao filtro nesta fotografia.");cell.colSpan=6;tr.append(cell);tbody.append(tr);return}
   for(const x of rows){
     const tr=create("tr");
     const fixture=create("td",null,"fixture");fixture.append(create("div",x.match_label),create("span",x.match_key||"","small"));tr.append(fixture);
     tr.append(create("td",formatDate(x.kickoff_utc),"nums"));
     const cat=create("td"),[label,style]=category(x.category);cat.append(tag(label,style));tr.append(cat);
     tr.append(create("td",num(x.messages)+" / "+num(x.episodes),"nums"));
     tr.append(create("td",(x.observations||[]).map(o=>sign(o.delta_lambda)).join(" · "),"values nums"));
     tr.append(create("td",num(x.v4_total_count)+" V4 · "+num(x.h1_legacy_total_count)+" H1","nums"));
     tbody.append(tr);
   }
 }
 function patterns(){
   const r=data("research"),where=clear("p-cards");
   if(!r){empty(where,"Relatório de padrões não disponível.");return}
   const target=$("p-target").value,type=$("p-type").value,sort=$("p-sort").value,query=$("p-query").value.toLocaleLowerCase("pt-PT");
   let list=(type==="combinations"?r.combinations_top:r.patterns)||[];
   list=list.filter(x=>x.outcomes?.[target]&&(!query||x.label.toLocaleLowerCase("pt-PT").includes(query)));
   list.sort((a,b)=>{
     const aa=a.outcomes[target],bb=b.outcomes[target];
     if(sort==="n")return bb.known-aa.known;
     if(sort==="effect")return Math.abs(bb.diff||0)-Math.abs(aa.diff||0);
     return (aa.p_two_sided??2)-(bb.p_two_sided??2);
   });
   put("p-visible",num(list.length)+" hipóteses mostradas");
   if(!list.length){empty(where,"Não foram encontrados padrões para estes filtros.");return}
   for(const h of list.slice(0,40)){
     const o=h.outcomes[target],card=create("article",null,"hyp-card");
     const top=create("div",null,"insight-head");top.append(create("span",type==="combinations"?"CRUZAMENTO":"PADRÃO INDIVIDUAL","small-label"),tag(h.state||"EXPLORATÓRIO","warn"));card.append(top);
     card.append(create("h3",h.label));
     const stats=create("div",null,"stats-line");
     for(const [label,value] of [["Com padrão",perc(o.rate)],["Sem padrão",perc(o.reference_rate)],["FT no grupo",num(o.known)],["Valor-q",nDec(o.q_bh)]]){const el=create("div");el.append(create("strong",value),create("span",label));stats.append(el)}
     card.append(stats);
     const bars=create("div",null,"bar-compare");bars.append(bar("Com padrão",o.rate,1),bar("Sem padrão",o.reference_rate,1,true));card.append(bars);
     const foot=create("div",null,"hyp-meta");foot.append(create("span","p nominal "+nDec(o.p_two_sided,4)),create("span","Δ "+(typeof o.diff==="number"?(o.diff>0?"+":"")+nDec(o.diff*100,1)+" pp":"—")));
     card.append(foot);
     card.append(create("p","Associação exploratória · "+(o.evidence==="NOT_SIGNIFICANT_AFTER_FDR"?"sem significância após correção múltipla":"consultar critérios de validação"),"muted"));
     where.append(card);
   }
   if(list.length>40)where.append(create("p","Mostradas as primeiras 40 hipóteses; utiliza a pesquisa ou consulta o relatório completo.","muted"));
 }
 function renderPatternsMeta(){
   const r=data("research");
   if(!r){
     for(const id of ["p-count","p-individual","p-tests","p-frozen"])metric(id,"—");
     patterns();return;
   }
   metric("p-count",num(r.generation?.hypotheses_evaluated));
   metric("p-individual",num(r.generation?.individual_patterns_with_support));
   metric("p-tests",num(r.generation?.tests_performed));
   metric("p-frozen",num((r.frozen||[]).length));
   patterns();
 }
 function funnel(parent,label,count,total,shade){
   const row=create("div",null,"funnel-row");row.append(create("span",label));
   const track=create("div",null,"track"),fill=create("div",null,"fill"+(shade?" reference":""));
   fill.style.width=Math.min(100,count&&total?Math.max(1,100*count/total):0)+"%";track.append(fill);row.append(track);
   row.append(create("strong",num(count)));parent.append(row);
 }
 function renderValidation(){
   const r=data("research");
   if(!r){
     for(const id of ["v-explore","v-candidates","v-oos","v-validated"])metric(id,"—");
     for(const id of ["v-funnel","v-brier","v-frozen"])empty(clear(id),"Investigação indisponível; sem métricas atuais.");
     put("v-brier-note","Relatório de investigação indisponível.");
     return;
   }
   const states=r.state_counts||{},total=r.generation?.hypotheses_evaluated||0;
   metric("v-explore",num(states.EXPLORATORIO||0));metric("v-candidates",num(states.CANDIDATO||0));
   metric("v-oos",num(states.EM_VALIDACAO||0));metric("v-validated",num(states.VALIDADO||0));
   const funnelList=clear("v-funnel");
   funnel(funnelList,"Investigadas",total,total);
   funnel(funnelList,"Candidatas",states.CANDIDATO||0,total);
   funnel(funnelList,"Em validação",states.EM_VALIDACAO||0,total);
   funnel(funnelList,"Validadas",states.VALIDADO||0,total);
   const sim=r.similarity_walk_forward||{},brier=clear("v-brier");
   if(sim.matches_evaluated){
     const candidates=[["Jogos semelhantes (kNN)",sim.brier_knn],["Mercado implícito",sim.brier_market_implied_model],["Taxa histórica",sim.brier_running_base_rate]];
     for(const [label,val] of candidates){
       if(typeof val!=="number")continue;
       const row=create("div",null,"funnel-row");row.append(create("span",label));
       const track=create("div",null,"track"),fill=create("div",null,"fill"+(label==="Mercado implícito"?"":" reference"));
       fill.style.width=Math.min(100,val/0.5*100)+"%";track.append(fill);row.append(track);
       row.append(create("strong",nDec(val,4)));brier.append(row);
     }
     put("v-brier-note","Amostra: "+num(sim.matches_evaluated)+" jogos · "+(sim.status==="INSUFFICIENT_SAMPLE"?"insuficiente para concluir que o cérebro supera o mercado.":"comparação exploratória; não mede lucratividade."));
   }else{empty(brier,"Ainda não há jogos suficientes para medir o método.");put("v-brier-note","Amostra insuficiente.");}
   const frozen=clear("v-frozen");
   if(!(r.frozen||[]).length)empty(frozen,"Ainda não existem hipóteses congeladas que tenham passado os critérios de descoberta. Isto não significa que o motor esteja parado.");
   else for(const h of r.frozen.slice(0,10)){
     const card=create("article",null,"insight-card");card.append(create("h3",h.label),tag(h.state,"flat"),create("p","Congelada: "+formatDate(h.frozen_at)+" · OOS: "+num(h.out_of_sample?.known)+" jogos"));frozen.append(card);
   }
   const evol=clear("v-evolution"),days=(r.evolution||[]).slice(-12);
   if(!days.length)empty(evol,"Sem histórico de dias.");else{
     const table=create("div",null,"gate-list");
     for(const day of days){
       const row=create("div",null,"gate");row.append(create("span",formatDate(day.kickoff_day+"T12:00:00+00:00",{day:"2-digit",month:"short"})+" · "+num(day.matches)+" jogos"),
         create("strong",num(day.known||0)+" FT","state "+(day.known?"pass":"")));
       table.append(row);
     }evol.append(table);
   }
 }
 function renderData(){
   const f=data("ft"),r=data("research"),q=data("quality"),w=data("watch");
   if(f){
     metric("d-games",num(f.matches));metric("d-ft",num(f.final_recorded));
     metric("d-future",num((f.coverage_diagnostics?.future||0)+(f.coverage_diagnostics?.grace||0)));
     metric("d-pending",num(f.coverage_diagnostics?.past_unverified_eligible||0));
   }
   if(!f)for(const id of ["d-games","d-ft","d-future","d-pending"])metric(id,"—");
   const gates=clear("d-gates");if(q){
     for(const [key,value] of Object.entries(q.acceptance_gates||{}))gate(gates,GATE_LABELS[key]||key,!!value,"Comprovado","Pendente");
   }else empty(gates,"Auditoria V4 indisponível.");
   const feeds=clear("d-feeds");
   if(f)rowKeyVal(feeds,"Relatório FT",formatDate(f.last_updated_at));
   if(r){rowKeyVal(feeds,"Pesquisa V5",formatDate(r.generated_at));rowKeyVal(feeds,"FT usados no V5",num(r.scope?.ft_confirmed));rowKeyVal(feeds,"Universo elegível",num(r.scope?.research_eligible));}
   if(w){rowKeyVal(feeds,"Padrões futuros",formatDate(w.generated_at));rowKeyVal(feeds,"Registos de primeira deteção",num(w.summary?.total_historical_first_detections));}
   if(data("h1"))rowKeyVal(feeds,"Arquivo Under H1",num(data("h1").singles?.total)+" sinais simulados");
 }
 function render(){renderRadar();renderChronology();renderProspective();renderFuture();renderPatternsMeta();renderValidation();renderData()}
 if(typeof module!=="undefined"&&module.exports){module.exports={validateData,renderPatternsMeta,renderValidation,renderChronology,_testState:state};return}
 setupNav();load();
})();
