"""Project directory + explicit activation above MemoryScheduler. No model calls."""
from __future__ import annotations
from contextlib import closing
from dataclasses import replace
import argparse
import json
from pathlib import Path
import re
import sqlite3
import uuid

from work_memory import WorkMemory, ConflictError
from memory_scheduler import MemoryScheduler, MODES

STATES = ('active', 'paused', 'completed', 'archived')


def text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\n' in value:
        raise ValueError(f'{name}: nonempty single-line text, max {limit} characters')
    return value.strip()


class ProjectMemory:
    """Use one directory per user. Sessions choose exactly one detailed project."""
    def __init__(self, directory='project_memory_data', companion_memory=None, *,
                 identity='', session='default'):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory/'projects.sqlite3'
        self.session = text(session, 'session', 100)
        self.companion, self.identity = companion_memory, identity
        # Dedicated empty backend: no project details can be loaded while idle.
        self.idle = WorkMemory(self.directory/'idle', project='idle')
        MemoryScheduler(self.idle, identity=identity, session=self.session)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS projects (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT UNIQUE NOT NULL,
                  purpose TEXT NOT NULL, summary TEXT NOT NULL, state TEXT NOT NULL,
                  directory TEXT NOT NULL, work_key TEXT NOT NULL,
                  fingerprint TEXT NOT NULL, version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS project_sessions (
                  session TEXT PRIMARY KEY, project_id TEXT, mode TEXT NOT NULL);
            ''')

    def _db(self):
        # closing is essential on Windows: a sqlite transaction context alone does not close.
        from contextlib import contextmanager
        @contextmanager
        def connection():
            with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                db.row_factory = sqlite3.Row
                yield db
        return connection()

    def projects(self):
        with self._db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY name_key')]

    def resolve(self, reference):
        reference = text(reference, 'project reference', 100)
        rows = [r for r in self.projects()
                if r['id'] == reference or r['name_key'] == reference.casefold()]
        if not rows:
            raise KeyError('Unknown project; create or select a registered project')
        if len(rows) != 1:
            raise ValueError('Ambiguous project name; use a unique full project ID')
        return rows[0]

    def work(self, reference):
        r = self.resolve(reference)
        return WorkMemory(r['directory'], project=r['work_key'])

    @staticmethod
    def _fingerprint(work):
        # Deleted tombstones contain no body and do not appear in list(). Any change
        # to current/archived working records invalidates the approved overview.
        return work.revision_token()

    def register(self, name, purpose, *, summary='尚未整理项目进展', state='active',
                 existing_directory=None, existing_project=None):
        name, purpose = text(name,'name',80), text(purpose,'purpose',120)
        summary = text(summary,'summary',160)
        if state not in STATES:
            raise ValueError('Invalid project state')
        if (existing_directory is None) != (existing_project is None):
            raise ValueError('Provide both existing_directory and existing_project')
        pid = uuid.uuid4().hex
        directory = (Path(existing_directory).resolve() if existing_directory is not None
                     else self.directory/'projects'/pid)
        if existing_directory is not None and not (directory/'work.sqlite3').is_file():
            raise ValueError('Existing work.sqlite3 not found; refusing silent empty import')
        key = text(existing_project,'existing_project',100) if existing_project is not None else pid
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM projects WHERE name_key=? OR (directory=? AND work_key=?)',
                          (name.casefold(),str(directory),key)).fetchone():
                raise ConflictError('Name or backing project already registered')
            memory = WorkMemory(directory,project=key)
            db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (pid,name,name.casefold(),purpose,summary,state,str(directory),key,
                        self._fingerprint(memory),1))
        return pid

    def update_overview(self, reference, summary, *, expected_version, state=None):
        summary = text(summary,'summary',160)
        row = self.resolve(reference)
        state = row['state'] if state is None else state
        if state not in STATES:
            raise ValueError('Invalid project state')
        fingerprint = self._fingerprint(self.work(row['id']))
        with self._db() as db:
            changed = db.execute('UPDATE projects SET summary=?,state=?,fingerprint=?,version=version+1 WHERE id=? AND version=?',
                                 (summary,state,fingerprint,row['id'],expected_version)).rowcount
            if not changed:
                raise ConflictError('Stale overview; refresh before updating')

    def current(self):
        with self._db() as db:
            row = db.execute('SELECT * FROM project_sessions WHERE session=?',(self.session,)).fetchone()
        return dict(row) if row else {'session':self.session,'project_id':None,'mode':'companion'}

    def enter(self, reference, *, mode='work'):
        row = self.resolve(reference)
        if row['state'] == 'archived':
            raise ValueError('Archived project: explicitly update its state before entering')
        if mode not in ('work','mixed'):
            raise ValueError('Project detail mode must be work or mixed')
        self._save_session(row['id'],mode)
        return row['id']

    def _save_session(self, pid, mode):
        with self._db() as db:
            db.execute('INSERT INTO project_sessions VALUES(?,?,?) ON CONFLICT(session) DO UPDATE SET project_id=excluded.project_id,mode=excluded.mode',
                       (self.session,pid,mode))

    def exit(self):
        self._save_session(None,'companion')

    def _command(self, message, mode):
        if not isinstance(message,str):
            raise ValueError('message must be text')
        if mode is not None and mode not in MODES:
            raise ValueError('Invalid mode')
        command = message.strip().rstrip('。！!')
        # Full-match canonical commands only; ambiguous natural language never
        # silently switches the selected project's writable destination.
        match = re.fullmatch(r'(?:进入项目|切换项目|切换到项目)\s+([^\n]+)',command)
        if match:
            self.enter(match[1])
        elif command in ('退出工作','退出项目','进入陪伴模式','先不工作，陪我聊聊'):
            self.exit()
        elif command in ('进入工作模式','进入混合模式'):
            selected = self.current()['project_id']
            if not selected:
                raise ValueError('Select a project first: 进入项目 项目名称')
            self.enter(selected,mode='mixed' if command=='进入混合模式' else 'work')
        if mode is not None:
            if mode not in MODES:
                raise ValueError('Invalid mode')
            if mode == 'companion':
                self.exit()
            elif not self.current()['project_id']:
                raise ValueError('Select a project first')
            else:
                self.enter(self.current()['project_id'],mode=mode)

    def overview_context(self, message='', *, all_projects=False, char_budget=480):
        if not isinstance(message,str) or not isinstance(char_budget,int) or isinstance(char_budget,bool) or char_budget < 0:
            raise ValueError('Invalid overview request')
        lines=[]
        header='【项目概况，仅为粗略印象；具体进度以进入项目后的记录为准】\n'
        for row in self.projects():
            if not all_projects and row['name'].casefold() not in message.casefold():
                continue
            fresh = self._fingerprint(self.work(row['id'])) == row['fingerprint']
            # Never quote stale summaries: might mention a deleted or replaced plan.
            detail = row['summary'] if fresh else '详细记录已有变化，旧进展摘要停用；需进入项目核实'
            state = row['state'] if fresh else '状态待核实'
            line = f"- {row['name']}：{row['purpose']}；{state}；{detail}\n"
            if len(header)+sum(map(len,lines))+len(line) <= char_budget:
                lines.append(line)
        return header+''.join(lines) if lines else ''

    def build_context(self, message, *, mode=None, char_budget=2200, recall=None, visible_context=None, include_facts=True):
        if isinstance(char_budget,bool) or not isinstance(char_budget,int) or char_budget < 1024:
            raise ValueError('char_budget must be >=1024')
        if recall is not None and not isinstance(recall,bool):
            raise ValueError('recall must be bool or None')
        if not isinstance(include_facts,bool):
            raise ValueError('include_facts must be bool')
        self._command(message,mode)
        current=self.current()
        pid=current['project_id']
        if pid and self.resolve(pid)['state']=='archived':
            self.exit()
            current=self.current()
            pid=None
        memory=self.work(pid) if pid else self.idle
        scheduler=MemoryScheduler(memory,self.companion,identity=self.identity,session=self.session)
        # No implicit work keyword is allowed to open details while no project is selected.
        packet=scheduler.build_context(message,mode=current['mode'],char_budget=char_budget,
                                       recall=recall,allow_work=pid is not None,include_facts=include_facts)
        overview=''
        if not pid:
            overview=self.overview_context(message,all_projects=message.strip().rstrip('。！!')=='项目列表',
                                           char_budget=min(480,char_budget-len(packet.text)))
        result=packet.text+overview
        return replace(packet,text=result,char_count=len(result),unchanged=result==visible_context,
                       reason='project:'+pid if pid else 'no_active_project')

    def active_work(self):
        pid=self.current()['project_id']
        if not pid or self.resolve(pid)['state']=='archived':
            raise ValueError('No active project; refuse implicit writes')
        return self.work(pid)

    def export_handoff(self, path, *, char_budget=6000, include_identity=False):
        work=self.active_work()
        row=self.resolve(self.current()['project_id'])
        title=f"项目名称：{row['name']}\n项目目录 ID：{row['id']}\n\n"
        scheduler=MemoryScheduler(work,self.companion,identity=self.identity,session=self.session)
        scheduler.set_mode(self.current()['mode'])
        packet=scheduler.export_handoff(path,char_budget=char_budget-len(title),include_identity=include_identity)
        target=Path(path)
        target.write_text(title+target.read_text(encoding='utf-8'),encoding='utf-8')
        return packet


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir',default='project_memory_data')
    parser.add_argument('--session',default='default')
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('create'); create.add_argument('name'); create.add_argument('purpose')
    sub.add_parser('list')
    enter=sub.add_parser('enter'); enter.add_argument('project')
    sub.add_parser('exit')
    sub.add_parser('current')
    context=sub.add_parser('context'); context.add_argument('message'); context.add_argument('--budget',type=int,default=2200)
    add=sub.add_parser('add'); add.add_argument('kind'); add.add_argument('content')
    overview=sub.add_parser('overview'); overview.add_argument('project'); overview.add_argument('summary'); overview.add_argument('--version',required=True,type=int); overview.add_argument('--state',choices=STATES)
    handoff=sub.add_parser('handoff'); handoff.add_argument('path')
    args=parser.parse_args()
    manager=ProjectMemory(args.dir,session=args.session)
    if args.command=='create': print(manager.register(args.name,args.purpose))
    elif args.command=='list': print(json.dumps(manager.projects(),ensure_ascii=False,indent=2))
    elif args.command=='current': print(json.dumps(manager.current(),ensure_ascii=False))
    elif args.command=='enter': print(manager.enter(args.project))
    elif args.command=='exit': manager.exit()
    elif args.command=='context':
        packet=manager.build_context(args.message,char_budget=args.budget)
        print(packet.text)
        if packet.required_omitted: raise SystemExit('Important work requirements omitted; increase budget')
    elif args.command=='add': print(manager.active_work().add(args.kind,args.content))
    elif args.command=='overview': manager.update_overview(args.project,args.summary,expected_version=args.version,state=args.state)
    elif args.command=='handoff': manager.export_handoff(args.path)


if __name__=='__main__':
    main()
