"""Loopback-only test server for the real baropy SDK; no actual NLP model."""
import http.server
import json
import os
from pathlib import Path
import sys
import threading

hello = json.loads(sys.stdin.readline())
root = Path(os.environ['BAREUN_ROOT'])
(root / 'var' / 'models').mkdir(parents=True, exist_ok=True)
(root / 'var' / 'models' / 'stub-model').write_bytes(b'model fixture')


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.headers.get('X-Baropy-Token') != hello['token']:
            self.send_response(401); self.end_headers(); return
        if self.path == '/bareun/register':
            (root / 'var' / 'api-keys.db.pb').write_bytes(body)
            data = b'{}'
        else:
            data = json.dumps({'sentences': [{'tokens': [{'morphemes': [
                {'text': {'content': '밥'}, 'tag': 'NNG'}]}]}]}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
print('READY', server.server_port, flush=True)


def eof():
    sys.stdin.read()
    server.shutdown()


threading.Thread(target=eof, daemon=True).start()
server.serve_forever()
