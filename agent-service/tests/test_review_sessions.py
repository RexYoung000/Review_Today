"""Review v2 contracts; isolated storage, synthetic materials, no paid calls."""
import hashlib
import json
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from agent_service import review_sessions as r


def binding():
    spec = dict(learning_goal='解释光合作用', must_cover=['利用光能', '二氧化碳和水生成有机物并释放氧气'],
                acceptable_paraphrases=['光驱动制造糖'], common_misconceptions=['将氧气作为主要原料'],
                evidence='植物利用光能，将二氧化碳和水转为有机物，并释放氧气。', order_rules='')
    raw = json.dumps(spec, ensure_ascii=False)
    return r.Binding(attempt_id=uuid4(), knowledge_id=uuid4(), knowledge_version=1, question_id=uuid4(),
                     spec_version=hashlib.sha256(raw.encode()).hexdigest(), rubric_json=raw,
                     prompt='光合作用利用什么能量，原料和产物是什么？', scoring_spec=spec)


def turn_body(**kw):
    return r.TurnInput(event_id=uuid4(), revision=0, binding=binding(), text='光驱动二氧化碳和水制造糖，并放出氧气。', **kw)


def judgment(**kw):
    return r.Judgment(**(dict(intent='answer', coverage=['met', 'met'], misconceptions=['absent'],
                             explicit_recall_difficulty=False, answer_revealed=False, feedback='正确。') | kw))


class EvaluationTests(unittest.TestCase):
    def evaluate(self, j, body=None):
        with patch.object(r, 'parse_model', return_value=j):
            return r.evaluate(body or turn_body())

    def test_independent_grades(self):
        self.assertEqual(self.evaluate(judgment())['grade'], 'good')
        self.assertEqual(self.evaluate(judgment(explicit_recall_difficulty=True))['grade'], 'hard')
        for j in [judgment(coverage=['met', 'missing']), judgment(misconceptions=['present'])]:
            self.assertEqual(self.evaluate(j)['grade'], 'again')
        self.assertIsNone(self.evaluate(judgment(coverage=['met', 'uncertain']))['grade'])
        self.assertIsNone(self.evaluate(judgment(misconceptions=['uncertain']))['grade'])

    def test_controls_and_help_are_not_answer_grades(self):
        for intent in ['clarify', 'hint', 'explain', 'skip', 'pause', 'correction', 'wait', 'understood']:
            self.assertIsNone(self.evaluate(judgment(intent=intent, coverage=[], misconceptions=[]))['grade'])
        self.assertEqual(self.evaluate(judgment(intent='forgot', coverage=[], misconceptions=[]))['grade'], 'again')

    def test_partial_schema_and_action_mismatch_fail_closed(self):
        with self.assertRaises(ValueError): self.evaluate(judgment(coverage=['met']))
        with self.assertRaises(ValueError): self.evaluate(judgment(), turn_body(action='hint'))
        raw = binding().model_dump(); raw['rubric_json'] += ' '
        with self.assertRaises(ValueError): r.Binding.model_validate(raw)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='review-today-v2-')
        self.store = r.ReviewStore(self.tmp.name + '/test.sqlite3')
        self.body = turn_body(); self.sid = str(uuid4())
        self.session = r.SessionInput(session_id=self.sid, revision=0, binding=self.body.binding)
        self.store.upsert(self.session)

    def tearDown(self): self.tmp.cleanup()

    def test_duplicate_conflict_and_recovery(self):
        self.assertIsNone(self.store.lookup(self.sid, self.body))
        with self.assertRaises(HTTPException): self.store.lookup(self.sid, self.body)
        restart = r.ReviewStore(self.store.path)
        self.assertIsNone(restart.lookup(self.sid, self.body))
        restart.finish(self.sid, self.body, {'grade': 'good'})
        self.assertEqual(restart.lookup(self.sid, self.body), {'grade': 'good'})
        changed = self.body.model_copy(update={'text': 'different'})
        with self.assertRaises(HTTPException): restart.lookup(self.sid, changed)
        with restart.db() as db:
            self.assertEqual(json.loads(db.execute('SELECT payload FROM review_inputs').fetchone()[0])['text'], self.body.text)

    def test_pause_versions_and_late_result(self):
        self.store.lookup(self.sid, self.body)
        self.store.upsert(self.session.model_copy(update={'revision': 1, 'paused': True}))
        with self.assertRaises(HTTPException): self.store.finish(self.sid, self.body, {'grade':'good'})
        with self.assertRaises(HTTPException): self.store.upsert(self.session)
        with self.assertRaises(HTTPException): self.store.lookup(self.sid, self.body)

    def test_receipt_idempotency(self):
        b = self.body.binding
        receipt = r.CommitInput(attempt_id=b.attempt_id, knowledge_id=b.knowledge_id, knowledge_version=1,
                                question_id=b.question_id, spec_version=b.spec_version, correction_revision=0,
                                state='completed', effective_grade='good', schedule_after='synthetic')
        self.assertTrue(self.store.commit(self.sid, receipt)['accepted'])
        self.assertTrue(self.store.commit(self.sid, receipt)['accepted'])
        with self.assertRaises(HTTPException): self.store.commit(self.sid, receipt.model_copy(update={'effective_grade':'again'}))
        self.store.commit(self.sid, receipt.model_copy(update={'effective_grade':'again','correction_revision':1}))
        with self.store.db() as db: self.assertEqual(db.execute('SELECT count(*) FROM review_commits').fetchone()[0], 2)

    def test_http_failure_has_no_success_result_and_can_retry(self):
        app = FastAPI(); app.include_router(r.router)
        with patch.object(r, 'store', self.store), TestClient(app) as client:
            path = f'/v2/review/sessions/{self.sid}/turns'
            with patch.object(r, 'evaluate', side_effect=TimeoutError):
                self.assertEqual(client.post(path, json=self.body.model_dump(mode='json')).status_code, 502)
            with patch.object(r, 'evaluate', return_value={'grade':'good'}) as call:
                for _ in range(2): self.assertEqual(client.post(path, json=self.body.model_dump(mode='json')).json(), {'grade':'good'})
                self.assertEqual(call.call_count, 1)
            invalid = self.body.model_dump(mode='json'); del invalid['binding']['question_id']
            self.assertEqual(client.post(path, json=invalid).status_code, 422)

    def test_pause_cancels_inflight_transport_and_drops_late_result(self):
        started, closed = threading.Event(), threading.Event()
        def slow(body, register):
            register(closed.set); started.set(); closed.wait(3)
            return {'grade': 'good'}
        app = FastAPI(); app.include_router(r.router)
        with patch.object(r, 'store', self.store), patch.object(r, 'evaluate', slow), TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
            job=pool.submit(client.post, f'/v2/review/sessions/{self.sid}/turns', json=self.body.model_dump(mode='json'))
            self.assertTrue(started.wait(3))
            self.store.upsert(self.session.model_copy(update={'revision':1,'paused':True}))
            self.assertEqual(job.result(timeout=3).status_code,409)
            self.assertTrue(closed.is_set())
        with self.store.db() as db: self.assertEqual(db.execute('SELECT count(*) FROM review_turns').fetchone()[0],0)


if __name__ == '__main__': unittest.main()
