"""Official FoxGTP -> AI Engine TCP mode, not the FoxClient wire protocol."""
import re
import socket
import threading


class FoxServer:
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
            if self.client:
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
                            result = self.app.fox_command(command)
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
            self.app.fox_connected = self.app.fox_ready = False
            self.app.log('fox', 'FoxGTP disconnected. Reconnect and synchronize to resume.')

    def stop(self):
        self.stopped.set()
        self.socket.close()
        if self.client:
            try:
                self.client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.client.close()
