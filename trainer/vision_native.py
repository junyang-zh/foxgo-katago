"""Windows capture/input boundary. Imported only when vision is selected."""
import ctypes as C
from ctypes import wintypes as W
import os
import re
from pathlib import Path


class WindowsDesktop:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Screen connector requires Windows.')
        try:
            from PIL import ImageGrab
        except ImportError:
            raise RuntimeError('Install vision support: python -m pip install Pillow>=11.2.1')
        self.grab = ImageGrab.grab
        self.u = C.WinDLL('user32', use_last_error=True)
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.u.SetThreadDpiAwarenessContext.argtypes = [C.c_void_p]
        self.u.SetThreadDpiAwarenessContext.restype = C.c_void_p
        self.u.GetForegroundWindow.restype = W.HWND
        self.u.WindowFromPoint.argtypes = [W.POINT]
        self.u.WindowFromPoint.restype = W.HWND
        self.u.GetAncestor.argtypes = [W.HWND,W.UINT]
        self.u.GetAncestor.restype = W.HWND
        self.u.GetWindowRect.argtypes = [W.HWND,C.POINTER(W.RECT)]
        self.u.GetWindowTextW.argtypes = [W.HWND,W.LPWSTR,C.c_int]
        self.u.GetWindowThreadProcessId.argtypes = [W.HWND,C.POINTER(W.DWORD)]
        self.u.IsWindowVisible.argtypes = [W.HWND]
        self.u.IsIconic.argtypes = [W.HWND]
        self.u.SetForegroundWindow.argtypes = [W.HWND]
        self.k.OpenProcess.argtypes = [W.DWORD,W.BOOL,W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.QueryFullProcessImageNameW.argtypes = [W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.u.GetAsyncKeyState.argtypes = [C.c_int]
        self.u.GetAsyncKeyState.restype = C.c_short

    def describe(self, hwnd):
        self.u.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        pid=W.DWORD();self.u.GetWindowThreadProcessId(hwnd,C.byref(pid))
        handle=self.k.OpenProcess(0x1000,False,pid.value)
        if not handle: raise ValueError('Cannot inspect selected window process.')
        try:
            name=C.create_unicode_buffer(32768);length=W.DWORD(len(name))
            if not self.k.QueryFullProcessImageNameW(handle,0,name,C.byref(length)):
                raise ValueError('Cannot identify window executable.')
        finally:self.k.CloseHandle(handle)
        if Path(name.value).name.lower() != 'foxwq.exe':
            raise ValueError('Select a FoxGo (foxwq.exe) window.')
        title=C.create_unicode_buffer(2048);self.u.GetWindowTextW(hwnd,title,len(title))
        rect=W.RECT()
        if not self.u.GetWindowRect(hwnd,C.byref(rect)):raise ValueError('Window disappeared.')
        room=re.search(r'(\d+(?:\|\d+)?号房间)',title.value)
        number=re.search(r'第(\d+)手',title.value)
        return dict(hwnd=int(hwnd),pid=pid.value,title=title.value,
                    active='对弈中' in title.value, room=room[1] if room else None,
                    moveNumber=int(number[1]) if number else None,
                    rect=[rect.left,rect.top,rect.right,rect.bottom])

    def windows(self):
        found=[]
        callback=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        def visit(hwnd,_):
            if self.u.IsWindowVisible(hwnd):
                try:
                    info=self.describe(hwnd)
                    if info['rect'][2]-info['rect'][0]>500 and info['rect'][3]-info['rect'][1]>400:
                        found.append(info)
                except ValueError:pass
            return True
        self.u.EnumWindows(callback(visit),0)
        return found

    def capture(self, hwnd):
        info=self.describe(hwnd)
        if self.u.IsIconic(hwnd):raise ValueError('Restore the minimized FoxGo window.')
        image=self.grab(window=hwnd).convert('RGB')
        if image.size!=(info['rect'][2]-info['rect'][0],info['rect'][3]-info['rect'][1]):
            raise ValueError('FoxGo capture dimensions disagree with window geometry.')
        return image,info

    def prepare_click(self, hwnd):
        info=self.describe(hwnd)
        from .windows_privileges import integrity_level
        target_level=integrity_level(info['pid']);our_level=integrity_level(os.getpid())
        if target_level is not None and our_level is not None and target_level>our_level:
            raise ValueError('Windows blocks input: FoxGo runs as Administrator, but the trainer does not. Restart with start.ps1 -Administrator, or run FoxGo without Administrator privileges.')
        if self.u.GetForegroundWindow()!=hwnd:self.u.SetForegroundWindow(hwnd)
        if self.u.GetForegroundWindow()!=hwnd:
            raise ValueError('Windows prevented FoxGo activation; select FoxGo once to allow input.')

    def emergency(self):
        return bool(self.u.GetAsyncKeyState(0x1B)&0x8000)

    def click(self, hwnd, x, y, expected):
        current=self.describe(hwnd)
        if current != expected or self.u.GetForegroundWindow()!=hwnd or self.emergency():
            raise ValueError('Window changed or Escape pressed; click cancelled.')
        if any(self.u.GetAsyncKeyState(key)&0x8000 for key in (1,2,16,17,18)):
            raise ValueError('Release mouse buttons and modifier keys before automatic play.')
        px,py=current['rect'][0]+round(x),current['rect'][1]+round(y)
        hit=self.u.WindowFromPoint(W.POINT(px,py))
        if self.u.GetAncestor(hit,2)!=hwnd:
            raise ValueError('Another window covers the move; click cancelled.')
        class MOUSEINPUT(C.Structure):
            _fields_=[('dx',W.LONG),('dy',W.LONG),('mouseData',W.DWORD),('dwFlags',W.DWORD),('time',W.DWORD),('dwExtraInfo',C.c_size_t)]
        class INPUTUNION(C.Union):
            _fields_=[('mi',MOUSEINPUT)]
        class INPUT(C.Structure):
            _fields_=[('type',W.DWORD),('u',INPUTUNION)]
        self.u.SendInput.argtypes=[W.UINT,C.POINTER(INPUT),C.c_int]
        # GetWindowRect and SetCursorPos share physical coordinates under the
        # thread's DPI context; avoid virtual-desktop normalization across DPIs.
        self.u.SetCursorPos.argtypes=[C.c_int,C.c_int]
        self.u.GetCursorPos.argtypes=[C.POINTER(W.POINT)]
        if not self.u.SetCursorPos(px,py):raise RuntimeError('Windows rejected cursor positioning.')
        actual=W.POINT();self.u.GetCursorPos(C.byref(actual))
        if (actual.x,actual.y)!=(px,py):raise ValueError('Cursor did not reach the move; click cancelled.')
        events=[INPUT(0,INPUTUNION(MOUSEINPUT(0,0,0,f,0,0))) for f in (0x0002,0x0004)]
        # Leave the cursor here until the next observation cycle. FoxGo can
        # consult its current position when processing queued button events.
        inputs=(INPUT*2)(*events)
        if self.u.SendInput(2,inputs,C.sizeof(INPUT))!=2:
            raise RuntimeError('Windows rejected mouse input. Match application privilege levels.')

    def park(self, hwnd):
        current=self.describe(hwnd)
        if self.u.GetForegroundWindow()!=hwnd:return
        self.u.SetCursorPos.argtypes=[C.c_int,C.c_int]
        self.u.SetCursorPos(round((current['rect'][0]+current['rect'][2])/2),current['rect'][1]+10)
