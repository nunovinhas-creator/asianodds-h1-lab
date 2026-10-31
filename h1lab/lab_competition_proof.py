"""Review-only competition identity registry. Not imported by FT certification.

Names and scores are never identity keys. Source captures plus an explicit
review decision are mandatory; no production binding is inferred or enabled.
"""
import copy
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

HOSTS = {'api_football': 'v3.football.api-sports.io', 'goal': 'api.goal-api.com',
         'bsd': 'sports.bzzoiro.com', 'openfoot': 'openfootapi.com',
         'sportscore': 'sportscore.com', 'espn': 'site.api.espn.com',
         'thesportsdb': 'www.thesportsdb.com'}
CONTEXT = ('country_code', 'season', 'division', 'gender', 'age', 'squad')


def encode(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(x): return hashlib.sha256(encode(x)).hexdigest()


def empty(): return {'schema_version': 1, 'revision': 0, 'bindings': {}}


def _endpoint(value):
    if not isinstance(value, dict) or value.get('provider') not in HOSTS:
        raise ValueError('Unknown official provider')
    if (not isinstance(value.get('competition_id'), str) or not value['competition_id'].strip()
            or any(not isinstance(value.get(k), str) or not value[k].strip() for k in CONTEXT)):
        raise ValueError('Missing explicit country/season/division/gender/age/squad context')
    if len(value['country_code']) != 2 or not value['country_code'].isupper():
        raise ValueError('Country must be an explicit ISO code; unresolved multinational scopes stay blocked')
    if value['gender'] not in ('MEN', 'WOMEN', 'MIXED') or value['squad'] not in ('FIRST', 'B', 'RESERVES'):
        raise ValueError('Unresolved gender/squad category')
    if value['age'] != 'SENIOR' and not (value['age'].startswith('U') and value['age'][1:].isdigit()):
        raise ValueError('Unresolved age category')
    return {k: value[k] for k in ('provider', 'competition_id', *CONTEXT)}


def _capture(capture, endpoint):
    """Validate pinned source document and exact structured identity claims.

    This checks the review package, not the truth of an unseen web page.
    A reviewer must verify provenance and claims against official documents.
    """
    u = urlsplit(capture.get('url', ''))
    if (u.scheme != 'https' or u.hostname != HOSTS[endpoint['provider']]
            or u.username or u.password or u.query or u.fragment or u.port not in (None, 443)):
        raise ValueError('Official public evidence URL required without credentials/query')
    document = capture.get('document')
    if not isinstance(document, dict) or capture.get('document_sha256') != digest(document):
        raise ValueError('Unpinned or corrupt evidence document')
    if document.get('identity') != endpoint:
        raise ValueError('Document does not explicitly support the full competition context')
    at = datetime.fromisoformat(capture['captured_at'].replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('Evidence time requires timezone')
    fixtures = document.get('fixtures')
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError('Independent fixture identity witnesses required')
    for f in fixtures:
        if (not isinstance(f, dict) or any(not isinstance(f.get(k), str) or not f[k]
                for k in ('fixture_id', 'home_team_id', 'away_team_id', 'kickoff_utc'))
                or f['home_team_id'] == f['away_team_id']):
            raise ValueError('Official fixture/team IDs and orientation required')
    return at.astimezone(timezone.utc)


def prepare(proposal):
    """Create a PROPOSED record; can never produce a reviewed/active binding."""
    left, right = (_endpoint(proposal[k]) for k in ('left', 'right'))
    if left['provider'] == right['provider'] or any(left[k] != right[k] for k in CONTEXT):
        raise ValueError('Independent providers and equal explicit context required')
    captures = proposal.get('captures', [])
    if len(captures) != 2: raise ValueError('Two independent official captures required')
    stamps = [_capture(c, e) for c, e in zip(captures, (left, right))]
    if any(t > datetime.now(timezone.utc) for t in stamps): raise ValueError('Future source evidence')
    witnesses = proposal.get('fixture_crosswalk', [])
    if len(witnesses) < 2: raise ValueError('At least two independently reviewed fixture witnesses required')
    used_left, used_right = set(), set()
    team_map, reverse_team_map = {}, {}
    for w in witnesses:
        if (set(w) != {'left_fixture_id', 'right_fixture_id', 'team_identity_evidence'}
                or not isinstance(w['team_identity_evidence'], dict)):
            raise ValueError('Explicit independent team identity evidence required')
        a = [f for f in captures[0]['document']['fixtures'] if f['fixture_id'] == w['left_fixture_id']]
        b = [f for f in captures[1]['document']['fixtures'] if f['fixture_id'] == w['right_fixture_id']]
        if len(a) != 1 or len(b) != 1 or a[0]['kickoff_utc'] != b[0]['kickoff_utc']:
            raise ValueError('Ambiguous fixture witness or kickoff mismatch')
        proof = w['team_identity_evidence']
        # Names/score agreement and a boolean are insufficient. The package
        # must pin a separately reviewed official cross-provider team ID map.
        if (proof.get('kind') != 'OFFICIAL_TEAM_ID_CROSSWALK'
                or not isinstance(proof.get('document'), dict)
                or proof.get('sha256') != digest(proof['document'])
                or proof['document'].get('left_team_ids') != [a[0]['home_team_id'], a[0]['away_team_id']]
                or proof['document'].get('right_team_ids') != [b[0]['home_team_id'], b[0]['away_team_id']]
                or urlsplit(proof.get('source_url', '')).scheme != 'https'
                or urlsplit(proof.get('source_url', '')).hostname not in HOSTS.values()
                or urlsplit(proof.get('source_url', '')).query
                or urlsplit(proof.get('source_url', '')).username):
            raise ValueError('No pinned independent team ID evidence')
        if w['left_fixture_id'] in used_left or w['right_fixture_id'] in used_right:
            raise ValueError('Repeated fixture witness is not independent evidence')
        used_left.add(w['left_fixture_id']);used_right.add(w['right_fixture_id'])
        for a_id,b_id in zip(proof['document']['left_team_ids'],proof['document']['right_team_ids']):
            if team_map.get(a_id,b_id)!=b_id or reverse_team_map.get(b_id,a_id)!=a_id:
                raise ValueError('Contradictory team identity crosswalk')
            team_map[a_id]=b_id;reverse_team_map[b_id]=a_id
    content = copy.deepcopy(proposal)
    return {'binding_id': digest({'left': left, 'right': right}), 'state': 'PROPOSED',
            'left': left, 'right': right, 'evidence_sha256': digest(content), 'proposal': content}


def review(registry, proposed, decision, *, expected_revision):
    """Explicit offline review, never automatic promotion or productive use."""
    if registry.get('schema_version') != 1 or registry.get('revision') != expected_revision:
        raise ValueError('Registry revision conflict')
    check = prepare(proposed['proposal'])
    if check != proposed: raise ValueError('Proposal changed after preparation')
    if (decision.get('decision') != 'APPROVE' or not decision.get('reviewer')
            or decision.get('evidence_sha256') != proposed['evidence_sha256']
            or not decision.get('rationale') or not decision.get('reviewed_at')):
        raise ValueError('Explicit pinned human review decision required')
    reviewed_at=datetime.fromisoformat(decision['reviewed_at'].replace('Z','+00:00'))
    captured=[datetime.fromisoformat(c['captured_at'].replace('Z','+00:00')) for c in proposed['proposal']['captures']]
    if reviewed_at.tzinfo is None or reviewed_at>datetime.now(timezone.utc) or any(reviewed_at<t for t in captured):
        raise ValueError('Invalid review chronology')
    out = copy.deepcopy(registry)
    for old in out['bindings'].values():
        if old['binding_id'] == proposed['binding_id']:
            raise ValueError('Immutable binding already exists')
        for a, b in ((proposed['left'], proposed['right']), (proposed['right'], proposed['left'])):
            for x, y in ((old['left'], old['right']), (old['right'], old['left'])):
                if x == a and y['provider'] == b['provider'] and y != b:
                    raise ValueError('Conflicting competition binding requires explicit review')
    out['bindings'][proposed['binding_id']] = {**copy.deepcopy(proposed),
        'state': 'REVIEWED_OFFLINE_NOT_ACTIVATED', 'review': copy.deepcopy(decision)}
    out['revision'] += 1
    return out


def save(path, registry, *, expected_file_sha256):
    """Durable offline registry with file CAS, lock, fsync and atomic replace."""
    import fcntl
    import os
    import tempfile
    from pathlib import Path
    path=Path(path)
    if path.is_symlink(): raise ValueError('Symlinked registry')
    if registry.get('schema_version')!=1 or not isinstance(registry.get('bindings'),dict):
        raise ValueError('Invalid registry')
    for key,row in registry['bindings'].items():
        proposal=prepare(row['proposal'])
        if (key!=proposal['binding_id'] or row.get('state')!='REVIEWED_OFFLINE_NOT_ACTIVATED'
                or any(row.get(k)!=v for k,v in proposal.items() if k!='state')
                or row.get('review',{}).get('evidence_sha256')!=proposal['evidence_sha256']):
            raise ValueError('Corrupt or unreviewed registry record')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path.with_suffix('.lock'),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        old=path.read_bytes() if path.exists() else None
        if (hashlib.sha256(old).hexdigest() if old is not None else None)!=expected_file_sha256:
            raise ValueError('Registry file CAS conflict')
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.registry-',delete=False) as f:
            tmp=Path(f.name);f.write(encode(registry)+b'\n');f.flush();os.fsync(f.fileno())
        try:
            os.replace(tmp,path)
            directory=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:tmp.unlink(missing_ok=True)
    finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
