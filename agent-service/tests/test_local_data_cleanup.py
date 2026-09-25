import tempfile
import unittest
from uuid import uuid4
from pathlib import Path
from fastapi import HTTPException
from agent_service.review_sessions import ReviewStore, SessionInput
from agent_service.store import TaskStore, TaskRecord
from tests.test_review_sessions import turn_body


class CleanupTests(unittest.TestCase):
    def test_scoped_cleanup_and_late_result(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory) / 'review.db')
            sid, other = str(uuid4()), str(uuid4())
            body = turn_body()
            initial = SessionInput(session_id=sid, revision=0, paused=False, binding=body.binding)
            store.upsert(initial)
            store.upsert(SessionInput(session_id=other, revision=0, paused=False, binding=body.binding))
            store.lookup(sid, body)
            store.erase([sid], [str(body.binding.attempt_id)])
            store.erase([sid], [str(body.binding.attempt_id)])
            with store.db() as db:
                self.assertEqual(db.execute('SELECT id FROM review_sessions').fetchall(), [(other,)])
                self.assertEqual(db.execute('SELECT count(*) FROM review_inputs').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM review_turns').fetchone()[0], 0)
            with self.assertRaises(HTTPException): store.finish(sid, body, {'feedback': 'late'})
            with self.assertRaises(HTTPException): store.upsert(initial)
            reopened = ReviewStore(Path(directory) / 'review.db')
            with self.assertRaises(HTTPException): reopened.upsert(initial)

    def test_capture_cleanup_fences_worker(self):
        store = TaskStore()
        removed = TaskRecord('one', 'source', 'private', 'zh')
        kept = TaskRecord('two', 'source', 'keep', 'zh')
        store.put(removed); store.put(kept)
        store.erase(['one']); store.put(removed)
        self.assertIsNone(store.get('one'))
        self.assertIsNotNone(store.get('two'))
        with self.assertRaises(ValueError): store.upsert_new(removed)

    def test_endpoint_validates_ids_and_returns_receipt(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from agent_service import main, review_sessions
        with tempfile.TemporaryDirectory() as directory, patch.object(review_sessions, 'store', ReviewStore(Path(directory)/'r.db')), patch.object(main, 'store', TaskStore()):
            client = TestClient(main.app)
            self.assertEqual(client.post('/v2/local-data/cleanup', json={'review_ids':['bad']}).status_code, 422)
            result = client.post('/v2/local-data/cleanup', json={'review_ids':[str(uuid4())]})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json(), {'cleaned': True})

if __name__ == '__main__': unittest.main()
