from copy import deepcopy
import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

from trainer.app import Trainer
from trainer.board import Board, point
from trainer.fox import FoxServer
from trainer.gtp import GTP, EngineError, parse_analysis
from trainer.server import create_server

FIXTURE = str(Path(__file__).with_name('fake_engine.py'))


class BoardTests(unittest.TestCase):
    def test_capture_and_undo(self):
        b=Board(9)
        for c,v in [('W','B2'),('B','A2'),('B','B1'),('B','C2'),('B','B3')]: b.play(c,v)
        self.assertEqual(b.grid[7][1],'')
        self.assertEqual(b.captures['B'],1)
        b.undo()
        self.assertEqual(b.grid[7][1],'W')
        self.assertEqual(b.captures['B'],0)

    def test_suicide_atomic(self):
        b=Board(9)
        for v in ('A2','B1','C2','B3'): b.play('B',v)
        old=deepcopy(b.__dict__)
        with self.assertRaises(ValueError): b.play('W','B2')
        self.assertEqual(b.__dict__,old)

    def test_ko(self):
        b=Board(9)
        for c,v in [('B','B2'),('B','D2'),('B','C1'),('W','C2'),('W','B3'),('W','D3'),('W','C4')]: b.play(c,v)
        b.play('B','C3')
        with self.assertRaises(ValueError): b.play('W','C2')
        b.play('W','PASS');b.play('B','PASS');b.play('W','C2')

    def test_coordinates_pass_resign_sgf_handicap(self):
        self.assertEqual(point('T19',19),(18,0))
        for v in ('I4','A0','T20','J10','D4\nquit'):
            with self.assertRaises(ValueError): point(v,9)
        b=Board(9);b.setup(['C3','G7']);b.play('W','PASS');b.play('B','RESIGN')
        self.assertIn('HA[2]AB[cg][gc]',b.sgf())
        self.assertIn(';W[]',b.sgf());self.assertIn('RE[W+R]',b.sgf())


class GTPTests(unittest.TestCase):
    def setUp(self): self.e=GTP([sys.executable,'-u',FIXTURE],timeout=.5)
    def tearDown(self): self.e.close()
    def test_framing_error_analysis(self):
        self.assertEqual(self.e.command('protocol_version'),'2')
        with self.assertRaises(EngineError): self.e.command('reject')
        samples=[]
        self.assertEqual(self.e.command('kata-search_analyze B 25',samples.append),'play D4')
        self.assertEqual(samples[0]['choices'][0]['pv'],['D4','E4'])
        self.assertEqual(self.e.command('name'),'KataGo test fixture')
    def test_timeout_kills(self):
        with self.assertRaises(EngineError): self.e.command('hang')
        self.assertFalse(self.e.alive)
    def test_id_mismatch_kills(self):
        with self.assertRaises(EngineError): self.e.command('wrongid')
        self.assertFalse(self.e.alive)
    def test_parse_order_future_fields(self):
        parsed=parse_analysis('info visits 2 order 1 move Q16 futureField yes scoreLead -3 winrate .4 pv Q16 pass info move D4 order 0 visits 8 winrate .6 scoreLead 3 pv D4 E4 rootInfo scoreLead 2 visits 10 winrate .55 ownership .5 -.6')
        self.assertEqual(parsed['choices'][0]['move'],'D4')
        self.assertEqual(parsed['ownership'],[.5,-.6])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Trainer(self.tmp.name)
        self.app.engine=GTP([sys.executable,'-u',FIXTURE])
    def tearDown(self): self.app.close();self.tmp.cleanup()
    def test_local_ai_undo_persistence(self):
        self.app.action('new',{'size':9})
        self.app.action('play',{'vertex':'E5'})
        self.assertEqual(self.app.board.moves,[['B','E5'],['W','D4']])
        self.assertAlmostEqual(self.app.evaluations[1]['blackWinrate'],.38)
        self.app.action('undo',{'pair':True})
        restored=Trainer(self.tmp.name)
        self.assertEqual(restored.board.moves,[])
        self.assertEqual(restored.board.size,9)
    def test_failed_move_does_not_mutate(self):
        self.app.settings['aiColor']='none'
        self.app.action('play',{'vertex':'E5'})
        before=deepcopy(self.app.board.__dict__)
        with self.assertRaises(ValueError):self.app.action('play',{'vertex':'E5'})
        self.assertEqual(before,self.app.board.__dict__)
    def test_http_token_origin_and_static(self):
        server=create_server(self.app,0);threading.Thread(target=server.serve_forever,daemon=True).start()
        c=http.client.HTTPConnection('127.0.0.1',server.server_port)
        try:
            c.request('GET','/');r=c.getresponse();self.assertEqual(r.status,200);self.assertIn(b'GO STUDIO',r.read())
            c.request('GET','/api/state');r=c.getresponse();state=json.loads(r.read())
            c.request('POST','/api/action/new',body='{}');r=c.getresponse();self.assertEqual(r.status,403);r.read()
            c.request('POST','/api/action/new',body='{}',headers={'X-Trainer-Token':state['token'],'Origin':'https://evil.invalid'});r=c.getresponse();self.assertEqual(r.status,403);r.read()
            c.request('GET','/api/state',headers={'Host':'evil.invalid'});r=c.getresponse();self.assertEqual(r.status,403);r.read()
            c.request('GET','/../../.git/config');r=c.getresponse();self.assertEqual(r.status,404);r.read()
        finally:c.close();server.shutdown();server.server_close()


if __name__=='__main__':unittest.main()
