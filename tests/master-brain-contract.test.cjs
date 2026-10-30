const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {validateData,renderPatternsMeta,renderValidation,renderChronology,_testState}=require('../docs/master-brain.js');
test('reject empty/array/wrong schema and missing fields instead of zero opportunities',()=>{
 for(const bad of [{},[],null,{schema_version:999},{schema_version:1,future_strict:[]}])
  assert.throws(()=>validateData('watch',bad));
});
test('real published contracts pass without mutating source',()=>{
 for(const [k,p] of Object.entries({research:'lab/pattern-research.json',watch:'lab/pattern-watch.json',discovery:'lab/discoveries.json',ft:'lab/ft-results.json',quality:'lab/v4-audit.json',h1:'data.json'})){
  const d=JSON.parse(fs.readFileSync('docs/'+p));const before=JSON.stringify(d);validateData(k,d);assert.equal(JSON.stringify(d),before);
 }
});
test('FT inconsistent/nonfinite counts rejected',()=>{
 const d=JSON.parse(fs.readFileSync('docs/lab/ft-results.json'));
 for(const n of [NaN,-1,'485'])assert.throws(()=>validateData('ft',{...d,matches:n}));
 assert.throws(()=>validateData('ft',{...d,unverified:d.unverified+1}));
});

test('missing nested counters and string booleans are not zero/true',()=>{
 const research=JSON.parse(fs.readFileSync('docs/lab/pattern-research.json'));
 assert.throws(()=>validateData('research',{...research,scope:{}}));
 const ft=JSON.parse(fs.readFileSync('docs/lab/ft-results.json'));
 assert.throws(()=>validateData('ft',{...ft,coverage_diagnostics:{}}));
 const quality=JSON.parse(fs.readFileSync('docs/lab/v4-audit.json'));
 assert.throws(()=>validateData('quality',{...quality,acceptance_gates:{data_integrity:"false"}}));
 const h1=JSON.parse(fs.readFileSync('docs/data.json'));
 assert.throws(()=>validateData('h1',{...h1,singles:{...h1.singles,pending:h1.singles.total+1}}));
});


test('malformed nested watch data is rejected before future sort/render',()=>{
 const original=JSON.parse(fs.readFileSync('docs/lab/pattern-watch.json'));
 assert.ok(original.future_strict.length>0);
 const malformed=[
  {...original,future_strict:[{...original.future_strict[0],kickoff_utc:null},...original.future_strict.slice(1)]},
  {...original,future_strict:[{...original.future_strict[0],observations:{}},...original.future_strict.slice(1)]},
  {...original,future_strict:[{...original.future_strict[0],observations:[null]},...original.future_strict.slice(1)]}
 ];
 for(const bad of malformed)assert.throws(()=>validateData('watch',bad),/Contrato de dados inválido/);
 assert.equal(validateData('watch',original),original);
});
test('nested research outcomes must be objects, not arrays or null',()=>{
 const original=JSON.parse(fs.readFileSync('docs/lab/pattern-research.json'));
 assert.ok(original.combinations_top.length>0);
 const bad={...original,combinations_top:[
  {...original.combinations_top[0],outcomes:{...original.combinations_top[0].outcomes,OVER_2_5:[]}},
  ...original.combinations_top.slice(1)
 ]};
 assert.throws(()=>validateData('research',bad),/Contrato de dados inválido/);
 assert.equal(validateData('research',original),original);
});

test('failed refresh cannot keep previous research metrics or discovery details visible',()=>{
 const oldDocument=global.document, nodes=new Map();
 function node(text=''){
   return {textContent:text,hidden:false,children:[],
     append(...children){this.children.push(...children)},
     replaceChildren(){this.children=[]}};
 }
 global.document={
   getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)},
   createElement(){return node()}
 };
 try {
   const ids=['p-count','p-individual','p-tests','p-frozen',
     'v-explore','v-candidates','v-oos','v-validated'];
   for(const id of ids)global.document.getElementById(id).textContent='999';
   for(const id of ['p-cards','v-funnel','v-brier','v-frozen','r-detail'])
     global.document.getElementById(id).append(node('old evidence'));
   _testState.data.research=null;_testState.data.discovery=null;
   renderPatternsMeta();renderValidation();renderChronology();
   for(const id of ids)assert.equal(nodes.get(id).textContent,'—',id);
   for(const id of ['p-cards','v-funnel','v-brier','v-frozen','r-detail'])
     assert.ok(nodes.get(id).children.every(x=>x.textContent!=='old evidence'),id);
   assert.equal(nodes.get('r-detail').hidden,true);
   assert.equal(nodes.get('discovery-count').textContent,'Indisponível');
 } finally {
   if(oldDocument===undefined)delete global.document;else global.document=oldDocument;
 }
});
