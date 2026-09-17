"""Keep public answer links tied to pages actually read in this search turn."""
import re


# Code is teaching material, not a claimed citation. Include unfinished code
# spans/fences so streamed prefixes cannot turn code URLs into citations.
_CODE = re.compile(r"(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:\n\1[^\n]*(?:\n|$)|$)|(`+)[^`]*(?:\2|$)")
_URL = re.compile(r"https?://[^\s<>\[\]()`\"，。；！？、]*", re.IGNORECASE)
_LINK = re.compile(r"\[([^\]\n]*)\]\((https?://[^\s()]+)\)", re.IGNORECASE)
_AUTO = re.compile(r"<(https?://[^<>\s]+)>", re.IGNORECASE)


def bound_source_links(text: str, allowed: list[str]) -> str:
    urls = set(allowed)

    def prose(part):
        # Protect exact known targets first, including balanced parentheses in
        # real documentation/Wikipedia URLs. Never protect a mere URL prefix.
        protected = {}
        for index, url in enumerate(sorted(urls, key=len, reverse=True)):
            token = f"\x00source_url_{index}\x00"
            while token in part:
                token += "\x00"
            part = re.sub(re.escape(url) + r"(?=$|[\s<>\])`\"，。；！？、.,;!?])", lambda m: token, part)
            protected[token] = url
        part = _LINK.sub(lambda m: m[0] if m[2] in urls else m[1] + "（链接未核验）", part)
        part = _AUTO.sub(lambda m: m[0] if m[1] in urls else "（链接未核验）", part)
        def bare(match):
            value = match[0]
            url = value.rstrip(".,;:!?")
            return value if url in urls else "（链接未核验）" + value[len(url):]
        part = _URL.sub(bare, part)
        for token, url in protected.items():
            part = part.replace(token, url)
        return part

    pieces, start = [], 0
    for match in _CODE.finditer(text):
        pieces.extend([prose(text[start:match.start()]), match[0]])
        start = match.end()
    pieces.append(prose(text[start:]))
    return "".join(pieces)
