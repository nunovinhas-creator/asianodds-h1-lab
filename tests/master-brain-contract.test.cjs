const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {validateData}=require('../docs/master-brain.js');
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
