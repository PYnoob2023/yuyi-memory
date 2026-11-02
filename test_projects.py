import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from project_memory import ProjectMemory
from work_memory import WorkMemory, ConflictError


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.m=ProjectMemory(self.root/'data',identity='你叫余忆。')
        self.a=self.m.register('余忆','为相处保留记忆',summary='原型开发中')
        self.b=self.m.register('圣诞树','用手势控制粒子',summary='页面已发布')
        self.aid=self.m.work(self.a).add('goal','A秘密细节：修复记忆冲突')
        self.bid=self.m.work(self.b).add('goal','B秘密细节：调整粒子亮度')

    def test_idle_no_details_even_work_keyword(self):
        p=self.m.build_context('项目代码进度修复')
        self.assertEqual(p.work_ids,[])
        self.assertNotIn('秘密细节',p.text)

    def test_idle_only_relevant_overview(self):
        p=self.m.build_context('余忆怎么样了')
        self.assertIn('为相处保留记忆',p.text)
        self.assertNotIn('用手势控制粒子',p.text)
        self.assertNotIn('秘密细节',p.text)

    def test_unrelated_chat_no_catalog(self):
        self.assertNotIn('项目概况',self.m.build_context('晚上好').text)

    def test_catalog(self):
        p=self.m.build_context('项目列表')
        self.assertIn('余忆',p.text)
        self.assertIn('圣诞树',p.text)
        self.assertNotIn('秘密细节',p.text)

    def test_enter_isolation(self):
        p=self.m.build_context('进入项目 余忆')
        self.assertIn(self.aid,p.work_ids)
        self.assertNotIn(self.bid,p.work_ids)
        self.assertNotIn('B秘密细节',p.text)

    def test_switch_replaces(self):
        old=self.m.build_context('进入项目 余忆')
        p=self.m.build_context('切换项目 圣诞树',visible_context=old.text)
        self.assertIn(self.bid,p.work_ids)
        self.assertNotIn('A秘密细节',p.text)
        self.assertFalse(p.unchanged)

    def test_exit_and_keyword_does_not_reopen(self):
        self.m.enter(self.a)
        self.m.build_context('退出工作')
        p=self.m.build_context('余忆项目的代码呢')
        self.assertEqual(p.work_ids,[])
        self.assertIsNone(self.m.current()['project_id'])

    def test_companion_mode_exits(self):
        self.m.enter(self.a)
        self.m.build_context('你好',mode='companion')
        self.assertIsNone(self.m.current()['project_id'])

    def test_mixed_requires_project(self):
        with self.assertRaises(ValueError): self.m.build_context('进入混合模式')
        with self.assertRaises(ValueError): self.m.build_context('你好',mode='work')
        self.m.enter(self.a)
        self.assertEqual(self.m.build_context('进入混合模式').mode,'mixed')

    def test_restart_and_sessions(self):
        self.m.enter(self.a)
        restarted=ProjectMemory(self.root/'data')
        self.assertIn(self.aid,restarted.build_context('继续').work_ids)
        other=ProjectMemory(self.root/'data',session='other')
        self.assertEqual(other.build_context('继续').work_ids,[])

    def test_missing_project_does_not_switch(self):
        self.m.enter(self.a)
        with self.assertRaises(KeyError): self.m.build_context('切换项目 不存在')
        self.assertEqual(self.m.current()['project_id'],self.a)

    def test_quotes_not_commands(self):
        self.m.build_context('文档写着“进入项目 余忆”')
        self.assertIsNone(self.m.current()['project_id'])

    def test_stale_summary_not_injected(self):
        p=self.m.build_context('余忆')
        self.assertNotIn('原型开发中',p.text)
        self.assertIn('旧进展摘要停用',p.text)

    def test_summary_refresh_and_version(self):
        self.m.update_overview(self.a,'调度完成，下一步修复写入',expected_version=1)
        self.assertIn('调度完成',self.m.build_context('余忆').text)
        with self.assertRaises(ConflictError):
            self.m.update_overview(self.a,'过期写入',expected_version=1)

    def test_deletion_invalidates_summary(self):
        self.m.update_overview(self.a,'调度完成',expected_version=1)
        self.m.work(self.a).transition(self.aid,'deleted',expected_version=1)
        self.assertNotIn('调度完成',self.m.build_context('余忆').text)

    def test_archived_active_project_auto_exits(self):
        self.m.enter(self.a)
        self.m.update_overview(self.a,'归档',expected_version=1,state='archived')
        self.assertEqual(self.m.build_context('继续').work_ids,[])
        with self.assertRaises(ValueError): self.m.enter(self.a)

    def test_write_requires_active_project(self):
        with self.assertRaises(ValueError): self.m.active_work()
        self.m.enter(self.b)
        rid=self.m.active_work().add('task','只写入B')
        self.assertEqual(self.m.work(self.b).get(rid)['content'],'只写入B')
        with self.assertRaises(KeyError): self.m.work(self.a).get(rid)

    def test_duplicate_name_case_insensitive(self):
        self.m.register('Demo','用途')
        with self.assertRaises(ConflictError): self.m.register('DEMO','用途')

    def test_attach_old_work(self):
        old=WorkMemory(self.root/'old',project='old')
        rid=old.add('goal','原有工作细节')
        pid=self.m.register('旧项目','继承数据',existing_directory=self.root/'old',existing_project='old')
        self.m.enter(pid)
        self.assertIn(rid,self.m.build_context('继续').work_ids)
        with self.assertRaises(ConflictError):
            self.m.register('重复挂载','用途',existing_directory=self.root/'old',existing_project='old')

    def test_attach_missing_does_not_create(self):
        with self.assertRaises(ValueError):
            self.m.register('错误','用途',existing_directory=self.root/'missing',existing_project='old')
        self.assertFalse((self.root/'missing').exists())

    def test_budget_many_overviews(self):
        for i in range(20): self.m.register('项目'+str(i),'用途'*40,summary='摘要'*60)
        self.assertLessEqual(self.m.build_context('项目列表',char_budget=1024).char_count,1024)
        self.m.enter(self.a)
        self.assertLessEqual(self.m.build_context('继续',char_budget=1024).char_count,1024)

    def test_handoff_only_selected_project(self):
        with self.assertRaises(ValueError): self.m.export_handoff(self.root/'HANDOFF.md')
        self.m.enter(self.a)
        path=self.root/'HANDOFF.md'
        self.m.export_handoff(path,char_budget=1500)
        body=path.read_text(encoding='utf-8')
        self.assertIn('项目名称：余忆',body)
        self.assertIn('A秘密细节',body)
        self.assertNotIn('B秘密细节',body)
        self.assertLessEqual(len(body),1500)

    def test_idle_overview_never_reads_record_bodies(self):
        with patch.object(WorkMemory,'list',side_effect=AssertionError('No bodies in idle')):
            self.assertIn('项目概况',self.m.build_context('余忆').text)

    def test_unchanged_full_packet(self):
        p=self.m.build_context('项目列表')
        self.assertTrue(self.m.build_context('项目列表',visible_context=p.text).unchanged)

    def test_invalid_input_no_switch(self):
        for budget in (True,100,2.5):
            with self.assertRaises(ValueError): self.m.build_context('进入项目 余忆',char_budget=budget)
        self.assertIsNone(self.m.current()['project_id'])


if __name__=='__main__': unittest.main()
