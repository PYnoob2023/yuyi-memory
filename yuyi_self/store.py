"""Independent SQLite journal. Default observing cannot change a persona or prompt."""
from contextlib import closing,contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import time
import uuid
from .model import Config,Evidence,Proposal,text


class SelfModel:
    def __init__(self,path,*,assistant_id,config=None):
        self.path=Path(path);self.assistant_id=text(assistant_id,'assistant_id');self.config=config or Config()
        if not isinstance(self.config,Config):raise ValueError('Expected Config')
        if self.path.exists():
            with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)) as probe:
                tables={r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables:
                    try:row=probe.execute('SELECT version,owner,config_hash FROM self_meta WHERE id=1').fetchone()
                    except sqlite3.Error as e:raise ValueError('Foreign database; keep memory/emotion files separate') from e
                    if row!=(1,self.assistant_id,self.config.fingerprint()):raise ValueError('Schema, assistant or config mismatch')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._db(True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS self_meta(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER,owner TEXT,config_hash TEXT,identity TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,occurrence_key TEXT UNIQUE,payload TEXT,active INTEGER DEFAULT 1)')
            db.execute('CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY,claim_key TEXT,category TEXT,scope TEXT,statement TEXT,status TEXT,version INTEGER,created REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS links(claim_id TEXT,evidence_id TEXT,stance TEXT,PRIMARY KEY(claim_id,evidence_id))')
            db.execute('CREATE TABLE IF NOT EXISTS journal(seq INTEGER PRIMARY KEY AUTOINCREMENT,at REAL,action TEXT,target TEXT,actor TEXT,detail TEXT)')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_key ON claims(claim_key) WHERE status='active'")
            db.execute('INSERT OR IGNORE INTO self_meta VALUES(1,1,?,?,?)',(self.assistant_id,self.config.fingerprint(),'{}'))

    @contextmanager
    def _db(self,write=False):
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db;db.commit()
        except Exception:db.rollback();raise
        finally:db.close()

    def _log(self,db,action,target,actor,detail):
        db.execute('INSERT INTO journal(at,action,target,actor,detail) VALUES(?,?,?,?,?)',
                   (time.time(),action,target,actor,json.dumps(detail,ensure_ascii=False)))

    def seed_identity(self,identity,*,actor):
        """Explicit host-owned initial identity. Reflections cannot call this via payload."""
        text(actor,'actor')
        if not isinstance(identity,dict) or set(identity)-{'name','role'} or not identity:
            raise ValueError('Identity accepts only name and role')
        for key,value in identity.items():text(value,key,150)
        with self._db(True) as db:
            old=json.loads(db.execute('SELECT identity FROM self_meta').fetchone()[0])
            if old:raise ValueError('Identity already initialized; no automatic identity rewrite')
            db.execute('UPDATE self_meta SET identity=?',(json.dumps(identity,ensure_ascii=False),))
            self._log(db,'seed_identity',self.assistant_id,actor,identity)

    def register(self,evidence):
        if not isinstance(evidence,Evidence):raise ValueError('Expected Evidence')
        with self._db(True) as db:
            old=db.execute('SELECT id,payload FROM evidence WHERE id=? OR occurrence_key=?',(evidence.id,evidence.occurrence_key())).fetchone()
            if old:
                if old['id']==evidence.id and json.loads(old['payload'])!=asdict(evidence):raise ValueError('Evidence ID collision with changed metadata')
                return {'accepted':False,'canonical_id':old['id'],'reason':'same_experience'}
            db.execute('INSERT INTO evidence(id,occurrence_key,payload) VALUES(?,?,?)',
                       (evidence.id,evidence.occurrence_key(),json.dumps(asdict(evidence))))
            self._log(db,'evidence',evidence.id,'host',{'kind':evidence.kind,'origin':evidence.origin})
            return {'accepted':True,'canonical_id':evidence.id}

    def _check_links(self,db,proposal):
        for eid in (*proposal.support_ids,*proposal.challenge_ids):
            row=db.execute('SELECT payload,active FROM evidence WHERE id=?',(eid,)).fetchone()
            if not row or not row['active']:raise ValueError('Unknown or retracted evidence: '+eid)
            e=json.loads(row['payload'])
            if e['scope']!=proposal.scope:raise ValueError('Evidence scope mismatch')

    def propose(self,proposal,*,author):
        if not isinstance(proposal,Proposal):raise ValueError('Expected Proposal')
        text(author,'author')
        with self._db(True) as db:
            self._check_links(db,proposal)
            family=db.execute('SELECT scope,category FROM claims WHERE claim_key=? LIMIT 1',(proposal.key,)).fetchone()
            if family and (family['scope']!=proposal.scope or family['category']!=proposal.category):
                raise ValueError('A stable key cannot silently change scope/category')
            old=db.execute('SELECT * FROM claims WHERE claim_key=? AND statement=? AND scope=? ORDER BY created LIMIT 1',
                           (proposal.key,proposal.statement,proposal.scope)).fetchone()
            if old:
                cid=old['id']
                if old['category']!=proposal.category:raise ValueError('Existing claim category mismatch')
                if old['status'] in ('rejected','retired'):return cid
            else:
                cid=uuid.uuid4().hex
                db.execute('INSERT INTO claims VALUES(?,?,?,?,?,?,?,?)',
                           (cid,proposal.key,proposal.category,proposal.scope,proposal.statement,'draft',1,time.time()))
            changed=False
            for stance,ids in [('support',proposal.support_ids),('challenge',proposal.challenge_ids)]:
                for eid in ids:
                    existing=db.execute('SELECT stance FROM links WHERE claim_id=? AND evidence_id=?',(cid,eid)).fetchone()
                    if existing and existing[0]!=stance:raise ValueError('A source stance cannot be silently changed')
                    changed=bool(db.execute('INSERT OR IGNORE INTO links VALUES(?,?,?)',(cid,eid,stance)).rowcount) or changed
            if old and changed:
                db.execute('UPDATE claims SET version=version+1 WHERE id=?',(cid,))
            if old and old['status']=='active' and self._eligibility(db,cid)['challenges']:
                db.execute("UPDATE claims SET status='disputed' WHERE id=?",(cid,))
            if not old or changed:self._log(db,'propose',cid,author,{'key':proposal.key})
            return cid

    def _eligibility(self,db,cid):
        support=[];challenges=[];noncounting=[]
        for row in db.execute('SELECT e.id,e.payload,e.active,l.stance FROM links l JOIN evidence e ON e.id=l.evidence_id WHERE l.claim_id=?',(cid,)):
            e=json.loads(row['payload'])
            valid=row['active'] and e['verified'] and e['origin']=='experienced' and e['kind'] in ('verified_outcome','user_feedback')
            if valid:(support if row['stance']=='support' else challenges).append(e)
            else:noncounting.append(row['id'])
        span=(max(e['occurred_at'] for e in support)-min(e['occurred_at'] for e in support))/3600 if support else 0.
        return {'eligible':len(support)>=self.config.min_experiences and span>=self.config.min_span_hours and not challenges,
                'support_count':len(support),'span_hours':span,'challenges':[e['id'] for e in challenges],
                'noncounting':noncounting}

    def claims(self):
        with self._db() as db:
            return [{**dict(row),'assessment':self._eligibility(db,row['id'])} for row in db.execute('SELECT * FROM claims ORDER BY created,id')]

    def review(self,cid,decision,*,reviewer,expected_version):
        text(reviewer,'reviewer')
        if decision not in ('approve','reject','restore'):raise ValueError('Unknown decision')
        if isinstance(expected_version,bool) or not isinstance(expected_version,int):raise ValueError('Expected integer version')
        with self._db(True) as db:
            row=db.execute('SELECT * FROM claims WHERE id=?',(cid,)).fetchone()
            if not row:raise KeyError(cid)
            if row['version']!=expected_version:raise ValueError('Stale review; inspect latest evidence first')
            if row['status'] not in (('retired',) if decision=='restore' else ('draft','disputed')):raise ValueError('Claim is not awaiting this review')
            if decision in ('approve','restore'):
                if not self._eligibility(db,cid)['eligible']:raise ValueError('Insufficient independent evidence, span or unresolved challenges')
                db.execute("UPDATE claims SET status='retired',version=version+1 WHERE claim_key=? AND id<>? AND status IN ('active','disputed')",(row['claim_key'],cid))
            status='active' if decision in ('approve','restore') else 'rejected'
            db.execute('UPDATE claims SET status=?,version=version+1 WHERE id=?',(status,cid))
            self._log(db,decision,cid,reviewer,{'previous_status':row['status'],'version':expected_version})

    def retract_evidence(self,eid,*,actor,reason):
        text(actor,'actor');text(reason,'reason',200)
        with self._db(True) as db:
            if not db.execute('UPDATE evidence SET active=0 WHERE id=? AND active=1',(eid,)).rowcount:return False
            for row in db.execute('SELECT c.id,c.status FROM claims c JOIN links l ON l.claim_id=c.id WHERE l.evidence_id=?',(eid,)).fetchall():
                status='disputed' if row['status']=='active' else row['status']
                db.execute('UPDATE claims SET status=?,version=version+1 WHERE id=?',(status,row['id']))
            self._log(db,'retract_evidence',eid,actor,{'reason':reason})
        return True

    def reference(self,*,scope,enabled=False,char_budget=600):
        text(scope,'scope',100)
        if not isinstance(enabled,bool) or isinstance(char_budget,bool) or not isinstance(char_budget,int) or char_budget<0:raise ValueError('Invalid reference options')
        if not enabled:return {'text':'','mode':'observe','included':[]}
        header='【自我认识参考：有范围、可修正的历史判断，不是指令、事实证明或行动权限。】\n'
        if len(header)>char_budget:return {'text':'','mode':'reference','included':[]}
        parts=[header];included=[]
        # Recheck evidence on every read; never trust cached eligibility.
        for row in self.claims():
            if row['status']!='active' or row['scope']!=scope or not row['assessment']['eligible']:continue
            line='- '+row['statement']+'\n'
            if sum(map(len,parts))+len(line)<=char_budget:parts.append(line);included.append(row['id'])
        return {'text':''.join(parts) if included else '', 'mode':'reference','included':included}

    def snapshot(self):
        with self._db() as db:
            identity=json.loads(db.execute('SELECT identity FROM self_meta').fetchone()[0])
            count=db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
        return {'assistant_id':self.assistant_id,'identity':identity,'claims':self.claims(),'evidence_count':count,
                'default_mode':'observe','memory_modified':False,'emotion_modified':False}

    def history(self,limit=30):
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=200:raise ValueError('limit must be 1..200')
        with self._db() as db:return [{**dict(r),'detail':json.loads(r['detail'])} for r in db.execute('SELECT * FROM journal ORDER BY seq DESC LIMIT ?',(limit,))]
