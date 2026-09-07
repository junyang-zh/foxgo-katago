"""Deterministic GTP fixture. Never used by the application or presented as KataGo."""
import sys
import time

for line in sys.stdin:
    if not line.strip():
        continue
    ident, command = line.strip().split(' ',1)
    verb = command.split()[0]
    if verb == 'kata-search_analyze_cancellable' and '--wait-cancel' in sys.argv:
        print(f'={ident}\ninfo move D4 visits 1 winrate .5 scoreLead 0 order 0 pv D4',flush=True)
        sys.stdin.readline()
        print('play cancelled\n',flush=True)
        continue
    if verb == 'hang':
        time.sleep(5)
    if verb == 'reject':
        print(f'?{ident} illegal move\n',flush=True)
        continue
    if verb == 'wrongid':
        print('=9999 wrong\n',flush=True)
        continue
    result = {'name':'KataGo test fixture','version':'test','protocol_version':'2',
              'known_command':'true','final_score':'B+2.5','fixed_handicap':'C3 G7'}.get(verb,'')
    if verb.startswith('kata-') and 'analyze' in verb:
        print(f'={ident}\ninfo move D4 visits 20 winrate 0.62 scoreLead 2.5 order 0 pv D4 E4 rootInfo visits 20 winrate 0.62 scoreLead 2.5\nplay D4\n',flush=True)
    else:
        print(f'={ident} {result}\n',flush=True)
