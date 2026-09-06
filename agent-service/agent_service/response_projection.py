"""Public-text-only projections of incomplete structured model output.

Never project routing, authorization, scoring verdicts, or raw JSON. State and
actions are still published only after full validation in ConversationHarness.
"""


def public_preview(node: str, value: dict) -> str:
    def text(item):
        return item if isinstance(item, str) else ""

    if node in {"answer", "lesson", "organize"}:
        return text(value.get("message"))
    if node == "problem_answer":
        answer = value.get("answer")
        return "基础答案\n" + text(answer.get("direct_answer")) if isinstance(answer, dict) and answer.get("direct_answer") else ""
    if node == "evaluate":
        return text(value.get("feedback"))
    if node == "jd_analysis":
        result = text(value.get("role_goal"))
        for key, title in [("competency_map", "能力地图"), ("risk_points", "风险点"), ("prioritized_questions", "优先问题")]:
            items = value.get(key)
            if isinstance(items, list) and items:
                result += "\n\n" + title + "\n" + "\n".join("- " + item for item in items if isinstance(item, str))
        return result
    return ""
