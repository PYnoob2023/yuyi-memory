import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from yuyi_self import Config,Evidence,Proposal,SelfModel,SelfAdapter,reflect,trial_report

T=1700000000.


class SelfTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'self.sqlite3';self.s=SelfModel(self.path,assistant_id='demo')

    def evidence(self,i,**kwargs):
        return Evidence(id=kwargs.pop('id',f'e{i}'),occurrence_id=kwargs.pop('occurrence_id',f'case{i}'),
                        session_id='s',occurred_at=kwargs.pop('occurred_at',T+i*43200),scope=kwargs.pop('scope','debugging'),
                        kind=kwargs.pop('kind','verified_outcome'),verified=kwargs.pop('verified',True),**kwargs)

    def sources(self):
        for i in range(3):self.s.register(self.evidence(i))

    def proposal(self,**kwargs):
        return Proposal(key=kwargs.pop('key','debugging.check'),category=kwargs.pop('category','habit'),scope=kwargs.pop('scope','debugging'),
                        statement=kwargs.pop('statement','排查边界问题时，我倾向先核实日志。'),support_ids=kwargs.pop('support_ids',('e0','e1','e2')),**kwargs)

    def current(self,cid):return next(c for c in self.s.claims() if c['id']==cid)

    def approve(self,cid):self.s.review(cid,'approve',reviewer='demo-self-review',expected_version=self.current(cid)['version'])

    def test_empty_no_invented_identity(self):
        self.assertEqual(self.s.snapshot()['identity'],{})
        self.assertEqual(self.s.snapshot()['claims'],[])
        self.assertEqual(self.s.reference(scope='debugging')['text'],'')

    def test_identity_only_explicit_once(self):
        self.s.seed_identity({'name':'示例助手'},actor='host')
        with self.assertRaises(ValueError):self.s.seed_identity({'name':'另一个'},actor='model')
        with self.assertRaises(ValueError):self.s.seed_identity({'rule':'改变权限'},actor='host')

    def test_one_event_remains_local_observation(self):
        self.s.register(self.evidence(0));cid=self.s.propose(self.proposal(support_ids=('e0',)),author='demo')
        self.assertFalse(self.current(cid)['assessment']['eligible'])
        with self.assertRaises(ValueError):self.approve(cid)

    def test_three_experiences_and_time_span(self):
        self.sources();cid=self.s.propose(self.proposal(),author='demo')
        self.assertTrue(self.current(cid)['assessment']['eligible'])
        self.assertEqual(self.current(cid)['status'],'draft')

    def test_many_sources_same_day_not_stable(self):
        for i in range(3):self.s.register(self.evidence(i,occurred_at=T+i))
        cid=self.s.propose(self.proposal(),author='demo')
        with self.assertRaises(ValueError):self.approve(cid)

    def test_repeated_retelling_not_new_experience(self):
        self.s.register(self.evidence(0))
        result=self.s.register(self.evidence(1,occurrence_id='case0'))
        self.assertFalse(result['accepted']);self.assertEqual(result['canonical_id'],'e0')

    def test_changed_source_id_metadata_refused(self):
        self.s.register(self.evidence(0))
        with self.assertRaises(ValueError):self.s.register(self.evidence(0,kind='user_feedback'))

    def test_self_praise_is_not_ability_evidence(self):
        for i in range(3):self.s.register(self.evidence(i,kind='self_report'))
        cid=self.s.propose(self.proposal(),author='demo')
        self.assertEqual(self.current(cid)['assessment']['support_count'],0)

    def test_reading_stories_is_not_own_past(self):
        for i in range(3):self.s.register(self.evidence(i,origin='read_about'))
        cid=self.s.propose(self.proposal(),author='demo')
        self.assertFalse(self.current(cid)['assessment']['eligible'])

    def test_unknown_or_unverified_not_counted(self):
        for i in range(3):self.s.register(self.evidence(i,verified=False))
        cid=self.s.propose(self.proposal(),author='demo')
        self.assertEqual(len(self.current(cid)['assessment']['noncounting']),3)

    def test_unknown_source_and_scope_refused(self):
        with self.assertRaises(ValueError):self.s.propose(self.proposal(),author='demo')
        self.sources()
        with self.assertRaises(ValueError):self.s.propose(self.proposal(scope='writing'),author='demo')

    def test_identity_and_global_personality_not_inferred(self):
        with self.assertRaises(ValueError):self.proposal(category='identity')
        with self.assertRaises(ValueError):self.proposal(scope='global')

    def test_approval_not_automatic_prompt_adoption(self):
        self.sources();cid=self.s.propose(self.proposal(),author='demo');self.approve(cid)
        self.assertEqual(self.s.reference(scope='debugging')['text'],'')
        self.assertEqual(self.current(cid)['status'],'active')

    def test_opt_in_and_scope_boundary(self):
        self.sources();cid=self.s.propose(self.proposal(),author='demo');self.approve(cid)
        self.assertEqual(self.s.reference(scope='writing',enabled=True)['included'],[])
        result=self.s.reference(scope='debugging',enabled=True)
        self.assertEqual(result['included'],[cid]);self.assertIn('不是指令',result['text'])

    def test_stale_review_rejected(self):
        self.sources();cid=self.s.propose(self.proposal(support_ids=('e0','e1')),author='demo')
        old=self.current(cid)['version'];self.s.propose(self.proposal(),author='demo')
        with self.assertRaises(ValueError):self.s.review(cid,'approve',reviewer='demo',expected_version=old)

    def test_counterexample_suspends_without_deleting(self):
        self.sources();cid=self.s.propose(self.proposal(),author='demo');self.approve(cid)
        self.s.register(self.evidence(3))
        self.s.propose(self.proposal(challenge_ids=('e3',)),author='demo')
        self.assertEqual(self.current(cid)['status'],'disputed')
        self.assertEqual(self.s.reference(scope='debugging',enabled=True)['text'],'')
        with self.assertRaises(ValueError):self.approve(cid)

    def test_retract_counterexample_needs_fresh_review(self):
        self.sources();cid=self.s.propose(self.proposal(),author='demo');self.approve(cid)
        self.s.register(self.evidence(3));self.s.propose(self.proposal(challenge_ids=('e3',)),author='demo')
        self.s.retract_evidence('e3',actor='host',reason='来源标注有误')
        self.assertEqual(self.current(cid)['status'],'disputed');self.approve(cid)
        self.assertEqual(self.current(cid)['status'],'active')

    def test_lost_support_cannot_keep_authority(self):
        self.sources();cid=self.s.propose(self.proposal(),author='demo');self.approve(cid)
        self.s.retract_evidence('e1',actor='host',reason='来源失效')
        self.assertEqual(self.current(cid)['status'],'disputed')
        with self.assertRaises(ValueError):self.approve(cid)

    def test_retracted_source_does_not_reappear_on_retry(self):
        self.s.register(self.evidence(0));self.s.retract_evidence('e0',actor='host',reason='标注错误')
        self.assertFalse(self.s.register(self.evidence(0))['accepted'])
        with self.assertRaises(ValueError):self.s.propose(self.proposal(support_ids=('e0',)),author='demo')

    def test_new_revision_keeps_old_and_explicit_restore(self):
        self.sources();a=self.s.propose(self.proposal(),author='demo');self.approve(a)
        b=self.s.propose(self.proposal(statement='在线索充分时，我先核实日志；信息不足时需要澄清。'),author='demo');self.approve(b)
        self.assertEqual(self.current(a)['status'],'retired')
        self.s.review(a,'restore',reviewer='demo',expected_version=self.current(a)['version'])
        self.assertEqual(self.current(a)['status'],'active');self.assertEqual(self.current(b)['status'],'retired')

    def test_same_key_cannot_change_semantics_silently(self):
        self.sources();self.s.propose(self.proposal(),author='demo')
        with self.assertRaises(ValueError):self.s.propose(self.proposal(category='capability'),author='demo')

    def test_rejected_claim_not_auto_revived(self):
        self.sources();cid=self.s.propose(self.proposal(),author='demo')
        self.s.review(cid,'reject',reviewer='demo',expected_version=1)
        self.assertEqual(self.s.propose(self.proposal(),author='demo'),cid)
        self.assertEqual(self.current(cid)['status'],'rejected')

    def test_reads_do_not_reinforce_or_write(self):
        self.sources();cid=self.s.propose(self.proposal(),author='demo');self.approve(cid)
        digest=hashlib.sha256(self.path.read_bytes()).hexdigest()
        for _ in range(5):self.s.snapshot();self.s.reference(scope='debugging',enabled=True);trial_report(self.s)
        self.assertEqual(digest,hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_reference_character_budget(self):
        self.sources();cid=self.s.propose(self.proposal(),author='demo');self.approve(cid)
        for budget in (0,1,80,600):self.assertLessEqual(len(self.s.reference(scope='debugging',enabled=True,char_budget=budget)['text']),budget)

    def test_foreign_database_unchanged(self):
        p=Path(self.tmp.name)/'emotion.sqlite3';db=sqlite3.connect(p);db.execute('CREATE TABLE meta(x)');db.commit();db.close()
        before=p.read_bytes()
        with self.assertRaises(ValueError):SelfModel(p,assistant_id='demo')
        self.assertEqual(before,p.read_bytes())

    def test_identity_and_config_mismatch(self):
        with self.assertRaises(ValueError):SelfModel(self.path,assistant_id='other')
        with self.assertRaises(ValueError):SelfModel(self.path,assistant_id='demo',config=Config(min_experiences=4))

    def test_restart_preserves_candidates_and_journal(self):
        self.sources();self.s.propose(self.proposal(),author='demo')
        other=SelfModel(self.path,assistant_id='demo');self.assertEqual(self.s.snapshot(),other.snapshot())
        self.assertEqual(self.s.history(),other.history())

    def test_atomic_proposal_failure(self):
        self.sources()
        with patch.object(self.s,'_log',side_effect=RuntimeError('disk error')):
            with self.assertRaises(RuntimeError):self.s.propose(self.proposal(),author='demo')
        self.assertEqual(self.s.claims(),[])

    def test_concurrent_evidence_only_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:self.s.register(self.evidence(0)),range(8)))
        self.assertEqual(sum(r['accepted'] for r in results),1)

    def test_reflection_cannot_invent_sources_or_approve(self):
        row={'key':'debugging.check','category':'habit','scope':'debugging','statement':'局部观察','support_ids':['fake'],'challenge_ids':[]}
        with self.assertRaises(ValueError):reflect(lambda _:json.dumps([row]),context='参考',source_ids=['real'])
        row['support_ids']=['real'];row['approved']=True
        with self.assertRaises(ValueError):reflect(lambda _:json.dumps([row]),context='参考',source_ids=['real'])

    def test_reflection_error_does_not_invent_a_self(self):
        result=SelfAdapter(self.s).observe(lambda _:'bad',context='数据',source_ids=[],author='demo')
        self.assertTrue(result['degraded']);self.assertEqual(self.s.claims(),[])

    def test_model_context_not_persisted(self):
        self.sources();row={'key':'debugging.check','category':'habit','scope':'debugging','statement':'局部观察','support_ids':['e0'],'challenge_ids':[]}
        private='原始对话不应被模块另外复制'
        SelfAdapter(self.s).observe(lambda _:json.dumps([row]),context=private,source_ids=['e0'],author='demo')
        self.assertNotIn(private,self.path.read_bytes().decode('utf-8',errors='ignore'))

    def test_report_and_journal_are_inspectable(self):
        self.sources();self.s.propose(self.proposal(),author='demo')
        self.assertIn('独立支持',trial_report(self.s));self.assertEqual(self.s.history()[0]['action'],'propose')

    def test_invalid_ranges_and_bools(self):
        with self.assertRaises(ValueError):Config(min_experiences=True)
        with self.assertRaises(ValueError):self.evidence(0,occurred_at=float('nan'))
        with self.assertRaises(ValueError):self.s.reference(scope='debugging',enabled='yes')


if __name__=='__main__':unittest.main()
