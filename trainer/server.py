"""Loopback-only HTTP server. No third-party Python dependencies."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from .app import Trainer, ROOT


def create_server(app, port=8173):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def valid_host(self):
            return self.headers.get('Host') in (
                f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

        def send(self, status, content, mime='application/json; charset=utf-8'):
            body = content if isinstance(content, bytes) else content.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if not self.valid_host():
                return self.send(403,'{"error":"Invalid host"}')
            route = urlsplit(self.path).path
            if route == '/api/state':
                return self.send(200,json.dumps({**app.state(), 'token':token},ensure_ascii=False))
            if route == '/api/sgf':
                with app.state_lock:
                    sgf = app.board.sgf()
                return self.send(200,sgf,'application/x-go-sgf; charset=utf-8')
            if route == '/api/vision-image':
                if not app.vision or not app.vision.preview:return self.send(404,'{}')
                return self.send(200,app.vision.preview,'image/png')
            if route == '/api/logs':
                return self.send(200,json.dumps(app.state()['logs'],indent=2,ensure_ascii=False))
            static = {'/':'index.html','/app.js':'app.js','/style.css':'style.css','/vision.js':'vision.js'}
            if route not in static:
                return self.send(404,'{"error":"Not found"}')
            path = ROOT / 'web' / static[route]
            mime = {'.html':'text/html','.js':'text/javascript','.css':'text/css'}[path.suffix]
            self.send(200,path.read_bytes(),mime+'; charset=utf-8')

        def do_POST(self):
            origin = self.headers.get('Origin')
            expected = {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
            if not self.valid_host() or (origin and origin not in expected) or self.headers.get('X-Trainer-Token') != token:
                return self.send(403,'{"error":"Invalid origin or session token"}')
            try:
                length = int(self.headers.get('Content-Length','0'))
                if length < 0 or length > 65536:
                    return self.send(413,'{"error":"Request too large"}')
                data = json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(data,dict):
                    raise ValueError('Expected a JSON object.')
                route = urlsplit(self.path).path
                if not route.startswith('/api/action/'):
                    return self.send(404,'{"error":"Not found"}')
                result = app.action(route.removeprefix('/api/action/'),data)
                self.send(200,json.dumps({**result,'token':token},ensure_ascii=False))
            except (ValueError, RuntimeError, OSError, IndexError, TypeError) as exc:
                self.send(400,json.dumps({'error':str(exc)}))
            except Exception as exc:
                app.log('error',f'Unexpected server error: {exc}')
                self.send(500,'{"error":"Unexpected error. See diagnostic log."}')

    server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description='Personal KataGo trainer with direct FoxGo TCP connection')
    parser.add_argument('--port',type=int,default=8173)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    args = parser.parse_args()
    app = Trainer(args.data_dir)
    server = create_server(app,args.port)
    try:
        print('Starting KataGo automatically. Initial GPU setup may take a minute...',flush=True)
        app.ensure_engine()
        print(f'FoxGo KataGo trainer: http://127.0.0.1:{server.server_port} — KataGo ready',flush=True)
        print('Press Ctrl+C to stop.',flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, ValueError, OSError) as exc:
        print(f'Backend startup failed: {exc}',flush=True)
        raise SystemExit(1)
    finally:
        server.server_close()
        app.close()


if __name__ == '__main__':
    main()
