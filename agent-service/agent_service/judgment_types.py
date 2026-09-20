"""Bounded semantic decisions. No stores, provider settings or answer generation."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL = "jev-1.13.0"
VERSION = "jev-harness-1"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


class JudgmentQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["choice"] = "choice"
    instructions: str = Field(min_length=1)
    criteria: dict[str, str]

    @model_validator(mode="after")
    def bounded(self):
        if not 2 <= len(self.criteria) <= 255 or "unsure" not in self.criteria:
            raise ValueError("bounded choices require unsure")
        if any(not k.strip() or not v.strip() for k, v in self.criteria.items()):
            raise ValueError("blank choice")
        return self


def question(instructions, criteria):
    return JudgmentQuestion(instructions=instructions, criteria={
        **criteria, "unsure": "材料不足、范围不清或不能确定，不猜测。"})


class JudgmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: str
    version: str = VERSION
    state: dict[str, Any]
    questions: dict[str, JudgmentQuestion] = Field(min_length=1, max_length=128)
    sources: list[dict[str, Any]] = Field(default_factory=list)

    def payload(self):
        return dict(model=MODEL, state=self.state,
                    questions={k: q.model_dump() for k, q in self.questions.items()})


class JudgmentResult(BaseModel):
    node: str
    version: str = VERSION
    model: str | None = None
    input_hash: str
    status: Literal["ok", "uncertain", "failed", "skipped"]
    answers: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: float = 0
    usage: dict[str, Any] | None = None
    applied: bool = False
    reason: str = ""
    cached: bool = False
    sources: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def labels(self):
        return {key: value["choice"] for key, value in self.answers.items()}


def validate_choices(questions, answers):
    """Validate the entire response; failures never become negative selections."""
    if not isinstance(answers, dict) or answers.keys() != questions.keys():
        raise ValueError("missing or extra judgments")
    for key, q in questions.items():
        criteria = q.criteria if hasattr(q, "criteria") else q["criteria"]
        answer = answers[key]
        if not isinstance(answer, dict) or answer.get("type") != "choice" or answer.get("choice") not in criteria:
            raise ValueError("invalid choice")
        probs = answer.get("probabilities")
        if not isinstance(probs, dict) or probs.keys() != criteria.keys():
            raise ValueError("incomplete probability distribution")
        if any(type(v) not in (int, float) or not 0 <= v <= 1 or not math.isfinite(v)
               for v in [*probs.values(), answer.get("confidence")]):
            raise ValueError("invalid probability")
        # The API rounds probabilities to two decimals.
        if abs(sum(probs.values()) - 1) > len(probs) * .005 + 1e-8:
            raise ValueError("invalid probability sum")
        if probs[answer["choice"]] + .010001 < max(probs.values()):
            raise ValueError("choice disagrees with probabilities")
    return answers
