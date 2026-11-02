"""python -m yuyi_emotion --help"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time
import sqlite3
import sys

from . import Config, EmotionEvent, EmotionStore, EmotionAtlas


def timestamp(value):
    if value is None:
        return time.time()
    try:
        return float(value)
    except ValueError:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('ISO timestamps need a timezone')
        return parsed.timestamp()


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='余忆独立情绪模块：三层状态、三维坐标、可回放事件。')
    parser.add_argument('--db', default='data/emotion.sqlite3')
    parser.add_argument('--assistant', default='companion')
    parser.add_argument('--config', help='JSON Config file; use a new DB when changing parameters')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    status = commands.add_parser('status'); status.add_argument('--at'); status.add_argument('--budget', type=int, default=500)
    event = commands.add_parser('event'); event.add_argument('file')
    audit = commands.add_parser('audit'); audit.add_argument('--limit', type=int, default=20)
    commands.add_parser('changes')
    retract = commands.add_parser('retract'); retract.add_argument('event_id'); retract.add_argument('--reason', choices=('correction','user_request','invalid_evidence'), default='correction')
    restore = commands.add_parser('restore'); restore.add_argument('event_id')
    replay = commands.add_parser('replay'); replay.add_argument('--at')
    backup = commands.add_parser('backup'); backup.add_argument('destination')
    atlas = commands.add_parser('atlas'); atlas.add_argument('--resolution',type=int,default=9)
    args = parser.parse_args()
    try:
        if args.command=='atlas':
            print(json.dumps(EmotionAtlas(args.resolution).export(),ensure_ascii=False))
            return
        cfg=Config.from_dict(json.loads(Path(args.config).read_text(encoding='utf-8-sig'))) if args.config else Config()
        store=EmotionStore(args.db,assistant_id=args.assistant,config=cfg)
        if args.command=='init': result={'ready':True,'assistant_id':args.assistant,'memory_modified':False}
        elif args.command=='status': result=store.state(timestamp(args.at),char_budget=args.budget)
        elif args.command=='event':
            data=json.loads(Path(args.file).read_text(encoding='utf-8-sig'))
            if isinstance(data.get('timestamp'),str): data['timestamp']=timestamp(data['timestamp'])
            result=store.submit(EmotionEvent.from_dict(data))
        elif args.command=='audit': result=store.audit(limit=args.limit)
        elif args.command=='changes': result=store.changes()
        elif args.command in ('retract','restore'):
            result={'changed':store.set_active(args.event_id,args.command=='restore',reason='reviewed_restore' if args.command=='restore' else args.reason)}
        elif args.command=='replay': result=store.replay(timestamp(args.at))
        elif args.command=='backup': store.backup(args.destination); result={'backup':args.destination}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,OSError,TypeError,sqlite3.Error) as error:
        parser.exit(2, f'{type(error).__name__}: {error}\n')


if __name__=='__main__':
    main()
