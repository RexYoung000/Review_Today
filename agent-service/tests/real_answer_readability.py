"""Explicit real-provider generation checks with synthetic material only.
Tests generation components, not routing/search, persistence or full App acceptance.
Run: .venv/bin/python -m tests.real_answer_readability
"""
import argparse
import json
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from agent_service.conversation_prompts import COACH_SYSTEM, EVALUATION_SYSTEM
from agent_service.openai_client import parse_model, ModelCallError
from agent_service.schemas import ConversationOutput, MasteryEvaluation
from agent_service.config import COACH_MODEL

MATERIAL = """RAG 在回答前从外部知识库检索资料，把资料和问题作为上下文交给模型。
模型训练知识有截止时间，也可能缺少企业内部材料。知识库更新后应更新受影响的索引。
RAG 不保证正确，检索可能找错资料，资料可能过期，生成也可能误读。
删除知识库条目不等于删除模型训练知识。应分别评估检索召回和回答忠实度。"""
CASES = [
    ("lesson", "按这份材料讲清为什么需要 RAG，面向准备面试的初学者。保留关键原因、例子和限制。"),
    ("comparison", "用表格比较依靠训练知识回答与 RAG 的区别，保留关键限制。"),
    ("flow", "用流程图解释查询资料到生成回答的过程，配简短说明。"),
    ("organize", "把给定材料整理成有明确标记的并列知识点，先交付整理结果。"),
    ("followup", "接着刚才的流程说明：检索到了资料就一定能答对吗？简短解释。"),
]
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[label for label, _ in CASES] + ["evaluation"])
    selected = parser.parse_args().case
    history = []
    failures = []
    for label, instruction in CASES:
        if selected and selected != label: continue
        previews = []
        start = time.monotonic()
        result = None
        for attempt in range(1, 3):
            try:
                result = parse_model(COACH_SYSTEM, json.dumps(dict(instruction=instruction, sources=[dict(type="user_material", content=MATERIAL)],
                    context=dict(recent_messages=history[-2:]), evidence=dict(state="unverified")), ensure_ascii=False),
                    ConversationOutput, model=COACH_MODEL, on_partial=lambda value: previews.append(time.monotonic()))
                break
            except ModelCallError as error:
                print(json.dumps(dict(case=label, attempt=attempt, error=str(error), diagnostic=error.diagnostic, kind="generation_component"), ensure_ascii=False), flush=True)
        if result is None:
            failures.append(label)
            continue
        history += [dict(role="user", content=instruction), dict(role="coach", content=result.message)]
        print(json.dumps(dict(case=label, attempt=attempt, kind="generation_component", ms=round((time.monotonic()-start)*1000),
            first_ms=round((previews[0]-start)*1000) if previews else None, chunks=len(previews), response=result.message,
            question=result.check_question), ensure_ascii=False), flush=True)
    if selected in {None, "evaluation"}:
        start = time.monotonic()
        result = None
        for attempt in range(1, 3):
            try:
                result = parse_model(EVALUATION_SYSTEM, json.dumps(dict(question="检索到资料就一定能答对吗？",
                    reference=MATERIAL, answer="不一定，还要检查资料是否相关、是否过期，以及模型有没有误读。"), ensure_ascii=False),
                    MasteryEvaluation, model=COACH_MODEL)
                break
            except ModelCallError as error:
                print(json.dumps(dict(case="evaluation", attempt=attempt, error=str(error), diagnostic=error.diagnostic,
                                      kind="generation_component"), ensure_ascii=False), flush=True)
        if result:
            print(json.dumps(dict(case="evaluation", kind="generation_component", attempt=attempt,
                ms=round((time.monotonic()-start)*1000), response=result.feedback,
                question=result.followup_question, passed=result.passed), ensure_ascii=False), flush=True)
        else:
            failures.append("evaluation")
    if failures:
        raise SystemExit("Generation cases failed: " + ", ".join(failures))

if __name__ == "__main__": main()
