"""Isolated synthetic SQLite contracts for the one-time decision-260 tool."""
from contextlib import closing, contextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('legacy_lifecycle_repair', ROOT/'tools/repair-legacy-deletion-lifecycle.py')
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
REAL_SCOPE, REAL_SHA = tool.SCOPE_FILE, tool.SCOPE_SHA256

@contextmanager
def database(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


class RepairContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='review-today-legacy-lifecycle-', suffix='.noindex',dir='/private/tmp')
        self.work = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        self.ids = [str(uuid.uuid4()) for _ in range(3)]
        self.queue = [dict(session_id=sid, action_id=str(uuid.uuid4()), archive_action_id=str(uuid.uuid4()),
                           action='delete', lifecycle_revision=1, cleaned=False, deleted_at='2026-09-07T13:03:53Z') for sid in self.ids]
        with database(self.work/'app.store') as db:
            db.execute('create table ZAPPSETTINGS(ZSESSIONDELETIONSJSON text)')
            db.execute('insert into ZAPPSETTINGS values (?)', (json.dumps(self.queue),))
            db.execute('create table ZAGENTSESSION(ZID blob)')
        with database(self.work/'archive-proof.store') as db:
            db.execute('create table ZAGENTSESSION(ZID blob,ZSTATUS text,ZLIFECYCLEREVISION integer)')
            db.executemany('insert into ZAGENTSESSION values (?,?,?)', [(uuid.UUID(sid).bytes,'archived',0) for sid in self.ids])
        self.payloads = {sid:dict(session_id=sid,messages=[dict(content='synthetic transcript '+str(i))],runs={},events=[]) for i,sid in enumerate(self.ids)}
        with database(self.work/'checkpoint.sqlite3') as db:
            db.execute('create table agent_sessions_v2(session_id text primary key,payload text)')
            db.executemany('insert into agent_sessions_v2 values (?,?)', [(sid,json.dumps(p)) for sid,p in self.payloads.items()])
            db.execute('insert into agent_sessions_v2 values (?,?)', ('keep',json.dumps(dict(status='active',lifecycle_revision=4,messages=['preserve']))))
            db.execute('create table agent_session_deletions(session_id text,action_id text,lifecycle_revision integer,deleted_at text)')
            db.execute('create table usage(request_id text,amount integer)');db.execute("insert into usage values ('keep',9)")
        self.scope = dict(scope_id='synthetic',archive_proof_sha256=tool.file_digest(self.work/'archive-proof.store'),
                          native_queue_sha256=tool.digest(self.queue),reconstruct=dict(status='archived',lifecycle_revision=0),
                          records=[dict(record_number=i+4,session_id=sid,native_marker_sha256=tool.digest(self.queue[i]),service_payload_sha256=tool.digest(self.payloads[sid])) for i,sid in enumerate(self.ids)])
        self.scope_file = self.work/'scope.json'
        self.pin = patch.object(tool,'SCOPE_FILE',self.scope_file);self.pin.start();self.addCleanup(self.pin.stop)
        self.sha = patch.object(tool,'SCOPE_SHA256','');self.sha.start();self.addCleanup(self.sha.stop)
        self.pin_scope()

    def pin_scope(self):
        self.scope_file.write_text(json.dumps(self.scope))
        tool.SCOPE_SHA256 = tool.file_digest(self.scope_file)

    def state(self):
        with database(self.work/'checkpoint.sqlite3') as db:return tool.table_snapshot(db)

    def refuse(self,reason):
        before = self.state()
        with self.assertRaisesRegex((tool.RepairError,sqlite3.Error),reason):
            tool.repair(self.work,apply=True)
        self.assertEqual(self.state(),before)
        self.assertFalse((self.work/'compatibility-result.json').exists())

    def test_real_manifest_pin(self):
        self.assertEqual(tool.file_digest(REAL_SCOPE),REAL_SHA)
        self.assertEqual(len(json.loads(REAL_SCOPE.read_text())['records']),3)

    def test_default_dry_run_writes_nothing(self):
        before = self.state()
        self.assertEqual(tool.repair(self.work)['status'],'ready')
        self.assertEqual(before,self.state())
        self.assertFalse((self.work/'compatibility-backup').exists())

    def test_apply_only_two_fields_and_preserves_native(self):
        original_native = tool.file_digest(self.work/'app.store')
        before = self.state();report = tool.repair(self.work,apply=True)
        self.assertEqual(report['written_records'],3)
        after = self.state();self.assertEqual(after['usage'],before['usage'])
        for sid,raw in after['agent_sessions_v2']:
            p = json.loads(raw)
            if sid in self.ids:
                self.assertEqual(p.pop('status'),'archived');self.assertEqual(p.pop('lifecycle_revision'),0)
                self.assertEqual(p,self.payloads[sid])
            else:self.assertIn([sid,raw],before['agent_sessions_v2'])
        self.assertEqual(tool.file_digest(self.work/'app.store'),original_native)
        with database(self.work/'compatibility-backup/checkpoint.sqlite3') as backup:self.assertEqual(tool.table_snapshot(backup),before)

    def test_second_apply_does_not_write(self):
        tool.repair(self.work,apply=True);before=self.state()
        self.assertEqual(tool.repair(self.work,apply=True)['status'],'already_applied')
        self.assertEqual(self.state(),before)

    def test_changed_delete_identity_refused(self):
        self.queue[1]['action_id']=str(uuid.uuid4())
        with database(self.work/'app.store') as db:db.execute('update ZAPPSETTINGS set ZSESSIONDELETIONSJSON=?',(json.dumps(self.queue),))
        self.refuse('原删除队列')

    def test_present_native_session_refused(self):
        with database(self.work/'app.store') as db:db.execute('insert into ZAGENTSESSION values (?)',(uuid.UUID(self.ids[0]).bytes,))
        self.refuse('本机仍保留')

    def test_archive_fingerprint_change_refused(self):
        with database(self.work/'archive-proof.store') as db:db.execute("update ZAGENTSESSION set ZSTATUS='active'")
        self.refuse('旧备份指纹')

    def test_archive_not_archived_even_if_pinned_refused(self):
        with database(self.work/'archive-proof.store') as db:db.execute("update ZAGENTSESSION set ZSTATUS='active'")
        self.scope['archive_proof_sha256']=tool.file_digest(self.work/'archive-proof.store');self.pin_scope()
        self.refuse('旧备份未证明')

    def test_one_changed_payload_prevents_all_three(self):
        with database(self.work/'checkpoint.sqlite3') as db:db.execute('update agent_sessions_v2 set payload=? where session_id=?',(json.dumps(dict(self.payloads[self.ids[2]],new_message='new')),self.ids[2]))
        self.refuse('后台内容与固定快照')

    def test_existing_lifecycle_field_refused(self):
        with database(self.work/'checkpoint.sqlite3') as db:db.execute('update agent_sessions_v2 set payload=? where session_id=?',(json.dumps(dict(self.payloads[self.ids[1]],status=None)),self.ids[1]))
        self.refuse('后台已有生命周期字段')

    def test_missing_service_row_refused(self):
        with database(self.work/'checkpoint.sqlite3') as db:db.execute('delete from agent_sessions_v2 where session_id=?',(self.ids[1],))
        self.refuse('后台记录不存在')

    def test_existing_tombstone_refused(self):
        with database(self.work/'checkpoint.sqlite3') as db:db.execute('insert into agent_session_deletions values (?,?,?,?)',(self.ids[1],'receipt',1,'then'))
        self.refuse('后台已有删除回执')

    def test_failure_on_second_row_rolls_back_first(self):
        with database(self.work/'checkpoint.sqlite3') as db:db.execute("create trigger fail_second before update on agent_sessions_v2 when new.session_id='"+self.ids[1]+"' begin select raise(abort,'injected');end")
        self.refuse('injected')
        self.assertTrue((self.work/'compatibility-backup/checkpoint.sqlite3').exists())

    def test_unexpected_trigger_side_effect_rolls_back(self):
        with database(self.work/'checkpoint.sqlite3') as db:db.execute("create trigger unexpected after update on agent_sessions_v2 begin update usage set amount=0;end")
        self.refuse('写入超出三条元数据范围')

    def test_fixed_manifest_cannot_expand(self):
        self.scope_file.write_text('{}')
        self.refuse('固定范围清单')

    def test_daily_directory_rejected_before_database_access(self):
        with self.assertRaises(tool.RepairError):tool.isolated_work(Path.home()/'Library/Application Support/Review Today')

    def test_symlink_input_refused(self):
        p=self.work/'checkpoint.sqlite3';real=self.work/'copied-checkpoint';p.rename(real);p.symlink_to(real)
        with self.assertRaises(tool.RepairError):tool.repair(self.work,apply=True)

    def test_hardlink_input_refused(self):
        (self.work/'extra-link').hardlink_to(self.work/'checkpoint.sqlite3')
        self.refuse('独立实际副本')

    def test_tampered_receipt_refused(self):
        tool.repair(self.work,apply=True)
        p=self.work/'compatibility-result.json';v=json.loads(p.read_text());v['after_service_sha256']='wrong';p.write_text(json.dumps(v));before=self.state()
        with self.assertRaises(tool.RepairError):tool.repair(self.work,apply=True)
        self.assertEqual(before,self.state())

    def test_receipt_write_failure_reports_committed_state(self):
        (self.work/'compatibility-result.pending').write_text('reserved')
        with self.assertRaises(tool.CommittedRepairError):tool.repair(self.work,apply=True)
        self.assertFalse((self.work/'compatibility-result.json').exists())
        for sid,raw in self.state()['agent_sessions_v2']:
            if sid in self.ids:self.assertEqual(json.loads(raw)['status'],'archived')
        # A missing receipt must never silently authorize another write.
        self.refuse('后台已有生命周期字段')


if __name__=='__main__':unittest.main(verbosity=2)
