import tempfile
import unittest
from trainer.app import Trainer
from trainer.board import Board, point
from trainer.entertainment import heart_opening, heart_points


class HeartTests(unittest.TestCase):
    def test_complete_for_both_colors_and_all_board_sizes(self):
        for size in (9,13,19):
            for ai in ('B','W'):
                b=Board(size);enemy='W' if ai=='B' else 'B'
                plan=heart_points(size)
                self.assertEqual(len(set(plan)),14)
                for i,v in enumerate(plan):
                    decision=heart_opening(b,ai,True)
                    self.assertEqual(decision['next'],v)
                    self.assertEqual(decision['placed'],i)
                    self.assertEqual(heart_opening(b,ai,True),decision)
                    b.play(ai,v);b.play(enemy,'PASS')
                self.assertIsNone(heart_opening(b,ai,True)['next'])
                self.assertIn('complete',heart_opening(b,ai,True)['status'])

    def test_interruption_and_capture_fall_back(self):
        b=Board(19);plan=heart_points(19)
        b.play('B',plan[0]);b.play('W',plan[-1])
        self.assertIsNone(heart_opening(b,'B',True)['next'])
        x,y=point(plan[-1],19);b.grid[y][x]=''
        self.assertIsNone(heart_opening(b,'B',True)['next'])
        b=Board(19);b.play('B',plan[0]);x,y=point(plan[0],19);b.grid[y][x]=''
        self.assertIn('captured',heart_opening(b,'B',True)['status'])

    def test_disabled_imported_and_nonopening_games(self):
        b=Board(19)
        self.assertIsNone(heart_opening(b,'B',False)['next'])
        b.play('B','D4')
        self.assertIsNone(heart_opening(b,'B',True)['next'])
        b.setup_position([['B','D4']],'W',1)
        self.assertIsNone(heart_opening(b,'W',True)['next'])

    def test_setting_persists_without_connecting_engine(self):
        with tempfile.TemporaryDirectory() as path:
            app=Trainer(path)
            app.action('entertainment-settings',{'enabled':True})
            self.assertTrue(Trainer(path).settings['heartOpening'])
            self.assertIsNone(app.engine)
            with self.assertRaises(ValueError):app.action('entertainment-settings',{'enabled':'false'})

    def test_local_generation_uses_confirmed_engine_play(self):
        class Engine:
            alive=True
            def __init__(self):self.commands=[]
            def command(self,text,*args):self.commands.append(text);return 'play D4'
        with tempfile.TemporaryDirectory() as path:
            app=Trainer(path);app.engine=Engine();app.settings['heartOpening']=True
            move=app.generate('B')
            self.assertEqual(move,heart_points(19)[0])
            self.assertEqual(app.engine.commands,['play B '+move])
            self.assertEqual(app.board.moves,[['B',move]])
            for v in heart_points(19)[1:]:
                app.play('W','PASS')
                self.assertEqual(app.generate('B'),v)
            app.play('W','PASS')
            self.assertEqual(app.generate('B'),'D4')
            self.assertTrue(app.engine.commands[-1].startswith('kata-genmove_analyze'))
