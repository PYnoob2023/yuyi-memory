"""Loopback-only visual UI for the sibling memory-scheduler project. Stdlib only."""
from argparse import ArgumentParser
from functools import partial
from http.server import SimpleHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from companion_memory import CompanionMemory


def build_memory(directory, demo=False):
    memory = CompanionMemory(directory)
    if demo and not memory.episodes and not memory.state['pending']:
        entries = [
            ('蓝桥公司加班后在河边谈过项目', ['蓝桥', '加班', '项目'], 8),
            ('蓝桥旧约定是晚上十一点休息', ['蓝桥', '约定', '休息'], 9),
            ('一起去海边看日出，远处的灯塔一直亮着', ['海边', '日出', '灯塔'], 9),
            ('收到一张灯塔明信片，写着下次还去看海', ['灯塔', '海边', '明信片'], 7),
            ('下雨天在街角小店喝热咖啡', ['咖啡', '小店', '下雨'], 6),
            ('小店靠窗的位置很安静，适合写作', ['小店', '安静', '写作'], 6),
            ('余忆的第一个记忆项目原型完成了', ['余忆', '记忆', '项目'], 9),
            ('讨论科幻神经元，想把记忆做成星空', ['科幻', '记忆', '星空'], 8),
        ]
        for text, cues, importance in entries:
            memory.remember(text, importance, anchors=cues)
    return memory


def make_handler(memory):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT/'dist'), **kwargs)

        def allowed(self):
            port = self.server.server_port
            allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
            origin = self.headers.get('Origin')
            return self.headers.get('Host') in allowed and (
                origin is None or origin in {f'http://{host}' for host in allowed})

        def reply(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed():
                return self.reply({'error': 'Invalid local origin'}, 403)
            if urlparse(self.path).path == '/api/state':
                with memory._atomic():
                    memory.decay()
                    rows = []
                    for m in memory.episodes:
                        rows.append({**m, 'text': m['text'] or m['gist'] or m['impression'],
                                     'title': (m['text'] or m['gist'] or m['impression'])[:20],
                                     'keywords': list(dict.fromkeys(m.get('keywords', [])+m.get('anchors', []))),
                                     'retention': memory.retention(m)})
                return self.reply({'engine': 'yuyi-python', 'memories': rows})
            if self.path.startswith('/api/'):
                return self.reply({'error': 'Unknown API'}, 404)
            return super().do_GET()

        def do_POST(self):
            if not self.allowed():
                return self.reply({'error': 'Invalid local origin'}, 403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 20000:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected object')
                if self.path == '/api/recall':
                    query = data.get('query')
                    if not isinstance(query, str) or len(query) > 500:
                        raise ValueError('Invalid query')
                    rows = memory.recall_for_scheduler(query, char_budget=1000, limit=3, explain=True)
                    return self.reply({'results': rows})
                if self.path == '/api/remember':
                    text = data.get('text')
                    keywords = data.get('keywords', [])
                    importance = data.get('importance', 8)
                    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                        raise ValueError('Expected 1..1000 characters')
                    if isinstance(importance, bool) or not isinstance(importance, int) or not 3 <= importance <= 10:
                        raise ValueError('Importance must be 3..10')
                    if not isinstance(keywords, list) or len(keywords) > 12 or any(not isinstance(x, str) or not 2 <= len(x) <= 40 for x in keywords):
                        raise ValueError('Invalid keywords')
                    # Use existing grounding rule: only cues occurring in text become anchors.
                    mid = memory.remember(text, importance, anchors=keywords)
                    return self.reply({'id': mid})
                if self.path in ('/api/suppress', '/api/delete'):
                    mid = data.get('id')
                    m = next((m for m in memory.episodes if m['id'] == mid), None)
                    if m is None:
                        return self.reply({'error': 'Memory no longer exists'}, 404)
                    if self.path == '/api/suppress':
                        value = data.get('value')
                        if not isinstance(value, bool):
                            raise ValueError('value must be bool')
                        memory.suppress(mid, value)
                    else:
                        # Keep the original erasure rules, including matching chat queues.
                        memory.forget(m['text'] or m['gist'] or m['impression'])
                    return self.reply({'ok': True})
                return self.reply({'error': 'Unknown API'}, 404)
            except (ValueError, KeyError, TypeError) as error:
                return self.reply({'error': str(error)}, 400)
            except Exception as error:
                return self.reply({'error': type(error).__name__ + ': ' + str(error)}, 409)

    return Handler


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data', type=Path, help='Existing or new companion-memory data directory')
    args = parser.parse_args()
    memory = build_memory(args.data or ROOT/'runtime_data', demo=args.data is None)
    server = HTTPServer(('127.0.0.1', args.port), make_handler(memory))
    print(f'Neural memory ready: http://127.0.0.1:{args.port}', flush=True)
    print('Mode: Python SQLite ledger. Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
