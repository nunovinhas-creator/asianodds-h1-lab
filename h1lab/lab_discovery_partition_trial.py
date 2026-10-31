"""Offline-only partition migration trial. NOT a productive state loader."""
import copy,hashlib,json


def encode(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def partition(state,limit=256000):
    meta=copy.deepcopy(state);patterns=meta.pop('patterns');shards={};parts=[];chunk={}
    def flush():
        if not chunk:return
        raw=encode(chunk);name='patterns-%04d.json'%len(parts)
        shards[name]=raw
        parts.append({'name':name,'sha256':hashlib.sha256(raw).hexdigest(),
                      'bytes':len(raw),'patterns':len(chunk)})
    for key,row in sorted(patterns.items()):
        if len(encode({key:row}))>limit:raise ValueError('Single pattern exceeds shard limit')
        if chunk and len(encode({**chunk,key:row}))>limit:
            flush();chunk={}
        chunk[key]=row
    flush()
    manifest={'status':'EXPERIMENTAL_NOT_FOR_PRODUCTION','source_sha256':hashlib.sha256(encode(state)).hexdigest(),
              'metadata':meta,'parts':parts,'pattern_count':len(patterns)}
    if len(encode(manifest))>limit:raise ValueError('Manifest exceeds trial limit')
    return manifest,shards


def restore(manifest,shards):
    if manifest.get('status')!='EXPERIMENTAL_NOT_FOR_PRODUCTION':raise ValueError('Invalid trial manifest')
    state=copy.deepcopy(manifest['metadata']);patterns={}
    for part in manifest['parts']:
        raw=shards.get(part['name'])
        if not isinstance(raw,bytes) or len(raw)!=part['bytes'] or hashlib.sha256(raw).hexdigest()!=part['sha256']:
            raise ValueError('Missing or corrupted state shard')
        rows=json.loads(raw)
        if not isinstance(rows,dict) or len(rows)!=part['patterns'] or set(patterns)&set(rows):
            raise ValueError('Invalid or duplicate shard keys')
        patterns.update(rows)
    state['patterns']=patterns
    if len(patterns)!=manifest['pattern_count'] or hashlib.sha256(encode(state)).hexdigest()!=manifest['source_sha256']:
        raise ValueError('Migration reconstruction mismatch')
    return state
