from copy import deepcopy
import socket
import tempfile
import unittest
from trainer.app import Trainer
from trainer.fox_presence import FoxPresence
from trainer.fox_protocol import encode


class PresenceTests(unittest.TestCase):
    def test_packets_do_not_play_or_change_cv_state(self):
        with tempfile.TemporaryDirectory() as path:
            app=Trainer(path);app.mode='vision'
            before=deepcopy(app.board.__dict__)
            listener=FoxPresence(app,0);listener.start()
            try:
                with socket.create_connection(('127.0.0.1',listener.port)) as client:
                    client.settimeout(.3)
                    client.sendall(encode('FASTATUS',0)+encode('FAMOVE',1,'W','1^4^4^B'))
                    with self.assertRaises(socket.timeout):client.recv(1024)
                    self.assertTrue(listener.state()['connected'])
                    self.assertEqual(listener.state()['lastMessage'],'FAMOVE')
                    self.assertEqual(app.board.__dict__,before)
                    self.assertEqual(app.mode,'vision');self.assertIsNone(app.engine)
            finally:listener.stop();app.close()
            replacement=FoxPresence(app,listener.port);replacement.stop()

    def test_conflicting_listener_fails_without_changing_board(self):
        with tempfile.TemporaryDirectory() as path:
            app=Trainer(path);listener=FoxPresence(app,0)
            try:
                with self.assertRaises(OSError):FoxPresence(app,listener.port)
                self.assertEqual(app.board.moves,[])
            finally:listener.stop();app.close()
