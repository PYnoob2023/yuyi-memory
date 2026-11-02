import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.project=Path(__file__).resolve().parents[2]

    def call(self,*args):
        return subprocess.run([sys.executable,'-m','yuyi_self','--db',str(self.root/'self.sqlite3'),'--assistant','trial',*args],
                              cwd=self.project,capture_output=True,encoding='utf-8',
                              env={**os.environ,'PYTHONIOENCODING':'utf-8'})

    def test_init_show_and_report(self):
        self.assertEqual(self.call('init').returncode,0)
        self.assertEqual(json.loads(self.call('show').stdout)['default_mode'],'observe')
        out=self.root/'report.md';r=self.call('report','--out',str(out))
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('观察报告',out.read_text(encoding='utf-8'))

    def test_complete_manual_trial(self):
        for i in range(3):
            f=self.root/'e.json';f.write_text(json.dumps({'id':f'e{i}','occurrence_id':f'case{i}','session_id':'trial',
                'occurred_at':1700000000+i*43200,'scope':'debugging','kind':'verified_outcome','verified':True}),encoding='utf-8')
            self.assertEqual(self.call('evidence',str(f)).returncode,0)
        f=self.root/'p.json';f.write_text(json.dumps({'key':'debugging.check','category':'habit','scope':'debugging',
            'statement':'在排查代码时，我倾向先核实日志。','support_ids':['e0','e1','e2']}),encoding='utf-8')
        cid=json.loads(self.call('propose',str(f),'--author','trial').stdout)['id']
        r=self.call('review',cid,'approve','--version','1','--reviewer','trial')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(self.call('reference','--scope','debugging').stdout)['text'],'')
        self.assertTrue(json.loads(self.call('reference','--scope','debugging','--enable').stdout)['text'])

    def test_bad_input_fails(self):
        f=self.root/'bad.json';f.write_text('{}',encoding='utf-8')
        self.assertNotEqual(self.call('evidence',str(f)).returncode,0)


if __name__=='__main__':unittest.main()
