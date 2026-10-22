#!/usr/bin/env python3
"""Decision 260: one pinned, isolated repair. No imports from the Agent runtime."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCOPE_FILE = Path(__file__).with_name('legacy-deletion-lifecycle-scope.json')
SCOPE_SHA256 = 'a928bb3adec522aaf64321a71ac9fd8ced3f807b506b17d9c255971661470937'


class RepairError(Exception):
    pass


class CommittedRepairError(RepairError):
    pass


def require(condition, message):
    if not condition:
        raise RepairError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_scope(path=None):
    path = path or SCOPE_FILE
    require(file_digest(path) == SCOPE_SHA256, '固定范围清单已变化；拒绝扩大对象。')
    return json.loads(path.read_text())


def isolated_work(path):
    work = Path(path).resolve(strict=True)
    allowed = ROOT/'output/legacy-lifecycle-repair-2026-10-22'
    temporary = next((p for p in (work, *work.parents) if p.parent == Path('/private/tmp')
                      and p.name.startswith('review-today-legacy-lifecycle-') and p.name.endswith('.noindex')), None)
    require(work.is_dir() and (work.is_relative_to(allowed) or temporary is not None), '本工具只接受决定 260 的隔离目录。')
    for name in ('app.store', 'checkpoint.sqlite3', 'archive-proof.store'):
        item = work/name
        require(item.is_file() and not item.is_symlink() and item.stat().st_nlink == 1, '输入须为三份独立实际副本。')
        for suffix in ('-wal', '-shm'):
            sidecar = work/(name+suffix)
            if sidecar.exists() or sidecar.is_symlink():
                require(not sidecar.is_symlink() and sidecar.stat().st_nlink == 1, '拒绝链接的数据库附属文件。')
    return work


def readonly(path):
    return sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)


def table_snapshot(db):
    result = {}
    for (table,) in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"):
        quoted = '"'+table.replace('"', '""')+'"'
        rows = db.execute('select * from '+quoted).fetchall()
        # This service schema contains only JSON/text/numeric columns.
        result[table] = sorted([list(row) for row in rows], key=canonical)
    return result


def validate_evidence(work, scope):
    proof = work/'archive-proof.store'
    require(file_digest(proof) == scope['archive_proof_sha256'], '旧备份指纹不匹配。')
    wal = work/'archive-proof.store-wal'
    require(not wal.exists() or wal.stat().st_size == 0, '旧备份存在未固定的 WAL。')
    with closing(readonly(work/'app.store')) as native:
        rows = native.execute('select ZSESSIONDELETIONSJSON from ZAPPSETTINGS').fetchall()
        require(len(rows) == 1, '原设置记录不唯一。')
        queue = json.loads(rows[0][0])
        require(digest(queue) == scope['native_queue_sha256'], '原删除队列或动作身份已变化。')
        for record in scope['records']:
            sid = record['session_id']
            markers = [m for m in queue if m.get('session_id') == sid]
            require(len(markers) == 1 and digest(markers[0]) == record['native_marker_sha256'], '原删除标记不匹配。')
            marker = markers[0]
            require(marker.get('action') == 'delete' and marker.get('lifecycle_revision') == 1 and marker.get('cleaned') is False,
                    '不属于固定的版本 1 待办。')
            require(not native.execute('select 1 from ZAGENTSESSION where ZID=?', (uuid.UUID(sid).bytes,)).fetchone(), '本机仍保留目标会话；拒绝兼容。')
    with closing(readonly(proof)) as old:
        for record in scope['records']:
            rows = old.execute('select ZSTATUS,ZLIFECYCLEREVISION from ZAGENTSESSION where ZID=?', (uuid.UUID(record['session_id']).bytes,)).fetchall()
            require(rows == [('archived', 0)], '旧备份未证明已归档／版本 0。')


def selected_payloads(db, scope, already_applied=False):
    result = {}
    for record in scope['records']:
        sid = record['session_id']
        require(not db.execute('select 1 from agent_session_deletions where session_id=?', (sid,)).fetchone(), '后台已有删除回执；拒绝重写旧记录。')
        rows = db.execute('select payload from agent_sessions_v2 where session_id=?', (sid,)).fetchall()
        require(len(rows) == 1, '对应后台记录不存在或不唯一。')
        raw = rows[0][0]
        payload = json.loads(raw)
        if already_applied:
            require(payload.get('status') == 'archived' and payload.get('lifecycle_revision') == 0, '已执行回执与后台状态不符。')
            original = dict(payload)
            del original['status']; del original['lifecycle_revision']
        else:
            require('status' not in payload and 'lifecycle_revision' not in payload, '后台已有生命周期字段；拒绝覆盖。')
            original = payload
        require(digest(original) == record['service_payload_sha256'], '后台内容与固定快照不匹配。')
        result[sid] = (raw, payload)
    return result


def backup_database(source, target):
    with closing(readonly(source)) as src, closing(sqlite3.connect(target)) as dest:
        src.backup(dest)
        require(dest.execute('pragma quick_check').fetchone()[0] == 'ok', '备份完整性检查失败。')


def repair(path, apply=False):
    work = isolated_work(path)
    scope = load_scope()
    validate_evidence(work, scope)
    target = work/'checkpoint.sqlite3'
    receipt_path = work/'compatibility-result.json'
    with closing(readonly(target)) as db:
        before = table_snapshot(db)
        if receipt_path.exists():
            require(not receipt_path.is_symlink(), '拒绝链接的回执。')
            receipt = json.loads(receipt_path.read_text())
            require(isinstance(receipt, dict), '执行回执格式不正确。')
            require(receipt.get('scope_sha256') == SCOPE_SHA256 and receipt.get('after_service_sha256') == digest(before), '回执与当前快照不一致。')
            selected_payloads(db, scope, already_applied=True)
            return dict(status='already_applied', records=3, written_records=0, scope_sha256=SCOPE_SHA256)
        selected_payloads(db, scope)
    if not apply:
        return dict(status='ready', records=3, written_records=0, scope_sha256=SCOPE_SHA256)
    backup = work/'compatibility-backup'
    require(not backup.exists(), '已有备份／失败现场；请保留并在新副本检查。')
    backup.mkdir(mode=0o700)
    for name in ('app.store', 'checkpoint.sqlite3', 'archive-proof.store'):
        backup_database(work/name, backup/name)
    with closing(readonly(backup/'checkpoint.sqlite3')) as copy:
        require(table_snapshot(copy) == before, '备份期间后台发生变化。')
    with closing(sqlite3.connect(target, timeout=1)) as db:
        try:
            db.execute('begin immediate')
            validate_evidence(work, scope)
            require(table_snapshot(db) == before, '事务开始前后台已变化。')
            selected = selected_payloads(db, scope)
            expected = json.loads(canonical(before))
            for sid, (raw, payload) in selected.items():
                patched = dict(payload, **scope['reconstruct'])
                encoded = json.dumps(patched, ensure_ascii=False)
                changed = db.execute('update agent_sessions_v2 set payload=? where session_id=? and payload=?', (encoded, sid, raw))
                require(changed.rowcount == 1, '目标在提交前变化。')
                for row in expected['agent_sessions_v2']:
                    if row[0] == sid:
                        row[1] = encoded
            expected['agent_sessions_v2'].sort(key=canonical)
            require(table_snapshot(db) == expected, '写入超出三条元数据范围；已拒绝提交。')
            db.commit()
        except Exception:
            db.rollback()
            raise
    receipt = dict(status='applied', records=3, written_records=3, scope_sha256=SCOPE_SHA256,
                   before_service_sha256=digest(before), after_service_sha256=digest(expected),
                   backup_directory=str(backup), native_marker_changed=False, model_requests=0, web_operations=0)
    with closing(readonly(target)) as db:
        if table_snapshot(db) != expected:
            raise CommittedRepairError('元数据已提交，但随后快照发生变化；保留备份并停止。')
    try:
        temporary = work/'compatibility-result.pending'
        with temporary.open('x') as stream:
            stream.write(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
        temporary.replace(receipt_path)
    except OSError as error:
        raise CommittedRepairError('三条元数据已提交，但回执未写入；保留现场，停止后续操作。') from error
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='only apply in an accepted isolated directory')
    args = parser.parse_args()
    try:
        result = repair(args.work_dir, args.apply)
    except CommittedRepairError as error:
        print(json.dumps(dict(status='committed_review_required', reason=str(error)), ensure_ascii=False))
        return 1
    except (RepairError, OSError, sqlite3.Error, ValueError, KeyError) as error:
        print(json.dumps(dict(status='refused', reason=str(error)), ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
