import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from work_memory import WorkMemory, ConflictError


class Tests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.m=WorkMemory(self.folder.name,'demo')

    def add(self,content='任务',**kwargs):
        return self.m.add(kwargs.pop('kind','task'),content,**kwargs)

    def test_reopen_keeps_project_details(self):
        rid=self.add('修复登录错误',brief='修复登录')
        self.assertEqual(WorkMemory(self.folder.name,'demo').get(rid)['content'],'修复登录错误')

    def test_project_isolation(self):
        rid=self.add('项目甲的资料')
        other=WorkMemory(self.folder.name,'other')
        self.assertFalse(other.list())
        with self.assertRaises(KeyError): other.get(rid)

    def test_key_conflict_is_not_silent_overwrite(self):
        self.m.add('decision','采用SQLite',key='storage')
        with self.assertRaises(ConflictError): self.m.add('decision','采用JSON',key='storage')

    def test_replace_retires_old_plan_atomically(self):
        old=self.m.add('decision','使用旧方案A',key='storage')
        new=self.m.replace(old,'使用新方案B',expected_version=1)
        packet=self.m.build_context()
        self.assertIn('新方案B',packet.text)
        self.assertNotIn('旧方案A',packet.text)
        self.assertEqual(self.m.get(old)['status'],'superseded')
        self.assertEqual(self.m.get(new)['supersedes'],old)

    def test_stale_update_rejected(self):
        rid=self.add()
        self.m.revise(rid,'新内容',expected_version=1)
        with self.assertRaises(ConflictError): self.m.revise(rid,'过时内容',expected_version=1)
        self.assertEqual(self.m.get(rid)['content'],'新内容')

    def test_done_keeps_only_result_and_is_not_default_context(self):
        rid=self.add('调试详细原文秘密ABC')
        self.m.transition(rid,'done',expected_version=1,summary='登录修复，回归通过')
        self.assertNotIn('秘密ABC',json.dumps(self.m.get(rid),ensure_ascii=False))
        self.assertNotIn('登录修复',self.m.build_context().text)
        self.assertIn('登录修复',self.m.build_context(include_done=True).text)

    def test_done_requires_explicit_summary(self):
        rid=self.add()
        with self.assertRaises(ValueError):self.m.transition(rid,'done',expected_version=1)
        self.assertEqual(self.m.get(rid)['status'],'active')

    def test_abandoned_is_excluded_even_when_similar(self):
        rid=self.add('采用MySQL进行存储')
        self.m.transition(rid,'abandoned',expected_version=1)
        self.assertNotIn('MySQL',self.m.build_context('MySQL',include_done=True).text)

    def test_abandoned_does_not_auto_reactivate(self):
        rid=self.add()
        self.m.transition(rid,'abandoned',expected_version=1)
        with self.assertRaises(ConflictError):self.m.transition(rid,'active',expected_version=2)

    def test_logical_deletion_removes_text_from_snapshot(self):
        rid=self.add('废弃秘密XYZ',brief='秘密XYZ',key='secretXYZ',source='secretXYZ')
        self.m.transition(rid,'deleted',expected_version=1)
        self.assertIsNone(self.m.get(rid)['content'])
        out=Path(self.folder.name)/'snapshot.json'
        self.m.export_snapshot(out)
        self.assertNotIn('XYZ',out.read_text(encoding='utf-8'))
        self.assertFalse(self.m.list(archived=True))

    def test_deleted_cannot_resurrect(self):
        rid=self.add()
        self.m.transition(rid,'deleted',expected_version=1)
        with self.assertRaises(ConflictError):self.m.transition(rid,'active',expected_version=2)

    def test_priority_then_urgency(self):
        later=self.add('重要但稍后做',priority=1,urgency=3)
        urgent=self.add('重要且立即做',priority=1,urgency=0)
        low=self.add('次要但紧急',priority=3,urgency=0)
        self.assertEqual([r['id'] for r in self.m.rank()],[urgent,later,low])

    def test_constraint_loaded_independent_of_query(self):
        self.m.add('constraint','不得修改生产数据库',priority=2)
        self.assertIn('不得修改生产数据库',self.m.build_context('样式').text)

    def test_required_content_does_not_use_lossy_brief(self):
        self.m.add('constraint','只改测试环境，绝不能改生产环境',brief='改环境')
        self.assertIn('绝不能改生产环境',self.m.build_context().text)

    def test_optional_item_uses_brief(self):
        self.add('冗长详细信息ABCD'*20,brief='短摘要')
        self.assertIn('短摘要',self.m.build_context().text)
        self.assertNotIn('ABCD',self.m.build_context().text)

    def test_budget_is_hard_and_reports_required_omissions(self):
        rid=self.m.add('constraint','重要约束'*200)
        packet=self.m.build_context(char_budget=256)
        self.assertLessEqual(len(packet.text),256)
        self.assertIn(rid,packet.required_omitted)
        self.assertIn('预算有限',packet.text)

    def test_long_optional_does_not_hide_short_optional(self):
        long=self.add('冗长内容'*500,priority=1)
        short=self.add('短任务',priority=2)
        packet=self.m.build_context(char_budget=256)
        self.assertIn(long,packet.omitted)
        self.assertIn(short,packet.included)

    def test_completed_summary_appears_in_handoff(self):
        rid=self.add('旧详细日志')
        self.m.transition(rid,'done',expected_version=1,summary='完成单元测试')
        path=Path(self.folder.name)/'handoff.md'
        self.m.export_handoff(path)
        text=path.read_text(encoding='utf-8')
        self.assertIn('完成单元测试',text)
        self.assertNotIn('旧详细日志',text)

    def test_handoff_refuses_incomplete_required_context(self):
        self.m.add('goal','必要目标'*2000)
        path=Path(self.folder.name)/'handoff.md'
        with self.assertRaises(ValueError):self.m.export_handoff(path,char_budget=256)
        self.assertFalse(path.exists())

    def test_snapshot_restore_preserves_versions_and_status(self):
        rid=self.add('阻塞于账号权限')
        self.m.transition(rid,'blocked',expected_version=1)
        path=Path(self.folder.name)/'snapshot.json'
        self.m.export_snapshot(path)
        with tempfile.TemporaryDirectory() as folder:
            other=WorkMemory(folder,'demo')
            other.import_snapshot(path)
            self.assertEqual(other.get(rid)['version'],2)
            self.assertEqual(other.get(rid)['status'],'blocked')

    def test_import_cannot_overwrite_existing_project(self):
        self.add()
        path=Path(self.folder.name)/'snapshot.json';self.m.export_snapshot(path)
        with self.assertRaises(ConflictError):self.m.import_snapshot(path)

    def test_bad_import_does_not_partially_write(self):
        path=Path(self.folder.name)/'snapshot.json'
        self.m.export_snapshot(path)
        data=json.loads(path.read_text(encoding='utf-8'));data['records']=[{'kind':'bad'}]
        path.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ValueError):self.m.import_snapshot(path)
        self.assertFalse(self.m.list())

    def test_import_duplicate_live_keys_rolls_back(self):
        self.m.add('decision','SQLite',key='storage')
        path=Path(self.folder.name)/'snapshot.json';self.m.export_snapshot(path)
        data=json.loads(path.read_text(encoding='utf-8'))
        duplicate=copy.deepcopy(data['records'][0]);duplicate['id']='a'*32
        data['records'].append(duplicate);path.write_text(json.dumps(data),encoding='utf-8')
        with tempfile.TemporaryDirectory() as folder:
            other=WorkMemory(folder,'demo')
            with self.assertRaises(sqlite3.IntegrityError):other.import_snapshot(path)
            self.assertFalse(other.list())

    def test_short_id_lookup_and_update(self):
        rid=self.add('任务甲')
        self.assertEqual(self.m.get(rid[:12])['id'],rid)
        self.m.transition(rid[:12],'blocked',expected_version=1)
        self.assertEqual(self.m.get(rid)['status'],'blocked')

    def test_bad_priority_rejected(self):
        with self.assertRaises(ValueError):self.add(priority=True)
        with self.assertRaises(ValueError):self.add(urgency=9)

    def test_blocked_is_still_current_work(self):
        rid=self.add('等待测试账号，阻塞联调')
        self.m.transition(rid,'blocked',expected_version=1)
        self.assertIn('blocked',self.m.build_context().text)

    def test_no_extra_model_or_transcript_needed(self):
        self.m.add('goal','发布一个可预览版本')
        first=self.m.build_context()
        second=self.m.build_context()
        self.assertEqual(first,second)


if __name__=='__main__':unittest.main(verbosity=2)
