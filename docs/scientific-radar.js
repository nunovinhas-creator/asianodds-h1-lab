/* MASTER BRAIN V6.2 — journal-derived evidence viewer; zero betting controls. */
(() => {
  "use strict";
  const SOURCE="./lab/v6-scientific-radar.json";
  const $=id=>document.getElementById(id);
  const node=(name,value,cls)=>{
    const n=document.createElement(name);
    if(value!==undefined&&value!==null)n.textContent=String(value);
    if(cls)n.className=cls;
    return n;
  };
  const line=(root,k,v)=>{
    const r=node("div",null,"science-pair");
    r.append(node("span",k),node("strong",v===null||v===undefined||v===""?"Não disponível":v));
    root.append(r);return r;
  };
  const hash=(value)=>value?String(value).slice(0,16)+"…":"Sem SHA";
  const pcent=value=>typeof value==="number"&&(value>=0&&value<=1)?new Intl.NumberFormat("pt-PT",{style:"percent",maximumFractionDigits:2}).format(value):"Sem probabilidade válida";
  const num=value=>typeof value==="number"?new Intl.NumberFormat("pt-PT").format(value):"—";
  const date=value=>{
    if(!value||!Number.isFinite(Date.parse(value)))return "Não observado";
    return new Intl.DateTimeFormat("pt-PT",{dateStyle:"short",timeStyle:"short",timeZone:"Europe/Lisbon"}).format(new Date(value));
  };
  const blank=(root,text)=>{root.replaceChildren(node("p",text,"empty"))};
  const safeLink=(url,text)=>{
    const a=node("a",text,"science-link");
    if(typeof url==="string"&&/^https:\/\/(github\.com|www\.github\.com)\//.test(url)){
      a.href=url;a.target="_blank";a.rel="noopener noreferrer";
    } else {a.removeAttribute("href");}
    return a;
  };
  const badge=(text,kind="muted")=>node("span",text,"science-badge "+kind);
  const state={radar:null,hypothesis:null,selected:null};
  function renderSummary(){
    const r=state.radar;
    $("sc-hyp").textContent=num(r.active_hypotheses);
    $("sc-frozen").textContent=num(r.totals.frozen_snapshots);
    $("sc-games").textContent=num(r.totals.unique_matches);
    $("sc-ft").textContent=num(r.hypotheses.reduce((n,h)=>n+h.ft_verified,0));
    $("radar-updated").textContent="Memórias verificadas · "+num(r.source_tails&&r.source_tails.forecasts?1:0)+" cadeia V6";
    $("science-flag").textContent="V6 EM INVESTIGAÇÃO · Sem padrão confirmado";
  }
  function renderHypotheses(){
    const where=$("science-hypotheses");where.replaceChildren();
    if(!state.radar.hypotheses.length)return blank(where,"Nenhuma hipótese formalmente registada.");
    state.radar.hypotheses.forEach((h,index)=>{
      const btn=node("button",null,"science-hypothesis"+(state.hypothesis===h.id?" selected":""));
      btn.type="button";btn.setAttribute("aria-pressed",state.hypothesis===h.id?"true":"false");
      const head=node("span",null,"science-hyp-top");
      head.append(node("strong","Hipótese "+(index+1)+" · "+h.outcome),badge(h.state,"warn"));
      btn.append(head,node("span",h.id,"science-monospace"));
      const desc=node("span","Condição: "+h.definition.op+" · "+(h.definition.all||[]).join(" + ")+" · exclui "+(h.definition.none||[]).join(", "),"science-small");
      btn.append(desc,node("span",num(h.frozen_matches)+" jogos congelados · "+num(h.ft_verified)+" com FT comprovado","science-small"));
      btn.addEventListener("click",()=>selectHypothesis(h.id));
      where.append(btn);
    });
  }
  function selectHypothesis(id){
    const h=state.radar.hypotheses.find(x=>x.id===id);
    if(!h)return;
    state.hypothesis=id;state.selected=null;
    $("science-workspace").hidden=false;
    $("science-query").value="";$("science-filter").value="all";
    renderHypotheses();renderGames();renderTests(h);renderSources(h);
    blank($("science-detail"),"Seleciona um jogo à esquerda. A observação, a previsão e o FT aparecem juntos.");
    $("science-workspace").scrollIntoView({block:"start",behavior:"auto"});
  }
  function renderGames(){
    const h=state.radar.hypotheses.find(x=>x.id===state.hypothesis);
    if(!h)return;
    const query=$("science-query").value.toLocaleLowerCase("pt-PT").trim();
    const filter=$("science-filter").value;
    const rows=h.games.filter(x=>{
      if(query&&!(x.match_label+" "+x.match_key+" "+x.event_id).toLocaleLowerCase("pt-PT").includes(query))return false;
      if(filter==="selected"&&!x.forecast.original_posthoc_condition)return false;
      if(filter==="strict"&&!x.forecast.strict_observation)return false;
      if(filter==="ft"&&!x.ft.score)return false;
      if(filter==="missing"&&x.ft.score)return false;
      if(filter==="source"&&x.source_v4.status!=="V4_VERSION_VERIFIED_BEFORE_FREEZE")return false;
      return true;
    });
    $("science-visible").textContent=num(rows.length)+" / "+num(h.games.length)+" jogos";
    const where=$("science-games");where.replaceChildren();
    if(!rows.length)return blank(where,"Nenhum jogo corresponde aos filtros.");
    for(const x of rows){
      const btn=node("button",null,"science-game"+(state.selected===x.match_key?" selected":""));
      btn.type="button";btn.setAttribute("aria-pressed",state.selected===x.match_key?"true":"false");
      btn.append(node("strong",x.match_label));
      const meta=node("span",date(x.kickoff_utc)+" · "+num(x.snapshot_history_count)+" captura(s)","science-small");
      btn.append(meta);
      const tags=node("span",null,"science-game-tags");
      tags.append(badge(x.forecast.original_posthoc_condition?"Condição presente":"Controlo",
                        x.forecast.original_posthoc_condition?"accent":"muted"));
      tags.append(badge(x.ft.score?"FT confirmado":"FT por confirmar",x.ft.score?"ok":"warn"));
      btn.append(tags);
      btn.addEventListener("click",()=>selectGame(x.match_key));
      where.append(btn);
    }
  }
  function section(title){
    const box=node("section",null,"science-proof-step");
    box.append(node("h3",title));return box;
  }
  function selectGame(key){
    const h=state.radar.hypotheses.find(x=>x.id===state.hypothesis);
    const g=h?.games.find(x=>x.match_key===key);
    if(!g)return;
    state.selected=key;
    renderGames();
    const where=$("science-detail");where.replaceChildren();
    const title=node("h2",g.match_label);
    where.append(title,node("p",g.match_key+" · "+date(g.kickoff_utc),"science-small"));
    const evidence=section("1 · O que foi observado");
    line(evidence,"Mensagem Telegram",g.event_id);
    line(evidence,"Data da mensagem",date(g.telegram_original_at));
    line(evidence,"Versão V4 comprovada",g.source_v4.status==="V4_VERSION_VERIFIED_BEFORE_FREEZE"?"Sim, antes da previsão":"Não comprovada nesse instante");
    line(evidence,"SHA do registo V4",hash(g.source_v4.sha256));
    line(evidence,"Hora da versão V4",g.source_v4.known_at?date(g.source_v4.known_at):"Não comprovada");
    line(evidence,"Edição Telegram",g.source_v4.telegram_edit_at?date(g.source_v4.telegram_edit_at):"Não demonstrada");
    if(g.source_v4.markets){
      const kinds=Object.keys(g.source_v4.markets);
      line(evidence,"Mercados efetivamente registados",kinds.join(" · ")||"Não registados");
    }
    where.append(evidence);
    const frozen=section("2 · O que ficou congelado antes do jogo");
    line(frozen,"Conhecido pelo cérebro em",date(g.frozen_known_at));
    line(frozen,"Hash da previsão",hash(g.forecast.sha256));
    line(frozen,"Hash da memória de observação",hash(g.forecast.memory_observation_sha256));
    line(frozen,"Hash da memória de padrão",hash(g.forecast.memory_pattern_sha256));
    line(frozen,"Estado da cotação Total",g.forecast.quality_status||"Não disponível");
    line(frozen,"Linha Total observada (após)",g.forecast.market_total_after?.line??"Sem linha");
    line(frozen,"Preço Over na linha observada",g.forecast.market_total_after?.over_price??"Sem preço");
    line(frozen,"Preço Under na linha observada",g.forecast.market_total_after?.under_price??"Sem preço");
    line(frozen,"Probabilidade de referência O2,5",pcent(g.forecast.market_probability_over_2_5));
    line(frozen,"Condição original pós-hoc",g.forecast.original_posthoc_condition?"Presente":"Ausente");
    line(frozen,"Condição de episódios rigorosos",g.forecast.strict_observation?"Presente":"Ausente");
    line(frozen,"Tipo de previsão",g.forecast.forecast_kind||"Não identificado");
    line(frozen,"Contexto de mercados V6F2",g.forecast.feature_version===2?
         "Registo congelado SHA "+hash(g.forecast.feature_sha256):"Não recolhido nessa versão");
    const note=node("p","A probabilidade de referência O2,5 deriva de um modelo de mercado e não é uma odd O2,5 negociável. A captura não é uma aposta.","science-note");
    frozen.append(note);where.append(frozen);
    const ft=section("3 · O que aconteceu e como foi verificado");
    line(ft,"Estado do FT",g.ft.status);
    line(ft,"Evidência científica V6",g.ft.science_status);
    line(ft,"Qualidade da fonte",g.ft.evidence_level||"Ainda não avaliada");
    line(ft,"Instante da verificação",date(g.ft.checked_at));
    if(g.ft.score){
      line(ft,"Resultado final",num(g.ft.score.home)+" – "+num(g.ft.score.away));
      const outcome=g.ft.score.home+g.ft.score.away>2.5;
      line(ft,"Over 2,5 observado",outcome?"Sim":"Não");
      if(g.ft.source_url){
        const url=g.ft.source_url;
        if(/^https:\/\//.test(url)){
          const link=node("a","Abrir fonte FT original ↗","science-link");
          link.href=url;link.target="_blank";link.rel="noopener noreferrer";ft.append(link);
        }
      }
    }else{
      ft.append(node("p","Sem FT verificável para a previsão. Não é contado como red nem como demonstração de erro.","science-note"));
    }
    line(ft,"SHA do evento FT",hash(g.ft.sha256));
    line(ft,"SHA da evidência científica",hash(g.ft.scientific_event_sha256));
    where.append(ft);
    where.append(node("p","Rastreio completo: observação Telegram → previsão congelada → FT e fonte. As ligações temporais não comprovadas ficam identificadas como ausentes.","science-trail"));
    where.scrollIntoView({block:"nearest",behavior:"auto"});
  }
  function renderTests(h){
    const where=$("science-tests");where.replaceChildren();
    const info=node("p","Registo formal "+date(h.registered_at)+" · Seleção histórica "+date(h.selected_at_claimed)+" · Relatório: "+h.falsification_status,"science-small");
    where.append(info);
    if(!h.falsification_checks.length){
      where.append(node("p","Os dez testes ainda não têm um relatório que corresponda à cauda atual dos diários. Não serão apresentados valores antigos como atuais.","science-note"));
      return;
    }
    for(const x of h.falsification_checks){
      const row=node("div",null,"science-test");
      const left=node("div");left.append(node("strong",x.name),node("small",x.code+" · n = "+num(x.n)));
      row.append(left,badge(x.result,x.result==="PASS"?"ok":x.result==="FAIL"?"warn":"muted"));
      const exp=node("small",x.required,"science-test-requirement");row.append(exp);where.append(row);
    }
    where.append(node("p","PASS significa apenas que esta verificação descritiva foi satisfeita; nunca valida a hipótese por si só.","science-note"));
  }
  function renderSources(h){
    const where=$("science-sources");where.replaceChildren();
    line(where,"SHA da definição da hipótese",hash(h.definition_sha256));
    line(where,"SHA da decisão",hash(h.decision_event_sha256));
    line(where,"Motivo da decisão",h.decision_reason);
    const links=state.radar.source_links||{};
    for(const [name,key] of [
      ["Registo formal da hipótese","hypotheses"],
      ["Previsões congeladas","forecasts"],
      ["Memória de observações","observations"],
      ["Memória de padrões","patterns"],
      ["Decisões científicas","decisions"],
      ["Evidência FT universal","universal_ft"],
      ["Revisões Telegram V4","v4_revisions"]]){
      if(links[key]){
        const r=node("div",null,"science-source-row");
        r.append(node("span",name),safeLink(links[key],"Ver diário no GitHub"));
        where.append(r);
      }
    }
  }
  // Weekly drift snapshots are derived from already recorded V6 forecasts,
  // FT and Telegram formats. Never display the current incomplete week
  // as a confirmed signal.
  const driftName={quality:"Cotações suspeitas",formats:"Formatos Telegram",
                   market:"Probabilidades do mercado",calibration:"Calibração FT"};
  const driftState={
    INSUFFICIENT_HISTORY:"Sem semanas comparáveis",
    INSUFFICIENT_N:"Amostra insuficiente",
    SUSPECTED_DRIFT_REVIEW:"Alteração suspeita · rever",
    NO_THRESHOLD_CROSSED:"Sem ultrapassar o limiar",
  };
  async function loadWeekly(){
    const status=$("weekly-status"),where=$("weekly-signals"),weeks=$("weekly-weeks");
    if(!status||!where||!weeks)return;
    try{
      const res=await fetch("./lab/v6-weekly-drift.json",{cache:"no-store"});
      if(!res.ok)throw Error("Relatório ainda não publicado");
      const json=await res.json();
      if(json.status!=="V6_WEEKLY_DRIFT_MONITOR_SHADOW"||!json.latest)
        throw Error("Relatório incompleto");
      const d=json.latest;
      status.textContent="Última fotografia: "+date(json.latest_snapshot_at)+
        " · semana "+json.latest_monitor_week+" · "+
        (d.overall==="SUSPECTED_DRIFT_REVIEW"?"REVISÃO NECESSÁRIA":
          "Sem evidência suficiente para declarar drift");
      where.replaceChildren();
      for(const [key,label] of Object.entries(driftName)){
        const c=d.comparisons?.[key]||{};
        const b=node("article",null,"weekly-drift-card");
        b.append(node("h3",label));
        b.append(badge(driftState[c.status]||"Sem avaliação",
                       c.status==="SUSPECTED_DRIFT_REVIEW"?"warn":"muted"));
        const v=c.value;
        let formatted="Sem métrica comparável";
        if(typeof v==="number")formatted=(key==="quality"?
          (v*100).toLocaleString("pt-PT",{maximumFractionDigits:1})+" pp":
          v.toLocaleString("pt-PT",{maximumFractionDigits:4}));
        b.append(node("strong",formatted,"weekly-value"));
        b.append(node("small","Amostras: "+num(c.reference_n)+" / "+num(c.comparison_n)+
                            " · limiar: "+(c.review_threshold??"não disponível"),"science-small"));
        where.append(b);
      }
      weeks.replaceChildren();
      const head=node("h3","Últimas semanas observadas");
      weeks.append(head);
      const table=node("div",null,"weekly-week-grid");
      for(const w of (d.weeks||[]).slice(-6)){
        const box=node("div",null,"weekly-week");
        box.append(node("strong",w.week+(w.period==="CURRENT_INCOMPLETE"?" · parcial":"")));
        box.append(node("span","Observações: "+num(w.quality.n)));
        box.append(node("span","Cotação inutilizável: "+(
          w.quality.unusable_rate===null?"—":pcent(w.quality.unusable_rate))));
        box.append(node("span","Formatos: "+num(w.formats.n)+" · famílias: "+num(w.formats.distinct_families)));
        box.append(node("span","FT para calibração: "+num(w.calibration.n)));
        box.append(node("span","Brier: "+(w.calibration.brier_score===null?
          "não calculável":w.calibration.brier_score.toLocaleString("pt-PT",{maximumFractionDigits:4}))));
        table.append(box);
      }
      if(!table.children.length)table.append(node("p","Ainda não existem observações semanais."));
      weeks.append(table);
    }catch(e){
      status.textContent="Monitor semanal ainda indisponível: "+e.message+
        ". Não serão inferidas alterações a partir de relatórios ausentes.";
      where.replaceChildren();weeks.replaceChildren();
    }
  }
  async function load(){
    const button=$("radar-refresh");button.disabled=true;
    try{
      const response=await fetch(SOURCE,{cache:"no-store"});
      if(!response.ok)throw Error("HTTP "+response.status);
      const obj=await response.json();
      if(obj.status!=="V6_SCIENTIFIC_RADAR_SHADOW_NOT_VALIDATED"||
         obj.active_hypotheses>10||!Array.isArray(obj.hypotheses))throw Error("Relatório incompatível");
      state.radar=obj;
      $("science-error").hidden=true;
      renderSummary();renderHypotheses();
      if(state.hypothesis&&obj.hypotheses.some(h=>h.id===state.hypothesis)){
        const previous=state.selected;
        selectHypothesis(state.hypothesis);
        if(previous)selectGame(previous);
      }else{
        $("science-workspace").hidden=true;
        state.selected=null;
      }
    }catch(error){
      $("science-error").hidden=false;
      $("science-error").textContent="Radar Científico indisponível ou sem relatório atual: "+error.message+". Não são apresentados dados antigos como novos.";
      $("radar-updated").textContent="Relatório não disponível";
    }finally{button.disabled=false}
  }
  $("science-query").addEventListener("input",renderGames);
  $("science-filter").addEventListener("change",renderGames);
  $("radar-refresh").addEventListener("click",()=>{load();loadWeekly()});
  load();loadWeekly();
})();
