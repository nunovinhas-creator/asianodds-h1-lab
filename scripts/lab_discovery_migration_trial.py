"""Offline migration/recovery drill; never writes productive data/docs paths."""
import argparse
import json
from pathlib import Path
from h1lab.lab_discovery_snapshot_trial import publish_trial,read_snapshot,rollback_trial,recover_legacy_file

ROOT=Path(__file__).resolve().parents[1]


def safe_trial_path(path):
    value=path.resolve()
    if (value in (ROOT,Path('/'),Path.home()) or any(value.is_relative_to(ROOT/p)
            for p in ('data','docs','h1lab','.github'))):
        raise ValueError('Trial output must be outside productive paths')
    return value


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['migrate','verify','rollback','recover'])
    p.add_argument('--source',type=Path,default=ROOT/'data/lab/discovery-state.json')
    p.add_argument('--trial-dir',type=Path,required=True)
    p.add_argument('--recover-output',type=Path)
    args=p.parse_args(argv);root=safe_trial_path(args.trial_dir)
    if args.mode=='migrate':result=publish_trial(args.source.read_bytes(),root)
    elif args.mode=='rollback':result=rollback_trial(root)
    else:
        state,legacy=read_snapshot(root)
        result={'verified':True,'patterns':len(state['patterns']),'legacy_bytes':len(legacy)}
        if args.mode=='recover':
            if args.recover_output is None:raise ValueError('Recovery requires a new output path')
            target=safe_trial_path(args.recover_output)
            # Exclusive create: an existing legacy or user file is never overwritten.
            recover_legacy_file(root,target)
    print('DISCOVERY_OFFLINE_TRIAL',json.dumps(result,sort_keys=True));return result


if __name__=='__main__':main()
