"""Allowlisted diagnostics; no provider bodies, prompts or credentials."""
import re


def diagnose(error):
    status = getattr(error, "status_code", None)
    match = re.fullmatch(r"HTTP (\d{3})", getattr(error, "diagnostic", ""))
    if status is None and match:
        status = int(match[1])
    code = str(getattr(error, "code", ""))
    name = type(error).__name__
    request_id = getattr(error, "request_id", None)
    request_id = request_id if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", request_id) else None
    if code.startswith("RT.RUN.BUDGET_"): category = "run_budget"
    elif code == "RT.MODEL.BUSY": category = "capacity_busy"
    elif code.endswith(("CHAIN_FAILED", "BUDGET_EXHAUSTED")): category = "web_unavailable"
    elif status == 429 or code.endswith("RATE_LIMIT"): category = "rate_limit"
    elif code.endswith(("AUTH_REQUIRED", "CANCELLED", "TOOL_FAILED")): category = code.rsplit(".", 1)[-1].lower()
    elif status in (401, 403): category = "access_denied"
    elif status in (400, 404, 405, 422) or code.endswith(("UNSUPPORTED", "PROTOCOL", "NOT_CONFIGURED", "INVALID_QUERY")): category = "unsupported"
    elif "NO_KEY" in str(error): category = "credential_missing"
    elif "TIMEOUT" in code or "Timeout" in name: category = "timeout"
    elif "CONNECTION" in code or "Connection" in name or isinstance(error, OSError): category = "connection"
    elif code.endswith(("EMPTY", "SCHEMA", "REFUSAL", "INCOMPLETE", "SEARCH_LIMIT", "SEARCH_FAILED", "READ_FAILED")): category = code.rsplit(".", 1)[-1].lower()
    else: category = "provider"
    return dict(category=category, http_status=status, request_id=request_id, retryable=category in {"timeout", "connection", "provider"},
                diagnostic=f"HTTP {status}" if status else code if code.startswith("RT.") else name,
                recovery={"run_budget": "reduce_scope_or_explicit_retry", "capacity_busy": "wait_for_capacity"}.get(category,
                    "retry_connection" if category in {"timeout", "connection", "provider"} else "check_configuration"))
