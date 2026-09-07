"""Fox Go AI Protocol v1.05: ASCII, XOR checksum, CRLF; scores in hundredths."""
from dataclasses import dataclass
from decimal import Decimal
from functools import reduce
from operator import xor
import re
from .board import LETTERS, point

MAX_PACKET = 65536


def encode(command, *fields):
    body = ','.join([command, *(str(v) for v in fields)])
    if not re.fullmatch(r'[A-Z]+(?:,[^$*\r\n]*)?', body):
        raise ValueError('Invalid FoxGo packet body.')
    raw = body.encode('ascii')
    if len(raw) > MAX_PACKET-6:
        raise ValueError('FoxGo packet is too large.')
    return b'$'+raw+f'*{reduce(xor,raw,0):02X}\r\n'.encode('ascii')


def decode(packet):
    if len(packet) > MAX_PACKET or not packet.endswith(b'\r\n'):
        raise ValueError('FoxGo packet must end in CRLF and fit within 64 KiB.')
    match = re.fullmatch(rb'\$([^$*\r\n]+)\*([0-9a-fA-F]{2})\r\n',packet)
    if not match or reduce(xor,match[1],0) != int(match[2],16):
        raise ValueError('Malformed FoxGo packet or checksum mismatch.')
    fields = match[1].decode('ascii').split(',')
    if fields[0] not in {'FASTATUS','FAMOVE','FASKIP','FARESULT','FARULE','FATIMELEFT','FASCORE'}:
        raise ValueError(f'Unsupported FoxGo command: {fields[0]}')
    return fields[0],fields[1:]


class Framer:
    def __init__(self):
        self.pending = b''

    def feed(self,chunk):
        self.pending += chunk
        packets = []
        while b'\n' in self.pending:
            line,self.pending = self.pending.split(b'\n',1)
            if len(line)+1 > MAX_PACKET:
                raise ValueError('FoxGo packet exceeds 64 KiB.')
            packets.append(line+b'\n')
        if len(self.pending) >= MAX_PACKET:
            raise ValueError('Unterminated FoxGo packet exceeds 64 KiB.')
        return packets


def integer(text,minimum=0,maximum=2**31-1):
    if not re.fullmatch(r'-?\d+',str(text)):
        raise ValueError('Expected a FoxGo integer.')
    value = int(text)
    if not minimum <= value <= maximum:
        raise ValueError('FoxGo integer is out of range.')
    return value


def side(text):
    if text not in ('B','W'):
        raise ValueError('FoxGo color must be B or W.')
    return text


def flag(text):
    return bool(integer(text,0,1))


def other(c):
    return 'W' if c == 'B' else 'B'


def move_record(text,size,*,handicap=False,sentinel=False):
    if sentinel and text == '0^0^0^N':
        return None
    fields = text.split('^')
    if len(fields) != 4:
        raise ValueError('FoxGo move must contain index^x^y^color.')
    index = integer(fields[0],0 if handicap else 1)
    if handicap and (index != 0 or fields[3] != 'B'):
        raise ValueError('Handicap records must have index 0 and color B.')
    x,y = integer(fields[1],0,size-1),integer(fields[2],0,size-1)
    return index,side(fields[3]),LETTERS[x]+str(size-y)


def outgoing_move(index,c,vertex,size):
    x,y = point(vertex,size)
    return encode('AFPLAY',c,f'{index}^{x}^{y}^{c}')


def score_from_fox(text):
    if text == '0':
        return '0'
    match = re.fullmatch(r'([BW])\+(R|\d+)',text)
    if not match:
        raise ValueError('Invalid FoxGo game result.')
    if match[2] == 'R':
        return text
    return match[1]+'+'+format(Decimal(match[2])/100,'f')


def score_to_fox(text):
    text = text.strip().upper()
    if text in ('0','DRAW','JIGO'):
        return '0'
    match = re.fullmatch(r'([BW])\+(\d+(?:\.\d+)?)',text)
    if not match:
        return 'error'
    units = Decimal(match[2])*100
    return f'{match[1]}+{int(units)}' if units == units.to_integral_value() else 'error'


@dataclass(frozen=True)
class Rules:
    size: int
    main: int
    byo: int
    periods: int
    komi: float
    handicap: tuple

    @classmethod
    def parse(cls,fields):
        if len(fields) < 5:
            raise ValueError('FARULE requires size, main time, byo-yomi, periods and komi.')
        size = integer(fields[0],9,19)
        if size not in (9,13,19):
            raise ValueError('Unsupported FoxGo board size.')
        main,byo,periods = (integer(v) for v in fields[1:4])
        if bool(byo) != bool(periods):
            raise ValueError('Byo-yomi time and periods must both be positive or both zero.')
        komi = integer(fields[4],-10000,10000)/100
        handicap = tuple(move_record(v,size,handicap=True)[2] for v in fields[5:])
        if len(handicap) > 9 or len(set(handicap)) != len(handicap):
            raise ValueError('Invalid handicap placement.')
        return cls(size,main,byo,periods,komi,handicap)
