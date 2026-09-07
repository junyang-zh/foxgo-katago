"""Application state. All engine mutations share one operation lock."""
from copy import deepcopy
from collections import deque
from pathlib import Path
import json
import math
import re
import threading
import time

from .board import Board, color, point
from .gtp import GTP, EngineError

ROOT = Path(__file__).resolve().parent.parent


class Trainer:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir or ROOT / 'data')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.operation = threading.Lock()
        self.state_lock = threading.RLock()
        self.engine = None
        self.board = Board()
        self.logs = deque(maxlen=300)
        self.analysis = {}
        self.evaluations = {}
        self.analyses = {}
        self.busy = ''
        self.mode = 'local'
        self.fox_connected = False
        self.fox_ready = False
        self.fox_server = None
        self.fox_port = 6001
        self.fox_reserve = 1.0
        self.fox_game = {'status': 'Offline'}
        self.connector = 'direct'
        self.vision = None
        self.settings = dict(executable='', model='', config=str(ROOT/'config'/'gtp.cfg'),
                             visits=200, seconds=2.0, aiColor='W', foxAccount='')
        self.revision = 0
        saved = self.data_dir / 'settings.json'
        if saved.exists():
            try:
                self.settings.update(json.loads(saved.read_text('utf-8')))
            except (OSError, ValueError):
                self.log('warning', 'Could not read settings.json; using defaults.')
        session = self.data_dir / 'session.json'
        if session.exists():
            try:
                data = json.loads(session.read_text('utf-8'))
                b = Board(data['size'], data['komi'], data['rules'])
                b.setup(data.get('handicap', []))
                if data.get('initialStones') or data.get('moveOffset'):
                    b.setup_position(data.get('initialStones',[]),data.get('initialTurn','B'),data.get('moveOffset',0))
                for c,v in data['moves']:
                    b.play(c,v)
                b.result = data.get('result', '')
                self.board = b
                self.evaluations = {int(k):v for k,v in data.get('evaluations', {}).items()}
                self.analyses = {int(k):v for k,v in data.get('analyses', {}).items()}
            except (KeyError, ValueError, OSError):
                self.log('warning', 'Could not restore the saved game.')
        self.log('info', 'Trainer initialized. The command-line backend starts KataGo automatically.')

    def log(self, level, message):
        with self.state_lock:
            self.logs.append(dict(time=time.strftime('%H:%M:%S'), level=level, message=str(message)[:4000]))

    def state(self):
        with self.state_lock:
            b = self.board
            return deepcopy(dict(size=b.size, komi=b.komi, rules=b.rules, grid=b.grid,
                turn=b.turn, moves=b.moves, handicap=b.handicap, captures=b.captures,
                initialStones=b.initial_stones,initialTurn=b.initial_turn,moveOffset=b.move_offset,
                result=b.result, history=b.history, analysis=self.analysis,
                evaluations=self.evaluations, analyses=self.analyses, logs=list(self.logs), busy=self.busy,
                mode=self.mode, engine=bool(self.engine and self.engine.alive),
                settings=self.settings, foxConnected=self.fox_connected,
                foxReady=self.fox_ready, foxPort=self.fox_port, foxReserve=self.fox_reserve,
                foxGame=self.fox_game, connector=self.connector,
                vision=self.vision.state() if self.vision else {}, revision=self.revision))

    def save(self):
        with self.state_lock:
            b = self.board
            data = dict(size=b.size, komi=b.komi, rules=b.rules, moves=b.moves,
                        handicap=b.handicap,initialStones=b.initial_stones,initialTurn=b.initial_turn,moveOffset=b.move_offset,
                        result=b.result, evaluations=self.evaluations, analyses=self.analyses)
            for name, value in (('session', data), ('settings', self.settings)):
                tmp = self.data_dir / (name + '.tmp')
                tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
                tmp.replace(self.data_dir / (name + '.json'))

    def require_engine(self):
        if not self.engine or not self.engine.alive:
            raise EngineError('KataGo is unavailable. Check the backend startup log.')
        return self.engine

    def ensure_engine(self):
        """Start the saved engine, discovering a bundled installation if needed."""
        if self.engine and self.engine.alive:return self.engine
        settings=self.settings.copy()
        if not Path(settings['executable']).is_file():
            settings['executable']=str(ROOT/'engines'/'katago'/'katago.exe')
        if not Path(settings['model']).is_file():
            models=sorted((ROOT/'models').glob('*.bin.gz'),key=lambda p:p.stat().st_mtime,reverse=True)
            if models:settings['model']=str(models[0])
        self.log('info','Starting KataGo automatically with the backend.')
        self.connect_engine(settings)
        return self.require_engine()

    def reset_engine(self, board):
        engine = self.require_engine()
        engine.command('clear_board')
        engine.command(f'boardsize {board.size}')
        engine.command(f'komi {board.komi}')
        engine.command(f'kata-set-rules {board.rules}')
        if board.handicap:
            engine.command('set_free_handicap ' + ' '.join(board.handicap))
        if board.initial_stones:
            engine.command('set_position '+' '.join(f'{c} {v}' for c,v in board.initial_stones))
        for c,v in board.moves:
            if v != 'RESIGN':
                engine.command(f'play {c} {v}')

    def connect_engine(self, data):
        settings = {**self.settings, **{k:data[k] for k in self.settings if k in data}}
        for key in ('executable', 'model', 'config'):
            path = Path(settings[key]).expanduser()
            if not path.is_file():
                raise ValueError(f'{key.title()} file does not exist: {path}')
            settings[key] = str(path.resolve())
        settings['visits'] = int(settings['visits'])
        settings['seconds'] = float(settings['seconds'])
        if not 1 <= settings['visits'] <= 100000 or not .1 <= settings['seconds'] <= 60:
            raise ValueError('Use 1–100000 visits and 0.1–60 seconds per search.')
        if settings['aiColor'] not in ('B','W','none'):
            raise ValueError('Choose Black, White, or manual AI replies.')
        if self.engine:
            self.engine.close()
            self.engine = None
        command = [settings['executable'], 'gtp', '-model', settings['model'],
            '-config', settings['config'], '-override-config',
            f'maxVisits={settings["visits"]},maxTime={settings["seconds"]},reportAnalysisWinratesAs=SIDETOMOVE,ponderingEnabled=false']
        # First OpenCL launch can compile and tune kernels for several minutes.
        engine = GTP(command, self.log, timeout=600, cwd=ROOT)
        self.engine = engine
        try:
            name = engine.command('name')
            engine.timeout = 120
            version = engine.command('version')
            if engine.command('known_command kata-search_analyze').strip() != 'true':
                raise EngineError('This engine must support KataGo kata-search_analyze.')
            self.reset_engine(self.board)
        except Exception:
            engine.close()
            self.engine = None
            raise
        self.settings = settings
        self.log('info', f'Connected {name} {version}.')

    def receive_analysis(self, analysis):
        with self.state_lock:
            turn, move = self.board.turn, len(self.board.moves)
            analysis.update(turn=turn, moveNumber=move)
            root = analysis.get('root', {})
            if 'winrate' in root and ('scoreLead' in root or 'scoreMean' in root):
                wr = float(root['winrate'])
                score = float(root.get('scoreLead', root.get('scoreMean', 0)))
                self.evaluations[move] = dict(move=move,
                    blackWinrate=wr if turn == 'B' else 1-wr,
                    blackScore=score if turn == 'B' else -score,
                    visits=root.get('visits', 0))
            self.analysis = analysis
            self.analyses[move] = deepcopy(analysis)

    def analyze(self):
        if self.board.result:
            return
        self.require_engine().command(
            f'kata-search_analyze {self.board.turn} 25 maxmoves 8 rootInfo true ownership true',
            self.receive_analysis)

    def commit_board(self, board):
        with self.state_lock:
            self.board = board
            self.analysis = {}
            self.revision += 1

    def play(self, c, vertex):
        candidate = deepcopy(self.board)
        candidate.play(c, vertex)
        if self.engine and self.engine.alive and str(vertex).upper() != 'RESIGN':
            self.engine.command(f'play {c} {vertex}')
        self.commit_board(candidate)

    def generate(self, c=None):
        c = color(c or self.board.turn)
        with self.state_lock:
            self.board.turn = c
        reply = self.require_engine().command(
            f'kata-genmove_analyze {c} 25 maxmoves 8 rootInfo true ownership true',
            self.receive_analysis)
        match = re.search(r'^play (\S+)\s*$', reply, re.M)
        if not match:
            self.engine.close()
            raise EngineError('Missing generated move; stopped engine to prevent desynchronization.')
        vertex = match[1].upper()
        candidate = deepcopy(self.board)
        try:
            candidate.play(c,vertex, authoritative=True)
        except ValueError:
            self.engine.close()
            raise EngineError('Generated move could not be mirrored; engine stopped.')
        self.commit_board(candidate)
        return vertex.lower() if vertex in ('PASS','RESIGN') else vertex

    def action(self, name, data):
        if name.startswith('vision-'):
            return self.vision_action(name,data)
        if name == 'fox-sync':
            if not self.fox_server or self.connector != 'direct':
                raise ValueError('Start the FoxGo listener first.')
            self.fox_server.request_status(data.get('color'))
            return self.state()
        if name == 'fox-stop' and self.fox_server:
            self.fox_server.stop()
        if not self.operation.acquire(timeout=10 if name == 'fox-stop' else .25):
            raise ValueError('An operation is in progress. Wait for it to finish.')
        self.busy = name
        try:
            if self.mode != 'local' and name not in ('fox-stop',):
                raise ValueError('Stop the FoxGo connection before changing the engine or local game.')
            if name == 'engine-connect':
                self.connect_engine(data)
                self.analyze()
            elif name == 'engine-stop':
                if self.engine:
                    self.engine.close()
                self.engine = None
                self.analysis = {}
            elif name == 'new':
                size, komi = int(data.get('size',19)), float(data.get('komi',7.5))
                rules = data.get('rules','chinese')
                if not math.isfinite(komi) or not -100 <= komi <= 100 or rules not in ('chinese','japanese'):
                    raise ValueError('Invalid rules or komi.')
                board = Board(size,komi,rules)
                handicap = int(data.get('handicap',0))
                if not 0 <= handicap <= 9 or handicap == 1:
                    raise ValueError('Use 0 or 2–9 handicap stones.')
                if self.engine and self.engine.alive:
                    try:
                        self.reset_engine(board)
                        if handicap:
                            vertices = self.engine.command(f'fixed_handicap {handicap}').split()
                            board.setup(vertices)
                    except Exception:
                        self.engine.close()
                        raise
                elif handicap:
                    raise ValueError('Connect KataGo to place handicap stones.')
                self.commit_board(board)
                self.evaluations = {}
                self.analyses = {}
                if self.engine and self.engine.alive:
                    if self.settings['aiColor'] == self.board.turn:
                        self.generate()
                    self.analyze()
            elif name in ('play','pass','resign'):
                if self.board.result:
                    raise ValueError('The game has ended. Undo or start a new game.')
                vertex = data.get('vertex','') if name == 'play' else name
                self.play(self.board.turn, str(vertex).upper())
                if self.engine and self.engine.alive and not self.board.result:
                    if self.settings['aiColor'] == self.board.turn:
                        self.generate()
                    self.analyze()
            elif name == 'genmove':
                if self.board.result:
                    raise ValueError('The game has ended.')
                self.generate()
                self.analyze()
            elif name == 'analyze':
                self.analyze()
            elif name == 'undo':
                count = 2 if data.get('pair') and len(self.board.moves) >= 2 else 1
                candidate = deepcopy(self.board)
                for _ in range(count):
                    candidate.undo()
                if self.engine and self.engine.alive:
                    # Replay also handles resignation, which never entered engine history.
                    try:
                        self.reset_engine(candidate)
                    except Exception:
                        self.engine.close()
                        raise
                self.commit_board(candidate)
                self.evaluations = {k:v for k,v in self.evaluations.items() if k <= len(candidate.moves)}
                self.analyses = {k:v for k,v in self.analyses.items() if k <= len(candidate.moves)}
                if self.engine and self.engine.alive:
                    self.analyze()
            elif name == 'score':
                score = self.require_engine().command('final_score')
                with self.state_lock:
                    self.board.result = score
                    self.board.history[-1]['result'] = score
                self.log('score', score)
            elif name == 'fox-start':
                from .fox import FoxServer
                from .foxgtp import FoxGTPServer
                self.require_engine()
                kind=data.get('connector','direct')
                if kind not in ('direct','foxgtp'):raise ValueError('Select direct TCP or FoxGTP.')
                port = int(data.get('port',6001))
                reserve = float(data.get('reserve',1))
                if not math.isfinite(reserve) or not .1 <= reserve <= 10:
                    raise ValueError('Use a clock reserve of 0.1–10 seconds.')
                if self.engine.command('known_command kata-search_analyze_cancellable').strip() != 'true':
                    raise EngineError('Direct FoxGo play requires KataGo cancellable search support.')
                if not 1024 <= port <= 65535:
                    raise ValueError('Choose a TCP port from 1024 to 65535.')
                server = (FoxServer if kind=='direct' else FoxGTPServer)(self, port)
                try:
                    self.engine.command('kata-set-rules chinese')
                except Exception:
                    server.stop()
                    raise
                self.board.rules = 'chinese'
                self.analysis = {}
                self.evaluations = {}
                self.analyses = {}
                self.fox_server, self.fox_port = server, port
                self.connector=kind
                self.fox_reserve = reserve
                self.fox_game = {'status':'Listening · connect FoxGo'}
                self.mode = 'online'
                server.start()
                self.log('fox', f'Listening for {kind} on 127.0.0.1:{port}.')
            elif name == 'fox-stop':
                if self.fox_server:
                    self.fox_server.stop()
                self.fox_server = None
                self.mode = 'local'
                self.fox_connected = self.fox_ready = False
                self.fox_game = {'status':'Offline'}
                if self.engine and self.engine.alive:
                    self.engine.command('kata-time_settings none')
                    self.engine.command(f'kata-set-param maxTime {self.settings["seconds"]}')
                self.log('fox', 'FoxGo listener stopped. Local controls enabled.')
            else:
                raise ValueError('Unknown action.')
            self.save()
        except Exception as exc:
            self.log('error', str(exc))
            raise
        finally:
            self.busy = ''
            self.operation.release()
        return self.state()

    def close(self):
        if self.vision:self.vision.stop()
        if self.fox_server:
            self.fox_server.stop()
        with self.operation:
            pass
        if self.engine:
            self.engine.close()

    def vision_action(self,name,data):
        from .vision import VisionConnector
        if self.mode=='online':raise ValueError('Stop the TCP connector before using vision.')
        if not self.vision:self.vision=VisionConnector(self)
        v=self.vision
        if name=='vision-pause':v.pause();return self.state()
        if name=='vision-stop':v.stop()
        if not self.operation.acquire(timeout=10):raise ValueError('Wait for the current engine operation.')
        try:
            if name=='vision-start' and v.started:
                raise ValueError('Vision is already running.')
            if name=='vision-start':
                v.start(data);self.mode='vision';self.connector='vision'
            elif name=='vision-arm':v.arm()
            elif name=='vision-pass':
                if not v.started or not v.initialized:raise ValueError('Start tracking first.')
                v.manual_pass()
            elif name=='vision-stop':self.mode='local'
            else:raise ValueError('Unknown vision action.')
        finally:self.operation.release()
        return self.state()
