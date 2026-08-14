from agent_service.capture.prompts import GRADE_SYSTEM
from agent_service.openai_client import parse_model
from agent_service.schemas import GradeRequest, GradeResult


def grade_answer(body: GradeRequest) -> GradeResult:
    spec = body.scoring_spec
    parsed = parse_model(
        GRADE_SYSTEM,
        (
            f"用户主语言：{body.primary_language}\n"
            f"提示已使用：{'是' if body.hint_used else '否'}\n"
            f"问题：{body.prompt_text}\n"
            f"学习目标：{spec.learning_goal}\n"
            f"必答点：{spec.must_cover}\n"
            f"可接受同义：{spec.acceptable_paraphrases}\n"
            f"常见误解：{spec.common_misconceptions}\n"
            f"证据：{spec.evidence}\n"
            f"顺序规则：{spec.order_rules}\n"
            f"用户回答：{body.answer_text}"
        ),
        GradeResult,
    )
    result = GradeResult.model_validate(parsed.model_dump())
    result.attempt_id = body.attempt_id
    result.hint_used = body.hint_used
    if result.agent_grade == "good" and body.hint_used:
        result.agent_grade = "hard"
    if result.agent_grade not in {"again", "hard", "good"}:
        result.agent_grade = "again"
    return result
