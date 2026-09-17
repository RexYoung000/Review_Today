"""Strict case inventory. No production imports, model calls or database access."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / 'agent-service/tests/fixtures/agent_cases'
# Preserve message whitespace verbatim; trimming a fixture can change Markdown
# or the very input that triggered the original issue.
Text = Annotated[str, StringConstraints(min_length=1, pattern=r'\S')]
CaseID = Annotated[str, StringConstraints(pattern=r'^A\d{3}$')]
ScenarioID = Annotated[str, StringConstraints(pattern=r'^A\d{3}-[a-z0-9-]+$')]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Source(Strict):
    kind: Literal['user_report', 'test_discovery']
    reference: Text
    inputs: list[Text] = Field(min_length=1)
    actual: Text
    context_status: Literal['complete', 'partial', 'not_applicable']
    known_context: list[Text] = Field(min_length=1)
    missing_context: list[Text]

    @model_validator(mode='after')
    def honest_gaps(self):
        if (self.context_status == 'partial') != bool(self.missing_context):
            raise ValueError('partial context must list gaps; complete context cannot hide gaps')
        return self


class Evidence(Strict):
    layer: Literal['controlled', 'live_fixed_context', 'live_flow', 'native']
    reference: Text
    limits: Text


class Case(Strict):
    id: CaseID
    title: Text
    domain: Literal['dialogue', 'tool', 'native', 'mixed']
    source: Source
    expected: list[Text] = Field(min_length=1)
    forbidden: list[Text] = Field(min_length=1)
    controlled: list[Text] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    fixed_scenarios: list[ScenarioID]
    fixed_scope: Text
    remaining_gap: Text
    acceptance: Literal['pending', 'accepted']
    acceptance_reference: Text | None

    @model_validator(mode='after')
    def acceptance_needs_evidence(self):
        if self.domain == 'dialogue' and self.source.context_status == 'not_applicable':
            raise ValueError('dialogue cases must describe context completeness')
        if self.acceptance == 'accepted' and not self.acceptance_reference:
            raise ValueError('acceptance requires an explicit review record')
        return self


class Catalog(Strict):
    schema_version: Literal[1]
    cases: list[Case] = Field(min_length=1)


class Exchange(Strict):
    user: Text
    coach: Text
    social_reply_kind: Literal['social', 'companionship', 'learning_support'] | None


class Step(Strict):
    title: Text
    state: Literal['pending', 'explained', 'verified', 'skipped']
    understanding: Literal['unknown', 'partial', 'verified']


class Goal(Strict):
    title: Text
    mode: Literal['source_learning', 'topic_exploration', 'problem_solving']
    steps: list[Step] = Field(min_length=1, max_length=10)
    current_step: int = Field(ge=0)
    understanding: Literal['unknown', 'partial', 'verified']

    @model_validator(mode='after')
    def valid_step(self):
        if self.current_step >= len(self.steps) or len({s.title for s in self.steps}) != len(self.steps):
            raise ValueError('invalid current step or duplicate step title')
        return self


class InitialState(Strict):
    mode: Literal['auto', 'memory_organization', 'source_learning', 'topic_exploration', 'problem_solving']
    thinking_strength: Literal['smart', 'deep']
    history: list[Exchange]
    summary: str
    paused: bool
    current_task: Goal | None
    task_history_index: int | None
    other_goals: list[Goal]
    # Version 1 supports an explicitly empty pending state. Complex bound actions
    # remain in their transactional tests; unknown data must never be ignored.
    pending: None
    draft: None

    @model_validator(mode='after')
    def task_has_message_evidence(self):
        if self.current_task is None:
            if self.task_history_index is not None:
                raise ValueError('no task can refer to a task history entry')
        elif self.task_history_index is None or not 0 <= self.task_history_index < len(self.history):
            raise ValueError('current task requires a history entry containing its request/lesson')
        return self


FIELD_TYPES = {
    'mode': str,
    'intent.conversation_kind': str, 'intent.clarification_kind': str,
    'intent.intents': list, 'social_reply_kind': str, 'reply': str,
    'intent.resource_boundary': str,
    'resource_scope_reply': bool,
    'reply_length': int, 'stages': list, 'task_count': int,
    'tasks_unchanged': bool, 'plan_ids_unchanged': bool,
    'old_goals_unchanged': bool, 'capture_offer_count': int,
    'goal_transfer': bool, 'current_understanding': str,
}
POSITIVE_FIELDS = {'intent.conversation_kind', 'intent.intents', 'intent.clarification_kind',
                   'intent.resource_boundary', 'resource_scope_reply', 'social_reply_kind', 'reply', 'stages', 'goal_transfer'}


class Check(Strict):
    field: Text
    op: Literal['eq', 'contains', 'excludes', 'gte', 'lte']
    value: str | int | bool

    @model_validator(mode='after')
    def valid_operation(self):
        kind = FIELD_TYPES.get(self.field)
        if kind is None:
            raise ValueError(f'unknown assertion field: {self.field}')
        if self.op in {'gte', 'lte'}:
            valid = kind is int and type(self.value) is int
        elif self.op in {'contains', 'excludes'}:
            valid = kind in {str, list} and type(self.value) is str and bool(self.value.strip())
        else:
            valid = type(self.value) is kind
        if not valid:
            raise ValueError(f'invalid assertion {self.field} {self.op}')
        return self


class Scenario(Strict):
    id: ScenarioID
    case_id: CaseID
    provenance: Literal['synthetic_reconstruction', 'observed_sanitized']
    provenance_note: Text
    source_reference: Text
    initial: InitialState
    input: Text
    checks: list[Check] = Field(min_length=1)
    manual_review: list[Text] = Field(min_length=1)

    @model_validator(mode='after')
    def behavior_not_just_absence(self):
        if not self.id.startswith(self.case_id + '-'):
            raise ValueError('scenario must use its case prefix')
        positive = any(c.field in POSITIVE_FIELDS and c.op in {'eq', 'contains'}
                       and bool(c.value) for c in self.checks)
        if not positive:
            raise ValueError('requires a positive routing/response behavior assertion')
        signatures = [(c.field, c.op, str(c.value)) for c in self.checks]
        if len(signatures) != len(set(signatures)):
            raise ValueError('duplicate assertion')
        return self


class Scenarios(Strict):
    schema_version: Literal[1]
    scenarios: list[Scenario] = Field(min_length=1)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def check_reference(reference, root=ROOT):
    parts = reference.split('::')
    path = root / parts[0]
    if Path(parts[0]).is_absolute() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'missing or external reference: {reference}')
    if len(parts) > 1:
        if path.suffix != '.py':
            raise ValueError(f'only Python references support symbol selectors: {reference}')
        nodes = ast.parse(path.read_text()).body
        for name in parts[1:]:
            node = next((n for n in nodes if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                         and n.name == name), None)
            if node is None:
                raise ValueError(f'missing test symbol: {reference}')
            nodes = node.body


def validate(catalog, scenarios, root=ROOT):
    ids = [c.id for c in catalog.cases]
    sids = [s.id for s in scenarios.scenarios]
    if len(ids) != len(set(ids)) or len(sids) != len(set(sids)):
        raise ValueError('duplicate case or scenario ID')
    doc = (root / 'docs/agent-iteration.md').read_text()
    issue_lines = [line for line in doc.splitlines()
                   if re.match(r'^(?:\| |#{1,6} )A\d{3}', line)]
    documented = {identity for line in issue_lines for identity in re.findall(r'A\d{3}(?!\d)', line)}
    if set(ids) != documented:
        raise ValueError(f'case/document mismatch: {sorted(set(ids) ^ documented)}')
    case_map = {c.id: c for c in catalog.cases}
    claimed = []
    for case in catalog.cases:
        refs = [case.source.reference, *case.controlled, *[e.reference for e in case.evidence]]
        if case.acceptance_reference:
            refs.append(case.acceptance_reference)
        for reference in refs:
            check_reference(reference, root)
        # Tests must identify a Python test or a native test file, not a README.
        for reference in case.controlled:
            if not ((reference.endswith('.swift') and reference.startswith('tests/mac/')) or
                    ('::test_' in reference and reference.startswith('agent-service/tests/test_'))):
                raise ValueError(f'controlled mapping is not a test: {reference}')
        claimed.extend(case.fixed_scenarios)
    if len(claimed) != len(set(claimed)) or set(claimed) != set(sids):
        raise ValueError('scenario inventory has duplicate, missing or unregistered entries')
    for scenario in scenarios.scenarios:
        case = case_map.get(scenario.case_id)
        if not case or scenario.id not in case.fixed_scenarios:
            raise ValueError(f'wrong case association: {scenario.id}')
        if scenario.provenance == 'observed_sanitized' and case.source.context_status != 'complete':
            raise ValueError('partial original context cannot be labeled an observed replay')
        check_reference(scenario.source_reference, root)


def load(directory=FIXTURES, root=ROOT):
    # model_validate after json.loads retains strict type checks for primitives.
    catalog = Catalog.model_validate(json.loads((directory / 'catalog.json').read_text()))
    scenarios = Scenarios.model_validate(json.loads((directory / 'scenarios.json').read_text()))
    validate(catalog, scenarios, root)
    return catalog, scenarios


def select(scenarios, names):
    if not names or len(names) != len(set(names)):
        raise ValueError('select explicit, unique case/scenario IDs')
    known = {s.id for s in scenarios} | {s.case_id for s in scenarios}
    if set(names) - known:
        raise ValueError(f'unknown or not replayable: {sorted(set(names) - known)}')
    result = [s for s in scenarios if s.id in names or s.case_id in names]
    if not result:
        raise ValueError('empty selection is not a passing run')
    return result
