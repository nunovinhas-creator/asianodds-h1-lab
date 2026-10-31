"""Offline immutable segmented snapshots with atomic pointer and legacy recovery.

No production loader imports this module. Never silently fall back on corruption.
"""
import gzip
import io
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from .lab_discovery_partition_trial import partition, restore, encode


def digest(raw):return hashlib.sha256(raw).hexdigest()


def _decode(raw):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('Duplicate JSON key')
            out[k]=v
        return out
    def invalid(v):raise ValueError('Nonfinite JSON value')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def _sync_dir(path):
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(fd)
    finally:os.close(fd)


def _write_new(path,raw):
    with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())


def _replace_pointer(root,name,raw):
    with tempfile.NamedTemporaryFile(dir=root,prefix='.pointer-',delete=False) as f:
        tmp=Path(f.name);f.write(raw);f.flush();os.fsync(f.fileno())
    try:os.replace(tmp,root/name);_sync_dir(root)
    finally:tmp.unlink(missing_ok=True)


def _read_file(root,name):
    p=root/name
    if p.is_symlink() or not p.is_file():raise ValueError('Missing or symlinked snapshot member')
    if p.stat().st_size>20000000:raise ValueError('Oversized snapshot member')
    return p.read_bytes()


def _verify_pointer(root,raw):
    p=_decode(raw)
    if (not isinstance(p,dict) or p.get('schema_version')!=1
            or not re.fullmatch(r'[0-9a-f]{64}',str(p.get('generation','')))
            or not re.fullmatch(r'[0-9a-f]{64}',str(p.get('manifest_sha256','')))):
        raise ValueError('Invalid snapshot pointer')
    folder=root/p['generation']
    if folder.is_symlink() or not folder.is_dir():raise ValueError('Missing generation')
    manifest_raw=_read_file(folder,'manifest.json')
    if len(manifest_raw)>256000 or digest(manifest_raw)!=p['manifest_sha256']:
        raise ValueError('Manifest checksum mismatch')
    manifest=_decode(manifest_raw);shards={}
    for part in manifest['parts']:
        name=part['name']
        if not re.fullmatch(r'patterns-[0-9]{4}\.json',name) or name in shards:
            raise ValueError('Invalid or duplicate shard name')
        shards[name]=_read_file(folder,name)
        if len(shards[name])>256000:raise ValueError('Oversized shard')
    state=restore(manifest,shards)
    with gzip.GzipFile(fileobj=io.BytesIO(_read_file(folder,'legacy.json.gz'))) as backup:
        legacy=backup.read(20000001)
    if len(legacy)>20000000:raise ValueError('Oversized legacy backup')
    if digest(legacy)!=p['generation'] or _decode(legacy)!=state:
        raise ValueError('Legacy recovery mismatch')
    return state,legacy


def read_snapshot(directory):
    root=Path(directory)
    return _verify_pointer(root,_read_file(root,'CURRENT.json'))


def publish_trial(legacy,directory,*,crash_hook=lambda stage:None):
    if len(legacy)>20000000:raise ValueError('Oversized legacy input')
    state=_decode(legacy);manifest,shards=partition(state)
    manifest_raw=encode(manifest);generation=digest(legacy)
    pointer=encode({'schema_version':1,'generation':generation,
                    'manifest_sha256':digest(manifest_raw)})
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    current=_read_file(root,'CURRENT.json') if (root/'CURRENT.json').exists() else None
    if current is not None:_verify_pointer(root,current)
    destination=root/generation
    if not destination.exists():
        with tempfile.TemporaryDirectory(dir=root,prefix='.generation-') as tmp:
            stage=Path(tmp)/generation;stage.mkdir()
            for name,raw in shards.items():_write_new(stage/name,raw)
            _write_new(stage/'manifest.json',manifest_raw)
            _write_new(stage/'legacy.json.gz',gzip.compress(legacy,mtime=0))
            _sync_dir(stage)
            os.replace(stage,destination);_sync_dir(root)
    _verify_pointer(root,pointer)
    crash_hook('generation_verified_before_pointer')
    if current==pointer:return {'generation':generation,'changed':False,'shards':len(shards)}
    if current is not None:_replace_pointer(root,'PREVIOUS.json',current)
    _replace_pointer(root,'CURRENT.json',pointer)
    return {'generation':generation,'changed':True,'shards':len(shards)}


def rollback_trial(directory):
    root=Path(directory)
    old=_read_file(root,'PREVIOUS.json');_verify_pointer(root,old)
    # Explicit recovery may restore a verified PREVIOUS even when CURRENT is
    # corrupt. Normal readers never perform this rollback automatically.
    current=_read_file(root,'CURRENT.json')
    evidence=root/('before-rollback-'+digest(current)+'.json')
    if not evidence.exists():_write_new(evidence,current)
    _replace_pointer(root,'CURRENT.json',old)
    return {'generation':_decode(old)['generation'],'legacy_bytes':len(read_snapshot(root)[1])}


def recover_legacy_file(directory,target):
    _,legacy=read_snapshot(directory);target=Path(target)
    with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.recovery-',delete=False) as f:
        tmp=Path(f.name);f.write(legacy);f.flush();os.fsync(f.fileno())
    try:
        os.link(tmp,target)  # atomic and exclusive; never replace a user file
        _sync_dir(target.parent)
    finally:tmp.unlink(missing_ok=True)
