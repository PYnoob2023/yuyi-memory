"""Offline regression tests. python test_memory.py; no API, no personal data."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from companion_memory import CompanionMemory, ConcurrentUpdateError, QueueFullError, DAY
from memory_tools import MemoryTools
import test_legacy


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.clock = [1_760_000_000.0]
        self.m = CompanionMemory(self.folder.name, now_fn=lambda: self.clock[0])

    def reopen(self):
        return CompanionMemory(self.folder.name, now_fn=lambda: self.clock[0])

    def batch(self, text, data, role='user'):
        self.m.add_turn(role, text)
        return self.m.consolidate(lambda p: json.dumps(data, ensure_ascii=False))

    def event(self, text, **extra):
        return {'text': text, 'importance': 8, 'src': [1], **extra}

    def test_atomic_disk_failure_preserves_pending_and_retries(self):
        self.m.add_turn('user', '今天去公园野餐')
        original = self.m._write_snapshot
        count = [0]
        def fail_once():
            count[0] += 1
            if count[0] == 1:
                raise OSError('injected before commit')
            original()
        response = lambda p: json.dumps({'events': [self.event('公园野餐')]})
        with patch.object(self.m, '_write_snapshot', fail_once):
            self.assertFalse(self.m.consolidate(response))
        loaded = self.reopen()
        self.assertEqual(len(loaded.state['pending']), 1)
        self.assertFalse(loaded.episodes)
        self.assertEqual(loaded.state['fail_count'], 1)
        self.assertTrue(loaded.consolidate(response))
        loaded = self.reopen()
        self.assertEqual(len(loaded.episodes), 1)
        self.assertEqual(loaded.episodes[0]['recall_count'], 0)
        self.assertFalse(loaded.state['pending'])

    def test_total_disk_failure_does_not_mutate_memory(self):
        self.m.add_turn('user', '公园野餐')
        before = copy.deepcopy(self.m._payload())
        with patch.object(self.m, '_write_snapshot', side_effect=OSError('disk full')):
            self.assertFalse(self.m.consolidate(lambda p: json.dumps({'events': [self.event('公园野餐')]})))
        self.assertEqual(before, self.m._payload())
        self.assertTrue(self.m.last_report['retry_state_not_saved'])

    def test_exchange_is_one_transaction(self):
        with self.assertRaises(ValueError):
            self.m.add_exchange([('user', '你好'), ('invalid', '失败')])
        self.assertFalse(self.reopen().state['pending'])

    def test_stale_writer_does_not_overwrite(self):
        other = self.reopen()
        other.add_turn('user', '第二实例写入')
        with self.assertRaises(ConcurrentUpdateError):
            self.m.add_turn('user', '旧实例写入')
        self.assertFalse(self.m.state['pending'])
        self.assertEqual(self.reopen().state['pending'][0]['text'], '第二实例写入')

    def test_queue_full_never_silently_truncates(self):
        self.m.cfg['pending_max'] = 1
        self.m.add_turn('user', '第一条')
        with self.assertRaises(QueueFullError):
            self.m.add_turn('user', '第二条')
        self.assertEqual(len(self.reopen().state['pending']), 1)

    def test_invalid_import_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'episodes.json'
            path.write_text('{broken', encoding='utf-8')
            with self.assertRaises(json.JSONDecodeError):
                CompanionMemory(folder)
            self.assertEqual(path.read_text(encoding='utf-8'), '{broken')

    def test_legacy_migration_and_sqlite_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'state.json').write_text(json.dumps({'recent': [], 'pending': [{'role': 'user', 'text': '旧消息', 't': self.clock[0]}]}), encoding='utf-8')
            a = CompanionMemory(folder)
            self.assertEqual(a.state['pending'][0]['text'], '旧消息')
            a.add_turn('user', '新消息')
            Path(folder, 'state.json').write_text('corrupted old export', encoding='utf-8')
            b = CompanionMemory(folder)
            self.assertEqual(len(b.state['pending']), 2)

    def test_corrupt_database_is_not_reset(self):
        self.m.db_path.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            self.reopen()

    def test_negation_cannot_become_positive(self):
        self.assertTrue(self.batch('我没有升职', {'events': [self.event('用户升职了')]}))
        self.assertFalse(self.m.episodes)
        self.assertEqual(self.m.list_confirmations()[0]['reason'], 'negation_mismatch')
        self.assertNotIn('用户升职了', self.m.build_context('升职'))

    def test_hypothesis_is_not_current_fact(self):
        self.batch('我也许会搬去大阪', {'core_candidates': [{'fact': '搬去大阪', 'explicit': True, 'src': [1]}]})
        self.assertFalse(self.m.core['facts'])
        self.assertEqual(len(self.m.list_confirmations()), 1)

    def test_unrelated_deletion_requires_confirmation(self):
        self.m._add_core_candidate('喜欢喝咖啡', True)
        self.m._save_all()
        fid = self.m.core['facts'][0]['id']
        self.batch('今天去了公园', {'core_updates': [{'fact_id': fid, 'new': None, 'src': [1]}]})
        self.assertEqual(self.m.core['facts'][0]['id'], fid)
        self.assertEqual(self.m.list_confirmations()[0]['reason'], 'delete_intent_or_target_unclear')

    def test_sensitive_conflict_does_not_auto_promote(self):
        self.batch('我住在东京，请记住', {'core_candidates': [{'fact': '住在东京', 'explicit': True, 'src': [1]}]})
        self.batch('我住在大阪，请记住', {'core_candidates': [{'fact': '住在大阪', 'explicit': True, 'src': [1]}]})
        self.assertEqual(self.m.core['facts'][0]['fact'], '住在东京')
        proposal = self.m.list_confirmations()[0]
        self.m.confirm(proposal['id'])
        self.assertEqual(self.reopen().core['facts'][0]['fact'], '住在大阪')
        self.assertEqual(self.m.core['history'][0]['fact'], '住在东京')

    def test_stable_fact_id_survives_revision(self):
        self.batch('我住在东京，请记住', {'core_candidates': [{'fact': '住在东京', 'explicit': True, 'src': [1]}]})
        fid = self.m.core['facts'][0]['id']
        self.batch('我现在搬到大阪', {'core_updates': [{'fact_id': fid, 'new': '搬到大阪', 'src': [1]}]})
        self.assertEqual(self.m.core['facts'][0]['id'], fid)
        self.assertEqual(self.m.core['facts'][0]['fact'], '搬到大阪')
        self.assertEqual(self.m.core['history'][0]['fact_id'], fid)

    def test_rejected_proposal_never_enters_context(self):
        self.batch('我没有升职', {'events': [self.event('升职了')]})
        proposal = self.m.list_confirmations()[0]
        self.m.confirm(proposal['id'], accept=False)
        self.assertFalse(self.m.list_confirmations())
        self.assertFalse(self.m.episodes)

    def test_assistant_promise_is_not_fulfilment(self):
        self.batch('我答应你，下雨天陪你散步', {'events': [self.event('下雨天陪你散步', kind='promise', relationship=2)]}, role='assistant')
        m = self.m.episodes[0]
        self.assertEqual(m['kind'], 'promise')
        self.assertEqual(m['source_role'], 'assistant')
        self.assertEqual(m['status'], 'open')
        self.assertIn('说过不等于已兑现', self.m.build_context('散步'))

    def test_fabricated_assistant_event_still_rejected(self):
        self.batch('昨天一起去了月球', {'events': [self.event('一起去了月球')]}, role='assistant')
        self.assertFalse(self.m.episodes)

    def test_status_needs_target_evidence_and_user(self):
        mid = self.m.remember('陪你散步', kind='promise')
        self.assertFalse(self.m.set_status(mid, 'fulfilled', '完成了工作'))
        self.assertFalse(self.m.set_status(mid, 'fulfilled', '陪你散步还没有做到'))
        self.assertTrue(self.m.set_status(mid, 'fulfilled', '陪你散步的承诺已经兑现'))
        self.assertEqual(self.reopen().episodes[0]['status'], 'fulfilled')

    def test_closed_promise_stays_closed_on_repeat(self):
        mid = self.m.remember('陪你散步', kind='promise')
        self.m.set_status(mid, 'fulfilled', '陪你散步已经兑现')
        self.m.remember('陪你散步', kind='promise')
        self.assertEqual(self.m.episodes[0]['status'], 'fulfilled')

    def test_relationship_longevity_separate_from_status(self):
        a = self.m.remember('普通晚安甲', importance=5)
        b = self.m.remember('和解后的晚安乙', importance=5, relationship=3)
        values = {m['id']: self.m.stability(m) for m in self.m.episodes}
        self.assertGreater(values[b], values[a])
        old = values[b]
        self.m.episodes[1]['status'] = 'open'
        self.assertEqual(self.m.stability(self.m.episodes[1]), old)

    def test_no_relation_inferred_from_ordinary_goodnight(self):
        self.batch('今天晚安', {'events': [self.event('今天晚安', kind='relationship', relationship=3)]})
        self.assertEqual(self.m.episodes[0]['relationship'], 0)
        self.assertEqual(self.m.episodes[0]['kind'], 'event')

    def make_graph(self):
        a = self.m.remember('发烧住院', importance=8)
        b = self.m.remember('陪你等天亮', importance=8, kind='promise')
        c = self.m.remember('后来一起看星星', importance=8)
        self.assertTrue(self.m.link(a, b, '那次发烧住院之后，约定陪你等天亮'))
        return a, b, c

    def test_association_retrieves_without_literal_overlap(self):
        a, b, c = self.make_graph()
        self.m.cfg['retrieve_k'] = 2
        picked = self.m.retrieve('发烧住院')
        self.assertEqual({m['id'] for m in picked}, {a, b})
        # b has zero direct overlap; it is selected through the sourced edge.
        self.assertEqual(self.m._relevance(set(['发烧','烧住','住院']), next(m for m in picked if m['id']==b)), 0)

    def test_unsupported_link_does_not_create_experience(self):
        a, b, c = self.make_graph()
        self.assertFalse(self.m.link(a, c, '天气很好'))
        self.assertFalse(self.m.link(a, c, '如果发烧住院之后一起看星星'))
        self.assertEqual(len(self.m.core['edges']), 1)

    def test_hop_limit_prevents_unbounded_graph_walk(self):
        a, b, c = self.make_graph()
        self.m.link(b, c, '陪你等天亮之后，后来一起看星星')
        self.m.cfg.update(association_hops=1, retrieve_k=2)
        self.assertEqual({m['id'] for m in self.m.retrieve('发烧住院')}, {a, b})

    def test_model_cannot_invent_anchor(self):
        self.batch('发烧住院了', {'events': [self.event('发烧住院', anchors=['发烧', '海边旅行'])]})
        self.assertEqual(self.m.episodes[0]['anchors'], ['发烧'])

    def test_suppression_is_not_deletion_or_a_graph_bridge(self):
        a, b, c = self.make_graph()
        self.m.suppress(b)
        self.assertNotIn(b, [m['id'] for m in self.m.retrieve('发烧住院')])
        self.assertEqual(len(self.m.episodes), 3)
        self.m.suppress(b, False)
        self.assertIn(b, [m['id'] for m in self.m.retrieve('发烧住院')])

    def test_forget_removes_edges_reviews_history_and_chat(self):
        a, b, c = self.make_graph()
        self.m.add_turn('user', '发烧住院')
        self.m.core['history'].append({'fact_id':'old','fact':'发烧住院'})
        self.m._review('core', '发烧住院', 'uncertain', [])
        self.m.forget('发烧')
        payload = json.dumps(self.reopen()._payload(), ensure_ascii=False)
        self.assertNotIn('发烧', payload)
        self.assertFalse(self.m.core['edges'])

    def test_ghost_is_bounded_expires_and_has_no_details(self):
        self.m.remember('重要的晚安', importance=5, relationship=1)
        self.clock[0] += 100 * DAY
        traces = self.m.inspect_traces()
        self.assertEqual(len(traces), 1)
        self.assertNotIn('晚安', json.dumps(traces, ensure_ascii=False))
        self.assertFalse(self.m.episodes)
        self.clock[0] += 31 * DAY
        self.assertFalse(self.m.inspect_traces())

    def test_explicit_forget_clears_existence_traces(self):
        self.m.remember('重要的晚安', importance=5, relationship=1)
        self.clock[0] += 100 * DAY
        self.m.decay()
        self.assertTrue(self.m.core['traces'])
        self.m.forget('晚安')
        self.assertFalse(self.reopen().core['traces'])

    def test_budget_skips_long_first_item_and_no_false_reinforcement(self):
        long = self.m.remember('公园' * 35, importance=10)
        short = self.m.remember('公园散步', importance=3)
        self.m.cfg['context_char_budget'] = 25
        text = self.m.build_context('公园')
        self.assertIn('公园散步', text)
        byid = {m['id']:m for m in self.m.episodes}
        self.assertEqual(byid[long]['recall_count'], 0)
        self.assertEqual(byid[short]['recall_count'], 1)

    def test_nickname_last_explicit_intent_wins(self):
        self.m.add_exchange([('user','以后叫我山人'), ('assistant','山人你好'), ('user','别再叫我山人，不喜欢')])
        data = {'nicknames':[{'name':'山人','explicit':True,'src':[1]}],
                'rejected_nicknames':[{'name':'山人','src':[3]}]}
        self.assertTrue(self.m.consolidate(lambda p:json.dumps(data)))
        self.assertIn('山人',self.m.core['banned_names'])
        self.assertFalse(self.m.core['names'])

    def test_default_title_can_change_and_be_banned(self):
        self.m.reject_name('老李')
        self.m.set_user_title('朋友')
        self.assertEqual(self.reopen().user_title,'朋友')
        self.assertIn('老李',self.m.core['banned_names'])

    def test_existing_persona_is_untouched(self):
        self.m.persona_path.write_text('自定义人设',encoding='utf-8')
        self.reopen()
        self.assertEqual(self.m.persona_path.read_text(encoding='utf-8'),'自定义人设')

    def test_invalid_configuration_rejected(self):
        with self.assertRaises(ValueError):
            CompanionMemory(self.folder.name,config={'core_max':0})

    def test_same_batch_conflicts_do_not_make_two_current_residences(self):
        self.m.add_exchange([('user','我住在东京，请记住'),('user','我现在住在大阪，请记住')])
        data={'core_candidates':[{'fact':'住在大阪','explicit':True,'src':[2]},
                                 {'fact':'住在东京','explicit':True,'src':[1]}]}
        self.assertTrue(self.m.consolidate(lambda p:json.dumps(data)))
        self.assertEqual(len(self.m.core['facts']),1)
        self.assertEqual(self.m.core['facts'][0]['fact'],'住在东京')
        self.assertEqual(self.m.list_confirmations()[0]['value'],'住在大阪')

    def test_status_order_uses_source_position_not_model_array_order(self):
        mid=self.m.remember('陪你散步',kind='promise')
        self.m.add_exchange([('user','陪你散步的承诺已经兑现'),('user','陪你散步的承诺重新开始')])
        data={'status_updates':[{'id':mid,'status':'open','src':[2]},
                                {'id':mid,'status':'fulfilled','src':[1]}]}
        self.assertTrue(self.m.consolidate(lambda p:json.dumps(data)))
        self.assertEqual(self.m.episodes[0]['status'],'open')

    def test_fulfilment_from_assistant_is_not_enough(self):
        mid=self.m.remember('陪你散步',kind='promise')
        self.batch('陪你散步的承诺已经兑现',{'status_updates':[{'id':mid,'status':'fulfilled','src':[1]}]},role='assistant')
        self.assertEqual(self.m.episodes[0]['status'],'open')

    def test_model_links_require_a_cited_user_source(self):
        a=self.m.remember('发烧住院')
        b=self.m.remember('陪你等天亮',kind='promise')
        self.batch('那次发烧住院之后，约定陪你等天亮',{'links':[{'a':a,'b':b,'relation':'follow_up','src':[1]}]})
        self.assertEqual(len(self.m.core['edges']),1)
        self.assertEqual(self.m.core['edges'][0]['sources'][0]['role'],'user')

    def test_default_ban_does_not_conflict_with_context(self):
        self.m.reject_name('老李')
        text=self.m.build_context('你好')
        self.assertIn('默认叫“你”',text)
        self.assertNotIn('默认叫“老李”',text)

    def test_read_tool_budget_and_per_reply_limit(self):
        self.m.remember('公园野餐',importance=8)
        tools=MemoryTools(self.m,max_calls=1)
        result=tools.run('recall_memory',{'query':'野餐','char_budget':300})
        self.assertTrue(result['results'])
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),300)
        self.assertEqual(self.m.episodes[0]['recall_count'],0)
        self.assertEqual(tools.run('recall_memory',{'query':'野餐'}),{'error':'recall_call_limit'})

    def test_read_tool_cannot_delete(self):
        with self.assertRaises(ValueError):
            MemoryTools(self.m).run('forget',{'query':'公园'})


def load_tests(loader, tests, pattern):
    for name in dir(test_legacy):
        if name.startswith('test_'):
            tests.addTest(unittest.FunctionTestCase(getattr(test_legacy, name)))
    return tests


if __name__ == '__main__':
    unittest.main(verbosity=2)
