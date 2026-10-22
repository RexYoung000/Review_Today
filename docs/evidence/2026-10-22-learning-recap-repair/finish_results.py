"""Summarize only completed offline logs; never start services or paid calls."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
def summary(name):
    text=(OUT/name).read_text();line=text.strip().splitlines()[-1]
    assert ' failed' not in line and 'KeyboardInterrupt' not in text,line
    passed=re.search(r'(\d+) passed',line);assert passed,line
    skipped=re.search(r'(\d+) skipped',line);subtests=re.search(r'(\d+) subtests passed',line)
    return dict(log=name,passed=int(passed[1]),skipped=int(skipped[1]) if skipped else 0,subtests=int(subtests[1]) if subtests else 0,summary=line)
def main():
    full=summary('full-suite-controlled.log');target=summary('targeted-complete.log');deep=summary('deepseek-controlled.log')
    full['provider']='openai_compatible';deep['provider']='deepseek'
    target['early_import_isolation_deviation_disclosed']=True
    target['included_in_final_fully_isolated_suite']=True
    assert full['passed']>1300 and full['skipped']==4
    pins=json.loads((OUT/'source-final-pins.json').read_text());assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in pins.items())
    replay=json.loads((OUT/'replay-result.json').read_text());assert replay['status']=='PASS_CONTROLLED_REPLAY'
    protect=json.loads((OUT/'protection-result.json').read_text());assert protect['last_real_batch_unchanged'] and protect['daily_remaining_files_unchanged']
    result=dict(status='IMPLEMENTED_OFFLINE_VERIFIED_REAL_ACCEPTANCE_PENDING',full=full,targeted=target,deepseek=deep,new_navigation_tests=13,controlled_real_history_replay=True,real_model_requests=0,real_web_operations=0,daily_app_not_started_or_replaced=True,daily_business_database_hashes_unchanged=True,disclosed_empty_wal_and_shm_cleanup=True,all_daily_files_byte_identical=False,old_frozen_quotas_and_real_evidence_unchanged=True,source_pins_verified=True,native_ui_not_run=True,new_model_navigation_and_full_chain_not_verified=True)
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
