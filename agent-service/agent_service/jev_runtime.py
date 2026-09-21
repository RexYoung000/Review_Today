"""Explicit native test activation; never changes the normal provider or store."""
from __future__ import annotations

import json
import os
from pathlib import Path

from agent_service.jev_client import JevClient
from agent_service.judgment_nodes import ENTRY_VERSION
from agent_service.judgment_types import MODEL
from agent_service.judgments import JudgmentEngine


def configured_judgments(store, *, port, environment=None):
    environment = os.environ if environment is None else environment
    flag = environment.get("REVIEW_TODAY_JEV_TEST", "0")
    if flag not in {"0", "1"}:
        raise RuntimeError("RT.JEV.INVALID_TEST_FLAG")
    if flag == "0":
        return None
    if not 1024 <= port <= 65535 or port == 8742:
        raise RuntimeError("RT.JEV.ISOLATED_PORT_REQUIRED")
    JudgmentEngine.check_isolation(store)
    # The launcher passes a path, never the secret itself. Do not discover or
    # read credentials at all when the experiment is disabled.
    path = Path(environment.get("REVIEW_TODAY_JEV_KEY_FILE", "")).expanduser()
    try:
        if not path.is_absolute():
            raise ValueError("credential path required")
        key = json.loads(path.read_text(encoding="utf-8")).get("api_key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("credential unavailable")
    except (OSError, ValueError, AttributeError):
        raise RuntimeError("RT.JEV.CREDENTIAL_UNAVAILABLE") from None
    return JudgmentEngine(JevClient(key.strip()))


def runtime_status(engine):
    if engine is None:
        return dict(status="off", model=None, entry_rule=None)
    return dict(status="authentication_disabled" if engine.client.blocked.is_set() else "enabled",
                model=MODEL, entry_rule=ENTRY_VERSION)
