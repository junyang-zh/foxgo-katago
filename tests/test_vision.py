from copy import deepcopy
import tempfile
import time
import unittest
try:
    from PIL import Image, ImageDraw
except ImportError:
    raise unittest.SkipTest('Install Pillow to run vision tests.')
from trainer.app import Trainer
from trainer.board import Board
from trainer.vision import VisionConnector, calibration, recognize, next_board


def board_image(board):
    image=Image.new('RGB',(420,420),(220,178,98));d=ImageDraw.Draw(image)
    for i in range(board.size):
        v=30+i*40
        d.line((30,v,350,v),fill=(30,30,30),width=2)
        d.line((v,30,v,350),fill=(30,30,30),width=2)
    for y,row in enumerate(board.grid):
        for x,c in enumerate(row):
            if c:d.ellipse((30+x*40-18,30+y*40-18,30+x*40+18,30+y*40+18),fill=(25,25,25) if c=='B' else (225,225,225))
    return image


CFG=calibration(dict(size=9,x0=30,y0=30,x1=350,y1=350),420,420)

class Engine:
    alive=True
    def __init__(self):self.commands=[];self.cancel_on_search=False
    def command(self,text,callback=None,cancel_event=None):
        self.commands.append(text)
        if 'analyze' in text:
            if self.cancel_on_search:cancel_event.set()
            return 'play D4'
        return ''
    def close(self):self.alive=False

class Desktop:
    def __init__(self):
        self.board=Board(9);self.clicks=[];self.escape=False
        self.info=dict(hwnd=1,pid=1,rect=[0,0,420,420],title='test',active=True,room='1号房间',moveNumber=0)
    def capture(self,_):
        info={**self.info,'moveNumber':len(self.board.moves)}
        return board_image(self.board),info
    def emergency(self):return self.escape
    def click(self,*args):self.clicks.append(args)


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Trainer(self.tmp.name);self.app.engine=Engine()
        self.desktop=Desktop();self.v=VisionConnector(self.app,self.desktop)
        self.v.cfg=CFG;self.v.target=self.desktop.info.copy();self.v.ai='B'
        self.app.board=Board(9);self.v.initialized=True;self.v.room=None;self.v.started=True
        self.v.arm_after=0
    def tearDown(self):self.app.close();self.tmp.cleanup()
    def stable_tick(self):
        for _ in range(3):self.v.tick()

    def test_recognition_stones_and_markers(self):
        b=Board(9);b.play('B','D4');b.play('W','E5');im=board_image(b)
        ImageDraw.Draw(im).rectangle((147,227,153,233),fill='white')
        result=recognize(im,CFG)
        self.assertFalse(result['uncertain']);self.assertEqual(result['grid'],b.grid)
    def test_occlusion_is_uncertain(self):
        im=board_image(Board(9));ImageDraw.Draw(im).rectangle((0,0,200,200),fill=(40,80,200))
        self.assertTrue(recognize(im,CFG)['uncertain'])
        im=board_image(Board(9));ImageDraw.Draw(im).rectangle((0,0,200,200),fill='white')
        self.assertTrue(recognize(im,CFG)['uncertain'])
    def test_capture_reconciliation(self):
        b=Board(9)
        for c,v in [('W','B2'),('B','A2'),('B','B1'),('B','C2')]:b.play(c,v)
        b.turn='B';after=deepcopy(b);after.play('B','B3')
        result=next_board(b,after.grid)
        self.assertEqual(result.captures['B'],1)
        bad=deepcopy(after.grid);bad[0][0]='W'
        with self.assertRaises(ValueError):next_board(b,bad)
    def test_preview_never_clicks(self):
        self.stable_tick();self.assertEqual(self.desktop.clicks,[])
    def test_click_waits_for_confirmation_without_retry(self):
        self.v.armed=True;self.stable_tick()
        self.assertEqual(len(self.desktop.clicks),1);self.assertEqual(self.app.board.moves,[])
        self.stable_tick();self.assertEqual(len(self.desktop.clicks),1)
        self.desktop.board.play('B','D4');self.stable_tick()
        self.assertEqual(self.app.board.moves,[['B','D4']]);self.assertIsNone(self.v.pending)
    def test_fast_opponent_reply_confirms_both_moves(self):
        self.v.armed=True;self.stable_tick()
        self.desktop.board.play('B','D4');self.desktop.board.play('W','E5');self.stable_tick()
        self.assertEqual(self.app.board.moves,self.desktop.board.moves)
    def test_timeout_does_not_repeat_click(self):
        self.v.armed=True;self.stable_tick();self.v.pending_at=time.monotonic()-6
        with self.assertRaises(ValueError):self.stable_tick()
        self.assertEqual(len(self.desktop.clicks),1)
    def test_cancelled_search_does_not_click(self):
        self.app.engine.cancel_on_search=True;self.v.armed=True;self.stable_tick()
        self.assertEqual(self.desktop.clicks,[])
    def test_wrong_title_or_count_prevents_click(self):
        self.desktop.info['active']=False;self.v.armed=True
        with self.assertRaises(ValueError):self.stable_tick()
        self.assertEqual(self.desktop.clicks,[])
    def test_escape_and_geometry_changes_prevent_click(self):
        self.v.armed=True;self.desktop.escape=True;self.stable_tick();self.assertFalse(self.v.armed)
        self.desktop.escape=False;self.desktop.info['rect']=[1,0,421,420]
        with self.assertRaises(ValueError):self.v.tick()
        self.assertEqual(self.desktop.clicks,[])
    def test_bad_calibration(self):
        for data in (dict(size=9,x0=0,y0=0,x1=350,y1=350),dict(size=9,x0=30,y0=30,x1=50,y1=350)):
            with self.assertRaises(ValueError):calibration(data,420,420)

    def test_vision_blocks_local_mutations_and_tcp_start(self):
        self.app.vision=self.v;self.app.mode='vision'
        for action in ('new','play','engine-stop','fox-start'):
            with self.assertRaises(ValueError):self.app.action(action,{})
        self.v.armed=True
        self.app.action('vision-pause',{})
        self.assertFalse(self.v.armed)
        self.assertEqual(self.app.action('vision-stop',{})['mode'],'local')


if __name__=='__main__':unittest.main()
