"""Durable service-level probe facts; no Session, prompts or credentials."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from agent_service.config import HARNESS_DB
from agent_service.run_accounting import _same_request, _usage_state

PROBE_ROUNDS = 4
USAGE_FIELDS = frozenset({"request_id", "response_id", "input_tokens", "output_tokens", "total_tokens",
                          "cached_input_tokens", "reasoning_output_tokens"})


class CapabilityLedger:
    def __init__(self, path=HARNESS_DB):
        self.path = Path(path)
        self.lock = threading.RLock()

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            try:
                with db:
                    db.execute("CREATE TABLE IF NOT EXISTS agent_capability_batches "
                               "(batch_id TEXT PRIMARY KEY, created_at REAL NOT NULL, payload TEXT NOT NULL)")
                    yield db
            finally:
                db.close()

    @contextmanager
    def _update(self, batch_id):
        with self._connection() as db:
            row = db.execute("SELECT payload FROM agent_capability_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if row is None:
                raise ValueError("RT.CAPABILITY.BATCH_MISSING")
            batch = json.loads(row[0])
            yield batch
            batch["updated_at"] = time.time()
            db.execute("UPDATE agent_capability_batches SET payload=? WHERE batch_id=?",
                       (json.dumps(batch, ensure_ascii=False), batch_id))

    def begin(self, provider):
        identity = str(uuid.uuid4())
        started = time.time()
        batch = dict(batch_id=identity, provider=provider, created_at=started, updated_at=started,
                     rounds=0, status="checking", calls=[])
        with self._connection() as db:
            db.execute("INSERT INTO agent_capability_batches VALUES (?, ?, ?)",
                       (identity, started, json.dumps(batch, ensure_ascii=False)))
        return identity

    def start_round(self, batch_id, index):
        with self._update(batch_id) as batch:
            if index != batch["rounds"] + 1 or index > PROBE_ROUNDS:
                raise ValueError("RT.CAPABILITY.ROUNDS_EXHAUSTED")
            batch.update(rounds=index, status="checking")

    def reserve(self, batch_id, index, *, model, roles, kind, strength):
        identity = str(uuid.uuid4())
        with self._update(batch_id) as batch:
            if index != batch["rounds"] or batch["status"] != "checking":
                raise ValueError("RT.CAPABILITY.ROUND_INACTIVE")
            batch["calls"].append(dict(id=identity, round=index, model=model, roles=list(roles), kind=kind,
                strength=strength, transport_requests=0, request_ids=[], usage=[], usage_state="unavailable", status="started"))
        return identity

    def request(self, batch_id, call_id):
        identity = str(uuid.uuid4())
        with self._update(batch_id) as batch:
            call = next(c for c in batch["calls"] if c["id"] == call_id)
            if batch["status"] != "checking" or call["round"] != batch["rounds"]:
                raise ValueError("RT.CAPABILITY.ROUND_INACTIVE")
            call["request_ids"].append(identity)
            call["transport_requests"] += 1
            call["usage_state"] = _usage_state(call)
        return identity

    def record(self, batch_id, call_id, *, usage=None, status=None):
        # Late receipts keep their original identity; they never restart a batch.
        with self._update(batch_id) as batch:
            call = next(c for c in batch["calls"] if c["id"] == call_id)
            if usage is not None:
                incoming = {key: value for key, value in usage.items() if key in USAGE_FIELDS}
                if not incoming.get("request_id") and call["transport_requests"] == 1:
                    incoming["request_id"] = call["request_ids"][0]
                existing = next((row for row in call["usage"]
                                 if _same_request(row, incoming, call["transport_requests"])), None)
                if existing is None:
                    call["usage"].append(incoming)
                else:
                    existing.update({key: value for key, value in incoming.items() if value is not None})
                call["usage_state"] = _usage_state(call)
            if status is not None:
                call["status"] = status

    def finish(self, batch_id, status):
        with self._update(batch_id) as batch:
            batch["status"] = status

    def get(self, batch_id):
        with self._connection() as db:
            row = db.execute("SELECT payload FROM agent_capability_batches WHERE batch_id=?", (batch_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def recent(self, limit=20):
        with self._connection() as db:
            rows = db.execute("SELECT payload FROM agent_capability_batches ORDER BY created_at DESC, rowid DESC LIMIT ?",
                              (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]
