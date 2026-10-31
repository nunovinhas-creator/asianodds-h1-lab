"""Fail closed if a previously certified FT disappears or changes."""
import argparse
import json
from pathlib import Path
from h1lab.lab_ft_final_guard import snapshot_file, verify_files

FT = Path("data/lab/ft-ledger.json")

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("freeze","verify"))
    p.add_argument("--root",type=Path,default=Path.cwd())
    p.add_argument("--baseline",type=Path,required=True)
    a=p.parse_args(argv)
    source=a.root/FT
    if a.mode=="freeze":
        result=snapshot_file(source,a.baseline)
    else:
        result=verify_files(a.baseline,source)
    print("FT_IMMUTABLE_GUARD",json.dumps(
        {k:v for k,v in result.items() if k!="final_records"},
        sort_keys=True))
    return result

if __name__=="__main__":
    main()
