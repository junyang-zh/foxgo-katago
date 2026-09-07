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
        if self.u.IsIconic(hwnd) or self.u.GetForegroundWindow()!=hwnd:
            raise ValueError('Bring the calibrated FoxGo window to the foreground.')
        image=self.grab(bbox=tuple(info['rect']),all_screens=True).convert('RGB')
        return image,info

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
        # Absolute virtual-desktop coordinates make negative-monitor origins work.
        left,top=self.u.GetSystemMetrics(76),self.u.GetSystemMetrics(77)
        width,height=self.u.GetSystemMetrics(78),self.u.GetSystemMetrics(79)
        dx=round((px-left)*65535/max(1,width-1));dy=round((py-top)*65535/max(1,height-1))
        events=[INPUT(0,INPUTUNION(MOUSEINPUT(dx,dy,0,f,0,0))) for f in (0xC001,0xC003,0xC005)]
        # Park over the title bar so FoxGo's hover square cannot obscure recognition.
        parkx=round(((current['rect'][0]+current['rect'][2])/2-left)*65535/max(1,width-1))
        parky=round((current['rect'][1]+10-top)*65535/max(1,height-1))
        events.append(INPUT(0,INPUTUNION(MOUSEINPUT(parkx,parky,0,0xC001,0,0))))
        inputs=(INPUT*4)(*events)
        if self.u.SendInput(4,inputs,C.sizeof(INPUT))!=4:
            raise RuntimeError('Windows rejected mouse input. Match application privilege levels.')
