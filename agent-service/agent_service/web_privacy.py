"""Conservative outbound checks; never a claim of complete text anonymization."""
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit

from agent_service.call_errors import WebToolError


def normalized(value):
    value = unicodedata.normalize('NFKC', value)
    for _ in range(2):
        value = unquote(value)
    return value


# Match disclosures/values, not knowledge questions such as "密码哈希是什么".
PRIVATE = re.compile(
    r'内部(?:未公开|未发布|保密)|(?:未公开|未发布)的?.{0,12}(?:项目|方案|报价|财报)|'
    r'(?:以下|这是|我司|本公司|我们公司).{0,20}(?:内部资料|内部文档|客户名单|保密资料)|'
    r'(?:内部资料|内部文档|客户名单|私人资料|保密资料)\s*[:：]|'
    r'\b(?:confidential|internal.only|not.for.distribution)\s*[:：]|'
    r'\b(?:sk-[a-z0-9_-]{8,}|Bearer\s+\S+|eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)|'
    r'-----BEGIN|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\d)\+?\d[\d ()-]{8,}\d(?!\d)|'
    r'(?:密钥|密码|口令|访问令牌|api[_ -]?key|access[_ -]?token|password|secret)\s*[:=：]\s*\S+', re.I)


def sensitive_text(value):
    return isinstance(value, str) and bool(PRIVATE.search(normalized(value)))


def safe_public_query(value, *, max_length=180):
    value = value.strip() if isinstance(value, str) else ''
    if (not 2 <= len(value) <= max_length or sensitive_text(value)
            or re.search(r'https?://|\bsk-|\bBearer\b|\d{7,}', normalized(value), re.I)):
        return ''
    return value


def require_public_query(value):
    query = safe_public_query(value, max_length=600)  # includes program-added site filters
    if not query:
        raise WebToolError('PRIVATE_QUERY' if sensitive_text(value) else 'INVALID_QUERY')
    return query


ACCESS_PARAMETERS = {
    'token', 'accesstoken', 'refreshtoken', 'idtoken', 'authtoken', 'authorization', 'auth',
    'apikey', 'key', 'secret', 'clientsecret', 'password', 'passwd', 'pwd', 'passcode',
    'signature', 'sig', 'credential', 'ticket', 'jwt', 'sessionid', 'sessiontoken',
    'sharetoken', 'downloadtoken', 'securitytoken', 'policy',
}


def require_public_url(url):
    """Keep ordinary query parameters; never silently rewrite a signed URL."""
    if not isinstance(url, str):
        raise ValueError('RT.WEB.INVALID_URL')
    try:
        parts = urlsplit(normalized(url))
        if parts.username is not None or parts.password is not None:
            raise ValueError('RT.WEB.PRIVATE_URL')
        for component in (parts.query, parts.fragment.lstrip('?')):
            for key, value in parse_qsl(component, keep_blank_values=True):
                name = re.sub(r'[^a-z0-9]', '', key.lower())
                if name in ACCESS_PARAMETERS or name.startswith(('xamz', 'xgoog')):
                    raise ValueError('RT.WEB.PRIVATE_URL')
                # Query values may carry a nested URL (e.g. redirect=...token=...).
                if (sensitive_text(value) and not re.fullmatch(r'[\d-]+', value)) or re.search(
                        r'(?:[?&#]|^)(?:token|access_token|api_key|signature|password)=', value, re.I):
                    raise ValueError('RT.WEB.PRIVATE_URL')
    except ValueError as exc:
        if str(exc) == 'RT.WEB.PRIVATE_URL':
            raise
        raise ValueError('RT.WEB.INVALID_URL') from None
    return url


def public_service_url(url):
    """Public URL syntax only. Local network callers must also pin public DNS."""
    import ipaddress
    require_public_url(url)
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError('RT.WEB.INVALID_URL')
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        if (parsed.scheme not in {'http', 'https'} or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 80, 443)
                or host.endswith(('.local', '.internal', '.localhost', '.test', '.invalid'))
                or '.' not in host or '\\' in url or '%' in host
                or not re.fullmatch(r'[a-z0-9.-]+', host) or host in {'metadata.google.internal'}):
            raise ValueError('RT.WEB.INVALID_URL')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if all(part.isdigit() or part.startswith('0x') for part in host.split('.')):
                raise ValueError('RT.WEB.INVALID_URL')
        else:
            raise ValueError('RT.WEB.INVALID_URL')
    except (ValueError, TypeError):
        raise ValueError('RT.WEB.INVALID_URL') from None
    return url


def sensitive_material(value):
    # Recognizable contact values are independently rejected in the outgoing
    # query. Their mere presence must not block an unrelated public question.
    without_contacts = re.sub(r'[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\d)\+?\d[\d ()-]{8,}\d(?!\d)', '', value, flags=re.I)
    if sensitive_text(without_contacts):
        return True
    for url in re.findall(r'https?://[^\s<>"\']+', value):
        try:
            require_public_url(url)
        except ValueError as exc:
            if str(exc) == 'RT.WEB.PRIVATE_URL':
                return True
    return False
