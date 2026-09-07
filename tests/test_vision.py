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
from trainer.vision import VisionConnector, calibration, recognize, next_board, detect_board
from unittest.mock import patch


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
    def windows(self):return [self.info.copy()]
    def click(self,*args):self.clicks.append(args)


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Trainer(self.tmp.name);self.app.engine=Engine()
        self.desktop=Desktop();self.v=VisionConnector(self.app,self.desktop)
        self.v.cfg=CFG;self.v.target=self.desktop.info.copy();self.v.ai='B'
        self.v.auto_role=False
        self.role_patch=patch('trainer.vision_role.detect_role',return_value=dict(color='B',account='test',bounds=[0,0,1,1]))
        self.role_patch.start();self.addCleanup(self.role_patch.stop)
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

    def test_heart_waits_for_visual_confirmation(self):
        from trainer.entertainment import heart_points
        self.app.settings['heartOpening']=True;self.v.armed=True
        first=heart_points(9)[0];self.stable_tick()
        self.assertEqual(self.v.pending.moves,[['B',first]])
        self.assertEqual(self.app.board.moves,[])
        self.assertFalse(any('analyze' in c for c in self.app.engine.commands))
        self.desktop.board.play('B',first);self.stable_tick()
        self.assertEqual(self.app.board.moves,[['B',first]])

    def previous_game(self):
        self.desktop.board.play('B','D4');self.desktop.board.play('W','E5')
        self.app.board=deepcopy(self.desktop.board);self.v.room='1号房间'
        self.v.auto_play=True;self.v.armed=True;self.v.phase='playing'
        self.app.analyses={2:{'ownership':[.5]*81}}

    def test_new_room_clears_pending_history_and_restarts_heart(self):
        from trainer.entertainment import heart_points
        self.previous_game();self.app.settings['heartOpening']=True
        self.v.pending=deepcopy(self.app.board);self.v.pending.play('B','C3')
        self.desktop.info['room']='2号房间';self.desktop.board=Board(9)
        self.stable_tick()
        self.assertFalse(self.v.initialized);self.assertIsNone(self.v.pending)
        self.assertEqual(self.app.board.moves,[]);self.assertEqual(self.app.analyses,{})
        self.assertIsNone(self.v.role_key)
        self.stable_tick()
        self.assertEqual(self.v.pending.moves,[['B',heart_points(9)[0]]])

    def test_same_room_counter_reset_recovers_fault(self):
        self.previous_game();self.v.pause('old game mismatch',fault=True)
        self.desktop.board=Board(9)
        self.stable_tick();self.stable_tick()
        self.assertTrue(self.v.armed);self.assertEqual(len(self.desktop.clicks),1)

    def test_finished_game_waits_then_attaches_next_match(self):
        self.previous_game();self.desktop.info['active']=False
        self.desktop.board=Board(9)
        self.stable_tick()
        self.assertEqual(self.v.phase,'finished');self.assertFalse(self.desktop.clicks)
        self.assertEqual(len(self.app.board.moves),2)
        self.desktop.info['active']=True
        for c,v in [('B','A1'),('W','B1'),('B','C1')]:self.desktop.board.play(c,v)
        self.stable_tick();self.stable_tick()
        self.assertEqual(self.app.board.move_offset,3)
        self.assertEqual(self.app.board.grid,self.desktop.board.grid)

    def test_manual_pause_survives_new_game(self):
        self.previous_game();self.v.pause()
        self.desktop.board=Board(9);self.desktop.info['room']='2号房间'
        self.stable_tick();self.stable_tick()
        self.assertFalse(self.v.armed);self.assertFalse(self.desktop.clicks)
        self.assertTrue(self.v.initialized)

    def test_transient_counter_reset_does_not_discard_game(self):
        self.previous_game();old=deepcopy(self.desktop.board)
        self.desktop.board=Board(9);self.v.tick()
        self.desktop.board=old;self.v.tick()
        self.assertEqual(self.app.board.moves,old.moves)
        self.assertTrue(self.v.initialized)
    def test_timeout_does_not_repeat_click(self):
        self.v.armed=True;self.stable_tick();self.v.pending_at=time.monotonic()-6
        with self.assertRaises(ValueError):self.stable_tick()
        self.assertEqual(len(self.desktop.clicks),1)
    def test_cancelled_search_does_not_click(self):
        self.app.engine.cancel_on_search=True;self.v.armed=True;self.stable_tick()
        self.assertEqual(self.desktop.clicks,[])
    def test_wrong_title_or_count_prevents_click(self):
        self.desktop.info['active']=False;self.v.armed=True
        self.stable_tick()
        self.assertEqual(self.desktop.clicks,[])
        self.assertTrue(self.v.armed)
        self.desktop.info['active']=True;self.stable_tick()
        self.assertEqual(len(self.desktop.clicks),1)
    def test_escape_and_geometry_changes_prevent_click(self):
        self.v.armed=True;self.desktop.escape=True;self.stable_tick();self.assertFalse(self.v.armed)
        self.desktop.escape=False;self.desktop.info['rect']=[1,0,421,420]
        self.v.tick()
        self.assertEqual(self.v.target['rect'],self.desktop.info['rect'])
        self.assertEqual(self.desktop.clicks,[])
        self.desktop.info['pid']=2
        with self.assertRaises(ValueError):self.v.tick()

    def test_detect_grid_and_last_white_marker(self):
        b=Board(9);b.play('B','D4');b.play('W','E5')
        im=board_image(b)
        ImageDraw.Draw(im).pieslice((172,172,208,208),0,90,fill=(25,25,25))
        cfg=detect_board(im,9)
        self.assertLess(abs(cfg['x0']-30),2)
        self.assertEqual(recognize(im,cfg)['grid'],b.grid)
        with self.assertRaises(ValueError):detect_board(Image.new('RGB',(420,420),'white'),9)

    def test_black_quarter_marker_with_grey_highlight(self):
        b=Board(9);b.play('B','D4');im=board_image(b)
        draw=ImageDraw.Draw(im)
        draw.pieslice((132,212,168,248),0,90,fill='white')
        draw.pieslice((132,212,168,248),170,230,fill=(130,130,130))
        result=recognize(im,CFG)
        self.assertFalse(result['uncertain'])
        self.assertEqual(result['grid'],b.grid)

    def test_touching_stones_do_not_look_like_an_obstruction(self):
        b=Board(9)
        for y in range(3,6):
            for x in range(3,6):b.grid[y][x]='B' if (x+y)%2 else 'W'
        im=board_image(b);draw=ImageDraw.Draw(im)
        for y in range(3,6):
            for x in range(3,6):
                cx,cy=30+x*40,30+y*40
                draw.ellipse((cx-20,cy-20,cx+20,cy+20),fill=(25,25,25) if b.grid[y][x]=='B' else (225,225,225))
        result=recognize(im,CFG)
        self.assertFalse(result['uncertain'])
        self.assertEqual(result['grid'],b.grid)

    def test_one_action_starts_detection_and_automatic_play(self):
        self.v.cfg=None;self.v.started=False
        with patch('trainer.vision.threading.Thread'):
            self.v.start(dict(size=9,color='B'))
        self.assertTrue(self.v.armed)
        self.stable_tick()
        self.assertIsNotNone(self.v.cfg)
        self.assertEqual(len(self.desktop.clicks),1)

    def test_opening_white_reply_without_empty_frame(self):
        self.desktop.board.play('B','E5')
        self.v.ai='W';self.v.initialized=False;self.v.armed=True
        self.stable_tick()
        self.assertEqual(self.app.board.moves,[['B','E5']])
        self.assertEqual(len(self.desktop.clicks),1)

    def test_uncertain_frame_and_unavailable_capture_recover(self):
        self.v.armed=True
        with patch.object(self.desktop,'capture',side_effect=ValueError('Minimized')):self.v.tick()
        self.assertTrue(self.v.armed)
        obscured=board_image(Board(9));ImageDraw.Draw(obscured).rectangle((0,0,200,200),fill='blue')
        with patch.object(self.desktop,'capture',return_value=(obscured,self.desktop.info)):self.stable_tick()
        self.assertTrue(self.v.armed);self.assertFalse(self.desktop.clicks)
        self.stable_tick();self.assertEqual(len(self.desktop.clicks),1)

    def test_auto_detection_waits_and_recovers(self):
        self.v.cfg=None;self.v.armed=True
        with patch.object(self.desktop,'capture',return_value=(Image.new('RGB',(420,420),'white'),self.desktop.info)):
            self.stable_tick()
        self.assertTrue(self.v.armed);self.assertFalse(self.desktop.clicks)
        self.stable_tick();self.assertEqual(len(self.desktop.clicks),1)

    def test_resume_has_no_countdown(self):
        self.v.pause();self.v.arm();self.stable_tick()
        self.assertEqual(len(self.desktop.clicks),1)

    def test_unknown_role_blocks_clicks_but_tracks_board(self):
        self.v.auto_role=True;self.v.armed=True;self.v.ai=None
        with patch('trainer.vision_role.detect_role',side_effect=ValueError('Name obscured')):
            self.stable_tick()
        self.assertFalse(self.desktop.clicks);self.assertTrue(self.v.armed)
        self.v.role_checked=0
        self.stable_tick();self.assertEqual(len(self.desktop.clicks),1)

    def test_connector_never_starts_engine(self):
        self.app.engine=None
        with patch.object(self.app,'ensure_engine') as start:
            with self.assertRaises(RuntimeError):self.v.start({})
        start.assert_not_called()

    def test_attach_midgame_syncs_position_and_plays(self):
        self.desktop.board.play('B','E5');self.desktop.board.play('W','F5')
        self.v.initialized=False;self.v.armed=True
        self.stable_tick()
        self.assertEqual(self.app.board.grid,self.desktop.board.grid)
        self.assertEqual(self.app.board.move_offset,2)
        self.assertEqual(self.app.state()['history'][0]['grid'],self.desktop.board.grid)
        self.assertEqual(self.app.board.moves,[])
        self.assertTrue(any(c.startswith('set_position ') for c in self.app.engine.commands))
        self.assertEqual(len(self.desktop.clicks),1)
        self.desktop.board.play('B','D4');self.stable_tick()
        self.assertEqual(self.app.board.moves,[['B','D4']])
        self.v.pause()
        self.desktop.board.play('W','F6');self.stable_tick()
        self.assertEqual(self.app.board.grid,self.desktop.board.grid)

    def test_snapshot_survives_save_and_exports_as_setup(self):
        self.app.board.setup_position([['B','E5'],['W','F5']],'B',24)
        self.app.board.play('B','D4');self.app.save()
        restored=Trainer(self.tmp.name)
        self.assertEqual(restored.board.grid,self.app.board.grid)
        self.assertEqual(restored.board.move_offset,24)
        sgf=restored.board.sgf()
        self.assertIn('AB[ee]',sgf);self.assertIn('AW[fe]',sgf);self.assertIn('PL[B]',sgf)
        self.assertEqual(restored.board.moves,[['B','D4']])
        restored.close()

    def test_snapshot_odd_move_waits_for_white(self):
        for c,v in [('B','E5'),('W','F5'),('B','D5')]:self.desktop.board.play(c,v)
        self.v.initialized=False;self.v.armed=True;self.stable_tick()
        self.assertEqual(self.app.board.turn,'W');self.assertFalse(self.desktop.clicks)

    def test_snapshot_without_counter_never_guesses_turn(self):
        self.v.initialized=False;self.v.armed=True
        with patch.object(self.desktop,'capture',return_value=(board_image(Board(9)),{**self.desktop.info,'moveNumber':None})):
            self.stable_tick()
        self.assertFalse(self.v.initialized);self.assertFalse(self.desktop.clicks)
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
