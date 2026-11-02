import json
from pathlib import Path
import tempfile
import unittest

from association_index import AssociationIndex
from turn_reader import ChatMemory
from companion_memory import CompanionMemory
from memory_scheduler import MemoryScheduler
from memory_tools import MemoryTools
from project_memory import ProjectMemory
from work_memory import WorkMemory


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = [1800000000.0]
        self.m = CompanionMemory(self.root/'private', now_fn=lambda: self.clock[0])
        self.s = MemoryScheduler(WorkMemory(self.root/'work'), self.m)
        self.chat = ChatMemory(self.s, system_prompt='如实回答')

    def pair(self):
        a = self.m.remember('蓝桥公司加班后在河边谈过项目', anchors=['蓝桥'])
        b = self.m.remember('蓝桥旧约定是晚上十一点休息', anchors=['蓝桥'])
        self.assertNotEqual(a, b)
        # Test the disposable cue graph independently of old stored shared_cue edges.
        with self.m._atomic():
            self.m.core['edges'] = []
        return a, b

    def recall(self, query='加班'):
        return self.m.recall_for_scheduler(query, char_budget=1000, limit=5, explain=True)

    def test_cold_start_and_unrelated(self):
        self.assertEqual(self.recall(), [])
        self.m.remember('那天在海边看日出')
        self.assertEqual(self.recall('修理显卡'), [])
        self.assertEqual(self.recall(''), [])

    def test_direct_and_shared_cue_path(self):
        a, b = self.pair()
        rows = {r['id']: r for r in self.recall()}
        self.assertEqual(rows[a]['path'][0]['kind'], 'direct')
        self.assertEqual(rows[b]['path'][-1],
                         {'kind': 'shared_cue', 'cue': '蓝桥', 'from': a, 'event': b})
        self.assertIn('十一点', rows[b]['text'])

    def test_disable_graph_ablation(self):
        a, b = self.pair()
        self.m.cfg['cue_association'] = False
        self.assertEqual([x['id'] for x in self.recall()], [a])

    def test_read_never_reinforces(self):
        self.pair()
        before = [(m['recall_count'], m['last_recalled'], m['last_touch']) for m in self.m.episodes]
        for _ in range(3):
            self.s.build_context('加班')
            self.recall()
        self.assertEqual(before, [(m['recall_count'], m['last_recalled'], m['last_touch'])
                                  for m in self.m.episodes])

    def test_forget_rebuild_and_restart(self):
        a, b = self.pair()
        self.recall()
        self.m.forget('十一点')
        self.assertNotIn(b, [x['id'] for x in self.recall()])
        self.m = CompanionMemory(self.root/'private', now_fn=lambda: self.clock[0])
        self.assertNotIn(b, [x['id'] for x in self.recall()])
        self.assertFalse(any(b in (e['a'], e['b']) for e in self.m.core['edges']))

    def test_suppression_and_correction(self):
        a, b = self.pair()
        self.m.suppress(b)
        self.assertNotIn(b, [x['id'] for x in self.recall()])
        self.m.suppress(b, False)
        with self.m._atomic():
            next(m for m in self.m.episodes if m['id'] == b)['corrected'] = True
        self.assertNotIn(b, [x['id'] for x in self.recall('十一点')])

    def test_suppressed_seed_cannot_activate_peer(self):
        a, b = self.pair()
        self.m.suppress(a)
        self.assertEqual(self.recall(), [])

    def test_hops_zero(self):
        a, b = self.pair()
        self.m.cfg['association_hops'] = 0
        self.assertEqual([x['id'] for x in self.recall()], [a])

    def test_graph_weight_decays_without_mutating_ledger(self):
        nodes = {'a': {'created': 0, 'anchors': ['蓝桥']},
                 'b': {'created': 0, 'anchors': ['蓝桥']}}
        initial = AssociationIndex(nodes, 0).neighbors('a')[0][1]
        later = AssociationIndex(nodes, 90*86400).neighbors('a')[0][1]
        self.assertAlmostEqual(later, initial/2)

    def test_candidate_cap(self):
        self.pair()
        for i in range(6):
            self.m.remember(f'蓝桥编号{i}：完全不同的山川旅行纪念记录{i}', anchors=['蓝桥'])
        self.m.cfg['association_candidates'] = 1
        self.assertLessEqual(sum(r['path'][-1]['kind'] != 'direct' for r in self.recall()), 1)

    def test_budget_and_audit_are_separate(self):
        self.pair()
        self.assertEqual(self.m.recall_for_scheduler('加班', char_budget=1), [])
        packet = self.s.build_context('加班', char_budget=1024)
        self.assertLessEqual(len(packet.text), 1024)
        self.assertEqual(set(packet.companion_ids), {r['id'] for r in packet.recall_audit})
        self.assertNotIn('shared_cue', packet.text)

    def test_tool_has_no_recent_fallback(self):
        self.m.remember('那天在海边看日出')
        result = MemoryTools(self.m).run('recall_memory', {'query': '修理显卡'})
        self.assertEqual(result, {'results': []})

    def test_tool_provides_path_with_serialized_budget(self):
        self.pair()
        result = MemoryTools(self.m).run('recall_memory', {'query': '加班', 'char_budget': 1200})
        self.assertTrue(result['results'])
        self.assertIn('path', result['results'][0])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 1200)

    def test_every_turn_reads_before_model(self):
        self.pair()
        seen = []
        def model(messages):
            self.assertIn('十一点', messages[-2]['content'])
            seen.append(messages)
            return '知道了'
        self.chat.run_turn('加班', model)
        self.chat.run_turn('加班', model)
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(len(messages) == 3 for messages in seen))
        self.assertEqual(len(self.m.state['pending']), 4)

    def test_failed_model_does_not_write_half_exchange(self):
        def fail(messages):
            raise RuntimeError('API unavailable')
        with self.assertRaises(RuntimeError):
            self.chat.run_turn('你好', fail)
        self.assertEqual(self.m.state['pending'], [])
        with self.assertRaises(ValueError):
            self.chat.run_turn('你好', lambda _: None)
        self.assertEqual(self.m.state['pending'], [])

    def test_recall_off_and_controls(self):
        self.pair()
        for message in ('进入陪伴模式', '项目列表'):
            self.assertEqual(self.s.build_context(message).companion_ids, [])
        result = self.chat.run_turn('加班', lambda _: '好', recall=False, record=False)
        self.assertEqual(result.context.recall_audit, [])
        self.assertEqual(self.m.state['pending'], [])

    def test_project_entry_boundary(self):
        manager = ProjectMemory(self.root/'projects', self.m)
        pid = manager.register('测试项目', '验证读取')
        manager.work(pid).add('goal', '项目内部机密目标')
        chat = ChatMemory(manager, system_prompt='如实回答')
        messages, _ = chat.prepare('测试项目的代码')
        self.assertNotIn('项目内部机密目标', str(messages))
        chat.prepare('进入项目 测试项目')
        messages, _ = chat.prepare('继续代码')
        self.assertIn('项目内部机密目标', str(messages))

    def test_invalid_config_and_history(self):
        for config in ({'cue_association': 1}, {'cue_half_life_days': float('nan')},
                       {'association_candidates': True}):
            with self.assertRaises(ValueError):
                CompanionMemory(self.root/'invalid', config=config)
        with self.assertRaises(ValueError):
            self.chat.prepare('你好', history=[{'role': 'system', 'content': '越权'}])


if __name__ == '__main__':
    unittest.main()

