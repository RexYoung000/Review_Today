"""Collect already durable native state and local quota; no HTTP or model calls."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
PRIVATE=ROOT/'output/navigation-save-real-2026-10-22/gates'
def main():
    setup=json.loads((OUT/'setup.json').read_text());runtime=Path(setup['directory']);name=sys.argv[1]
    quota=json.loads((runtime/'quota.json').read_text());native=json.loads((runtime/'native-recheck-events.jsonl').read_text().splitlines()[-1])
    checkpoint=json.loads(native['checkpoint_json'])['checkpoint'] if native.get('checkpoint_json') else {}
    for suffix,value in [('snapshot',native),('quota',quota)]:
        (PRIVATE/(name+'-'+suffix+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    report=dict(name=name,models=quota['model_requests'],web=quota['web_operations'],phase=native['phase'],cards=native['knowledge_count'],cursor=native['cursor'],
        messages=[dict(role=m['role'],state=m['response_state'],text=m['text']) for m in native['messages'][-2:]],
        runs=[dict(id=k,status=v['status']) for k,v in checkpoint.get('runs',{}).items()],
        tasks=[dict(id=k,status=v['status'],current_step=(v['context'].get('learning_plan') or {}).get('current_step_id')) for k,v in checkpoint.get('tasks',{}).items()])
    (PRIVATE/(name+'-summary.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
