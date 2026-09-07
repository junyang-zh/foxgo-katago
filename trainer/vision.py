"""Calibrated screen recognition and confirmed-move tracking; no network protocol."""
from copy import deepcopy
import io
import math
import re
import threading
import time
from .board import Board, LETTERS, point


def detect_board(image, size=19):
    """Locate two matching, regularly spaced sets of long dark grid lines."""
    scale=min(1,900/max(image.size))
    small=image.convert('RGB').resize((round(image.width*scale),round(image.height*scale)))
    w,h=small.size;cols=[0]*w;pixels=small.load()
    def wood(rgb):
        r,g,b=rgb
        return r>120 and r>b+25 and g>b+15
    for y in range(h):
        for x in range(3,w-3):
            if max(pixels[x,y])<160 and wood(pixels[x-3,y]) and wood(pixels[x+3,y]):cols[x]+=1
    def lattices(values, threshold):
        peaks=[];group=[]
        for i,v in enumerate(values+[0]):
            if v>=threshold:group.append(i)
            elif group:
                peaks.append(max(group,key=lambda p:values[p]));group=[]
        candidates=[]
        for a in peaks:
            for b in peaks:
                step=(b-a)/(size-1)
                if step<12*scale:continue
                error=sum(min(abs(p-(a+i*step)) for p in peaks) for i in range(size))
                if error<size*1.2:candidates.append((error,a,b,step))
        return sorted(candidates)[:12]
    for _,x0,x1,dx in lattices(cols,h*.18):
        # Exclude side panels: their dark backgrounds can merge horizontal peaks.
        rows=[sum(max(small.getpixel((x,y)))<160 for x in range(x0,x1+1)) for y in range(h)]
        for _,y0,y1,dy in lattices(rows,(x1-x0)*.65):
            if abs(dx-dy)>max(1,dx*.025):continue
            try:
                cfg=calibration(dict(size=size,x0=x0/scale,y0=y0/scale,x1=x1/scale,y1=y1/scale),*image.size)
                result=recognize(image,cfg)
                if len(result['uncertain'])<=size:return cfg
            except ValueError:pass
    raise ValueError('Waiting for a visible standard yellow FoxGo board to detect its grid.')


def calibration(data, width, height):
    size=int(data.get('size',19))
    if size not in (9,13,19):raise ValueError('Use a 9, 13 or 19 line board.')
    x0,y0,x1,y1=(float(data[k]) for k in ('x0','y0','x1','y1'))
    if not all(math.isfinite(v) for v in (x0,y0,x1,y1)):
        raise ValueError('Invalid board corners.')
    dx,dy=(x1-x0)/(size-1),(y1-y0)/(size-1)
    if min(dx,dy)<12 or not .85<dx/dy<1.15:
        raise ValueError('Select top-left and bottom-right grid intersections on a square board.')
    if x0<dx*.4 or y0<dy*.4 or x1+dx*.4>=width or y1+dy*.4>=height:
        raise ValueError('Board corners are too close to the image edge.')
    return dict(size=size,x0=x0,y0=y0,x1=x1,y1=y1,dx=dx,dy=dy,width=width,height=height)


def recognize(image, cfg):
    if image.size != (cfg['width'],cfg['height']):raise ValueError('Window resized; recalibrate.')
    pixels=image.convert('RGB').load();grid=[];uncertain=[];confidence=[]
    for y in range(cfg['size']):
        row=[]
        for x in range(cfg['size']):
            cx=cfg['x0']+x*cfg['dx'];cy=cfg['y0']+y*cfg['dy']
            counts={'B':0,'W':0,'':0}
            # An annulus avoids the grid crossing and the last-move marker.
            for i in range(32):
                a=(i+.5)*math.tau/32
                r,g,b=pixels[round(cx+cfg['dx']*.30*math.cos(a)),round(cy+cfg['dy']*.30*math.sin(a))]
                if max(r,g,b)<105:counts['B']+=1
                elif min(r,g,b)>145 and max(r,g,b)-min(r,g,b)<48:counts['W']+=1
                elif r>b+25 and g>b+15 and r>120:counts['']+=1
            value=max(counts,key=counts.get);score=counts[value]/32
            # FoxGo draws a black quarter-sector over the last white stone.
            if value=='W' and counts['W']>=20 and counts['W']+counts['B']>=30:score=.9
            if value in ('B','W'):
                # A flat dialog/menu patch is not a stone: require surrounding wood.
                wood=0
                for i in range(16):
                    a=(i+.5)*math.tau/16
                    px=round(cx+cfg['dx']*.52*math.cos(a));py=round(cy+cfg['dy']*.52*math.sin(a))
                    if not (0<=px<image.width and 0<=py<image.height):continue
                    r,g,b=pixels[px,py]
                    if r>b+25 and g>b+15 and r>120:wood+=1
                if wood<10:score=0
            confidence.append(score)
            if score<.78:uncertain.append(LETTERS[x]+str(cfg['size']-y));value='?'
            row.append(value)
        grid.append(row)
    return dict(grid=grid,uncertain=uncertain,confidence=min(confidence))


def next_board(board, grid):
    """Accept exactly one legal placement, including all of its captures."""
    if board.grid==grid:return None
    additions=[(x,y) for y in range(board.size) for x in range(board.size)
               if not board.grid[y][x] and grid[y][x]==board.turn]
    if len(additions)!=1:raise ValueError('Not one legal move: restore visibility or restart tracking from an empty board.')
    x,y=additions[0];candidate=deepcopy(board)
    candidate.play(board.turn,LETTERS[x]+str(board.size-y))
    if candidate.grid!=grid:raise ValueError('Observed captures or colors disagree with the legal move.')
    return candidate


class VisionConnector:
    def __init__(self,app,desktop=None):
        self.app=app
        if desktop is None:
            from .vision_native import WindowsDesktop
            desktop=WindowsDesktop()
        self.desktop=desktop;self.cfg=None;self.target=None;self.preview=b''
        self.stopped=threading.Event();self.cancel=threading.Event();self.guard=threading.RLock()
        self.thread=None;self.armed=False;self.pending=None;self.pending_at=0
        self.last=None;self.stable=0;self.started=False;self.ai=None
        self.auto_role=True;self.role=None;self.role_image=None;self.role_checked=0;self.role_key=None
        self.status={'status':'Start automatic play to detect FoxGo','armed':False,'running':False}

    def state(self):
        with self.guard:return deepcopy({**self.status,'armed':self.armed,'running':self.started,
            'pendingMove':self.pending.moves[-1][1] if self.pending else None,'calibration':self.cfg,'aiColor':self.ai})

    def start(self,data):
        if self.thread and self.thread.is_alive():raise ValueError('Previous vision worker is still stopping.')
        self.cfg=None;self.target=None;self.role=None;self.role_image=None;self.role_checked=0;self.role_key=None
        self.app.require_engine()
        board=Board(19,7.5,'chinese')
        self.app.reset_engine(board);self.app.commit_board(board)
        self.app.analysis={};self.app.evaluations={};self.app.analyses={}
        self.ai=None;self.auto_role=True;self.started=True;self.initialized=False;self.armed=True;self.room=None
        self.stopped.clear();self.cancel.clear();self.last=None;self.stable=0;self.pending=None
        self.status={'status':'Reading FoxGo continuously · automatic moves enabled'}
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def arm(self):
        with self.guard:
            if not self.started:raise ValueError('Start tracking first.')
            if self.pending:raise ValueError('Wait for the pending move to be confirmed.')
            self.cancel.clear();self.armed=True
            self.status['status']='Reading FoxGo continuously · automatic moves enabled'

    def pause(self,reason='Paused'):
        with self.guard:self.armed=False;self.cancel.set();self.status['status']=reason

    def stop(self):
        self.pause('Stopped');self.stopped.set();self.started=False
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=10)

    def manual_pass(self):
        # Board images cannot distinguish a pass from a player still thinking.
        if self.armed or self.pending:raise ValueError('Pause automatic play before confirming a pass.')
        b=deepcopy(self.app.board);b.play(b.turn,'PASS')
        self.app.require_engine().command(f'play {self.app.board.turn} PASS');self.app.commit_board(b)
        self.last=None;self.stable=0

    def tick(self):
        if self.desktop.emergency():self.pause('Escape pressed');return
        if self.pending and hasattr(self.desktop,'park'):self.desktop.park(self.target['hwnd'])
        if not self.target:
            windows=self.desktop.windows()
            choices=[w for w in windows if w.get('active')] or [w for w in windows if w.get('room')]
            if len(choices)!=1:
                self.status['status']='Waiting for one FoxGo game window';return
            self.target=choices[0]
        try:image,info=self.desktop.capture(self.target['hwnd'])
        except (ValueError,OSError) as exc:
            self.last=None;self.stable=0;self.status['status']=str(exc);return
        if info['pid']!=self.target['pid']:
            raise ValueError('FoxGo process was replaced; restart tracking.')
        out=io.BytesIO();image.save(out,format='PNG');self.preview=out.getvalue()
        if not self.cfg or image.size!=(self.cfg['width'],self.cfg['height']):
            self.cfg=None
            for size in (19,13,9):
                try:self.cfg=detect_board(image,size);break
                except ValueError:pass
            if not self.cfg:
                self.status['status']='Waiting to detect the FoxGo board grid';return
            if self.cfg['size']!=self.app.board.size:
                if self.initialized:raise ValueError('Board size changed during the game.')
                board=Board(self.cfg['size'],7.5,'chinese')
                self.app.reset_engine(board);self.app.commit_board(board)
            self.last=None;self.stable=0
        self.target=info
        if self.auto_role:
            key=(info.get('room'),image.size)
            if key!=self.role_key or time.monotonic()-self.role_checked>3:
                self.role=None;self.ai=None;self.role_key=key
                try:
                    from .vision_role import detect_role
                    self.role=detect_role(image,self.cfg,self.app.settings.get('foxAccount',''))
                    self.role_image=image.crop(tuple(self.role['bounds'])).tobytes()
                    self.ai=self.role['color'];self.role_key=key
                except (ValueError,OSError) as exc:
                    self.status['roleStatus']=str(exc)
                self.role_checked=time.monotonic()
            if self.role:self.status['roleStatus']=self.role['account']+' · '+('Black' if self.ai=='B' else 'White')+' detected in FoxGo'
        result=recognize(image,self.cfg)
        with self.guard:self.status.update(result)
        if result['uncertain']:
            self.last=None;self.stable=0
            self.status['status']='Waiting for clear intersections: '+', '.join(result['uncertain'][:8]);return
        grid=result['grid']
        if grid==self.last:self.stable+=1
        else:self.last=deepcopy(grid);self.stable=1
        if self.stable<3:return
        if not self.initialized:
            number=info.get('moveNumber')
            if not isinstance(number,int) or number<0:
                self.status['status']='Waiting for FoxGo’s move counter to identify the turn';return
            if number>1:
                stones=[[c,LETTERS[x]+str(self.app.board.size-y)] for y,row in enumerate(grid) for x,c in enumerate(row) if c]
                candidate=Board(self.app.board.size,self.app.board.komi,self.app.board.rules)
                candidate.setup_position(stones,'B' if number%2==0 else 'W',number)
                self.app.reset_engine(candidate);self.app.commit_board(candidate)
                self.status['historyNote']=f'Attached at move {number}; earlier moves, captures and ko history are unknown.'
                self.app.log('vision',self.status['historyNote'])
            self.initialized=True;self.status['status']='Board verified'
            self.room=info.get('room') if info.get('active') else None
        if self.pending:
            following=None
            if grid!=self.pending.grid and grid!=self.app.board.grid:
                following=next_board(self.pending,grid)
            if grid==self.pending.grid or following:
                c,v=self.pending.moves[-1];self.app.require_engine().command(f'play {c} {v}')
                self.app.commit_board(self.pending);self.pending=None
                if following:
                    c,v=following.moves[-1];self.app.require_engine().command(f'play {c} {v}')
                    self.app.commit_board(following)
                self.status['status']='Move visually confirmed'
            elif grid!=self.app.board.grid:raise ValueError('Unexpected board after click; no retry will be sent.')
            elif time.monotonic()-self.pending_at>5:raise ValueError('Click was not confirmed within 5 seconds; no retry will be sent.')
            return
        candidate=next_board(self.app.board,grid)
        if candidate:
            c,v=candidate.moves[-1];self.app.require_engine().command(f'play {c} {v}')
            self.app.commit_board(candidate);self.status['status']='Observed '+c+' '+v
        if self.app.board.result:self.pause('Game ended locally; verify result in FoxGo');return
        if not self.armed:return
        if self.auto_role and not self.ai:
            self.status['status']='Waiting to identify the account’s color in FoxGo';return
        if self.app.board.turn!=self.ai:
            self.status['status']='Watching opponent’s turn';return
        if not info.get('active') or not info.get('room'):
            self.status['status']='Waiting for an active FoxGo match';return
        if self.room and info['room']!=self.room:
            raise ValueError('Different game room; stop and start tracking a fresh game.')
        if info.get('moveNumber')!=self.app.board.move_offset+len(self.app.board.moves):
            raise ValueError('FoxGo move counter disagrees with tracked history; check for a pass or missed move.')
        self.room=info['room']
        if hasattr(self.desktop,'prepare_click'):
            try:self.desktop.prepare_click(self.target['hwnd'])
            except ValueError as exc:
                self.status['status']=str(exc);return
        # Search does not mutate the engine board; the click must be confirmed.
        self.app.busy='Vision: thinking'
        self.cancel.clear()
        def on_analysis(sample):
            if self.desktop.emergency():self.pause('Escape pressed')
            self.app.receive_analysis(sample)
        reply=self.app.require_engine().command(f'kata-search_analyze_cancellable {self.ai} 25 maxmoves 8 rootInfo true ownership true',
             on_analysis,cancel_event=self.cancel)
        if self.cancel.is_set() or self.stopped.is_set():return
        match=re.search(r'^play (\S+)\s*$',reply,re.M)
        if not match:raise ValueError('KataGo did not return a move.')
        move=match[1].upper()
        if move in ('PASS','RESIGN'):
            self.pause('KataGo recommends '+move+'; perform it in FoxGo manually, then confirm pass or stop tracking.');return
        if hasattr(self.desktop,'prepare_click'):
            try:self.desktop.prepare_click(self.target['hwnd'])
            except ValueError as exc:
                self.status['status']=str(exc);return
        fresh,new_info=self.desktop.capture(self.target['hwnd'])
        check=recognize(fresh,self.cfg)
        if new_info!=info or check['grid']!=grid or check['uncertain']:
            self.last=None;self.stable=0
            self.status['status']='Board changed during search; reading again';return
        if self.auto_role and (not self.role or fresh.crop(tuple(self.role['bounds'])).tobytes()!=self.role_image):
            self.role_key=None;self.status['status']='Player identity display changed; checking color again';return
        candidate=deepcopy(self.app.board);candidate.play(self.ai,move)
        x,y=point(move,candidate.size)
        with self.guard:
            if not self.armed or self.cancel.is_set() or self.stopped.is_set():return
            self.desktop.click(self.target['hwnd'],self.cfg['x0']+x*self.cfg['dx'],self.cfg['y0']+y*self.cfg['dy'],new_info)
            self.pending=candidate;self.pending_at=time.monotonic()
            self.status['status']='Clicked '+move+' · awaiting visual confirmation'
            self.last=None;self.stable=0

    def run(self):
        while not self.stopped.wait(.35):
            if self.desktop.emergency():self.pause('Escape pressed')
            if not self.app.operation.acquire(timeout=.05):continue
            try:
                if self.stopped.is_set():break
                before=self.app.revision
                self.tick()
                if self.app.revision!=before:self.app.save()
            except Exception as exc:
                changed=self.status.get('status')!=str(exc)
                self.pause(str(exc))
                if changed:self.app.log('vision',str(exc))
            finally:
                self.app.busy='';self.app.operation.release()
