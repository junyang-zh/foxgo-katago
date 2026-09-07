"""Direct FoxGo TCP controller. No FoxGTP process is needed.

A reader receives during searches and invalidates stale results. Search never
changes KataGo's board: only moves confirmed by FoxGo are committed.
"""
from copy import deepcopy
import queue
import re
import socket
import threading
import time
from .board import Board
from .fox_protocol import (Framer, Rules, decode, encode, flag, integer,
    move_record, other, outgoing_move, score_from_fox, score_to_fox, side)


class FoxGame:
    """One connection's state; caller holds Trainer.operation for engine access."""
    def __init__(self,app,send):
        self.app,self.send = app,send
        self.rules = self.ai = self.pending = None
        self.in_game = self.synced = self.want_move = False
        self.index = 0
        self.records = {}
        self.main = self.byo = self.periods = 0
        self.clock_received = self.requested_status = False

    def publish(self,status=''):
        with self.app.state_lock:
            self.app.fox_ready = self.synced
            self.app.fox_game = dict(inGame=self.in_game,aiColor=self.ai,lastIndex=self.index,
                pendingMove=self.pending[2] if self.pending else None,
                mainTime=round(self.main,2),byoTime=self.byo,periods=self.periods,
                status=status or ('Playing' if self.in_game else 'Connected · idle'))

    def resync(self,reason):
        self.synced = self.want_move = False
        self.pending = None
        self.app.log('warning',f'FoxGo synchronization needed: {reason}')
        self.publish('Waiting for game snapshot')
        if self.ai and not self.requested_status:
            self.send(encode('AFSTATUS',self.ai))
            self.requested_status = True

    def _clock(self):
        engine = self.app.require_engine()
        reserve = self.app.fox_reserve
        if self.periods and self.byo:
            seconds = max(.05,self.byo-min(reserve,self.byo/2))
            engine.command(f'kgs-time_settings byoyomi {self.main} {seconds} {self.periods}')
            remaining = max(.01,self.main-reserve) if self.main else seconds
            engine.command(f'time_left {self.ai} {remaining} {0 if self.main else self.periods}')
        else:
            engine.command(f'kgs-time_settings absolute {max(.01,self.main-reserve)}')
            engine.command(f'time_left {self.ai} {max(.01,self.main-reserve)} 0')

    def _apply(self,c,vertex,index=None):
        candidate = deepcopy(self.app.board)
        if candidate.turn != c:
            raise ValueError('Move color disagrees with the confirmed board turn.')
        candidate.play(c,vertex)
        self.app.require_engine().command(f'play {c} {vertex}')
        self.app.commit_board(candidate)
        if index is not None:
            self.index = index
            self.records[index] = (c,vertex)

    def _turn(self,ours):
        expected = self.ai if ours else other(self.ai)
        if self.app.board.turn != expected and not self.app.board.result:
            raise ValueError('FoxGo turn flag disagrees with the move sequence.')
        self.want_move = ours and not self.pending and not self.app.board.result

    def handle(self,command,args):
        if command == 'FARULE':
            self.rules = Rules.parse(args)
            self.synced = self.in_game = self.want_move = False
            self.pending = None
            self.records = {}
            self.index = 0
            self.clock_received = self.requested_status = False
            self.main,self.byo,self.periods = self.rules.main,self.rules.byo,self.rules.periods
            self.publish('Rules received · waiting for game snapshot')
            return
        if command == 'FASTATUS':
            if not args:
                raise ValueError('FASTATUS requires a game-state flag.')
            if not flag(args[0]):
                if len(args) != 1:
                    raise ValueError('Idle FASTATUS must not include moves.')
                self.in_game = self.want_move = False
                self.pending = None
                self.synced = True
                self.requested_status = False
                self.publish()
                return
            if len(args) < 2:
                raise ValueError('Active FASTATUS requires the AI color.')
            self.ai = side(args[1])
            if not self.rules:
                raise ValueError('FARULE must precede a game snapshot. Reconnect FoxGo.')
            r = self.rules
            moves = [move_record(v,r.size) for v in args[2:]]
            records = {}
            for i,c,v in moves:
                if i != len(records)+1:
                    raise ValueError('Snapshot has missing or duplicate move indexes.')
                records[i] = (c,v)
            # A same-connection snapshot can omit unindexed FASKIP events. Keep
            # known pass history if all indexed stones match the confirmed game.
            same = self.in_game and self.records == records and self.app.board.size == r.size
            if not same:
                board = Board(r.size,r.komi,'chinese')
                board.setup(r.handicap)
                for _,c,v in moves:
                    if board.turn != c:
                        raise ValueError('Snapshot has an ambiguous turn/pass history.')
                    board.play(c,v)
                try:
                    self.app.reset_engine(board)
                except Exception:
                    if self.app.engine:
                        self.app.engine.close()
                    raise
                self.app.commit_board(board)
                self.app.evaluations = {}
                self.app.analyses = {}
            self.records,self.index = records,(moves[-1][0] if moves else 0)
            self.pending = None
            self.synced = self.in_game = True
            self.want_move = False  # Only FAMOVE/FASKIP authorizes an AI reply.
            self.requested_status = False
            self.publish('Snapshot synchronized · waiting for turn notice')
            return
        if command == 'FARESULT':
            if len(args) != 1:
                raise ValueError('FARESULT requires one result.')
            result = score_from_fox(args[0])
            if not self.in_game:
                return
            with self.app.state_lock:
                self.app.board.result = result
                self.app.board.history[-1]['result'] = result
            self.in_game = self.want_move = False
            self.pending = None
            self.publish('Finished · '+result)
            self.app.log('fox score',result)
            return
        if command == 'FASCORE':
            if len(args) != 1:
                raise ValueError('FASCORE requires the applicant flag.')
            applicant = int(flag(args[0]))
            result = 'error'
            if self.in_game and self.synced and not self.pending:
                try:
                    result = score_to_fox(self.app.require_engine().command('final_score'))
                except RuntimeError as exc:
                    self.app.log('error',str(exc))
            self.send(encode('AFSCORE',applicant,result))
            return
        if not self.in_game or not self.synced:
            raise ValueError('Game snapshot is not synchronized.')
        if command == 'FATIMELEFT':
            if len(args) != 3:
                raise ValueError('FATIMELEFT requires main time, byo-yomi and periods.')
            main,byo,periods = (integer(v) for v in args)
            if bool(byo) != bool(periods):
                raise ValueError('Invalid byo-yomi clock.')
            self.main,self.byo,self.periods = main,byo,periods
            self.clock_received = True
            self.publish()
            return
        if command not in ('FAMOVE','FASKIP') or len(args) != (3 if command=='FAMOVE' else 2):
            raise ValueError('Invalid move notification.')
        ours,ai = flag(args[0]),side(args[1])
        if ai != self.ai:
            raise ValueError('AI color changed without a new game snapshot.')
        if command == 'FAMOVE':
            record = move_record(args[2],self.rules.size,sentinel=True)
            if record is None:
                if self.app.board.moves:
                    raise ValueError('Empty-board notice received for a nonempty game.')
            else:
                index,c,vertex = record
                if index in self.records:
                    if self.records[index] != (c,vertex):
                        raise ValueError('Conflicting move at an existing index.')
                    if index != self.index:
                        return
                else:
                    if index != self.index+1:
                        raise ValueError('Move index gap; requesting a complete snapshot.')
                    self._apply(c,vertex,index)
                    self.pending = None
        else:
            c = other(ai) if ours else ai
            if not (self.app.board.moves and self.app.board.moves[-1] == [c,'PASS']):
                self._apply(c,'PASS')
                self.pending = None
        self._turn(ours)
        self.publish()

    def search(self,changed):
        if not (self.in_game and self.synced and self.want_move and not self.pending and self.clock_received):
            return None
        if self.main <= 0 and not self.periods:
            raise ValueError('FoxGo reports no remaining time.')
        self._clock()
        engine = self.app.require_engine()
        budget = self.main if self.main > 0 else self.byo
        budget = max(.01,budget-min(self.app.fox_reserve,budget/2))
        engine.command(f'kata-set-param maxTime {min(self.app.settings["seconds"],budget)}')
        started = time.monotonic()
        reply = engine.command(
            f'kata-search_analyze_cancellable {self.ai} 25 maxmoves 8 rootInfo true ownership true',
            self.app.receive_analysis,cancel_event=changed)
        if self.main:
            self.main = max(0,self.main-(time.monotonic()-started)-self.app.fox_reserve)
        if changed.is_set():
            return None
        match = re.search(r'^play (\S+)\s*$',reply,re.M)
        if not match:
            raise ValueError('KataGo did not return a search result.')
        if match[1].lower() == 'cancelled' or changed.is_set():
            return None
        vertex = match[1].upper()
        if vertex == 'PASS':
            packet = encode('AFSKIP',self.ai)
        elif vertex == 'RESIGN':
            packet = encode('AFGIVEUP',self.ai)
        else:
            check = deepcopy(self.app.board)
            check.play(self.ai,vertex)
            packet = outgoing_move(self.index+1,self.ai,vertex,self.rules.size)
        return packet,(self.index+1,self.ai,vertex)


class FoxConnection:
    def __init__(self,server,client):
        self.server,self.app,self.client = server,server.app,client
        self.stopped = threading.Event()
        self.changed = threading.Event()
        self.ingest = threading.Lock()
        self.inbox = queue.Queue(maxsize=256)
        self.game = FoxGame(self.app,self.send)
        self.reader = threading.Thread(target=self._read,daemon=True)
        self.worker = threading.Thread(target=self._work,daemon=True)

    def start(self):
        self.reader.start()
        self.worker.start()

    def send(self,packet):
        if self.stopped.is_set():
            raise ConnectionError('FoxGo disconnected.')
        self.client.sendall(packet)
        self.app.log('fox ←',packet.decode('ascii').strip())

    def _read(self):
        framer = Framer()
        try:
            while not self.stopped.is_set():
                try:
                    chunk = self.client.recv(8192)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                for packet in framer.feed(chunk):
                    try:
                        message = decode(packet)
                    except ValueError as exc:
                        message = ('INVALID',[str(exc)])
                    self.app.log('fox →',packet.decode('ascii',errors='replace').strip())
                    with self.ingest:
                        self.changed.set()
                        self.inbox.put_nowait(message)
        except (OSError,ValueError,queue.Full) as exc:
            if not self.stopped.is_set():
                self.app.log('error',f'FoxGo input stopped: {exc}')
        finally:
            self.stop()

    def _work(self):
        try:
            while not self.stopped.is_set():
                try:
                    command,args = self.inbox.get(timeout=.1)
                except queue.Empty:
                    continue
                with self.app.operation:
                    if self.stopped.is_set():
                        break
                    self.app.busy = 'FoxGo: '+command
                    try:
                        if command == 'INVALID':
                            raise ValueError(args[0])
                        self.game.handle(command,args)
                    except (ValueError,RuntimeError) as exc:
                        self.game.resync(str(exc))
                    with self.ingest:
                        ready = self.inbox.empty() and not self.stopped.is_set()
                        if ready:
                            self.changed.clear()
                    if ready:
                        self.app.busy = 'FoxGo: thinking' if self.game.want_move else 'FoxGo: synchronized'
                        try:
                            result = self.game.search(self.changed)
                            # Make queued events and sending a move mutually exclusive.
                            with self.ingest:
                                if result and not self.changed.is_set() and not self.stopped.is_set():
                                    packet,pending = result
                                    self.send(packet)
                                    self.game.pending = pending
                                    self.game.want_move = False
                                    self.game.publish('Move sent · awaiting FoxGo confirmation')
                        except (ValueError,RuntimeError) as exc:
                            self.game.resync(str(exc))
                    self.app.save()
                    self.app.busy = ''
        except (OSError,RuntimeError,ValueError) as exc:
            if not self.stopped.is_set():
                self.app.log('error',f'FoxGo connection stopped: {exc}')
        finally:
            self.stop()
            self.server.finished(self)

    def stop(self):
        self.stopped.set()
        self.changed.set()
        try:
            self.client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.client.close()


class FoxServer:
    def __init__(self,app,port):
        self.app = app
        self.stopped = threading.Event()
        self.connection = None
        self.guard = threading.Lock()
        self.socket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            self.socket.bind(('127.0.0.1',port))
            self.socket.listen(2)
            self.socket.settimeout(.5)
        except Exception:
            self.socket.close()
            raise

    def start(self):
        threading.Thread(target=self._accept,daemon=True).start()

    def _accept(self):
        while not self.stopped.is_set():
            try:
                client,_ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self.guard:
                if self.stopped.is_set() or self.connection:
                    client.close()
                    continue
                client.settimeout(2)
                client.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                connection = FoxConnection(self,client)
                self.connection = connection
                with self.app.state_lock:
                    self.app.fox_connected = True
                    self.app.fox_ready = False
                    self.app.fox_game = {'status':'Connected · waiting for FoxGo snapshot'}
                self.app.log('fox','FoxGo connected directly. Awaiting FARULE / FASTATUS.')
                connection.start()

    def finished(self,connection):
        with self.guard:
            if self.connection is connection:
                self.connection = None
            if self.app.fox_server is self:
                with self.app.state_lock:
                    self.app.fox_connected = self.app.fox_ready = False
                    self.app.fox_game = {'status':'Disconnected · reconnect FoxGo to synchronize'}
                    self.app.busy = ''
                self.app.log('fox','FoxGo disconnected. The next connection needs a fresh snapshot.')

    def stop(self):
        self.stopped.set()
        self.socket.close()
        with self.guard:
            connection = self.connection
        if connection:
            connection.stop()
