// Render the real report and failure states using a minimal DOM, without network.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
  constructor(tag){this.tag=tag;this.children=[];this.textContent='';this.listeners={};}
  append(...xs){this.children.push(...xs);}
  replaceChildren(...xs){this.children=xs;}
  addEventListener(k,f){this.listeners[k]=f;}
  text(){return [this.textContent,...this.children.map(x=>x.text())].join(' ');}
  all(tag){return [...(this.tag===tag?[this]:[]),...this.children.flatMap(x=>x.all(tag))];}
}
async function render(data,ok=true){
  const root=new Node('section'),refresh=new Node('button');
  const document={createElement:t=>new Node(t),getElementById:id=>id==='python-statistics'?root:refresh};
  vm.runInNewContext(fs.readFileSync('docs/llm-statistics.js','utf8'),{document,fetch:async()=>({ok,status:404,json:async()=>data}),Date,Number,String,Object,Array,Error});
  await new Promise(setImmediate);return root;
}
function fixture(){return JSON.parse(fs.readFileSync('tests/fixtures/llm-statistics-ui.json','utf8'));}
test('real snapshot fixture distinguishes proposed, evaluated and proven; renders exact games',async()=>{
  const d=fixture(),r=await render(d);
  assert.match(r.text(),/Comprovação: nenhuma hipótese aprovada/);
  for(const h of d.hypotheses){assert.ok(r.text().includes(h.feature_codes.join(' + ')));for(const g of h.historical.games)assert.ok(r.text().includes(g.match_label));}
  assert.match(r.text(),/INCONCLUSIVA/);
  assert.match(r.text(),/Log Loss do modelo: Não calculável/);
  assert.ok(r.all('table').length>=3);
});
test('missing report is an explicit failure, not zero results',async()=>{
  const r=await render({},false);assert.match(r.text(),/Análise Python indisponível/);assert.match(r.text(),/Não equivale a zero jogos/);
});
test('invalid contract cannot render evidence',async()=>{
  const r=await render({schema_version:999});assert.match(r.text(),/Contrato estatístico inválido/);
});
test('untrusted labels render as text, never HTML',async()=>{
  const d=fixture();d.hypotheses[0].historical.games[0].match_label='<img src=x onerror=alert(1)>';
  const r=await render(d);assert.match(r.text(),/<img src=x/);assert.equal(r.all('img').length,0);
});
