"""Exercise the installed real KataGo over HTTP and FoxGTP TCP (isolated session).

Run after setup_katago.py. Does not contact FoxGo or join an online match.
"""
import json
from pathlib import Path
import socket
import tempfile
import threading
import urllib.request
import urllib.error
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from trainer.app import Trainer
from trainer.server import create_server


def main():
    settings=json.loads((ROOT/'data/settings.json').read_text('utf-8'))
    with tempfile.TemporaryDirectory() as tmp:
        app=Trainer(tmp)
        server=create_server(app,0)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        url=f'http://127.0.0.1:{server.server_port}'
        token=json.load(urllib.request.urlopen(url+'/api/state'))['token']
        def action(name,data=None):
            req=urllib.request.Request(url+'/api/action/'+name,
                data=json.dumps(data or {}).encode(),headers={'Content-Type':'application/json','X-Trainer-Token':token})
            try:
                with urllib.request.urlopen(req,timeout=650) as response:return json.load(response)
            except urllib.error.HTTPError as exc:
                raise RuntimeError(exc.read().decode()) from exc
        try:
            state=action('engine-connect',settings)
            assert state['engine'] and state['analysis']['choices']
            assert len(state['analysis']['ownership'])==361
            print('PASS: real GPU engine, streaming candidates and ownership',flush=True)
            state=action('play',{'vertex':'D4'})
            assert len(state['moves'])==2 and state['grid'][15][3]=='B'
            assert state['analyses'].get('1') and state['evaluations'].get('2')
            print('PASS: local human move, automatic AI reply, perspective-normalized curves',flush=True)
            state=action('undo',{'pair':True});assert state['moves']==[]
            # Choose an ephemeral port, then bind through the production action.
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            action('fox-start',{'port':port})
            with socket.create_connection(('127.0.0.1',port),timeout=30) as sock:
                reader=sock.makefile('rb')
                def command(ident,text):
                    sock.sendall(f'{ident} {text}\n'.encode())
                    response=b''
                    while not response.endswith(b'\n\n'):
                        line=reader.readline()
                        assert line,'unexpected EOF'
                        response+=line
                    assert response.startswith(f'={ident}'.encode()),response
                    return response.decode()
                for ident,cmd in enumerate(['protocol_version','clear_board','boardsize 19','komi 6.5',
                    'time_settings 60 29 1','time_left B 60 0','play B D4','genmove W','final_score'],1):
                    reply=command(ident,cmd)
                    if cmd=='genmove W':assert 'info move' not in reply and len(reply.splitlines())==2
                reader.close()
            print('PASS: numbered FoxGTP commands, clocks, real generated reply and scoring',flush=True)
            action('fox-stop')
            state=action('new',{'size':9,'handicap':2})
            assert len(state['handicap'])==2
            print('PASS: 9x9 fixed handicap',flush=True)
            assert 'HA[2]' in urllib.request.urlopen(url+'/api/sgf').read().decode()
            state=action('new',{'size':13,'rules':'japanese','komi':6.5})
            assert state['size']==13 and state['rules']=='japanese'
            print('PASS: 13x13 Japanese rules and SGF export',flush=True)
        finally:
            server.shutdown();server.server_close();app.close()


if __name__=='__main__':main()
