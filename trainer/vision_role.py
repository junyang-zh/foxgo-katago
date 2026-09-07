"""Read the known account's color from FoxGo's player list, using local OCR."""
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile


def read_words(image):
    with tempfile.TemporaryDirectory(prefix='foxgo-ocr-') as tmp:
        path=Path(tmp)/'role.png';image.save(path)
        shell=Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        try:
            result=subprocess.run([str(shell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                '-File',str(Path(__file__).with_name('windows_ocr.ps1')),'-ImagePath',str(path)],
                capture_output=True,encoding='utf-8',timeout=12,creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('Windows OCR timed out; waiting to read the player identity again.') from exc
        if result.returncode:raise ValueError('Windows OCR could not read FoxGo: '+result.stderr.strip()[:250])
        return json.loads(result.stdout)


def account_color(image, lines, nickname):
    """Require the account in the player header AND beside a player-list stone."""
    nickname=''.join(nickname.split())
    if not nickname:raise ValueError('No FoxGo account identity is saved for automatic role detection.')
    matches=[]
    for line in lines:
        words=line['words']
        for start in range(len(words)):
            text=''
            for end in range(start,len(words)):
                text+=''.join(words[end]['text'].split())
                if text==nickname:
                    part=words[start:end+1]
                    matches.append((min(w['x'] for w in part),min(w['y'] for w in part),
                        max(w['x']+w['width'] for w in part),max(w['y']+w['height'] for w in part)))
                if len(text)>=len(nickname):break
    # The upper occurrence is the seated player; the lower one is the user list.
    matches.sort(key=lambda r:r[1])
    if len(matches)!=2 or matches[1][1]-matches[0][3]<matches[0][3]-matches[0][1]:
        raise ValueError('Waiting to recognize the account in both FoxGo player header and user list.')
    x0,y0,x1,y1=matches[1];height=y1-y0
    cx=x1+height;cy=(y0+y1)/2
    samples=[]
    for i in range(32):
        a=i*math.tau/32
        x=round(cx+height*.15*math.cos(a));y=round(cy+height*.15*math.sin(a))
        if not (0<=x<image.width and 0<=y<image.height):raise ValueError('Player color icon is outside the image.')
        samples.append(image.getpixel((x,y))[:3])
    black=sum(max(rgb)<120 and max(rgb)-min(rgb)<45 for rgb in samples)
    white=sum(min(rgb)>165 and max(rgb)-min(rgb)<45 for rgb in samples)
    if max(black,white)<28:raise ValueError('Waiting for a clear player color icon beside the account name.')
    patch=image.crop((max(0,round(cx-height*.6)),max(0,round(cy-height*.6)),
        min(image.width,round(cx+height*.6)),min(image.height,round(cy+height*.6)))).convert('L')
    low,high=patch.getextrema()
    if high-low<45:raise ValueError('Player color icon has no visible stone edge or shading.')
    color='B' if black>white else 'W'
    return dict(color=color,account=nickname,source='FoxGo player header and user-list color icon',
        bounds=[max(0,round(x0)),max(0,round(y0-height*.3)),min(image.width,round(cx+height)),min(image.height,round(y1+height*.3))])


def detect_role(image,cfg,nickname):
    # Exclude board and chat: duplicate mentions in chat cannot identify a player.
    left=round(cfg['x1']+cfg['dx']*.7)
    top=round(cfg['y0']+cfg['dy']*2)
    bottom=min(image.height,round(cfg['y0']+cfg['dy']*8))
    crop=image.crop((left,top,image.width,bottom)).convert('RGB')
    result=account_color(crop,read_words(crop),nickname)
    x0,y0,x1,y1=result['bounds'];result['bounds']=[x0+left,y0+top,x1+left,y1+top]
    return result
