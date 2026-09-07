"""Small board model for local play, captures, history and SGF export.

KataGo remains the legality/scoring authority whenever it is connected.
Offline play implements no suicide and simple ko (Chinese/Japanese).
"""
from copy import deepcopy
import re

LETTERS = 'ABCDEFGHJKLMNOPQRST'


def point(vertex, size):
    vertex = str(vertex).upper()
    if not re.fullmatch(r'[A-HJ-T][1-9][0-9]?', vertex):
        raise ValueError('Use a board coordinate such as D4, or pass.')
    x, y = LETTERS.index(vertex[0]), size - int(vertex[1:])
    if not (0 <= x < size and 0 <= y < size):
        raise ValueError('Move is outside the board.')
    return x, y


def color(value):
    c = str(value).upper()
    if c not in ('B', 'W', 'BLACK', 'WHITE'):
        raise ValueError('Color must be B or W.')
    return c[0]


class Board:
    def __init__(self, size=19, komi=7.5, rules='chinese'):
        if size not in (9, 13, 19):
            raise ValueError('Supported board sizes: 9, 13, 19.')
        self.size, self.komi, self.rules = size, komi, rules
        self.grid = [['' for _ in range(size)] for _ in range(size)]
        self.turn = 'B'
        self.moves = []
        self.handicap = []
        self.initial_stones = []
        self.initial_turn = 'B'
        self.move_offset = 0
        self.captures = {'B': 0, 'W': 0}
        self.result = ''
        self.history = [self.snapshot()]

    def snapshot(self):
        return dict(grid=deepcopy(self.grid), turn=self.turn,
                    captures=self.captures.copy(), result=self.result)

    def neighbors(self, x, y):
        return [(a, b) for a, b in ((x-1,y), (x+1,y), (x,y-1), (x,y+1))
                if 0 <= a < self.size and 0 <= b < self.size]

    def group(self, x, y):
        c, seen, liberties, todo = self.grid[y][x], set(), set(), [(x,y)]
        while todo:
            p = todo.pop()
            if p in seen:
                continue
            seen.add(p)
            for a, b in self.neighbors(*p):
                if not self.grid[b][a]:
                    liberties.add((a,b))
                elif self.grid[b][a] == c and (a,b) not in seen:
                    todo.append((a,b))
        return seen, liberties

    def play(self, c, vertex, *, authoritative=False):
        c, vertex = color(c), str(vertex).upper()
        before = self.snapshot()
        if vertex == 'RESIGN':
            self.result = ('W' if c == 'B' else 'B') + '+R'
        elif vertex != 'PASS':
            x, y = point(vertex, self.size)
            if self.grid[y][x]:
                raise ValueError('That intersection is occupied.')
            self.grid[y][x] = c
            removed = 0
            for a, b in self.neighbors(x,y):
                if self.grid[b][a] and self.grid[b][a] != c:
                    group, liberties = self.group(a,b)
                    if not liberties:
                        removed += len(group)
                        for u,v in group:
                            self.grid[v][u] = ''
            _, liberties = self.group(x,y)
            ko = len(self.history) > 1 and self.grid == self.history[-2]['grid']
            if not authoritative and (not liberties or ko):
                self.grid = before['grid']
                raise ValueError('Illegal move: suicide or ko recapture.')
            self.captures[c] += removed
        self.turn = 'W' if c == 'B' else 'B'
        self.moves.append([c, vertex])
        if vertex == 'PASS' and len(self.moves) > 1 and self.moves[-2][1] == 'PASS':
            self.result = 'Two passes — ready to score'
        self.history.append(self.snapshot())

    def undo(self):
        if not self.moves:
            raise ValueError('No move to undo.')
        self.moves.pop()
        self.history.pop()
        last = deepcopy(self.history[-1])
        self.grid, self.turn, self.captures, self.result = (
            last['grid'], last['turn'], last['captures'], last['result'])

    def setup(self, vertices):
        fresh = Board(self.size, self.komi, self.rules)
        for vertex in vertices:
            x,y = point(vertex, self.size)
            if fresh.grid[y][x]:
                raise ValueError('Duplicate handicap vertex.')
            fresh.grid[y][x] = 'B'
        fresh.handicap = list(vertices)
        fresh.turn = 'W' if vertices else 'B'
        fresh.history = [fresh.snapshot()]
        self.__dict__.update(fresh.__dict__)

    def setup_position(self, stones, turn, move_offset=0):
        """Import a position without inventing the moves that produced it."""
        fresh=Board(self.size,self.komi,self.rules)
        if not isinstance(move_offset,int) or move_offset<0:raise ValueError('Invalid snapshot move number.')
        for c,v in stones:
            c=color(c);x,y=point(v,self.size)
            if fresh.grid[y][x]:raise ValueError('Duplicate setup stone.')
            fresh.grid[y][x]=c;fresh.initial_stones.append([c,v])
        for y,row in enumerate(fresh.grid):
            for x,c in enumerate(row):
                if c and not fresh.group(x,y)[1]:raise ValueError('Detected position contains stones with no liberties.')
        fresh.turn=color(turn);fresh.initial_turn=fresh.turn;fresh.move_offset=move_offset
        fresh.history=[fresh.snapshot()]
        self.__dict__.update(fresh.__dict__)

    def sgf(self):
        def coord(v):
            if v in ('PASS', 'RESIGN'):
                return ''
            x,y = point(v, self.size)
            return chr(97+x) + chr(97+y)
        out = f'(;GM[1]FF[4]CA[UTF-8]AP[FoxGoKataGo:1.0]SZ[{self.size}]KM[{self.komi}]RU[{self.rules}]'
        if self.result and re.fullmatch(r'(B|W)\+([0-9.]+|R)|0', self.result):
            out += f'RE[{self.result}]'
        if self.handicap:
            out += f'HA[{len(self.handicap)}]AB' + ''.join(f'[{coord(v)}]' for v in self.handicap)
        if self.initial_stones or self.move_offset:
            for c in ('B','W'):
                vertices=[v for stone,v in self.initial_stones if stone==c]
                if vertices:out+='A'+c+''.join(f'[{coord(v)}]' for v in vertices)
            out+=f'PL[{self.initial_turn}]C[Screen snapshot at move {self.move_offset}. Earlier history and captures unknown.]'
        return out + ''.join(f';{c}[{coord(v)}]' for c,v in self.moves if v != 'RESIGN') + ')'
