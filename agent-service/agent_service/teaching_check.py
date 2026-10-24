"""Question coverage declared in the teaching call, checked before publication.

The model owns semantic correspondence. This gate verifies its complete,
literal declaration and provenance; it is not an independent semantic judge.
"""

INSTRUCTION = """
教学题面覆盖 v1：有 check_question 时必须同时给 question_coverage。
按题面顺序将完整 check_question 分为连续逐字片段 question_quote，拼接必须与整道题完全一致（保留标点和空白）。并列的必要要求逐项列出，不能只覆盖其中一项或用整道长题合并掩盖未讲内容；引导语可与首项合并。
每项 taught 表示本轮是否已实际讲清该要求；concepts 只列该项实际考查且已讲的概念；evidence_quote_indices 从 0 开始引用 check_binding.evidence_quotes 中能支撑这项要求的讲解依据。不另外抄一份依据。
未讲清的项必须 taught=false、依据为空，不把学习地图、计划或后续标题冒充讲解。每项均已教、有真实依据，且各项 concepts 的并集恰好等于 check_binding.concepts，题目才能发布。
先补全用户明确要求本轮共同讲解和复述的内容，再出题；一个小知识点可用一个步骤涵盖这些共同要点。不能删掉用户明确要求的考查内容来绕过校验。
题目只放 check_question；message 不另写检查题段。question_coverage 是内部核对依据，不向用户展示。
"""


def coverage_errors(question, rows, binding, taught_concepts, message):
    """Check all question characters, declared scope and already-taught excerpts."""
    from agent_service.answer_style import teaching_passages
    from agent_service.learning_progress import quote_matches

    def error(kind, index=None):
        field = ["question_coverage"] + ([index] if index is not None else [])
        return dict(field=field, type="teaching_check_coverage_" + kind)

    if not rows:
        return [error("missing")]
    values = [row.model_dump() if hasattr(row, "model_dump") else row for row in rows]
    errors = []
    if "".join(row["question_quote"] for row in values) != question:
        errors.append(error("question"))
    if binding is None:
        return errors + [error("binding")]
    value = binding.model_dump() if hasattr(binding, "model_dump") else binding
    quotes = value.get("evidence_quotes", [])
    concepts = set(value.get("concepts", []))
    passages = teaching_passages(message)
    eligible = {i for i, quote in enumerate(quotes)
                if quote_matches(quote, message) and any(quote_matches(quote, part) for part in passages)}
    if len(eligible) != len(quotes):
        errors.append(error("evidence"))
    covered = set()
    for i, row in enumerate(values):
        if not row["taught"]:
            errors.append(error("untaught", i))
        row_concepts = set(row["concepts"])
        if not row_concepts or not row_concepts.issubset(concepts & set(taught_concepts)):
            errors.append(error("binding", i))
        covered.update(row_concepts)
        indices = row["evidence_quote_indices"]
        if not indices or not set(indices).issubset(eligible):
            errors.append(error("evidence", i))
    if covered != concepts:
        errors.append(error("binding"))
    return errors
