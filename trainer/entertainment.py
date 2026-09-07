"""A deterministic opening policy derived from confirmed game history."""
from copy import deepcopy
from .board import LETTERS, point


def heart_points(size):
    center=size//2
    offsets=[(-2,-2),(-1,-2),(0,-1),(1,-2),(2,-2),(3,-1),(3,0),
             (2,1),(1,2),(0,3),(-1,2),(-2,1),(-3,0),(-3,-1)]
    return [LETTERS[center+x]+str(size-center-y) for x,y in offsets]


def heart_opening(board, ai, enabled):
    plan=heart_points(board.size)
    result=dict(enabled=enabled, total=len(plan), placed=0, next=None, status='Disabled')
    if not enabled:return result
    if board.handicap or board.initial_stones or board.move_offset:
        return dict(result,status='KataGo · imported or handicap position')
    own=[v for c,v in board.moves if c==ai]
    result['placed']=min(len(own),len(plan))
    if own[:len(plan)]!=plan[:min(len(own),len(plan))]:
        return dict(result,status='KataGo · opening interrupted')
    if len(own)>=len(plan):return dict(result,status='KataGo · heart complete')
    # History makes interruption permanent, even if that opponent stone is captured.
    if any(c!=ai and v in plan for c,v in board.moves):
        return dict(result,status='KataGo · opponent interrupted the heart')
    for v in own:
        x,y=point(v,board.size)
        if board.grid[y][x]!=ai:return dict(result,status='KataGo · heart stone captured')
    vertex=plan[len(own)]
    try:
        candidate=deepcopy(board);candidate.play(ai,vertex)
    except ValueError:return dict(result,status='KataGo · next heart move is illegal')
    if board.result:return dict(result,status='Game ended')
    return dict(result,next=vertex,status=f'Heart opening · {len(own)}/{len(plan)} stones')
