"""Readability is a transport gate, not proof of relevance or factual support."""
import re
from agent_service.call_errors import WebToolError


class PageRead(tuple):
    """Keep the title/body contract while carrying observed reading provenance."""
    def __new__(cls, title, body, *, details):
        value = super().__new__(cls, (title, body))
        value.details = dict(details)
        return value


def readable_page(result):
    if (not isinstance(result, (tuple, list)) or len(result) != 2
            or not all(isinstance(value, str) for value in result)):
        raise WebToolError('UNUSABLE_CONTENT', 'missing_body')
    title, body = result
    body = body.strip()
    # Some extraction services return the HTML shell instead of article text.
    if re.search(r'<(?:!doctype|html|head|body|script|style)\b', body, re.I):
        from agent_service.capture.fetch import _TextExtractor
        parser = _TextExtractor()
        parser.feed(body)
        body = parser.text().strip()
    if not body or body == title.strip():
        raise WebToolError('UNUSABLE_CONTENT', 'empty_body')
    gate = r'登录后(?:查看|继续)|请(?:先)?登录|扫码(?:登录|查看)|开启\s*JavaScript|enable javascript|sign in to (?:continue|view)|access denied|verify you are human'
    if len(body) < 600 and re.search(gate, body, re.I):
        raise WebToolError('UNUSABLE_CONTENT', 'access_page')
    # Do not reject a technical article just because it includes a code sample.
    # Reject a browser bootstrap only when its code dominates the whole body.
    markers = re.findall(r'\b(?:window|document|navigator|location)\s*\.|\bfunction\s*\(|=>|\bvar\s+\w+\s*=|\bconst\s+\w+\s*=', body)
    prose = re.sub(r'```[\s\S]*?```', '', body)
    prose_lines = [line for line in prose.splitlines()
                   if len(line.strip()) > 25 and not re.search(r'[{};=]|\b(?:window|document)\.', line)
                   and (re.search(r'[。！？]', line) or len(line.split()) >= 6)]
    if len(markers) >= 3 and not prose_lines and (body.count(';') >= 3 or body.count('{') >= 3):
        raise WebToolError('UNUSABLE_CONTENT', 'script_shell')
    if isinstance(result, PageRead):
        return PageRead(title, body, details=result.details)
    return title, body
