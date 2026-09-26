"""Allowlisted output diagnostics and trusted, bounded repair instructions."""
import json


def schema_diagnostic(error, raw=None):
    # Never include input, invalid literals, validator messages or provider text.
    details = []
    for item in error.errors(include_input=False, include_url=False)[:8]:
        detail = {"field": list(item["loc"]), "type": item["type"]}
        if item["type"] == "literal_error":
            detail["allowed"] = item.get("ctx", {}).get("expected", "")
        if item["type"] in {"string_too_long", "string_too_short", "too_long", "too_short"}:
            # Trusted schema bounds only; input text and arbitrary context stay
            # excluded. Without the bound, a retry can repeat the same length.
            for key in ("max_length", "min_length"):
                value = item.get("ctx", {}).get(key)
                if type(value) is int and 0 <= value <= 1_000_000:
                    detail[key] = value
        if raw is not None and item["type"] == "json_invalid":
            stripped = raw.lstrip()
            detail.update(output_format="markdown_fence" if stripped.startswith("```") else
                          "non_json" if not stripped.startswith(("{", "[")) else "json_syntax",
                          chars=len(raw), bytes=len(raw.encode("utf-8", errors="replace")))
            try:
                json.loads(raw)
            except json.JSONDecodeError as exc:
                detail.update(line=exc.lineno, column=exc.colno, position=exc.pos)
                if exc.msg == "Extra data":
                    detail["output_format"] = "trailing_content"
            except RecursionError:
                pass  # Deeply nested invalid JSON must not break diagnostics.
        details.append(detail)
    return json.dumps(details, ensure_ascii=False)


def schema_repair_instruction(error):
    """Use fixed rules for syntax; only our sanitized schema fields are quoted."""
    try:
        details = json.loads(error.diagnostic)
    except (ValueError, TypeError):
        details = []
    if not isinstance(details, list):
        details = []
    invalid = next((d for d in details if isinstance(d, dict) and d.get("type") == "json_invalid"), None)
    common = ("重新根据原始上下文输出一个完整的 JSON 对象，所有字段仍须满足本次 schema。"
              "不得补造授权、证据、来源或已掌握状态。")
    if invalid is not None:
        reason = {
            "markdown_fence": "上一轮响应在 JSON 对象外包含 Markdown 代码围栏。",
            "non_json": "上一轮响应不是纯 JSON 对象，包含普通文字或前缀。",
            "trailing_content": "上一轮 JSON 后还有额外内容。",
            "json_syntax": "上一轮 JSON 语法无效，可能缺少结束符或字符串转义不正确。",
        }.get(invalid.get("output_format"), "上一轮输出无法解析为 JSON。")
        line, column = invalid.get("line"), invalid.get("column")
        if type(line) is int and type(column) is int and line > 0 and column > 0:
            reason += f"解析失败位置为第 {line} 行第 {column} 列。"
        return ("本次为输出格式重试：" + reason + common +
                "第一个非空字符必须是 {，最后一个非空字符必须是 }；"
                "JSON 对象外不得输出反引号、代码围栏、前言或后记。"
                "字符串内的引号、换行必须正确转义。")
    length_hint = ""
    if any(isinstance(d, dict) and d.get("type") == "string_too_long" for d in details):
        length_hint = "字符串的 max_length 按字符计数，包含空格和标点，不是英文单词数。证据只取原文中最短的连续必要片段，不要重复整段。"
    return ("输出结构校验失败：" + error.diagnostic + "\n" + common + length_hint +
            "修复标出的字段并严格使用 schema 的枚举；工作流放 workflow，"
            "直接教学放 direct_teaching 布尔字段。")
