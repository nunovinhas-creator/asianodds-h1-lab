"""Export complete individual FT diagnosis and cohort metrics without network."""
import argparse,csv,json,subprocess
from pathlib import Path
from h1lab.lab_ft_recovery_audit import audit_pending


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline-ref')
    args=p.parse_args(argv);root=args.root
    def read(path):return json.loads((root/path).read_text())
    baseline=(json.loads(subprocess.check_output(['git','show',args.baseline_ref+':data/lab/ft-ledger.json'],cwd=root))
              if args.baseline_ref else None)
    baseline_keys=({g['match_key'] for g in json.loads(subprocess.check_output(
        ['git','show',args.baseline_ref+':docs/lab/ft-backlog.json'],cwd=root))['overdue_games']}
        if args.baseline_ref else None)
    report=audit_pending(read('data/lab/ft-ledger.json'),read('docs/lab/ft-backlog.json'),
        read('data/state.json').get('alerts',[]),read('data/lab/ft-api-audit.json'),baseline=baseline,baseline_pending_keys=baseline_keys)
    report['source_sha']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(",",":"))+'\n')
    with args.output.with_suffix('.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=[k for k in report['games'][0] if k!='provider_evidence'] if report['games'] else ['match_key']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        writer.writerows({k:v for k,v in row.items() if k in fields} for row in report['games'])
    print('FT_RECOVERY_AUDIT',len(report['games']),report['primary_causes_exclusive'])
    return report

if __name__=='__main__':main()
