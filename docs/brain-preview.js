/* MASTER BRAIN — independent, read-only dashboard preview. */
(function(){
"use strict";
const paths={research:"./lab/pattern-research.json",watch:"./lab/pattern-watch.json",discovery:"./lab/discoveries.json",ft:"./lab/ft-results.json",quality:"./lab/v4-audit.json",readiness:"./lab/v6-readiness.json"};
const data={};const errors={};const $=id=>document.getElementById(id);
const element=(tag,txt,cls)=>{const e=document.createElement(tag);if(txt!==undefined&&txt!==null)e.textContent=String(txt);if(cls)e.className=cls;return e};
const fill=(id)=>{const n=$(id);n.replaceChildren();return n};
const count=n=>typeof n==="number"&&Number.isFinite(n)?n.toLocaleString("pt-PT"):"—";
const pct=n=>typeof n==="number"&&Number.isFinite(n)?(100*n).toLocaleString("pt-PT",{maximumFractionDigits:1})+"%":"—";
const decimal=n=>typeof n==="number"&&Number.isFinite(n)?n.toLocaleString("pt-PT",{maximumFractionDigits:3}):"—";
const time=s=>{const v=Date.parse(s||"");return Number.isFinite(v)?v:null};
const date=s=>time(s)===null?"Data não conhecida":new Intl.DateTimeFormat("pt-PT",{day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit",timeZone:"Europe/Lisbon"}).format(time(s));
const todayKey=ms=>new Intl.DateTimeFormat("en-GB",{year:"numeric",month:"2-digit",day:"2-digit",timeZone:"Europe/Lisbon"}).format(ms);
function state(el,title,description){
 const n=typeof el==="string"?fill(el):el;
 const b=element("div",null,"empty-state");
 b.append(element("strong",title));if(description)b.append(element("span",description));
 n.append(b);
}
function stat(holder,label,val){
 const b=element("div",null,"stat");
 b.append(element("strong",val),element("span",label));holder.append(b);
}
function card(holder,label,heading,stageName,stageCss){
 const box=element("article",null,"card"),head=element("div",null,"card-head");
 head.append(element("span",label,"index"),element("span",stageName,"stage "+(stageCss||"")));
 box.append(head,element("h3",heading));holder.append(box);return box;
}
function metricRow(box,items){
 const row=element("div",null,"pair");
 for(const item of items){const cell=element("div");
 cell.append(element("strong",item[1],item[2]||""),element("span",item[0]));row.append(cell)}
 box.append(row);
}
function safe(id,fn){
 try{fn()}catch(e){state(id,"Não foi possível apresentar este painel.","Falha no formato ou no processamento do relatório. Não foi convertida em zero resultados.");}
}
function candidates(r,scope="all"){
 if(!r)return[];
 const raw=[...(scope==="combinations"?[]:(Array.isArray(r.patterns)?r.patterns:[])),...(scope==="individual"?[]:(Array.isArray(r.combinations_top)?r.combinations_top:[]))];
 const unique=new Set(),out=[];
 for(const h of raw){const id=String(h.id||h.label||"");
 for(const target of ["OVER_2_5","BTTS_YES"]){const o=h.outcomes&&h.outcomes[target],key=id+"|"+target;
 if(unique.has(key)||!o||!Number.isFinite(o.rate)||!Number.isFinite(o.reference_rate))continue;
 unique.add(key);out.push({h:h,o:o,target:target})}}
 return out;
}
function explain(box,o){
 const detail=element("details"),summary=element("summary","Porque ainda não está provado?");
 detail.append(summary);
 detail.append(element("p","Taxa de acerto desportiva, não ROI. A correção por múltiplos testes (valor-q) é "+decimal(o.q_bh)+". É necessário observar jogos novos, confirmar estabilidade e conhecer as odds reais para medir rentabilidade."));
 box.append(detail);
}
function researchCard(holder,item){
 const h=item.h,o=item.o;
 const box=card(holder,item.target==="OVER_2_5"?"OVER 2,5":"AMBAS MARCAM",h.label||"Padrão sem descrição","Por confirmar","exploratory");
 metricRow(box,[["Com esta condição",pct(o.rate),"good"],["Restantes jogos",pct(o.reference_rate)],["Diferença",((o.diff>0)?"+":"")+pct(o.diff),"good"]]);
 box.append(element("p",count(o.hits)+" acertos em "+count(o.known)+" jogos com FT. Comparação: "+count(o.reference_known)+" jogos sem a condição.","summary"));
 const coverage=element("div","Amostra: "+count(o.known)+" com resultado, "+count(o.reference_known)+" de comparação. Não é uma projeção de ganhos.","mini");
 box.append(coverage);explain(box,o);
}
function linkMatches(box,m,r){
 const engine=typeof MBPatternMatcher==="object"&&MBPatternMatcher?MBPatternMatcher:null;
 if(!r||!engine){
  box.append(element("p","Associação histórica indisponível: faltam dados V5 ou o verificador.","mini"));return;
 }
 const matches=engine.linked(m,r,{minN:12,minDiff:0.08});
 if(!matches.length){
  box.append(element("p","Sem correspondência histórica verificável neste resumo. Podem faltar mercados ou amostra; isto não significa que os padrões não existam.","mini"));return;
 }
 const when=time(r.generated_at),first=time(m.first_alert_at);
 const caveat=Number.isFinite(when)&&Number.isFinite(first)&&when>first
  ?"O relatório histórico foi produzido depois do primeiro alerta: associação retrospetiva, não previsão pré-registada."
  :"Associação observacional. Não demonstra que esta hipótese tenha sido congelada antes da deteção.";
 box.append(element("p",count(matches.length)+" padrões históricos compatíveis com as condições efetivamente observadas.","summary"));
 for(const hit of matches.slice(0,2)){
  const block=element("div",null,"linked-pattern");
  block.append(element("strong",(hit.target==="OVER_2_5"?"Over 2,5":"Ambas marcam")+" · "+hit.label));
  const stat=element("div",null,"pair");
  for(const [label,v] of [["Com a condição",pct(hit.rate)],["Outros jogos",pct(hit.reference_rate)],["Diferença",((hit.diff>=0)?"+":"")+pct(hit.diff)]]){
   const cell=element("div");cell.append(element("strong",v),element("span",label));stat.append(cell)}
  block.append(stat);
  block.append(element("p",count(hit.hits)+"/"+count(hit.known)+" acertos históricos confirmados · "+count(hit.reference_known)+" jogos de comparação."));
  box.append(block);
 }
 if(matches.length>2)box.append(element("p","Mais "+count(matches.length-2)+" relações não mostradas; consultar o relatório de padrões.","meta"));
 box.append(element("p",caveat,"mini"));
}
function renderToday(){
 const w=data.watch,r=data.research,ms=fill("today-metrics"),list=fill("today-content");
 if(!w||!Array.isArray(w.future_strict)){state(list,"Jogos do dia indisponíveis.","O relatório de observação não foi carregado ou não é válido.");return}
 const now=Date.now(),matches=w.future_strict.filter(m=>time(m.kickoff_utc)!==null&&time(m.kickoff_utc)>now);
 const today=matches.filter(m=>todayKey(time(m.kickoff_utc))===todayKey(now));
 stat(ms,"Jogos rigorosos por começar hoje",count(today.length));stat(ms,"Jogos rigorosos futuros",count(matches.length));
 stat(ms,"Primeiras deteções históricas",count(w.summary?.total_historical_first_detections));
 if(r&&typeof MBPatternMatcher==="object"){
   stat(ms,"Jogos de hoje com relação histórica verificável",
     count(today.filter(m=>MBPatternMatcher.linked(m,r,{minN:12,minDiff:0.08}).length>0).length));
 }
 if(!today.length){state(list,"Sem jogos com a condição rigorosa para hoje.","Isto não significa que o sistema tenha parado; indica apenas a fotografia publicada. Verifique a data do relatório.");return}
 const cats={RISING_EACH_EPISODE:"Subidas consistentes",RISING_WITH_FLAT:"Subida e estabilidade",FLAT_EACH_EPISODE:"Quase estável"};
 for(const m of today.sort((a,b)=>time(a.kickoff_utc)-time(b.kickoff_utc)).slice(0,12)){
  const box=card(list,"INÍCIO "+date(m.kickoff_utc),m.match_label||"Jogo sem nome",cats[m.category]||"Movimentos observados","positive");
  box.append(element("p",count(m.episodes)+" episódios independentes · "+count(m.messages)+" mensagens.","summary"));
  box.append(element("p","Está sob observação. Nenhum padrão é apresentado como previsão validada."));
  linkMatches(box,m,r);
 }
 if(today.length>12)list.append(element("p","Ver todos os jogos no observatório detalhado.","meta"));
}
function renderPast(){
 const r=data.research,metrics=fill("past-metrics"),holder=fill("past-content");
 if(!r||!r.generation){state(holder,"Pesquisa histórica indisponível.","Não é possível avaliar os padrões sem o relatório V5.");return}
 stat(metrics,"Hipóteses analisadas",count(r.generation.hypotheses_evaluated));stat(metrics,"Jogos com FT usados",count(r.scope?.ft_confirmed));
 stat(metrics,"Última análise",date(r.generated_at));
 const ranked=candidates(r).filter(x=>x.o.known>=12&&x.o.reference_known>=12)
   .sort((a,b)=>b.o.known-a.o.known).slice(0,3);
 if(!ranked.length){state(holder,"Ainda não há amostras comparáveis para mostrar.");return}
 for(const x of ranked)researchCard(holder,x);
}
function renderSignals(){
 const r=data.research,holder=fill("signals-content");
 if(!r){state(holder,"Sinais históricos indisponíveis.","O relatório V5 não carregou.");return}
 const ranked=candidates(r,"individual").filter(x=>x.o.known>=12&&x.o.reference_known>=12&&x.o.diff>=0.08)
   .sort((a,b)=>(b.o.diff-a.o.diff)||b.o.known-a.o.known).slice(0,6);
 if(!ranked.length){state(holder,"Ainda não há sinais que cumpram este filtro.","Ausência de candidatos não equivale a falha do sistema.");return}
 for(const x of ranked)researchCard(holder,x);
}
function renderTesting(){
 const r=data.research,holder=fill("test-content");
 if(!r){state(holder,"Estado dos testes indisponível.","Não foi possível consultar o V5.");return}
 const frozen=Array.isArray(r.frozen)?r.frozen:[];
 const historical=candidates(r,"combinations").filter(x=>x.o.known>=12&&x.o.reference_known>=12&&x.o.diff>=0.08)
   .sort((a,b)=>(b.o.diff-a.o.diff)||b.o.known-a.o.known).slice(0,4);
 for(const x of historical)researchCard(holder,x);
 if(!frozen.length){
  const note=element("div",null,"empty-state");
  note.append(element("strong","Ainda não há regras V5 congeladas para teste independente."),
              element("span","Os cruzamentos apresentados acima são apenas candidatos históricos. O registo formal V6.2 deve ser consultado no Radar Científico."));
  holder.append(note);return}
 for(const h of frozen.slice(0,8)){const box=card(holder,"REGRA FIXADA",h.label||h.id||"Hipótese sem nome",h.state||"Em teste","positive");
 box.append(element("p","Congelada em "+date(h.frozen_at)+" · "+count(h.out_of_sample?.known)+" resultados novos confirmados."));
 box.append(element("p","Dados de descoberta não são contados como validação independente."))}
}
function renderProven(){
 const r=data.research,holder=fill("proven-content");
 if(!r){state(holder,"Validação indisponível.","Não é possível afirmar quantas hipóteses foram validadas.");return}
 const n=r.state_counts?.VALIDADO;
 if(typeof n!=="number"){state(holder,"Estado de validação não identificado.","O relatório não forneceu uma contagem válida.");return}
 if(n===0){state(holder,"Ainda não existe nenhuma estratégia V5 comprovada.","Esta secção só apresentará resultados depois de cumpridos os critérios de validação independente. O Radar Científico V6.2 mantém um registo próprio.");return}
 const valid=candidates(r).filter(x=>x.h.state==="VALIDADO");
 if(!valid.length){state(holder,count(n)+" estratégia(s) marcada(s) como validada(s), sem detalhe neste resumo.","Consulte o relatório técnico antes de interpretar a validação.");return}
 for(const x of valid.slice(0,8)){const b=card(holder,"VALIDAÇÃO V5",x.h.label||"Estratégia", "Validada","verified");b.append(element("p","Verificar amostras independentes e critérios na documentação."))}
}
function eventLine(holder,title,sub){
 const d=element("div",null,"event");d.append(element("strong",title),element("small",sub));holder.append(d);
}
function ageText(timestamp){
 const t=time(timestamp);
 if(!Number.isFinite(t))return "sem data fiável";
 const delta=Date.now()-t;
 if(delta<0)return "data futura / relógio incompatível";
 const mins=Math.floor(delta/60000);
 if(mins<60)return "há "+count(mins)+" min";
 const hours=Math.floor(mins/60);
 return hours<48?"há "+count(hours)+" h":"há "+count(Math.floor(hours/24))+" dias";
}
function renderOperations(){
 const stats=fill("operation-metrics"),warnings=fill("operation-warnings");
 const r=data.research,w=data.watch,ft=data.ft,q=data.quality,v6=data.readiness,d=data.discovery;
 const status=(name,obj,dateValue)=>{stat(stats,name,obj?ageText(dateValue):"Indisponível");};
 status("Pesquisa histórica V5",r,r?.generated_at);
 status("Observatório de jogos",w,w?.generated_at);
 status("Resultados FT",ft,ft?.last_updated_at);
 status("Controlo de qualidade",q,q?.generated_at);
 status("Evidência V6.2",v6,v6?.generated_at);
 stat(stats,"FT confirmados na fila LAB",typeof ft?.coverage_diagnostics?.ft_confirmed==="number"?count(ft.coverage_diagnostics.ft_confirmed):"—");
 stat(stats,"Jogos ainda por confirmar",typeof ft?.coverage_diagnostics?.past_unverified_eligible==="number"?count(ft.coverage_diagnostics.past_unverified_eligible):"—");
 stat(stats,"Novos acontecimentos no histórico",Array.isArray(d?.timeline)?count(d.timeline.length):"—");
 const checks=[];
 if(!r||!w||!ft||!q||!v6||!d)checks.push("Nem todas as fontes foram publicadas ou carregadas. O estado operacional global é INCOMPLETO.");
 if(r&&w&&time(r.generated_at)!==null&&time(w.generated_at)!==null&&
    Math.abs(time(r.generated_at)-time(w.generated_at))>3*3600000)
    checks.push("As análises histórica e prospetiva têm mais de 3 horas de diferença entre si; comparar as fotografias com cautela.");
 if(ft&&r&&typeof ft?.final_recorded==="number"&&typeof r.scope?.ft_confirmed==="number"&&
    ft.final_recorded!==r.scope.ft_confirmed)
    checks.push("FT recuperados na fila LAB ("+count(ft.final_recorded)+") diferem dos FT já incorporados na pesquisa V5 ("+count(r.scope.ft_confirmed)+"). São fotografias de momentos/âmbitos diferentes; não equiparar.");
 if(ft&&typeof ft.coverage_diagnostics?.past_unverified_eligible==="number"&&ft.coverage_diagnostics.past_unverified_eligible>0)
    checks.push(count(ft.coverage_diagnostics.past_unverified_eligible)+" jogos passados ainda aguardam confirmação FT; não são derrotas.");
 if(q&&q.acceptance_gates&&Object.values(q.acceptance_gates).some(v=>v===false))
    checks.push("Há critérios de integridade V4 ainda pendentes. A receção dos relatórios não prova certificação integral.");
 if(v6&&v6.p0_7_day_gate!=="PASS")
    checks.push("V6.2: janela de 7 dias "+String(v6.p0_7_day_gate||"desconhecida")+". Validação científica não concluída.");
 const summaries=[
   ["Leitura dos ficheiros","Um ficheiro atualizado comprova a existência de uma publicação, não o sucesso da recolha completa."],
   ["Recolha real","Sem evidência conciliada de execução + publicação + origem dos registos, o estado é NÃO VERIFICADO."],
   ["Proveniência V5",r?.source_commit?"Dados V5 referenciam o commit "+r.source_commit.slice(0,12)+".":"Commit de origem V5 não disponibilizado."]
 ];
 for(const [title,msg]of summaries)eventLine(warnings,title,msg);
 for(const m of checks)eventLine(warnings,"Atenção",m);
 if(!checks.length)eventLine(warnings,"Sem alertas nestas comparações","Não equivale a prova de funcionamento de ponta a ponta.");
}
function renderHistory(){
 const r=data.research,w=data.watch,d=data.discovery;
 const metric=fill("history-metrics"),ev=fill("history-events"),res=fill("history-results");
 if(r){stat(metric,"Último relatório V5",date(r.generated_at));stat(metric,"Com FT comprovado na pesquisa",count(r.scope?.ft_confirmed));}
 if(w)stat(metric,"Último observatório futuro",date(w.generated_at));
 if(!d){state(ev,"Cronologia indisponível.","Não se deve interpretar uma falha de leitura como ausência de alterações.");
         state(res,"Histórico prospetivo indisponível.","Não se deve contar resultados em falta como derrotas.");return}
 if(d.status==="AWAITING_FIRST_BASELINE"){state(ev,"A aguardar primeira baseline.","Sem acontecimentos históricos verificáveis.");state(res,"A aguardar histórico prospetivo.");return}
 if(!Array.isArray(d.timeline)){state(ev,"Cronologia com formato inesperado.","A lista de acontecimentos não está disponível.");}
 else if(!d.timeline.length)state(ev,"Nenhuma alteração registada desde a baseline.","Esta ausência é diferente de um erro de leitura.");
 else for(const e of [...d.timeline].sort((a,b)=>(time(b.at_utc)||0)-(time(a.at_utc)||0)).slice(0,5)){
  eventLine(ev,e.label||e.kind||"Alteração sem descrição",(e.explanation||"")+" · "+date(e.at_utc));}
 const p=d.prospective;
 if(!p||typeof p!=="object"){state(res,"Resultados prospetivos ainda não publicados.");return}
 eventLine(res,count(p.detected_total)+" jogos detetados inicialmente",count(p.settled_total)+" com FT confirmado; pendentes não são derrotas");
 const groups=p.by_first_detection_category;
 if(groups&&typeof groups==="object"){
 for(const [k,g] of Object.entries(groups).slice(0,5)){
  eventLine(res,k.replace(/_/g," ").toLowerCase(),count(g.known_ft)+" FT · "+count(g.over_2_5)+" Over 2,5 · "+count(g.btts_yes)+" ambas marcam");}}
}
function render(){
 safe("today-content",renderToday);safe("past-content",renderPast);safe("signals-content",renderSignals);
 safe("test-content",renderTesting);safe("proven-content",renderProven);safe("history-events",renderHistory);
 safe("operation-warnings",renderOperations);
}
async function fetchJson(path){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
 try{
  const response=await fetch(path,{cache:"no-store",signal:controller.signal});if(!response.ok)throw Error("HTTP "+response.status);
  const json=await response.json();
  if(!json||typeof json!=="object"||Array.isArray(json))throw Error("JSON inesperado");
  return json;
 }finally{clearTimeout(timer)}
}
async function load(){
 const button=$("refresh");button.disabled=true;button.textContent="A atualizar…";
 const results=await Promise.allSettled(Object.entries(paths).map(async ([name,path])=>({name,json:await fetchJson(path)})));
 Object.keys(data).forEach(k=>delete data[k]);Object.keys(errors).forEach(k=>delete errors[k]);
 const names=Object.keys(paths);
 for(let i=0;i<results.length;i++){
  const item=results[i],key=names[i];
  if(item.status==="fulfilled"){data[key]=item.value.json;}else{errors[key]=item.reason?.message||"Falha inesperada"}}
 const strip=fill("source-status");
 for(const [key,label] of [["research","Pesquisa passada"],["watch","Jogos observados"],["discovery","Cronologia / resultados"],["ft","Resultados FT"],["quality","Qualidade V4"],["readiness","V6.2"]]){
  strip.append(element("span",label+": "+(errors[key]?"Indisponível ("+errors[key]+")":"Publicado "+ageText(data[key]?.generated_at||data[key]?.last_updated_at)),"source"+(errors[key]?" bad":"")))}
 const n=Object.keys(errors).length;
 const latest=[data.research?.generated_at,data.watch?.generated_at,data.discovery?.generated_at].map(time).filter(v=>v!==null).sort((a,b)=>b-a)[0];
 $("overall-state").textContent=n?"Informação parcial: "+count(n)+" fonte(s) indisponível(eis).": "Relatórios recebidos (não comprova funcionamento operacional).";
 if(latest!==undefined)$("overall-state").textContent+=" Última data declarada: "+date(new Date(latest).toISOString())+".";
 render();button.disabled=false;button.textContent="Atualizar informação";
}
$("refresh").addEventListener("click",load);
load();
})();