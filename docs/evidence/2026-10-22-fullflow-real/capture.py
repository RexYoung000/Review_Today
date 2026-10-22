"""Read-only collection of the current native snapshot and quota; no model/UI calls."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
RUNTIME=Path('/private/tmp/review-today-fullflow-i9njdmrd.noindex')
PRIVATE=ROOT/'output/fullflow-real-2026-10-22/gates'
name=sys.argv[1]
q=json.loads((RUNTIME/'quota.json').read_text())
s=json.loads((RUNTIME/'native-recheck-events.jsonl').read_text().splitlines()[-1])
c=json.loads(s['checkpoint_json'])['checkpoint'] if s.get('checkpoint_json') else {}
PRIVATE.mkdir(parents=True,exist_ok=True)
(PRIVATE/(name+'-snapshot.json')).write_text(json.dumps(s,ensure_ascii=False,indent=2))
(PRIVATE/(name+'-quota.json')).write_text(json.dumps(q,ensure_ascii=False,indent=2))
print(json.dumps(dict(name=name,models=q['model_requests'],web=q['web_operations'],phase=s['phase'],knowledge=s['knowledge_count'],offers=json.loads(s['capture_offers_json']),messages=[dict(role=m['role'],state=m['response_state'],text=m['text']) for m in s['messages'][-2:]],runs=[dict(id=k,status=v['status']) for k,v in c.get('runs',{}).items()],tasks=[dict(id=k,status=v['status'],context=v['context']) for k,v in c.get('tasks',{}).items()]),ensure_ascii=False))
