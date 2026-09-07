"""Read-only Windows integrity checks for cross-process input permission."""
import ctypes as C
from ctypes import wintypes as W


def integrity_level(pid):
    kernel=C.WinDLL('kernel32',use_last_error=True);adv=C.WinDLL('advapi32',use_last_error=True)
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.CloseHandle.argtypes=[W.HANDLE]
    adv.OpenProcessToken.argtypes=[W.HANDLE,W.DWORD,C.POINTER(W.HANDLE)]
    adv.GetTokenInformation.argtypes=[W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)]
    adv.GetSidSubAuthorityCount.argtypes=[C.c_void_p];adv.GetSidSubAuthorityCount.restype=C.POINTER(C.c_ubyte)
    adv.GetSidSubAuthority.argtypes=[C.c_void_p,W.DWORD];adv.GetSidSubAuthority.restype=C.POINTER(W.DWORD)
    process=kernel.OpenProcess(0x1000,False,pid)
    if not process:return None
    token=W.HANDLE()
    try:
        if not adv.OpenProcessToken(process,8,C.byref(token)):return None
        length=W.DWORD();adv.GetTokenInformation(token,25,None,0,C.byref(length))
        if not length.value:return None
        buffer=C.create_string_buffer(length.value)
        if not adv.GetTokenInformation(token,25,buffer,len(buffer),C.byref(length)):return None
        sid=C.cast(buffer,C.POINTER(C.c_void_p))[0]
        return adv.GetSidSubAuthority(sid,adv.GetSidSubAuthorityCount(sid)[0]-1)[0]
    finally:
        if token:kernel.CloseHandle(token)
        kernel.CloseHandle(process)
