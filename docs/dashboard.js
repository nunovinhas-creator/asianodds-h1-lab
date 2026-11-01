/* UNDER TESTE — public, read-only dashboard.
   Never modifies H1 state, sends orders or claims certification.
   Uses only data.json and the published LAB JSON. */
(function (root) {
  "use strict";
  const VERSION = "monitor-v1";
  const LABELS = {
    coverage_99:"Cobertura ≥99%", data_integrity:"Integridade dos dados",
    field_agreement_100:"Concordância com proveniência",
    golden_set_verified:"Golden Set certificado",
    independent_identity:"Identidade independente",
    logs_clean_24h:"Logs verificados (24 h)",
    minimum_evidence:"Amostra suficiente",window_elapsed:"Janela completa"
  };
  const FAMILIES = {"1x2":"1X2 + AH + Total",total_up:"Total ↑",total_down:"Total ↓"};
  const NS="http://www.w3.org/2000/svg";
  function count(x){return Number.isFinite(Number(x))?Number(x).toLocaleString("pt-PT"): "—"}
  function decimal(x,d=2){return x==null || !Number.isFinite(Number(x))?"—":Number(x).toLocaleString("pt-PT",{minimumFractionDigits:d,maximumFractionDigits:d})}
  function signed(x,d=2){return x==null||!Number.isFinite(Number(x))?"—":(Number(x)>0?"+":"")+decimal(x,d)}
  function roi(x,n){return !n?"Sem resultados":(x==null?"—":signed(x,1)+"%")}
  function parseTime(x){const n=Date.parse(x||"");return Number.isFinite(n)?n:null}
  function timeText(x,opts={day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}) {
    const dt=parseTime(x);if(dt==null)return "Hora não disponível";
    return new Intl.DateTimeFormat("pt-PT",{timeZone:"Europe/Lisbon",...opts}).format(dt);
  }
  function ageState(x,now=Date.now(),maxMinutes=20){
    const t=parseTime(x);
    if(t==null || t>now+60000)return "unknown";
    return now-t<=maxMinutes*60000?"ok":"stale";
  }
  function h1Metrics(data){
    if(!data)return null;
    const s=data.singles||{},t=data.triples||{};
    return {alerts:data.alert_count||0,signals:s.total??data.signals?.length??0,
      triples:t.total??data.tickets?.length??0,
      pending:s.pending??0,settled:s.settled??0,roi:s.roi_pct,profit:s.profit_units,
      triplePending:t.pending??0,tripleSettled:t.settled??0,tripleRoi:t.roi_pct};
  }
  function labMetrics(timeline,v4,golden){
    const s=timeline?.summary||{},c=v4?.phase_coverage?.first_24h||{};
    return {messages:s.messages??null,matches:s.matches??null,repeated:s.repeated_matches??null,
      related:s.related_message_pairs??null,duplicates:s.possibly_redundant_snapshots??null,
      captured:c.captured??null,eligible:c.eligible??null,
      reviewed:golden?.human_review_totals?.messages_with_human_review??null,
      agreed:golden?.human_review_totals?.fields_matching_v4??null,
      compared:golden?.human_review_totals?.fields_compared??null,
      pending:golden?.pending_reference_count??null};
  }
  function sortedSignals(rows,now=Date.now()){
    return [...(rows||[])].sort((a,b)=>{
      const af=parseTime(a.kickoff_utc)??0,bf=parseTime(b.kickoff_utc)??0;
      const ac=af>=now?0:1,bc=bf>=now?0:1;
      return ac-bc || (ac===0?af-bf:bf-af);
    });
  }
  function filteredSignals(rows,query="",filter="all",now=Date.now()){
    const q=query.trim().toLocaleLowerCase("pt-PT");
    return sortedSignals(rows,now).filter(s=>{
      const text=[s.home,s.away,s.competition].join(" ").toLocaleLowerCase("pt-PT");
      return (!q||text.includes(q))&&
        (filter==="all"||filter==="pending"&&s.profit==null||
         filter==="settled"&&s.profit!=null||filter==="upcoming"&&(parseTime(s.kickoff_utc)??0)>=now);
    });
  }
  function filteredTimelines(rows,query="",filter="all"){
    const q=query.trim().toLocaleLowerCase("pt-PT");
    return (rows||[]).filter(t=>{
      const name=(t.match_label||"").toLocaleLowerCase("pt-PT");
      return (!q||name.includes(q))&&(filter==="all"||
       filter==="related"&&(t.related_messages||[]).length>0||
       filter==="reversals"&&(t.trajectory?.total?.reversals||[]).length>0||
       filter==="v4"&&(t.events||[]).some(e=>Object.values(e.snapshots||{}).some(m=>m.origin==="V4_EXPLICIT")));
    });
  }
  function telegramDecision(row){
    if(!row)return {three:"Sem auditoria de elegibilidade",two:"Sem auditoria de elegibilidade",note:"O painel não confirma o envio.",review:false};
    const receipts=row.receipts||{};
    function rule(key,eligible,count,threshold){
      const receipt=receipts[key];
      if(receipt?.status==="sent")return "Enviado · mensagem Telegram #"+receipt.telegram_message_id;
      if(receipt?.status==="delivery_uncertain_manual_review")return "Entrega incerta · revisão manual";
      if(eligible)return "Elegível · sem recibo publicado (verificar logs)";
      return "Excluído · "+count+"/"+threshold+" movimentos válidos";
    }
    const three=rule("three",row.three_eligible,row.valid_three_moves,3);
    let two=rule("two",row.two_eligible,row.valid_up_moves,2);
    if(!row.two_eligible&&!receipts.two){
      const n=Number(row.net_up)||0;
      two+=" · subida líquida "+decimal(n)+(row.v4_down_observed?" · descida V4 observada":"");
    }
    const reason=row.reason||"Motivo indisponível";
    const excludes=Object.entries(row.rejects||{}).filter(([,n])=>n>0);
    const names={
      suspected_duplicate:"repetições suspeitas",ambiguous_transition:"transições ambíguas",
      same_episode:"mesmo episódio",not_explicit_v4:"sem V4 explícito",
      flat_total_line:"Total estável",outside_decision_window:"fora da janela de decisão",
      invalid_direction:"direção inválida",invalid_line:"linha inválida"
    };
    const proof=excludes.map(([k,n])=>n+" "+(names[k]||k)).join(" · ");
    return {three,two,note:reason+(proof?" · Descartados: "+proof:""),
      review:!!row.review_possible_false_negative};
  }
  const api={h1Metrics,labMetrics,sortedSignals,filteredSignals,filteredTimelines,telegramDecision,ageState,roi,decimal,timeText};
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(typeof document==="undefined")return;
  const $=id=>document.getElementById(id);
  const app={current:"overview",h1:null,v4:null,golden:null,timeline:null,telegram:null,priority:null,failures:[],loading:false};
  function e(tag,txt,cls){const x=document.createElement(tag);if(txt!=null)x.textContent=String(txt);if(cls)x.className=cls;return x;}
  function append(parent,...children){for(const c of children)if(c!=null)parent.append(c);return parent;}
  function clear(id){const x=$(id);if(x)x.replaceChildren();return x}
  function set(id,value){const x=$(id);if(x)x.textContent=String(value??"—")}
  function status(label,kind){return e("span",label,"status-tag "+(kind||""))}
  function dateTag(x){return timeText(x)}
  function go(view){
    if(!["overview","h1","triples","market","quality"].includes(view))return;
    app.current=view;
    document.querySelectorAll(".view").forEach(el=>el.hidden=el.id!=="view-"+view);
    document.querySelectorAll("[data-view]").forEach(btn=>{
      const active=btn.dataset.view===view;btn.classList.toggle("active",active);
      if(active)btn.setAttribute("aria-current","page");else btn.removeAttribute("aria-current");
    });
    set("crumb-name",{overview:"Visão geral",h1:"Sinais H1",triples:"Triplas",market:"Mercados e jogos",quality:"Qualidade e Golden"}[view]);
    try{history.replaceState(null,"",view==="overview"?"./index.html":"#"+view)}catch(_){}
    window.scrollTo({top:0,behavior:"instant"});
  }
  document.querySelectorAll("[data-view]").forEach(el=>el.addEventListener("click",()=>go(el.dataset.view)));
  document.querySelectorAll("[data-go]").forEach(el=>el.addEventListener("click",()=>go(el.dataset.go)));
  for(const id of ["h1-query","h1-filter"])$(id).addEventListener("input",renderH1);
  $("triple-filter").addEventListener("input",renderTriples);
  for(const id of ["market-query","market-filter"])$(id).addEventListener("input",renderMarkets);
  $("refresh").addEventListener("click",()=>load());
  window.addEventListener("hashchange",()=>go(location.hash.slice(1)||"overview"));

  function health(){
    const poll=app.h1?.collector?.last_poll_at;
    const h=ageState(poll,Date.now(),20);
    const labTime=[app.v4?.generated_at,app.golden?.generated_at,app.timeline?.generated_at]
        .map(parseTime).filter(x=>x!=null);
    const labAt=labTime.length?Math.min(...labTime):null;
    const l=labAt===null?"unknown":ageState(new Date(labAt).toISOString(),Date.now(),25);
    const healthLabel={ok:"Atualizado",stale:"Desatualizado",unknown:"Sem dados"};
    for(const [key,kind] of [["h1",h],["lab",l]]){
      const dot=$(key+"-dot");dot.className="system-dot "+(kind==="stale"?"warn":kind==="ok"?"ok":"error");
      set(key+"-health",healthLabel[kind]);
    }
    const at=parseTime(app.h1?.generated_at);
    const source=app.h1?.collector?.trigger_source;
    const sr=source==="cloudflare-cron"?"Cloudflare Cron":source==="github-schedule"?"GitHub Cron":source==="workflow_dispatch"?"Manual":source||"origem não indicada";
    set("system-note","Último H1: "+(poll?dateTag(poll):"sem recolha")+" · "+sr);
    set("global-stamp",at!=null?"Dados H1 · "+dateTag(app.h1.generated_at):"Sem dados H1");
  }
  function info(msg){return e("p",msg,"empty-note")}
  function compact(id,rows){
    const parent=clear(id);
    if(!rows.length){parent.append(info("Ainda não existem registos disponíveis."));return}
    for(const r of rows){
      const clickable=!!r.go;
      const box=e(clickable?"button":"div",null,"compact-item");
      if(clickable){box.type="button";box.addEventListener("click",()=>go(r.go))}
      const left=e("div");append(left,e("div",r.title,"item-title"),e("small",r.sub,"item-sub"));
      const right=e("div",null,"item-right");append(right,e("strong",r.value),e("small",r.note));
      append(box,left,right);parent.append(box);
    }
  }
  function renderOverview(){
    const h=h1Metrics(app.h1),m=labMetrics(app.timeline,app.v4,app.golden);
    set("nav-h1",h?count(h.signals):"—");set("nav-triples",h?count(h.triples):"—");
    set("nav-matches",m.repeated==null?"—":count(m.repeated));
    if(h){
      set("k-h1-signals",count(h.signals));set("k-h1-triples",count(h.triples));
      set("k-h1-pending",count(h.pending));set("k-h1-roi",roi(h.roi,h.settled));
      set("k-h1-signals-sub",count(h.alerts)+" alertas processados");
      set("k-h1-triples-sub",count(h.triplePending)+" pendentes");
      set("k-h1-roi-sub",count(h.settled)+" singles liquidadas");
    }
    for(const [id,value] of [["k-lab-messages",m.messages],["k-lab-games",m.matches],["k-lab-repeated",m.repeated]])set(id,value==null?"—":count(value));
    set("k-lab-repeated-sub",m.repeated==null?"Sem relatório":"Jogos com 2 ou mais alertas");
    set("k-lab-capture",m.captured==null||!m.eligible?"—":count(m.captured)+"/"+count(m.eligible));
    const ts=app.timeline?.timelines||[];
    const top=[...ts].sort((a,b)=>(b.related_messages?.length||0)-(a.related_messages?.length||0)||
      (b.event_count||0)-(a.event_count||0)).slice(0,5);
    compact("overview-movements",top.map(t=>({
      title:t.match_label,sub:t.event_count+" alertas · "+(t.related_messages?.length||0)+" movimentos relacionados",
      value:t.trajectory?.total?decimal(t.trajectory.total.first_observed_line)+" → "+decimal(t.trajectory.total.last_observed_line):"Sem Total",
      note:t.possibly_redundant_event_ids?.length?"Repetição possível":"Cronologia observada",go:"market"
    })));
    const next=sortedSignals(app.h1?.signals||[]).filter(s=>(parseTime(s.kickoff_utc)??0)>Date.now()).slice(0,5);
    compact("overview-signals",next.map(s=>({title:s.home+" – "+s.away,sub:s.competition+" · "+dateTag(s.kickoff_utc),
      value:"Under "+decimal(s.line),note:"Odd "+decimal(s.under_odds),go:"h1"})));
    const recent=[...(app.h1?.tickets||[])].sort((a,b)=>(parseTime(b.created_at)||0)-(parseTime(a.created_at)||0)).slice(0,4);
    compact("overview-triples",recent.map(t=>({title:t.ticket_id,sub:t.legs?.length+" seleções · "+dateTag(t.created_at),
      value:decimal(t.theoretical_odds),note:t.profit==null?"Pendente":signed(t.profit)+" u.",go:"triples"})));
    const preview=clear("overview-quality");
    const v=app.v4,g=app.golden;
    if(!v&&!g){preview.append(info("Relatórios de validação indisponíveis."));return}
    const st=e("div",null,"preview-state");const col=e("div");
    append(col,e("strong",v?.status==="PENDING"?"Validação V4 pendente":v?.status||"Auditoria V4 indisponível"),
      e("p","Cobertura não significa exatidão das odds."));
    append(st,e("span","◇","metric-icon"),col,status(g?.golden_set_verified?"Golden verificado":"Golden não certificado",g?.golden_set_verified?"ok":"warn"));
    preview.append(st);
    const minis=e("div",null,"mini-stats");
    for(const [n,c] of [["Mensagens revistas",m.reviewed],["Campos coincidentes",m.compared==null?"—":count(m.agreed)+"/"+count(m.compared)]]){
      const box=e("div",null,"mini-stat");append(box,e("strong",c==null?"—":String(c)),e("span",n));minis.append(box)
    }
    preview.append(minis);
  }
  function sourceLink(url){
    if(typeof url!=="string"||!/^https:\/\/[^\s]+$/i.test(url))return null;
    const a=e("a","Ver alerta de origem ↗");a.href=url;a.target="_blank";a.rel="noopener noreferrer";return a;
  }
  function renderH1(){
    const h=h1Metrics(app.h1);
    set("h1-all",h?count(h.signals):"—");
    set("h1-all-caption",h?count(h.settled)+" liquidadas · "+count(h.pending)+" pendentes":"Dados indisponíveis");
    set("h1-roi",h?roi(h.roi,h.settled):"—");set("h1-roi-caption",h?count(h.settled)+" jogos com resultado":"—");
    set("h1-profit",h?signed(h.profit)+" u.":"—");
    const list=clear("h1-list");const items=filteredSignals(app.h1?.signals,$("h1-query").value,$("h1-filter").value);
    set("h1-count",count(items.length)+" jogos apresentados");
    if(!items.length){list.append(info("Sem sinais para este filtro."));return}
    for(const s of items){
      const card=e("article",null,"signal-card"),head=e("div",null,"signal-top");
      const label=e("div");append(label,e("h3",s.home+" – "+s.away),e("div",s.competition||"Competição não indicada","meta"),
       e("small",dateTag(s.kickoff_utc)+" · hora de Portugal","meta"));
      head.append(label,status(s.profit==null?"Pendente":s.profit>0?"GREEN":s.profit<0?"RED":"PUSH",s.profit==null?"warn":s.profit<0?"bad":"ok"));
      card.append(head);
      const badges=e("div",null,"signal-meta");
      for(const [k,v] of [["Mercado","Under "+decimal(s.line)],["Odd recolhida",decimal(s.under_odds)],
       ["Resultado FT",s.result?s.result.home_goals+"–"+s.result.away_goals:"Pendente"]]){
       const chip=e("div",null,"data-chip");append(chip,e("small",k),e("strong",v));badges.append(chip)
      }
      card.append(badges);
      const foot=e("div",null,"signal-footer");
      const pl=e("strong",s.profit==null?"Liquidação pendente":signed(s.profit)+" u.","profit"+(s.profit==null?"":s.profit>=0?" positive":" negative"));
      foot.append(pl);
      const url=sourceLink(s.source_url);if(url)foot.append(url);
      card.append(foot);list.append(card);
    }
  }
  function renderTriples(){
    const h=h1Metrics(app.h1);
    set("tri-all",h?count(h.triples):"—");
    set("tri-roi",h?roi(h.tripleRoi,h.tripleSettled):"—");
    set("tri-roi-caption",h?count(h.tripleSettled)+" triplas liquidadas":"—");
    set("tri-pending",h?count(h.triplePending):"—");
    const all=[...(app.h1?.tickets||[])].sort((a,b)=>(parseTime(b.created_at)||0)-(parseTime(a.created_at)||0));
    const filter=$("triple-filter").value;
    const rows=all.filter(t=>filter==="all"||filter==="pending"&&t.profit==null||filter==="settled"&&t.profit!=null);
    set("triple-count",count(rows.length)+" triplas apresentadas");
    const list=clear("triple-list");if(!rows.length){list.append(info("Sem triplas para este filtro."));return}
    for(const t of rows){
      const box=e("article",null,"ticket-card"),head=e("div",null,"ticket-top");
      const col=e("div");append(col,e("h3",t.ticket_id),e("div","Criada a "+dateTag(t.created_at)+" · seleção FIFO","meta"));
      append(head,col,status(t.profit==null?"Pendente":t.profit>0?"GREEN":t.profit<0?"RED":"PUSH",t.profit==null?"warn":t.profit<0?"bad":"ok"));
      box.append(head);
      const legs=e("div",null,"ticket-legs");
      (t.legs||[]).forEach((s,i)=>{
        const leg=e("div",null,"ticket-leg");
        append(leg,e("span",i+1,"leg-index"),e("span",s.name+" · Under "+decimal(s.line)),
          e("strong","@ "+decimal(s.odds),"leg-odd"));
        legs.append(leg);
      });box.append(legs);
      const foot=e("div",null,"ticket-summary");
      append(foot,e("span","Odd combinada teórica: "+decimal(t.theoretical_odds)),
        e("strong",t.profit==null?"Sem resultado final":signed(t.profit)+" u."));
      box.append(foot);list.append(box);
    }
  }
  function svgEl(tag,props){const x=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(props||{}))x.setAttribute(k,String(v));return x}
  function chart(points){
    const wrap=e("div",null,"market-chart");
    const caption=e("div",null,"chart-caption");
    append(caption,e("span","Linha Total · evolução observada"),
      e("strong",points.length?decimal(points[0].before)+" → "+decimal(points.at(-1).after):"Sem Total"));
    wrap.append(caption);
    if(!points.length){wrap.append(e("div","Sem linha Total comunicada","chart-empty"));return wrap}
    const svg=svgEl("svg",{viewBox:"0 0 360 105",role:"img","aria-label":"Linhas de Total: cada segmento cheio mostra o movimento dentro de uma mensagem; os tracejados mostram intervalos sem observação."});
    const ys=points.flatMap(p=>[Number(p.before),Number(p.after)]);
    const mn=Math.min(...ys),mx=Math.max(...ys),range=Math.max(.5,mx-mn),W=340;
    const yy=v=>87-((v-mn)/range)*63;
    function xPos(i,after){const c=10+(points.length===1?W/2:i*W/(points.length-1));return c+(after?6:-6)}
    for(let i=0;i<points.length;i++){
      const p=points[i],xb=xPos(i,false),xa=xPos(i,true),yb=yy(p.before),ya=yy(p.after);
      if(i>0){
        const prev=points[i-1];
        svg.append(svgEl("line",{x1:xPos(i-1,true),y1:yy(prev.after),x2:xb,y2:yb,class:"chart-gap"}));
      }
      svg.append(svgEl("line",{x1:xb,y1:yb,x2:xa,y2:ya,class:"chart-line"}));
      svg.append(svgEl("circle",{cx:xb,cy:yb,r:3.5,class:"chart-point"}));
      svg.append(svgEl("circle",{cx:xa,cy:ya,r:4,class:"chart-point"}));
    }
    const minLabel=svgEl("text",{x:"8",y:"100",class:"chart-label"});minLabel.textContent=decimal(mn);
    const maxLabel=svgEl("text",{x:"8",y:"12",class:"chart-label"});maxLabel.textContent=decimal(mx);
    svg.append(minLabel,maxLabel);wrap.append(svg);return wrap;
  }
  function renderMarkets(){
    const tl=app.timeline, s=tl?.summary||{};
    set("mk-repeat",s.repeated_matches==null?"—":count(s.repeated_matches));
    set("mk-pairs",s.related_message_pairs==null?"—":count(s.related_message_pairs));
    set("mk-duplicate",s.possibly_redundant_snapshots==null?"—":count(s.possibly_redundant_snapshots));
    const rows=filteredTimelines(tl?.timelines,$("market-query").value,$("market-filter").value);
    set("market-count",count(rows.length)+" jogos apresentados");
    const list=clear("market-list");if(!rows.length){list.append(info("Sem jogos neste filtro. O LAB publica detalhes dos jogos repetidos; os restantes são contados no resumo."));return}
    for(const t of rows){
      const box=e("article",null,"market-card"),head=e("div",null,"market-head"),left=e("div");
      append(left,e("h3",t.match_label),e("small",t.event_count+" alertas · "+dateTag(t.first_observed_at)+" até "+dateTag(t.last_observed_at)));
      append(head,left,status(t.related_messages?.length?"Movimentos relacionados":"Alertas distintos",t.related_messages?.length?"warn":""));
      box.append(head);
      const tags=e("div",null,"market-tags");
      const v4=(t.events||[]).some(x=>Object.values(x.snapshots||{}).some(v=>v.origin==="V4_EXPLICIT"));
      append(tags,status(v4?"Inclui V4 explícito":"Só legado H1",v4?"ok":""),
        status("AH: "+count(t.trajectory?.asian_handicap?.observations||0),""),
        status("1X2: "+count(t.trajectory?.one_x_two?.observations||0),""));
      if(t.possibly_redundant_event_ids?.length)tags.append(status(t.possibly_redundant_event_ids.length+" snapshot(s) possivelmente repetido(s)","warn"));
      box.append(tags,chart(t.trajectory?.total?.points||[]));
      const matchingAudit=app.telegram?.schema_version===1 &&
        app.telegram?.status==="READ_ONLY_PARITY_VERIFIED_NOT_DELIVERY_PROOF" &&
        app.telegram?.source_commit===app.timeline?.source_commit;
      const audit=matchingAudit?app.telegram.games?.[t.match_key]:null;
      const notice=e("section",null,"telegram-audit");
      notice.append(e("strong","Telegram · elegibilidade das duas regras"));
      if(!matchingAudit||!audit){
        notice.append(e("p","A aguardar auditoria compatível com esta cronologia; os alertas do gráfico não comprovam envios."));
      }else{
        const summary=telegramDecision(audit);
        notice.append(e("p","3 movimentos: "+summary.three),
          e("p","2 subidas: "+summary.two),
          e("p","Motivo: "+summary.note));
        if(summary.review)notice.append(e("p","Possível falso negativo: requer revisão da independência dos movimentos; não autoriza envio automático.","telegram-review"));
        notice.append(e("small","Fotografia de "+dateTag(app.telegram.generated_at)+" · faltas de recibo não provam que o Telegram recusou o envio."));
      }
      box.append(notice);
      const foot=e("div",null,"market-foot");
      append(foot,e("span",count(t.related_messages?.length||0)+" pares relacionados"),
        e("span",count(t.trajectory?.total?.reversals?.length||0)+" reversões assinaladas"));
      box.append(foot);
      const details=e("details",null,"market-detail");
      details.append(e("summary","Ver as "+t.event_count+" mensagens e respetivos mercados"));
      const ol=e("ol");
      for(const ev of t.events||[]){
        const li=e("li");const num=(ev.event_id||"").split(":").at(-1);
        const origins=Object.values(ev.snapshots||{}).map(s=>s.origin);
        const originsText=[...new Set(origins)].map(x=>x==="V4_EXPLICIT"?"V4 explícito":"H1 legado").join(" + ")||"Sem tabela";
        const total=ev.snapshots?.total;
        append(li,e("strong","#"+num+" · "+dateTag(ev.observed_at)+" · "+(ev.trigger_market==="1x2"?"1X2":"Total")),
          e("span"," · "+(total?"Total "+decimal(total.before.line)+" → "+decimal(total.after.line):"Sem Total")+" · "+originsText));
        ol.append(li);
      }
      details.append(ol);box.append(details);list.append(box);
    }
  }
  function gateRow(parent,name,detail,tagEl){
    const row=e("div",null,"gate-row"),left=e("div");
    append(left,e("strong",name),e("small",detail));
    append(row,left,tagEl);parent.append(row);
  }
  function renderQuality(){
    const m=labMetrics(app.timeline,app.v4,app.golden),g=app.golden,v=app.v4;
    set("q-reviewed",m.reviewed==null?"—":count(m.reviewed));
    set("q-fields",m.compared==null?"—":count(m.agreed)+"/"+count(m.compared));
    set("q-pending",m.pending==null?"—":count(m.pending));
    const gates=clear("quality-gates");
    if(!v){gates.append(info("Auditoria V4 indisponível."))}
    else for(const [key,ok] of Object.entries(v.acceptance_gates||{})){
      gateRow(gates,LABELS[key]||key,ok?"Critério atingido na janela definida":"Ainda não há evidência suficiente para aprovar",status(ok?"Cumprido":"Pendente",ok?"ok":"warn"))
    }
    const fam=clear("quality-families");
    if(!g){fam.append(info("Golden Set indisponível."))}
    else for(const [name,entry] of Object.entries(g.coverage_by_family||{})){
      const n=count(entry.messages_with_human_review)+"/"+count(entry.candidates)+" mensagens";
      gateRow(fam,FAMILIES[name]||name,n+" · "+count(entry.fields_matching_v4)+"/"+count(entry.fields_compared)+" campos coincidentes",
        status(entry.user_source_confirmed?count(entry.user_source_confirmed)+" origem confirmada":"R1 apenas",entry.user_source_confirmed?"ok":"warn"))
    }
  }
  function renderAll(){health();renderOverview();renderH1();renderTriples();renderMarkets();renderQuality()}
  async function load(){
    if(app.loading)return;
    app.loading=true;$("refresh").disabled=true;
    const paths={
      h1:"./data.json",v4:"./lab/v4-audit.json",golden:"./lab/golden-report.json",
      timeline:"./lab/match-trajectories.json",telegram:"./lab/telegram-eligibility.json",priority:"./lab/golden-priority.json"
    };
    const results=await Promise.all(Object.entries(paths).map(async ([key,path])=>{
      try{
        const result=await fetch(path,{cache:"no-store"});
        if(!result.ok)throw Error("HTTP "+result.status);
        return [key,await result.json(),null];
      }catch(err){return [key,null,String(err?.message||err)]}
    }));
    const fail=[];for(const [key,val,err] of results){
      if(err){fail.push(key);app[key]=null;}else app[key]=val;
    }
    app.failures=fail;const banner=$("error-banner");
    banner.hidden=!fail.length;
    if(fail.length)banner.textContent="Alguns relatórios não estão disponíveis ("+fail.join(", ")+"). Os restantes dados continuam acessíveis; não assumimos valores em falta.";
    renderAll();
    app.loading=false;$("refresh").disabled=false;
  }
  load();
  // Read-only refresh; no jobs, notifications or financial actions are triggered.
  setInterval(()=>{if(document.visibilityState==="visible")load()},60000);
  go(location.hash.slice(1)||"overview");
})(typeof window!=="undefined"?window:globalThis);
