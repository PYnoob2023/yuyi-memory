import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.project=Path(__file__).resolve().parents[2]

    def command(self,*args):
        return subprocess.run([sys.executable,'-m','yuyi_emotion','--db',str(self.root/'emotion.sqlite3'),*args],
                              cwd=self.project,encoding='utf-8',capture_output=True,
                              env={**__import__('os').environ,'PYTHONIOENCODING':'utf-8'})

    def test_init_and_status(self):
        result=self.command('init')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['ready'])
        result=self.command('status','--at','2026-11-02T00:00:00+09:00')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['description']['label'],'平静')

    def test_event_replay_retract_restore(self):
        result=self.command('event',str(self.project/'examples/emotion/shared_success.json'))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['accepted'])
        result=self.command('status','--at','2026-11-03T00:00:00+09:00')
        self.assertIn('轻快',json.loads(result.stdout)['description']['tendency']['tone'])
        for args in [('retract','demo-success-001'),('restore','demo-success-001'),
                     ('replay','--at','2026-11-03T00:00:00+09:00')]:
            result=self.command(*args)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_atlas_does_not_create_database(self):
        result=self.command('atlas','--resolution','3')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['resolution'],3)
        self.assertFalse((self.root/'emotion.sqlite3').exists())

    def test_naive_iso_timestamp_rejected(self):
        result=self.command('status','--at','2026-11-02T00:00:00')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('timezone',result.stderr)

    def test_malformed_event_and_config_do_not_fake_success(self):
        bad=self.root/'bad.json';bad.write_text('{"impact":0}',encoding='utf-8')
        result=self.command('event',str(bad))
        self.assertNotEqual(result.returncode,0)


if __name__=='__main__':
    unittest.main()
