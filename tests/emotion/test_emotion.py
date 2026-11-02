import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from yuyi_emotion import PAD, Config, EmotionEvent, EmotionStore, AffectAdapter, EmotionAtlas, assess
from yuyi_emotion.dynamics import initial, advance, apply, coordinates
from yuyi_emotion.expression import describe

T = 1800000000.


class EmotionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'emotion.sqlite3'
        self.store = EmotionStore(self.path, assistant_id='test-assistant')

    def event(self, name='e1', *, timestamp=T, impact=None, **kwargs):
        return EmotionEvent(event_id=name,evidence_id=kwargs.pop('evidence_id',name),
                            timestamp=timestamp,impact=impact or PAD(.8,.4,.3),
                            intensity=kwargs.pop('intensity',.8),confidence=kwargs.pop('confidence',1.),
                            appraisal_status=kwargs.pop('appraisal_status','grounded'),**kwargs)

    def point(self, at=T):
        return list(self.store.state(at)['coordinates'].values())

    def test_initial_neutral(self):
        self.assertEqual(self.point(), [0,0,0])
        self.assertEqual(self.store.state(T)['description']['label'],'平静')

    def test_positive_and_negative_change_coordinates(self):
        self.store.submit(self.event())
        self.assertGreater(self.point()[0],0)
        self.store.submit(self.event('e2',timestamp=T+1,impact=PAD(-1,.5,-1),intensity=1))
        self.assertLess(self.point(T+1)[0],0)

    def test_three_layers_separate(self):
        self.store.submit(self.event())
        state=self.store.state(T)
        self.assertEqual(list(state['layers']['baseline'].values()),[0,0,0])
        self.assertGreater(state['layers']['short_raw'][0],state['layers']['mood_raw'][0])
        self.assertGreater(state['layers']['mood_raw'][0],0)

    def test_exact_half_lives(self):
        self.store.submit(self.event())
        before=self.store.state(T)['layers']
        short=self.store.state(T+7200)['layers']
        long=self.store.state(T+72*3600)['layers']
        self.assertAlmostEqual(short['short_raw'][0],before['short_raw'][0]/2)
        self.assertAlmostEqual(long['mood_raw'][0],before['mood_raw'][0]/2)

    def test_tomorrow_has_mood_then_eventually_recovers(self):
        self.store.submit(self.event())
        tomorrow=self.store.state(T+86400)['layers']
        self.assertGreater(tomorrow['mood_raw'][0],tomorrow['short_raw'][0]*10)
        self.assertLess(abs(self.point(T+365*86400)[0]),1e-10)

    def test_baseline_does_not_learn_from_single_event(self):
        cfg=Config(baseline=PAD(.2,-.1,.1))
        store=EmotionStore(Path(self.tmp.name)/'baseline.sqlite3',config=cfg)
        store.submit(self.event())
        recovered=list(store.state(T+365*86400)['coordinates'].values())
        for actual,expected in zip(recovered,cfg.baseline.values()): self.assertAlmostEqual(actual,expected)

    def test_status_never_modifies_database(self):
        self.store.submit(self.event())
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        for i in range(20): self.store.state(T+i*100)
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_observation_frequency_does_not_change_state(self):
        self.store.submit(self.event())
        expected=self.point(T+10000)
        for i in range(30): self.store.state(T+i*10)
        self.assertEqual(expected,self.point(T+10000))

    def test_duplicate_event_and_evidence(self):
        e=self.event()
        self.assertTrue(self.store.submit(e)['accepted'])
        self.assertEqual(self.store.submit(e)['reason'],'duplicate_evidence')
        self.assertEqual(self.store.submit(self.event('other',evidence_id='e1'))['reason'],'duplicate_evidence')
        self.assertEqual(self.store.state(T)['event_count'],1)

    def test_same_local_evidence_id_in_other_session_is_distinct(self):
        self.store.submit(self.event())
        self.assertTrue(self.store.submit(self.event('other',evidence_id='e1',session_id='second'))['accepted'])

    def test_low_confidence_cannot_affect_mood(self):
        self.assertEqual(self.store.submit(self.event(confidence=.5))['reason'],'low_confidence')
        self.assertEqual(self.point(),[0,0,0])
        self.assertEqual(self.store.audit(),[])

    def test_user_emotion_does_not_become_agent_emotion(self):
        self.assertEqual(self.store.submit(self.event(owner='user'))['reason'],'not_agent_emotion')
        self.assertEqual(self.point(),[0,0,0])

    def test_recalling_is_not_new_evidence(self):
        self.assertEqual(self.store.submit(self.event(evidence_kind='recalled_memory'))['reason'],'not_new_supported_experience')
        self.assertEqual(self.point(),[0,0,0])

    def test_unknown_outcome_cannot_become_failure(self):
        self.assertFalse(self.store.submit(self.event(evidence_kind='unknown'))['accepted'])
        self.assertEqual(self.store.submit(self.event(evidence_kind='verified_outcome'))['reason'],'outcome_not_verified')
        self.assertTrue(self.store.submit(self.event(evidence_kind='verified_outcome',verified=True))['accepted'])

    def test_tentative_interpretation_never_updates_long_mood(self):
        self.store.submit(self.event(appraisal_status='tentative'))
        state=self.store.state(T)
        self.assertNotEqual(state['layers']['short_raw'],[0,0,0])
        self.assertEqual(state['layers']['mood_raw'],[0,0,0])
        self.assertTrue(state['description']['tentative_interpretation'])
        self.assertIn('尚未核实',state['reference'])

    def test_automatic_absence_event_is_not_supported(self):
        with self.assertRaises(ValueError): self.event(interpretation='user_absent')

    def test_no_wronged_word_without_context(self):
        self.store.submit(self.event(impact=PAD(-1,.25,-1),intensity=1))
        self.assertNotEqual(self.store.state(T)['description']['label'],'委屈')

    def test_wronged_word_requires_context_and_matching_coordinates(self):
        self.store.submit(self.event(impact=PAD(-1,.25,-1),intensity=1,interpretation='misunderstood'))
        self.assertEqual(self.store.state(T)['description']['label'],'委屈')

    def test_context_decays_without_permanent_wronged_label(self):
        self.store.submit(self.event(impact=PAD(-1,.25,-1),intensity=1,interpretation='misunderstood'))
        self.assertNotEqual(self.store.state(T+48*3600)['description']['label'],'委屈')

    def test_mixed_positive_negative_are_visible(self):
        self.store.submit(self.event(intensity=1,impact=PAD(1,.5,.2)))
        self.store.submit(self.event('negative',intensity=1,impact=PAD(-1,.4,-.2)))
        state=self.store.state(T)
        self.assertTrue(state['description']['mixed'])
        self.assertEqual(state['description']['label'],'复杂')
        self.assertGreater(state['positive_load'],0)
        self.assertGreater(state['negative_load'],0)

    def test_coordinate_bounds_under_many_independent_events(self):
        for i in range(100): self.store.submit(self.event(str(i),intensity=1,impact=PAD(1,1,1)))
        for value in self.point(): self.assertTrue(-1<=value<=1)
        for value in self.store.state(T)['layers']['short_raw']: self.assertLessEqual(value,3)

    def test_no_model_parameters_or_memory_flag_changes(self):
        state=self.store.state(T)
        self.assertTrue(state['simulated'])
        self.assertFalse(state['memory_modified'])

    def test_restart_preserves_layers_and_ids(self):
        self.store.submit(self.event())
        reopened=EmotionStore(self.path,assistant_id='test-assistant')
        self.assertEqual(self.store.state(T+100),reopened.state(T+100))
        self.assertFalse(reopened.submit(self.event())['accepted'])

    def test_second_connection_loads_current_state(self):
        second=EmotionStore(self.path,assistant_id='test-assistant')
        self.store.submit(self.event())
        second.submit(self.event('e2',timestamp=T+10))
        self.assertEqual(self.store.state(T+10),second.state(T+10))

    def test_configuration_and_assistant_mismatch_refused(self):
        for kwargs in ({'assistant_id':'another'}, {'assistant_id':'test-assistant','config':Config(short_gain=.4)}):
            with self.assertRaises(ValueError): EmotionStore(self.path,**kwargs)

    def test_foreign_memory_database_not_modified(self):
        path=Path(self.tmp.name)/'memory.sqlite3'
        db=sqlite3.connect(path);db.execute('CREATE TABLE memory (payload TEXT)');db.commit();db.close()
        before=path.read_bytes()
        with self.assertRaises(ValueError): EmotionStore(path)
        self.assertEqual(path.read_bytes(),before)

    def test_out_of_order_event_is_atomic(self):
        self.store.submit(self.event())
        before=self.store.state(T)
        with self.assertRaises(ValueError): self.store.submit(self.event('old',timestamp=T-1))
        self.assertEqual(before,self.store.state(T))

    def test_past_state_cannot_time_travel(self):
        self.store.submit(self.event())
        with self.assertRaises(ValueError): self.store.state(T-1)

    def test_zero_intensity_leaves_no_affect(self):
        self.store.submit(self.event(intensity=0))
        self.assertEqual(self.point(),[0,0,0])

    def test_replay_matches_snapshot_after_time_gap(self):
        for i in range(5): self.store.submit(self.event(str(i),timestamp=T+i*600,impact=PAD((-.6 if i%2 else .8),.2,-.2)))
        actual=self.store.state(T+50000)
        replay=self.store.replay(T+50000)
        self.assertEqual(list(actual['coordinates'].values()),replay['coordinates'])
        self.assertEqual(actual['layers']['short_raw'],replay['short_raw'])
        self.assertEqual(actual['description'],replay['description'])

    def test_retraction_recomputes_subsequent_state(self):
        self.store.submit(self.event('good',impact=PAD(.9,.2,.4)))
        self.store.submit(self.event('mistake',timestamp=T+1,impact=PAD(-1,.5,-1),interpretation='misunderstood'))
        self.store.set_active('mistake',False,reason='correction')
        control=EmotionStore(Path(self.tmp.name)/'control.sqlite3')
        control.submit(self.event('good',impact=PAD(.9,.2,.4)))
        for a,b in zip(self.point(T+1),list(control.state(T+1)['coordinates'].values())): self.assertAlmostEqual(a,b)
        self.assertEqual(self.store.changes()[0]['action'],'retract')

    def test_retraction_does_not_free_dedup_key(self):
        self.store.submit(self.event())
        self.store.set_active('e1',False,reason='user_request')
        self.assertFalse(self.store.submit(self.event('reappeared',evidence_id='e1'))['accepted'])
        self.assertEqual(self.point(),[0,0,0])

    def test_reviewed_restore_reconstructs_original_state(self):
        self.store.submit(self.event());expected=self.point()
        self.store.set_active('e1',False,reason='correction')
        with self.assertRaises(ValueError): self.store.set_active('e1',True,reason='correction')
        self.store.set_active('e1',True,reason='reviewed_restore')
        self.assertEqual(self.point(),expected)

    def test_rollback_replays_later_saturation(self):
        for i in range(8): self.store.submit(self.event(str(i),impact=PAD(1,1,1),intensity=1))
        self.store.set_active('0',False,reason='correction')
        self.assertEqual(self.point(),self.store.replay(T)['coordinates'])

    def test_backup_is_valid_independent_and_no_overwrite(self):
        self.store.submit(self.event())
        target=Path(self.tmp.name)/'backup.sqlite3'
        self.store.backup(target)
        self.assertEqual(self.store.state(T),EmotionStore(target,assistant_id='test-assistant').state(T))
        with self.assertRaises(ValueError): self.store.backup(target)

    def test_no_raw_dialogue_is_stored_by_assessor(self):
        secret='测试用的原始聊天，不应存入情绪数据库'
        raw=json.dumps({'impact':{'pleasure':.4,'arousal':.1,'agency':.2},'intensity':.5,'confidence':.9,'owner':'self','interpretation':'support','appraisal_status':'grounded'})
        e=assess(lambda prompt:raw,context=secret,event_id='e',evidence_id='opaque-1',timestamp=T)
        self.store.submit(e)
        self.assertNotIn(secret,self.path.read_bytes().decode('utf-8',errors='ignore'))

    def test_model_cannot_supply_authoritative_ids(self):
        raw={'impact':{'pleasure':0,'arousal':0,'agency':0},'intensity':.5,'confidence':1,'owner':'self','interpretation':'neutral','appraisal_status':'grounded','verified':True}
        with self.assertRaises(ValueError): assess(lambda _:json.dumps(raw),context='数据',event_id='e',evidence_id='id',timestamp=T)

    def test_bad_evaluator_fails_without_fabricated_emotion(self):
        adapter=AffectAdapter(self.store)
        for model in (lambda _:'not json',lambda _:None):
            result=adapter.consider(model,context='数据',event_id='e',evidence_id='id',timestamp=T)
            self.assertFalse(result['accepted'])
        self.assertEqual(self.point(),[0,0,0])

    def test_reference_budget_and_no_numeric_reward(self):
        self.store.submit(self.event())
        self.assertEqual(self.store.state(T,char_budget=1)['reference'],'')
        text=self.store.state(T,char_budget=500)['reference']
        self.assertLessEqual(len(text),500)
        self.assertNotIn('pleasure',text)
        self.assertNotIn('0.8',text)
        self.assertIn('认真程度',text)
        self.assertIn('不是',text)

    def test_bad_reference_degrades_without_blocking_host(self):
        result=AffectAdapter(self.store).reference(-1)
        self.assertTrue(result['degraded'])
        self.assertEqual(result['text'],'')

    def test_nan_bool_and_invalid_ranges_rejected(self):
        for value in (float('nan'),float('inf'),True,2):
            with self.assertRaises(ValueError): PAD(value,0,0)
        for kwargs in ({'confidence':float('nan')},{'intensity':True},{'timestamp':-1}):
            with self.assertRaises(ValueError): self.event(**kwargs)
        with self.assertRaises(ValueError): Config(short_half_life_hours=100,mood_half_life_hours=10)

    def test_no_personality_change_due_to_status_reads(self):
        self.store.submit(self.event())
        for i in range(5): self.store.state(T+i*3600)
        self.assertEqual(self.store.config.baseline,PAD())

    def test_small_next_day_mood_changes_expression(self):
        self.store.submit(self.event())
        self.assertIn('轻快',self.store.state(T+86400)['description']['tendency']['tone'])

    def test_small_negative_mood_changes_expression(self):
        self.store.submit(self.event(impact=PAD(-.8,-.2,-.3)))
        self.assertIn('安静',self.store.state(T+86400)['description']['tendency']['tone'])

    def test_three_dimensional_array_and_context_gates(self):
        atlas=EmotionAtlas(5)
        self.assertEqual((len(atlas.cells),len(atlas.cells[0]),len(atlas.cells[0][0])),(5,5,5))
        result=atlas.locate(PAD(-.65,.2,-.65))
        wronged=next(x for x in result['candidates'] if x['word']=='委屈')
        self.assertIn('misunderstood',wronged['requires_any'])
        self.assertEqual(atlas.locate(PAD(-1,-1,-1))['indices'],[0,0,0])
        self.assertEqual(atlas.locate(PAD(1,1,1))['indices'],[4,4,4])

    def test_atlas_validation_and_json_export(self):
        with self.assertRaises(ValueError): EmotionAtlas(1)
        data=json.loads(json.dumps(EmotionAtlas(3).export(),ensure_ascii=False))
        self.assertEqual(data['axes'],['pleasure','arousal','agency'])

    def test_long_positive_negative_do_not_disappear_in_average(self):
        self.store.submit(self.event('good',impact=PAD(1,.4,.2),intensity=1))
        self.store.submit(self.event('sad',impact=PAD(-1,-.4,-.2),intensity=1))
        state=self.store.state(T+86400)
        self.assertAlmostEqual(state['coordinates']['pleasure'],0)
        self.assertTrue(state['description']['mixed'])
        self.assertGreater(state['mood_positive_load'],0)
        self.assertGreater(state['mood_negative_load'],0)

    def test_write_failure_rolls_back_event_and_dedup(self):
        with patch.object(self.store,'_save',side_effect=RuntimeError('simulated write failure')):
            with self.assertRaises(RuntimeError): self.store.submit(self.event())
        self.assertEqual(self.store.state(T)['event_count'],0)
        self.assertTrue(self.store.submit(self.event())['accepted'])

    def test_concurrent_duplicate_has_only_one_effect(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            results=list(workers.map(lambda _: self.store.submit(self.event()),range(8)))
        self.assertEqual(sum(r['accepted'] for r in results),1)
        self.assertEqual(self.store.state(T)['event_count'],1)

    def test_label_hysteresis_keeps_boundary_stable(self):
        state=initial()
        state['short']=[math.atanh(v) for v in (.64,.475,.225)]
        state['label_hint']='欣喜'
        self.assertEqual(describe(state,Config())['label'],'欣喜')


if __name__=='__main__':
    unittest.main()
