"""Small, score-free API-Football error envelope for quota-safe diagnostics.

Do NOT log raw response bodies, request headers, URLs, credentials or fixture
scores. Provider errors are scrubbed and truncated before persistence.
"""
from __future__ import annotations
import json
import re

MAX_ERROR_TEXT = 200
_ALLOWED_KINDS = frozenset({
    "HTTP_ERROR", "TRANSPORT_ERROR", "TIMEOUT", "INVALID_JSON",
    "PROVIDER_ERRORS", "RESPONSE_TOO_LARGE", "INVALID_ENVELOPE",
    "INCOMPLETE_PAGINATION", "INVALID_FIXTURES", "INVALID_FIXTURE_IDS",
    "UNKNOWN_ERROR",
})


def scrub_errors(errors, key=""):
    """Return <=200 safe characters of provider-controlled *errors* only."""
    if isinstance(errors, dict):
        errors = "; ".join(str(k) + ": " + str(v)
                           for k, v in sorted(errors.items())[:5])
    elif isinstance(errors, (list, tuple)):
        errors = "; ".join(str(x) for x in errors[:5])
    elif not isinstance(errors, str):
        errors = ""
    if key:
        errors = errors.replace(key, "[redacted]")
    errors = re.sub(r"https?://[^\s;]+", "[url]", errors, flags=re.I)
    errors = re.sub(r"(?i)\b(bearer)\s+[\w.\-+/=]+", r"\1 [redacted]", errors)
    errors = re.sub(r"(?i)\b(api[_-]?key|token|password|secret|authorization|access[_-]?key)\b\s*[:=]\s*[^,;\s}]+",
                    r"\1=[redacted]", errors)
    errors = re.sub(r"[\x00-\x1f\x7f]", " ", errors)
    return errors.strip()[:MAX_ERROR_TEXT]


def provider_errors(raw):
    """Never expose a non-JSON HTTP body: it may contain gateway secrets."""
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError, TypeError):
        return None
    if isinstance(body, dict):
        return body.get("errors")
    return None


class APIRequestFailure(OSError):
    def __init__(self, kind, *, http_status=None, errors=None, key=""):
        if kind not in _ALLOWED_KINDS:
            kind = "UNKNOWN_ERROR"
        self.kind = kind
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        self.provider_error = scrub_errors(errors, key=key)
        super().__init__(kind)

    def report(self):
        return {
            "category": self.kind,
            "http_status": self.http_status,
            "provider_errors": self.provider_error,
        }


def failure_from(exc):
    if isinstance(exc, APIRequestFailure):
        return exc.report()
    if isinstance(exc, TimeoutError):
        kind = "TIMEOUT"
    elif isinstance(exc, ValueError):
        kind = "INVALID_ENVELOPE"
    else:
        kind = "TRANSPORT_ERROR"
    return APIRequestFailure(kind).report()
