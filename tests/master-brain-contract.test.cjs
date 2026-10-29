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
