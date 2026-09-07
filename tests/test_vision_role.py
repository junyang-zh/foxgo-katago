import unittest
from unittest.mock import patch, MagicMock
try:
    from PIL import Image, ImageDraw
except ImportError:
    raise unittest.SkipTest('Install Pillow to run vision tests.')
from trainer.vision_role import account_color
from trainer import server


class RoleTests(unittest.TestCase):
    def fixture(self,color):
        im=Image.new('RGB',(300,150),(210,215,220))
        lines=[dict(words=[dict(text='Account',x=150,y=20,width=70,height=20)]),
               dict(words=[dict(text='Account',x=20,y=100,width=70,height=20)])]
        ImageDraw.Draw(im).ellipse((97,97,123,123),fill=(35,35,35) if color=='B' else (245,245,245),outline=(100,100,100),width=2)
        return im,lines

    def test_black_and_white_roles(self):
        for c in ('B','W'):
            im,lines=self.fixture(c)
            self.assertEqual(account_color(im,lines,'Account')['color'],c)

    def test_missing_or_ambiguous_identity_and_missing_icon(self):
        im,lines=self.fixture('B')
        for ls,name in ((lines,'Other'),(lines[:1],'Account'),(lines+lines,'Account')):
            with self.assertRaises(ValueError):account_color(im,ls,name)
        with self.assertRaises(ValueError):account_color(Image.new('RGB',im.size,'white'),lines,'Account')

    def test_backend_starts_engine_before_serving(self):
        events=[];app=MagicMock();http=MagicMock()
        app.ensure_engine.side_effect=lambda:events.append('engine')
        http.serve_forever.side_effect=lambda:events.append('serve')
        with patch.object(server,'Trainer',return_value=app),patch.object(server,'create_server',return_value=http),patch('sys.argv',['trainer.server']),patch('builtins.print'):
            server.main()
        self.assertEqual(events,['engine','serve']);app.close.assert_called_once()

    def test_failed_engine_start_does_not_report_ready_or_serve(self):
        app=MagicMock();http=MagicMock();app.ensure_engine.side_effect=RuntimeError('missing model')
        with patch.object(server,'Trainer',return_value=app),patch.object(server,'create_server',return_value=http),patch('sys.argv',['trainer.server']),patch('builtins.print'),self.assertRaises(SystemExit):
            server.main()
        http.serve_forever.assert_not_called();app.close.assert_called_once();http.server_close.assert_called_once()
