"""Shared presentation guidance. No extra generation, authorization, or data writes."""
import re
from urllib.parse import urlsplit, unquote

ANSWER_STYLE = """
用户可见内容的阅读规则（不改变任务目标、证据或字段结构）：
- 外层仍严格输出 schema 要求的单一 JSON 对象。Markdown/流程图只放在相应字符串字段内部，换行与引号必须合法 JSON 转义；不要在 JSON 外输出 Markdown 或代码围栏。
- 保留讲清当前知识点所需的深度；开头直接回应，不铺客套话。每段一个意思，通常 1–3 句，段间空行；长解释按具体内容用 ## / ### 小标题。
- 少量关键短语加粗，不整段加粗。重要假设、限制紧跟结论，不能藏到文末。短追问自然回答，不凑固定章节或结尾小结。
- 追问只处理本轮新增问题，不复述上轮背景；同一结论不在首段和末尾重复总结，不默认附上邀请继续的套话。长回答通常仅强调 3–5 处真正关键的短语，列表项目不必全部加粗。
- 罗列多个并列要点时，每项用 - 无序列表，客户端显示圆点；有先后顺序、操作步骤或排名时，每项用 1. 2. 3. 有序列表。不能把排列项仅换行而省略标记；每项可包含必要解释，普通连贯解释仍用自然段。
- 并列比较且有共同维度时用 Markdown 表格（通常 2–4 列），单元格简洁，长解释放正文。转义单元格里的竖线，不把每句话都制成表格。
- 比较表保留关键限定，不把“可以实现的收益”写成“必然保证”，不因压缩单元格而夸大能力；需要时在对应单元格或紧邻正文说明限制。
- 过程、顺序或因果关系确实能帮助理解时，可用一个 fenced mermaid 线性流程图，配必要解释。仅用 flowchart LR 或 TD；ASCII 节点 ID、方括号内简短文字、--> 单向连接；所有节点须有标签，一个连通无环无分支的链。不要样式、点击、HTML、子图或复杂语法；复杂分支改为文字列表。流程节点不是学习状态。
- 示例格式（只在过程讲解确有帮助时用，不必每次输出）：
~~~mermaid
flowchart LR
A["检索相关资料"] --> B["结合资料回答"]
~~~
- 例子、类比、引用可用 > 轻量区块；引用只写实际依据。用列表表示并列点或步骤；--- 只用于明显的阅读目的切换，避免每段画线。
- learning_plan 已承担学习路线，正文不重复整份计划。check_question、calibration_question、followup_question 是独立问题字段，message/feedback/direct_answer 不重复这些题目；系统会在对应回答末尾呈现一次。没有必要问题就留空，不为排版强行考用户。
- 这些规则只约束用户可见文本字段；字段、枚举、授权、评价和真实来源不受排版改变。
"""


def normalized_text(text: str) -> str:
    return re.sub(r"[\s*#_>]", "", text)


def with_question(text: str, question: str, title: str = "想一想") -> str:
    """Keep the question in conversation history, without duplicating model echo."""
    if not question.strip() or normalized_text(question) in normalized_text(text):
        return text
    return text.rstrip() + f"\n\n---\n\n### {title}\n\n" + question.strip()


def render_jd(value: dict) -> str:
    """The final answer and its public streaming preview use identical headings."""
    parts = [value.get("role_goal", "") if isinstance(value.get("role_goal"), str) else ""]
    for key, title in [("competency_map", "能力地图"), ("risk_points", "风险点"), ("prioritized_questions", "优先问题")]:
        items = value.get(key)
        if isinstance(items, list) and any(isinstance(x, str) and x for x in items):
            clean = lambda x: re.sub(r'^\s*(?:\d+[.、）)]\s*|[-*]\s+)', '', x)
            rendered = [f"{i}. {clean(x)}" if key == "prioritized_questions" else f"- {clean(x)}"
                        for i, x in enumerate(items, 1) if isinstance(x, str) and x]
            parts.append(f"## {title}\n\n" + "\n".join(rendered))
    return "\n\n".join(x for x in parts if x)


def render_sources(sources: list[dict]) -> str:
    rows = []
    for source in sources:
        url = source["url"]
        title = source.get("title") or ""
        if not title or title.startswith(("https://", "http://")):
            parsed = urlsplit(url)
            filename = unquote(parsed.path.rsplit("/", 1)[-1])
            title = parsed.netloc + (" · " + filename if filename else "")
        title = title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ")
        rows.append(f"- [{title}]({url})")
    return "\n\n### 参考资料\n\n" + "\n".join(rows) if rows else ""
