#!/usr/bin/env python3
"""Простой статический сервер для превью (порт берёт из env PORT)."""
import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PORT = int(os.environ.get('PORT', 8431))
ROOT = os.path.dirname(os.path.abspath(__file__))

class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)
    def log_message(self, *a):
        pass

if __name__ == '__main__':
    print(f'serving {ROOT} on http://localhost:{PORT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
