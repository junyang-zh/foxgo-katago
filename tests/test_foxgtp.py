import socket
import sys
import tempfile
import unittest
from pathlib import Path
from trainer.app import Trainer
from trainer.foxgtp import FoxGTPServer
from trainer.gtp import GTP

class RelayTests(unittest.TestCase):
    def test_relay_numbered_commands_and_online_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Trainer(tmp)
            app.engine=GTP([sys.executable,'-u',str(Path(__file__).with_name('fake_engine.py'))])
            server=FoxGTPServer(app,0);app.fox_server=server;app.mode='online';app.connector='foxgtp';server.start()
            try:
                with socket.create_connection(('127.0.0.1',server.socket.getsockname()[1]),timeout=3) as client:
                    with client.makefile('rb') as reader:
                        client.sendall(b'1 protocol_ver');client.sendall(b'sion\n2 clear_board\n3 boardsize 9\n4 play B E5\n5 genmove W\n')
                        answers=[]
                        for _ in range(5):
                            out=b''
                            while not out.endswith(b'\n\n'):
                                line=reader.readline();self.assertTrue(line);out+=line
                            answers.append(out)
                        self.assertEqual(answers[0],b'=1 2\n\n')
                        self.assertEqual(answers[-1],b'=5 D4\n\n')
                        self.assertEqual(app.board.moves,[['B','E5'],['W','D4']])
                        with self.assertRaises(ValueError):app.action('new',{})
                        with self.assertRaises(ValueError):app.action('fox-sync',{'color':'W'})
            finally:app.close()
