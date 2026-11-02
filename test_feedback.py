import json
import tempfile
import unittest
from pathlib import Path
from companion_memory import CompanionMemory
from memory_scheduler import MemoryScheduler
from project_memory import ProjectMemory
from work_memory import WorkMemory


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.m=CompanionMemory(self.root/'private')
        self.s=MemoryScheduler(WorkMemory(self.root/'work'),self.m)

    def fact(self,value):
        with self.m._atomic():
            self.m._add_core_candidate(value,True)
            self.m._upgrade()

    def test_cross_kind_same_text(self):
        a=self.m.remember('陪你散步',kind='promise',relationship=2)
        b=self.m.remember('陪你散步',kind='event')
        self.assertNotEqual(a,b)
        self.assertEqual(len(self.m.episodes),2)
        self.assertEqual(self.m.episodes[0]['kind'],'promise')
        self.assertEqual(self.m.remember('陪你散步',kind='event'),b)

    def test_repeat_preserves_relationship_and_closed_status(self):
        mid=self.m.remember('陪你散步',kind='promise',relationship=2,anchors=['散步'])
        self.assertTrue(self.m.set_status(mid,'fulfilled','陪你散步的约定已经完成'))
        self.assertEqual(self.m.remember('陪你散步',kind='promise'),mid)
        self.assertEqual(self.m.episodes[0]['relationship'],2)
        self.assertEqual(self.m.episodes[0]['status'],'fulfilled')
        self.assertIn('散步',self.m.episodes[0]['anchors'])

    def test_cancel_accepts_unneeded_and_rejects_negations(self):
        mid=self.m.remember('陪你散步',kind='promise')
        for evidence in ('陪你散步的承诺没有取消','陪你散步的承诺不要取消','陪你散步的承诺不必取消','陪你散步的承诺不用再取消'):
            self.assertFalse(self.m.set_status(mid,'cancelled',evidence))
        self.assertFalse(self.m.set_status(mid,'fulfilled','陪你散步的承诺没有完成'))
        self.assertTrue(self.m.set_status(mid,'cancelled','陪你散步的承诺不用再履行'))

    def test_confirm_conflicting_old_proposals_rolls_back(self):
        for city in ('东京','大阪'):
            self.m.add_turn('user',f'我也许会住在{city}')
            self.assertTrue(self.m.consolidate(lambda p,city=city: json.dumps({
                'core_candidates':[{'fact':f'住在{city}','explicit':False,'src':[1]}]},ensure_ascii=False)))
        proposals=self.m.list_confirmations()
        self.assertEqual(len(proposals),2)
        self.m.confirm(proposals[0]['id'])
        with self.assertRaises(ValueError): self.m.confirm(proposals[1]['id'])
        self.assertEqual([f['fact'] for f in self.m.core['facts']],['住在东京'])
        self.assertIn(proposals[1]['id'],[p['id'] for p in self.m.list_confirmations()])
        loaded=CompanionMemory(self.root/'private')
        self.assertEqual([f['fact'] for f in loaded.core['facts']],['住在东京'])

    def test_stale_target_rejected(self):
        self.fact('住在东京')
        target=self.m.core['facts'][0]
        with self.m._atomic():
            self.m._review('core_update','住在大阪','test',[],target['id'])
            proposal=self.m.list_confirmations()[0]['id']
            target['fact']='住在京都'
        with self.assertRaises(ValueError): self.m.confirm(proposal)
        self.assertEqual(self.m.core['facts'][0]['fact'],'住在京都')

    def test_control_command_never_recalls_work(self):
        self.m.remember('我们聊工作，海康的工作很忙')
        for command in ('先不工作，陪我聊聊','进入工作模式','退出工作','进入项目 工作','项目列表'):
            self.assertEqual(self.s.build_context(command).companion_ids,[])
        self.assertTrue(self.s.build_context('海康的工作很忙').companion_ids)

    def test_confirmed_basics_without_private_dump(self):
        self.fact('名字是小鱼')
        self.fact('生日是五月十日')
        self.fact('住在东京')
        self.m.core['pending'].append({'fact':'生日是六月一日'})
        p=self.s.build_context('你好',recall=False)
        self.assertIn('名字是小鱼',p.text)
        self.assertIn('生日是五月十日',p.text)
        self.assertNotIn('住在东京',p.text)
        self.assertNotIn('六月一日',p.text)
        self.assertNotIn('五月十日',self.s.build_context('你好',include_facts=False).text)

    def test_fact_deletion_not_cached(self):
        self.fact('生日是五月十日')
        self.m.forget('五月十日')
        self.assertNotIn('五月十日',self.s.build_context('你好').text)

    def test_project_layer_basics_budget_and_exit(self):
        self.fact('名字是小鱼')
        self.m.remember('我们聊工作，海康的工作很忙')
        pm=ProjectMemory(self.root/'projects',self.m,identity='人'*400)
        pid=pm.register('海康','工作项目')
        pm.work(pid).add('goal','工作细节'*1000)
        pm.enter(pid)
        p=pm.build_context('继续',char_budget=1024)
        self.assertLessEqual(p.char_count,1024)
        self.assertTrue(p.required_omitted)
        p=pm.build_context('先不工作，陪我聊聊')
        self.assertEqual(p.companion_ids,[])
        self.assertEqual(p.work_ids,[])
        self.assertIn('名字是小鱼',p.text)


if __name__=='__main__': unittest.main()
