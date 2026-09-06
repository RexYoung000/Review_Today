"""Public-text-only projections of incomplete structured model output.

Never project routing, authorization, scoring verdicts, or raw JSON. State and
actions are still published only after full validation in ConversationHarness.
"""


from agent_service.answer_style import render_jd

def public_preview(node: str, value: dict) -> str:
    def text(item):
        return item if isinstance(item, str) else ""

    if node in {"answer", "lesson", "organize"}:
        return text(value.get("message"))
    if node == "problem_answer":
        answer = value.get("answer")
        return text(answer.get("direct_answer")) if isinstance(answer, dict) and answer.get("direct_answer") else ""
    if node == "evaluate":
        return text(value.get("feedback"))
    if node == "jd_analysis":
        return render_jd(value)
    return ""
