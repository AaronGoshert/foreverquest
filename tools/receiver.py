"""Tiny local HTTP sink so browser-side scraping JS can save JSON into data/.

Run:  python tools/receiver.py   (listens on 127.0.0.1:8765)
From the page:  fetch('http://127.0.0.1:8765/save?path=wowhead/list/1-10.json',
                      {method: 'POST', body: JSON.stringify(obj)})
Paths are relative to data/ and may not escape it. GET /has?path=... returns 1/0
so scrapers can skip pages that are already cached.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')


def resolve(query):
    rel = parse_qs(query).get('path', [''])[0]
    full = os.path.realpath(os.path.join(DATA, rel))
    if not rel or not full.startswith(os.path.realpath(DATA) + os.sep):
        return None
    return full


class Handler(BaseHTTPRequestHandler):
    def cors(self):
        self.send_header('Access-Control-Allow-Origin', 'https://www.wowhead.com')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def reply(self, code, body=b''):
        self.send_response(code)
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.reply(204)

    def do_GET(self):
        u = urlparse(self.path)
        full = resolve(u.query)
        if u.path == '/has' and full:
            return self.reply(200, b'1' if os.path.exists(full) else b'0')
        self.reply(404)

    def do_POST(self):
        u = urlparse(self.path)
        full = resolve(u.query)
        if u.path != '/save' or not full:
            return self.reply(400, b'bad path')
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        try:
            obj = json.loads(body)
        except ValueError:
            return self.reply(400, b'bad json')
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        print('saved', os.path.relpath(full, DATA), len(body), 'bytes', flush=True)
        self.reply(200, b'ok')

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    print('receiver on http://127.0.0.1:8765 ->', DATA, flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
