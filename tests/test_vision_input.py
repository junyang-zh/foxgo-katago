import os
import unittest
from unittest.mock import MagicMock
from trainer.vision_native import WindowsDesktop


@unittest.skipUnless(os.name=='nt','Windows input boundary')
class InputTests(unittest.TestCase):
    def desktop(self):
        desktop=object.__new__(WindowsDesktop);desktop.u=MagicMock()
        info=dict(hwnd=1,pid=1,rect=[-1400,52,960,1508])
        desktop.describe=MagicMock(return_value=info);desktop.emergency=lambda:False
        desktop.u.GetForegroundWindow.return_value=1
        desktop.u.GetAsyncKeyState.return_value=0
        desktop.u.GetAncestor.return_value=1
        cursor=[0,0]
        def position(x,y):cursor[:]=[x,y];return 1
        def read(ptr):ptr._obj.x,ptr._obj.y=cursor;return 1
        desktop.u.SetCursorPos.side_effect=position;desktop.u.GetCursorPos.side_effect=read
        desktop.u.SendInput.return_value=2
        return desktop,info,cursor

    def test_physical_target_and_no_early_parking(self):
        d,info,cursor=self.desktop();d.click(1,332,1077,info)
        self.assertEqual(cursor,[-1068,1129])
        count,inputs,size=d.u.SendInput.call_args.args
        self.assertEqual(count,2)
        self.assertEqual([event.u.mi.dwFlags for event in inputs],[2,4])
        d.park(1);self.assertEqual(cursor,[-220,62])

    def test_wrong_cursor_cancels_button_input(self):
        d,info,cursor=self.desktop();d.u.SetCursorPos.side_effect=lambda x,y:1
        with self.assertRaises(ValueError):d.click(1,332,1077,info)
        d.u.SendInput.assert_not_called()
