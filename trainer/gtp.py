"""ID-aware GTP framing, bounded subprocess lifecycle and analysis parsing."""
import queue
import re
import subprocess
import threading
import time


class EngineError(RuntimeError):
    pass


def parse_analysis(line):
    """Read extensible KataGo key/value fields without assuming field order."""
    moves = []
    root = {}
    ownership = []
    parts = re.split(r'\b(info|rootInfo|ownership|ownershipStdev)\s+', line)
    for i in range(1, len(parts)-1, 2):
        kind, values = parts[i], parts[i+1].split()
        if kind == 'ownership':
            ownership = [float(v) for v in values]
            continue
        if kind not in ('info', 'rootInfo'):
            continue
        data = {}
        j = 0
        while j < len(values)-1:
            key, val = values[j:j+2]
            if key == 'pv':
                pv = []
                for v in values[j+1:]:
                    if re.fullmatch(r'[A-HJ-T][0-9]+|pass|resign', v, re.I):
                        pv.append(v.upper())
                    else:
                        break
                data['pv'] = pv
                j += len(pv)+1
                continue
            try:
                data[key] = float(val)
            except ValueError:
                data[key] = val.upper() if key == 'move' else val
            j += 2
        if kind == 'info' and 'move' in data:
            moves.append(data)
        elif kind == 'rootInfo':
            root = data
    moves.sort(key=lambda m: m.get('order', 999))
    return dict(choices=moves, root=root or (moves[0] if moves else {}), ownership=ownership)


class GTP:
    def __init__(self, command, log=lambda *args: None, timeout=120):
        self.log, self.timeout = log, timeout
        self.next_id = 0
        self.lock = threading.Lock()
        self.lines = queue.Queue()
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()

    @property
    def alive(self):
        return self.process.poll() is None

    def _reader(self):
        for line in self.process.stdout:
            self.lines.put(line.rstrip('\r\n'))
        self.lines.put(None)

    def _stderr(self):
        for line in self.process.stderr:
            self.log('engine', line.rstrip())

    def command(self, command, on_analysis=None):
        if '\n' in command or '\r' in command:
            raise ValueError('GTP commands must be a single line.')
        with self.lock:
            if not self.alive:
                raise EngineError('KataGo is not running. Check the engine log and reconnect.')
            self.next_id += 1
            ident = str(self.next_id)
            self.log('gtp →', f'{ident} {command}')
            try:
                self.process.stdin.write(f'{ident} {command}\n')
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise EngineError('KataGo input closed.') from exc
            deadline = time.monotonic() + self.timeout
            started, success, payload = False, False, []
            while True:
                try:
                    line = self.lines.get(timeout=max(.01, deadline-time.monotonic()))
                except queue.Empty:
                    self.close()
                    raise EngineError('KataGo timed out; process stopped to prevent desynchronization.')
                if line is None:
                    raise EngineError('KataGo exited before completing its response.')
                if not started:
                    match = re.match(r'^([=?])(\d*)\s*(.*)$', line)
                    if not match:
                        self.log('engine stdout', line)
                        continue
                    if match[2] != ident:
                        self.close()
                        raise EngineError('KataGo response ID mismatch; engine stopped.')
                    started, success = True, match[1] == '='
                    if match[3]:
                        payload.append(match[3])
                elif not line.strip():
                    result = '\n'.join(payload)
                    self.log('gtp ←', ('=' if success else '?') + ident + ' ' + result[:1200])
                    if not success:
                        raise EngineError(result or 'KataGo rejected the command.')
                    return result
                else:
                    if line.startswith('info ') and on_analysis:
                        on_analysis(parse_analysis(line))
                    else:
                        payload.append(line)

    def close(self):
        if self.alive:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except OSError:
                pass
