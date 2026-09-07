"""Official FoxGTP -> AI Engine TCP mode, not the FoxClient wire protocol."""
import re
import socket
import threading


class FoxGTPServer:
    def __init__(self, app, port):
        self.app = app
        self.stopped = threading.Event()
        self.client = None
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.bind(('127.0.0.1',port))
            self.socket.listen(1)
            self.socket.settimeout(.5)
        except Exception:
            self.socket.close()
            raise

    def start(self):
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.stopped.is_set():
            try:
                client, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if self.stopped.is_set() or self.client:
                client.close()
                continue
            self.client = client
            self.app.fox_connected = True
            self.app.fox_ready = False
            self.app.log('fox', 'FoxGTP connected. Awaiting clear_board / game synchronization.')
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client):
        pending = b''
        try:
            while not self.stopped.is_set():
                chunk = client.recv(4096)
                if not chunk:
                    break
                pending += chunk
                if len(pending) > 65536:
                    raise ValueError('FoxGTP input exceeds 64 KiB.')
                while b'\n' in pending:
                    raw, pending = pending.split(b'\n',1)
                    line = raw.decode('ascii').split('#',1)[0].strip()
                    if not line:
                        continue
                    match = re.fullmatch(r'(\d*)\s*([a-zA-Z_][^\r\n]*)',line)
                    if not match:
                        client.sendall(b'? malformed command\n\n')
                        continue
                    ident, command = match.groups()
                    self.app.log('fox →', line)
                    with self.app.operation:
                        if self.stopped.is_set():
                            return
                        self.app.busy = 'FoxGTP: ' + command.split()[0]
                        try:
                            result = relay_command(self.app, command)
                            response = f'={ident} {result}\n\n'
                        except Exception as exc:
                            response = f'?{ident} {str(exc).replace(chr(10), " ")}\n\n'
                            self.app.log('error', str(exc))
                        finally:
                            self.app.busy = ''
                    # Respond before disk IO so time_left/genmove stays responsive.
                    client.sendall(response.encode('utf-8'))
                    self.app.log('fox ←', response.strip())
                    with self.app.operation:
                        self.app.save()
                    if command.split()[0].lower() == 'quit':
                        return
        except (OSError, ValueError) as exc:
            if not self.stopped.is_set():
                self.app.log('fox', f'Connection ended: {exc}')
        finally:
            client.close()
            self.client = None
            if self.app.fox_server is self:
                self.app.fox_connected = self.app.fox_ready = False
                self.app.log('fox', 'FoxGTP disconnected. Reconnect and synchronize to resume.')

    def stop(self):
        self.stopped.set()
        self.socket.close()
        client = self.client
        if client:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()

from copy import deepcopy
import math
from .board import Board, color

def relay_command(self, command):
    """Called with operation lock held. Never inject review searches into Fox time."""
    fields = command.split()
    if not fields:
        raise ValueError('Empty command.')
    verb, args = fields[0].lower(), fields[1:]
    allowed = {'protocol_version','name','version','list_commands','known_command','quit',
               'clear_board','boardsize','komi','time_settings','time_left','set_free_handicap',
               'play','genmove','final_score','showboard'}
    if verb not in allowed:
        raise ValueError('unknown command')
    if verb == 'quit':
        return ''
    if verb == 'list_commands':
        return '\n'.join(sorted(allowed))
    if verb == 'known_command':
        return 'true' if len(args) == 1 and args[0] in allowed else 'false'
    if verb in ('play','genmove','set_free_handicap') and not self.fox_ready:
        raise ValueError('Send clear_board before starting or restoring a game.')
    engine = self.require_engine()
    if verb == 'genmove':
        if len(args) != 1:
            raise ValueError('genmove requires a color')
        return self.generate(args[0])
    candidate = None
    if verb == 'boardsize':
        candidate = Board(int(args[0]),self.board.komi,self.board.rules)
    elif verb == 'clear_board':
        candidate = Board(self.board.size,self.board.komi,self.board.rules)
    elif verb == 'komi':
        value = float(args[0])
        if not math.isfinite(value) or abs(value) > 100:
            raise ValueError('Invalid komi')
        candidate = deepcopy(self.board)
        candidate.komi = value
    elif verb == 'set_free_handicap':
        candidate = deepcopy(self.board)
        candidate.setup([v.upper() for v in args])
    elif verb == 'play':
        if len(args) != 2:
            raise ValueError('play requires color and vertex')
        candidate = deepcopy(self.board)
        candidate.play(color(args[0]),args[1], authoritative=True)
    response = engine.command(command)
    if candidate:
        self.commit_board(candidate)
    if verb in ('clear_board','boardsize','komi','set_free_handicap'):
        self.evaluations = {}
        self.analyses = {}
    if verb == 'clear_board':
        self.fox_ready = True
    if verb == 'final_score':
        self.log('fox score', response)
    return response

