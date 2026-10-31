"""Prepared immutable discovery store. No productive reader/writer imports it.

Local POSIX atomicity/CAS only. Git publication activation is a separate review.
"""
import contextlib
import copy
import fcntl
import gzip
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

SHARD_LIMIT = 256_000
STATE_LIMIT = 20_000_000


def encode(x):
    return (json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)+'\n').encode()


def digest(raw): return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out: raise ValueError('Duplicate JSON key')
            out[k]=v
        return out
    def bad(v): raise ValueError('Nonfinite JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def partition(state):
    """Shard ALL top-level collections, including settled history/metadata."""
    if not isinstance(state, dict): raise ValueError('State must be an object')
    layout={}; entries=[]
    for field,value in sorted(state.items()):
        if isinstance(value, dict):
            layout[field]={'kind':'dict','length':len(value)}
            entries.extend({'field':field,'key':k,'value':v} for k,v in sorted(value.items()))
        elif isinstance(value, list):
            layout[field]={'kind':'list','length':len(value)}
            entries.extend({'field':field,'key':i,'value':v} for i,v in enumerate(value))
        else:
            layout[field]={'kind':'scalar','length':1}
            entries.append({'field':field,'key':None,'value':value})
    parts=[]; blobs={}; chunk=[]
    def flush():
        if not chunk:return
        raw=encode(chunk);name='state-%04d.json'%len(parts)
        blobs[name]=raw;parts.append({'name':name,'sha256':digest(raw),'bytes':len(raw),'entries':len(chunk)})
    for row in entries:
        if len(encode([row]))>SHARD_LIMIT: raise ValueError('Single entry exceeds shard limit')
        if chunk and len(encode(chunk+[row]))>SHARD_LIMIT:flush();chunk=[]
        chunk.append(row)
    flush()
    manifest={'schema_version':1,'layout':layout,'parts':parts,'state_sha256':digest(encode(state))}
    if len(encode(manifest))>SHARD_LIMIT:raise ValueError('Manifest exceeds shard limit')
    return manifest,blobs


def restore(manifest, blobs):
    if manifest.get('schema_version')!=1:raise ValueError('Unsupported store manifest')
    state={}; seen={}
    for field,row in manifest['layout'].items():
        kind=row['kind']
        if kind not in ('dict','list','scalar') or type(row['length']) is not int or row['length']<0:
            raise ValueError('Invalid layout')
        state[field]={} if kind=='dict' else [] if kind=='list' else None
        seen[field]=set()
    names=set()
    for part in manifest['parts']:
        name=part['name'];raw=blobs.get(name)
        if name in names or not isinstance(raw,bytes) or len(raw)>SHARD_LIMIT or len(raw)!=part['bytes'] or digest(raw)!=part['sha256']:
            raise ValueError('Corrupt, missing or duplicate shard')
        names.add(name);rows=decode(raw)
        if not isinstance(rows,list) or len(rows)!=part['entries']:raise ValueError('Invalid shard entries')
        for r in rows:
            field,key=r['field'],r['key']
            if field not in seen or key in seen[field]:raise ValueError('Duplicate/unknown state entry')
            seen[field].add(key);kind=manifest['layout'][field]['kind']
            if kind=='dict':
                if not isinstance(key,str):raise ValueError('Invalid map key')
                state[field][key]=r['value']
            elif kind=='list':
                if type(key) is not int or key!=len(state[field]):raise ValueError('Invalid list ordering')
                state[field].append(r['value'])
            else:
                if key is not None:raise ValueError('Invalid scalar key')
                state[field]=r['value']
    if any(len(seen[k])!=v['length'] for k,v in manifest['layout'].items()) or digest(encode(state))!=manifest['state_sha256']:
        raise ValueError('State reconstruction mismatch')
    return state


def _sync(path):
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(fd)
    finally:os.close(fd)


def _new(path,raw):
    with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())


def _read(root,name):
    path=root/name
    if path.is_symlink() or not path.is_file() or path.stat().st_size>STATE_LIMIT:
        raise ValueError('Missing, symlinked or oversized store file')
    return path.read_bytes()


def _replace(root,name,raw):
    with tempfile.NamedTemporaryFile(dir=root,prefix='.pointer-',delete=False) as f:
        tmp=Path(f.name);f.write(raw);f.flush();os.fsync(f.fileno())
    try:os.replace(tmp,root/name);_sync(root)
    finally:tmp.unlink(missing_ok=True)


@contextlib.contextmanager
def _lock(directory):
    root=Path(directory)
    if root.is_symlink():raise ValueError('Symlinked store root')
    root.mkdir(parents=True,exist_ok=True)
    fd=os.open(root/'WRITE.lock',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield root
    finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)


def _verify(root,pointer):
    p=decode(pointer)
    if (set(p)!={'schema_version','generation','manifest_sha256'} or p['schema_version']!=1
            or any(not re.fullmatch('[a-f0-9]{64}',str(p[k])) for k in ('generation','manifest_sha256'))):
        raise ValueError('Invalid store pointer')
    folder=root/p['generation']
    if folder.is_symlink() or not folder.is_dir():raise ValueError('Invalid generation folder')
    raw=_read(folder,'manifest.json')
    if len(raw)>SHARD_LIMIT or digest(raw)!=p['manifest_sha256']:raise ValueError('Manifest integrity mismatch')
    m=decode(raw);blobs={}
    for part in m['parts']:
        name=part['name']
        if not re.fullmatch(r'state-[0-9]{4}\.json',name):raise ValueError('Unsafe shard path')
        blobs[name]=_read(folder,name)
    state=restore(m,blobs)
    with gzip.GzipFile(fileobj=io.BytesIO(_read(folder,'legacy.json.gz'))) as g:legacy=g.read(STATE_LIMIT+1)
    if len(legacy)>STATE_LIMIT or digest(legacy)!=p['generation'] or decode(legacy)!=state:
        raise ValueError('Legacy reconstruction mismatch')
    return state,legacy


def read(directory):
    root=Path(directory)
    if root.is_symlink():raise ValueError('Symlinked store root')
    return _verify(root,_read(root,'CURRENT.json'))


def publish(legacy,directory,*,expected_generation,crash_hook=lambda stage:None):
    """CAS is mandatory: None means first migration; stale writers must reread."""
    if len(legacy)>STATE_LIMIT:raise ValueError('Oversized state')
    state=decode(legacy);m,blobs=partition(state);mraw=encode(m)
    generation=digest(legacy);pointer=encode({'schema_version':1,'generation':generation,'manifest_sha256':digest(mraw)})
    with _lock(directory) as root:
        old=_read(root,'CURRENT.json') if (root/'CURRENT.json').exists() else None
        if old is not None:_verify(root,old)
        current=decode(old)['generation'] if old else None
        if current!=expected_generation:raise ValueError('Stale discovery writer: compare-and-swap failed')
        destination=root/generation
        if not destination.exists():
            with tempfile.TemporaryDirectory(dir=root,prefix='.generation-') as tmp:
                stage=Path(tmp)/generation;stage.mkdir()
                for name,raw in blobs.items():_new(stage/name,raw)
                _new(stage/'manifest.json',mraw);_new(stage/'legacy.json.gz',gzip.compress(legacy,mtime=0))
                _sync(stage);os.replace(stage,destination);_sync(root)
        _verify(root,pointer);crash_hook('generation_verified_before_pointer')
        if old==pointer:return {'generation':generation,'changed':False,'shards':len(blobs)}
        if old is not None:_replace(root,'PREVIOUS.json',old)
        _replace(root,'CURRENT.json',pointer)
        return {'generation':generation,'changed':True,'shards':len(blobs)}


def rollback(directory,*,expected_pointer_sha256):
    """Explicit verified rollback, including corrupt CURRENT; no silent fallback."""
    with _lock(directory) as root:
        current=_read(root,'CURRENT.json')
        if digest(current)!=expected_pointer_sha256:raise ValueError('Rollback CAS conflict')
        previous=_read(root,'PREVIOUS.json');_verify(root,previous)
        evidence=root/('before-rollback-'+digest(current)+'.json')
        if not evidence.exists():_new(evidence,current);_sync(root)
        _replace(root,'CURRENT.json',previous)
        return decode(previous)['generation']


def recover_legacy(directory,target):
    _,raw=read(directory);target=Path(target)
    with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.recovery-',delete=False) as f:
        tmp=Path(f.name);f.write(raw);f.flush();os.fsync(f.fileno())
    try:os.link(tmp,target);_sync(target.parent)
    finally:tmp.unlink(missing_ok=True)
