import argparse
from dataclasses import fields
import json
from pathlib import Path
import sqlite3
import sys
from . import SelfModel,Evidence,Proposal,trial_report


def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='余忆自我模型：独立观察试运行。')
    p.add_argument('--db',default='data/self.sqlite3');p.add_argument('--assistant',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--identity');init.add_argument('--actor',default='host')
    for name in ('evidence','propose'):
        cmd=sub.add_parser(name);cmd.add_argument('file')
        if name=='propose':cmd.add_argument('--author',required=True)
    sub.add_parser('show');sub.add_parser('history')
    review=sub.add_parser('review');review.add_argument('id');review.add_argument('decision',choices=('approve','reject','restore'))
    review.add_argument('--version',type=int,required=True);review.add_argument('--reviewer',required=True)
    retract=sub.add_parser('retract-evidence');retract.add_argument('id');retract.add_argument('--actor',required=True);retract.add_argument('--reason',required=True)
    ref=sub.add_parser('reference');ref.add_argument('--scope',required=True);ref.add_argument('--enable',action='store_true');ref.add_argument('--budget',type=int,default=600)
    report=sub.add_parser('report');report.add_argument('--out')
    args=p.parse_args()
    try:
        store=SelfModel(args.db,assistant_id=args.assistant)
        if args.command=='init':
            if args.identity:store.seed_identity(json.loads(Path(args.identity).read_text(encoding='utf-8-sig')),actor=args.actor)
            result={'ready':True,'mode':'observe'}
        elif args.command=='evidence':result=store.register(Evidence(**json.loads(Path(args.file).read_text(encoding='utf-8-sig'))))
        elif args.command=='propose':result={'id':store.propose(Proposal(**json.loads(Path(args.file).read_text(encoding='utf-8-sig'))),author=args.author)}
        elif args.command=='show':result=store.snapshot()
        elif args.command=='history':result=store.history()
        elif args.command=='review':store.review(args.id,args.decision,reviewer=args.reviewer,expected_version=args.version);result={'reviewed':True,'still_default_observe':True}
        elif args.command=='retract-evidence':result={'changed':store.retract_evidence(args.id,actor=args.actor,reason=args.reason)}
        elif args.command=='reference':result=store.reference(scope=args.scope,enabled=args.enable,char_budget=args.budget)
        elif args.command=='report':
            result=trial_report(store)
            if args.out:Path(args.out).write_text(result,encoding='utf-8')
            print(result);return
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error) as error:p.exit(2,f'{type(error).__name__}: {error}\n')


if __name__=='__main__':main()
