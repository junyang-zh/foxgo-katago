"""Optional TCP presence for screen play; never sends moves or changes a board."""
import socket
import threading
from .fox_protocol import Framer, decode


class FoxPresence:
    def __init__(self,app,port):
        self.app=app;self.closed=threading.Event();self.guard=threading.Lock()
        self.client=None;self.connected=False;self.last='';self.thread=None
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            self.socket.bind(('127.0.0.1',port));self.socket.listen(1);self.socket.settimeout(.3)
            self.port=self.socket.getsockname()[1]
        except Exception:
            self.socket.close();raise

    def state(self):
        with self.guard:
            return dict(listening=not self.closed.is_set(),connected=self.connected,
                        port=self.port,lastMessage=self.last)

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def run(self):
        while not self.closed.is_set():
            try:client,_=self.socket.accept()
            except socket.timeout:continue
            except OSError:break
            with self.guard:
                if self.closed.is_set():client.close();break
                self.client=client;self.connected=True
            client.settimeout(.3);framer=Framer()
            self.app.log('fox','FoxGo connected to the AI presence listener; screen control owns moves.')
            try:
                while not self.closed.is_set():
                    try:data=client.recv(8192)
                    except socket.timeout:continue
                    if not data:break
                    for packet in framer.feed(data):
                        command,_=decode(packet)
                        with self.guard:self.last=command
                        self.app.log('fox →', 'Presence only: '+packet.decode('ascii').strip())
            except (OSError,ValueError) as exc:
                if not self.closed.is_set():self.app.log('warning','AI presence connection: '+str(exc))
            finally:
                client.close()
                with self.guard:self.client=None;self.connected=False

    def stop(self):
        self.closed.set();self.socket.close()
        with self.guard:client=self.client
        if client:
            try:client.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            client.close()
        if self.thread:self.thread.join(timeout=2)
