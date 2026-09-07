import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from trainer.app import Trainer
from trainer.fox import FoxGame, FoxServer
from trainer.fox_protocol import *
from trainer.gtp import GTP


class FoxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Trainer(self.tmp.name)
        self.app.engine = GTP([sys.executable, '-u', str(Path(__file__).with_name('fake_engine.py'))])
        self.sent = []
        self.game = FoxGame(self.app,self.sent.append)

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def start(self, ai='W', moves=('1^4^4^B',)):
        self.game.handle('FARULE',['9','60','30','5','650'])
        self.game.handle('FASTATUS',['1',ai,*moves])
        self.game.handle('FATIMELEFT',['60','30','5'])

    def test_codec(self):
        self.assertEqual(encode('FASTATUS',0),b'$FASTATUS,0*0F\r\n')
        packet=encode('FAMOVE',1,'W','1^4^4^B')
        framer=Framer()
        self.assertEqual(framer.feed(packet[:5]),[])
        self.assertEqual(framer.feed(packet[5:]+packet),[packet,packet])
        self.assertEqual(decode(packet),('FAMOVE',['1','W','1^4^4^B']))
        for bad in (packet.replace(b'1^4',b'2^4'),packet[:-2]+b'\n',b'$FASTATUS,0*ZZ\r\n'):
            with self.assertRaises(ValueError): decode(bad)
        with self.assertRaises(ValueError): Framer().feed(b'x'*MAX_PACKET)
        self.assertEqual(move_record('1^18^0^W',19),(1,'W','T19'))
        self.assertEqual(score_to_fox('B+2.5'),'B+250')
        self.assertEqual(score_from_fox('W+350'),'W+3.5')

    def test_search_requires_notice_and_confirmation(self):
        self.start()
        self.assertIsNone(self.game.search(threading.Event()))
        self.game.handle('FAMOVE',['1','W','1^4^4^B'])
        packet,pending=self.game.search(threading.Event())
        self.assertEqual(packet,encode('AFPLAY','W','2^3^5^W'))
        self.assertEqual(self.app.board.moves,[['B','E5']])
        self.game.pending=pending
        self.game.handle('FAMOVE',['1','W','1^4^4^B'])
        self.assertIsNone(self.game.search(threading.Event()))
        self.game.handle('FAMOVE',['0','W','2^3^5^W'])
        self.assertEqual(self.app.board.moves,[['B','E5'],['W','D4']])
        self.assertIsNone(self.game.pending)
        self.game.handle('FASCORE',['1'])
        self.assertEqual(self.sent[-1],encode('AFSCORE',1,'B+250'))
        self.game.handle('FARESULT',['W+350'])
        self.assertEqual(self.app.board.result,'W+3.5')

    def test_heart_move_uses_fox_confirmation(self):
        self.app.settings['heartOpening']=True
        self.start()
        self.game.handle('FAMOVE',['1','W','1^4^4^B'])
        packet,pending=self.game.search(threading.Event())
        self.assertEqual(packet,encode('AFPLAY','W','2^2^2^W'))
        self.assertEqual(self.app.board.moves,[['B','E5']])
        self.game.pending=pending
        self.game.handle('FAMOVE',['0','W','2^2^2^W'])
        self.assertEqual(self.app.board.moves[-1],['W','C7'])

    def test_pass_duplicate_does_not_clear_pending(self):
        self.start(moves=())
        self.game.handle('FASKIP',['1','W'])
        self.game.pending=(1,'W','D4')
        self.game.handle('FASKIP',['1','W'])
        self.assertEqual(self.game.pending,(1,'W','D4'))
        self.assertEqual(self.app.board.moves,[['B','PASS']])
        self.game.handle('FASTATUS',['1','W'])
        self.assertEqual(self.app.board.moves,[['B','PASS']])

    def test_gap_and_ambiguous_snapshot_rejected(self):
        self.start()
        with self.assertRaises(ValueError): self.game.handle('FAMOVE',['0','W','3^3^5^W'])
        self.game.resync('gap')
        self.assertEqual(self.sent[-1],encode('AFSTATUS','W'))
        self.assertFalse(self.game.synced)
        with self.assertRaises(ValueError): self.game.handle('FASTATUS',['1','W','1^4^4^B','2^3^5^B'])

    def test_handicap(self):
        self.game.handle('FARULE',['9','0','30','5','50','0^2^6^B','0^6^2^B'])
        self.game.handle('FASTATUS',['1','W'])
        self.assertEqual(self.app.board.handicap,['C3','G7'])
        self.assertEqual(self.app.board.turn,'W')

    def test_explicit_status_request_does_not_play(self):
        self.game.handle('REQUEST_STATUS',['W'])
        self.assertEqual(self.sent,[encode('AFSTATUS','W')])
        self.assertEqual(self.app.board.moves,[])
        self.assertFalse(self.game.synced)
        self.game.handle('FASTATUS',['0'])
        self.assertEqual(self.app.fox_game['status'],'FoxGo reports no active game')
        with self.assertRaises(ValueError):self.game.handle('REQUEST_STATUS',['invalid'])

    def test_tcp_pipeline_and_stop(self):
        server=FoxServer(self.app,0)
        self.app.fox_server=server
        self.app.mode='online'
        server.start()
        with socket.create_connection(('127.0.0.1',server.socket.getsockname()[1]),timeout=3) as client:
            packet=b''.join([encode('FARULE',9,60,30,5,650),encode('FASTATUS',1,'W','1^4^4^B'),encode('FATIMELEFT',60,30,5),encode('FAMOVE',1,'W','1^4^4^B')])
            client.sendall(packet[:7]);client.sendall(packet[7:])
            with client.makefile('rb') as reader:
                self.assertEqual(reader.readline(),encode('AFPLAY','W','2^3^5^W'))
                client.sendall(encode('FAMOVE',0,'W','2^3^5^W')+encode('FASCORE',0))
                self.assertEqual(reader.readline(),encode('AFSCORE',0,'B+250'))
                with self.assertRaises(ValueError): self.app.action('play',{'vertex':'C3'})
                state=self.app.action('fox-stop',{})
                self.assertEqual(state['mode'],'local')

    def test_cancellation_drains_response(self):
        self.app.engine.close()
        self.app.engine=GTP([sys.executable,'-u',str(Path(__file__).with_name('fake_engine.py')),'--wait-cancel'],timeout=2)
        changed=threading.Event()
        reply=self.app.engine.command('kata-search_analyze_cancellable B 25',lambda _:changed.set(),cancel_event=changed)
        self.assertEqual(reply,'play cancelled')
        self.assertEqual(self.app.engine.command('name'),'KataGo test fixture')

    def test_stop_interrupts_search(self):
        self.app.engine.close()
        self.app.engine=GTP([sys.executable,'-u',str(Path(__file__).with_name('fake_engine.py')),'--wait-cancel'],timeout=2)
        server=FoxServer(self.app,0)
        self.app.fox_server=server;self.app.mode='online';server.start()
        with socket.create_connection(('127.0.0.1',server.socket.getsockname()[1]),timeout=3) as client:
            client.sendall(encode('FARULE',9,60,30,5,650)+encode('FASTATUS',1,'B')+encode('FATIMELEFT',60,30,5)+encode('FAMOVE',1,'B','0^0^0^N'))
            deadline=time.monotonic()+2
            while not self.app.analysis and time.monotonic()<deadline: time.sleep(.01)
            self.assertTrue(self.app.analysis)
            self.assertEqual(self.app.action('fox-stop',{})['mode'],'local')
            self.assertEqual(client.recv(1024),b'')
            self.assertEqual(self.app.board.moves,[])
            self.assertEqual(self.app.engine.command('name'),'KataGo test fixture')


if __name__=='__main__': unittest.main()
