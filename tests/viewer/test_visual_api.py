"""Integration checks against a temporary SQLite ledger; no personal data."""
import http.client
from http.server import HTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'viewer'))
from serve_neural import build_memory, make_handler


class VisualAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.memory = build_memory(Path(cls.temp.name), demo=True)
        cls.server = HTTPServer(('127.0.0.1', 0), make_handler(cls.memory))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, path, data=None, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        conn.request('POST' if data is not None else 'GET', path,
                     json.dumps(data) if data is not None else None, headers)
        r = conn.getresponse()
        body = r.read()
        status = r.status
        conn.close()
        return status, json.loads(body) if path.startswith('/api/') else body

    def test_state_and_static(self):
        status, state = self.request('/api/state')
        self.assertEqual(status, 200)
        self.assertEqual(state['engine'], 'yuyi-python')
        self.assertGreaterEqual(len(state['memories']), 8)
        self.assertEqual(self.request('/')[0], 200)

    def test_real_association(self):
        status, result = self.request('/api/recall', {'query': '加班'})
        self.assertEqual(status, 200)
        self.assertTrue(any(len(row['path']) > 1 for row in result['results']))
        self.assertTrue(any('十一点' in row['text'] for row in result['results']))

    def test_write_suppress_delete(self):
        status, result = self.request('/api/remember', {'text': '测试彗星落在紫铜星港', 'keywords': ['彗星', '星港'], 'importance': 8})
        self.assertEqual(status, 200)
        mid = result['id']
        rows = self.request('/api/recall', {'query': '彗星'})[1]['results']
        self.assertIn(mid, [r['id'] for r in rows])
        self.request('/api/suppress', {'id': mid, 'value': True})
        self.assertNotIn(mid, [r['id'] for r in self.request('/api/recall', {'query': '彗星'})[1]['results']])
        self.request('/api/delete', {'id': mid})
        self.assertNotIn(mid, [r['id'] for r in self.request('/api/state')[1]['memories']])

    def test_reject_external_origin_and_invalid_write(self):
        self.assertEqual(self.request('/api/recall', {'query': '加班'}, 'https://external.example')[0], 403)
        self.assertEqual(self.request('/api/remember', {'text': '', 'importance': 99})[0], 400)


if __name__ == '__main__':
    unittest.main()
