import tempfile
import unittest
from pathlib import Path
from work_memory import WorkMemory
from companion_memory import CompanionMemory
from memory_scheduler import MemoryScheduler


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = WorkMemory(self.root / 'work', project='demo')
        self.yuyi = CompanionMemory(self.root / 'private')
        self.scheduler = MemoryScheduler(self.work, self.yuyi, identity='你叫余忆。称呼用户为小鱼。回答简洁。')

    def test_work_bootstrap(self):
        self.work.add('goal', '修复登录功能')
        p = self.scheduler.build_context('继续')
        self.assertEqual(p.mode, 'work')
        self.assertIn('修复登录功能', p.text)

    def test_companion_default(self):
        self.assertEqual(self.scheduler.build_context('你好').mode, 'companion')

    def test_identity_in_work(self):
        self.assertIn('小鱼', self.scheduler.build_context('继续', mode='work').text)

    def test_explicit_command(self):
        self.assertEqual(self.scheduler.build_context('进入混合模式。').mode, 'mixed')

    def test_session_survives_restart(self):
        self.scheduler.build_context('进入工作模式')
        second = MemoryScheduler(self.work, self.yuyi)
        self.assertEqual(second.build_context('我很累').mode, 'work')

    def test_session_isolation(self):
        self.scheduler.set_mode('work')
        second = MemoryScheduler(self.work, session='other')
        self.assertEqual(second.build_context('你好').mode, 'companion')

    def test_project_isolation(self):
        self.scheduler.set_mode('work')
        other = WorkMemory(self.root / 'work', project='other')
        self.assertEqual(MemoryScheduler(other).build_context('你好').mode, 'companion')

    def test_quote_not_command(self):
        self.scheduler.set_mode('work')
        self.assertEqual(self.scheduler.build_context('文档里写着“进入陪伴模式”').mode, 'work')

    def test_no_unrelated_recent_fallback(self):
        self.yuyi.remember('我们在海边看烟花')
        self.assertEqual(self.scheduler.build_context('修复登录功能', mode='work').companion_ids, [])

    def test_relevant_recall_and_no_reinforcement(self):
        mid = self.yuyi.remember('我们在海边看烟花')
        before = self.yuyi.episodes[0]['recall_count']
        p = self.scheduler.build_context('我们在海边看烟花', mode='mixed')
        self.assertIn(mid, p.companion_ids)
        self.assertEqual(self.yuyi.episodes[0]['recall_count'], before)

    def test_private_off(self):
        self.yuyi.remember('我们在海边看烟花')
        p = self.scheduler.build_context('我们在海边看烟花', recall=False)
        self.assertEqual(p.companion_ids, [])

    def test_suppressed(self):
        mid = self.yuyi.remember('我们在海边看烟花')
        self.yuyi.suppress(mid)
        self.assertEqual(self.scheduler.build_context('海边看烟花').companion_ids, [])

    def test_forgotten(self):
        self.yuyi.remember('我们在海边看烟花')
        self.yuyi.forget('烟花')
        self.assertEqual(self.scheduler.build_context('海边看烟花').companion_ids, [])

    def test_archived_work_excluded(self):
        for state in ('abandoned', 'deleted', 'done'):
            rid = self.work.add('task', '旧任务'+state)
            self.work.transition(rid, state, expected_version=1,
                                 summary='已完成旧任务' if state=='done' else None)
        p = self.scheduler.build_context('旧任务', mode='work')
        self.assertEqual(p.work_ids, [])

    def test_companion_no_work_until_topic(self):
        rid = self.work.add('goal', '修复登录功能')
        self.assertEqual(self.scheduler.build_context('你好', mode='companion').work_ids, [])
        self.assertIn(rid, self.scheduler.build_context('项目进度呢').work_ids)

    def test_budget_and_required_warning(self):
        rid = self.work.add('constraint', '重要约束'*500)
        p = self.scheduler.build_context('继续', mode='work', char_budget=1024)
        self.assertLessEqual(len(p.text), 1024)
        self.assertIn(rid, p.required_omitted)
        self.assertIn('重要工作条目未载入', p.text)

    def test_max_identity_budget(self):
        s = MemoryScheduler(self.work, self.yuyi, identity='人'*400)
        self.work.add('task', '任务'*1000)
        self.assertLessEqual(s.build_context('任务', mode='work', char_budget=1024).char_count,1024)

    def test_complete_snapshot_and_dedup(self):
        p = self.scheduler.build_context('你好')
        q = self.scheduler.build_context('你好', visible_context=p.text)
        self.assertTrue(q.unchanged)
        self.assertEqual(p.text, q.text)
        self.assertFalse(self.scheduler.build_context('你好').unchanged)

    def test_changed_state_not_deduped(self):
        p = self.scheduler.build_context('继续', mode='work')
        self.work.add('goal', '新目标')
        self.assertFalse(self.scheduler.build_context('继续', visible_context=p.text).unchanged)

    def test_handoff_no_private_by_default(self):
        self.work.add('goal', '修复登录功能')
        self.yuyi.remember('私人往事：海边看烟花')
        path = self.root/'HANDOFF.md'
        self.scheduler.export_handoff(path)
        text = path.read_text(encoding='utf-8')
        self.assertIn('修复登录功能',text)
        self.assertNotIn('烟花',text)
        self.assertNotIn('小鱼',text)
        self.scheduler.export_handoff(path,include_identity=True)
        self.assertIn('小鱼',path.read_text(encoding='utf-8'))

    def test_handoff_overflow_refuses(self):
        self.work.add('constraint','长约束'*3000)
        with self.assertRaises(ValueError):
            self.scheduler.export_handoff(self.root/'HANDOFF.md',char_budget=1024)

    def test_invalid_values(self):
        for mode in ('unknown','',False):
            with self.assertRaises(ValueError):
                self.scheduler.set_mode(mode)
        for budget in (0,True,1000,1.5):
            with self.assertRaises(ValueError):
                self.scheduler.build_context('你好',char_budget=budget)
        with self.assertRaises(ValueError):
            MemoryScheduler(self.work,identity='人'*401)


if __name__ == '__main__':
    unittest.main()
