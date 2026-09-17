"""Shared, sanitized call errors; model and web tools have separate namespaces."""
import re


class CallError(RuntimeError):
    namespace = 'CALL'

    def __init__(self, kind: str, diagnostic: str = '', request_id: str | None = None):
        self.code = f'RT.{self.namespace}.{kind}'
        self.diagnostic = diagnostic
        self.request_id = request_id if isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', request_id) else None
        super().__init__(self.code)


class ModelCallError(CallError):
    namespace = 'MODEL'


class WebToolError(CallError):
    namespace = 'WEB'
