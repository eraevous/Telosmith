import json
import statistics as st
from pathlib import Path

B=Path('/home/claude/telosmith/docs/evaluations/probe-001')
def load(sched, mech, tdir):
    m={r['trial']:r for r in mech}
    rows=[]
    for x in sched:
        s=json.loads((tdir/x['trial']/'transcript_summary.json').read_text())
        u=s['usage']; tot=sum(u.values())
        r=m[x['trial']]
        ok = r['own_suite_pass'] and r.get('preservation_pass') and (x['task']=='T3' or r.get('functionality_pass'))
        rows.append(dict(x, ok=ok, calls=s['tool_calls'], tot=tot, cr=u['cache_read']/tot, out=u['output']))
    return rows
new=load(json.load(open('/root/.cache/p001r-sealed/schedule.private.json')),[json.loads(line) for line in open('grade.out') if line.startswith('{')],Path('trials'))
old=load(json.load(open(B/'schedule.json')),[json.loads(line) for line in open(B/'mechanical.jsonl')],B/'trials')
def table(rows):
    for t in 'T1 T2 T3'.split():
        print(t,' | '.join(f"{c}: {sum(r['ok'] for r in rows if r['task']==t and r['cond']==c)}/2" for c in 'ABC'))
def med(rows,t,c,k='tot'): return st.median(r[k] for r in rows if r['task']==t and r['cond']==c)
for name,rows in (('rerun',new),('orig',old)):
    print('==',name); table(rows)
    for t in 'T1 T2 T3'.split():
        a=med(rows,t,'A'); print(t,'medtot A %.2fM'%(a/1e6),' B %+.0f%%'%(100*(med(rows,t,'B')/a-1)),' C %+.0f%%'%(100*(med(rows,t,'C')/a-1)),
              ' calls A/B/C', med(rows,t,'A','calls'),med(rows,t,'B','calls'),med(rows,t,'C','calls'),' out A/B/C',med(rows,t,'A','out'),med(rows,t,'B','out'),med(rows,t,'C','out'))
print('== rerun per trial')
for r in sorted(new,key=lambda r:(r['task'],r['cond'],r['trial'])):
    print(f"| {r['task']} | {r['cond']} | {r['trial']} | {r['calls']} | {r['tot']/1e6:.2f}M | {r['cr']*100:.0f}% | {r['out']:,} | {'yes' if r['ok'] else 'NO'} |")
json.dump(new,open('rerun_rows.json','w'),indent=1)
