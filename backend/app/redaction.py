"""Secret redaction — defense-in-depth for logs, audit records, and (later)
any context sent to an AI provider.

This is a safety net, NOT a licence to put secrets where they don't belong.
Secrets should never be placed in logs or audit detail in the first place;
this module ensures that if one slips through, it is masked.

Two layers:
  * key-based   — values under sensitive-looking keys are masked;
  * value-based — raw secret shapes (PEM blocks, known token prefixes,
                  bearer tokens) are masked wherever they appear.
"""
from __future__ import annotations

import re
from typing import Any

REDACTED = "***REDACTED***"

# Key names that indicate a secret value. "author"/"authored" are explicitly
# NOT secrets (common in GitHub payloads) and are excluded below.
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "apikey",
    "api_key",
    "access_key",
    "accesskey",
    "refresh_token",
    "authorization",
    "cookie",
    "ssh",
    "private_key",
    "privatekey",
    "credential",
    "recovery_code",
    "recovery",
    "totp_secret",
    "mfa_secret",
    "client_secret",
    "signing_key",
    "session_token",
)

# Raw secret shapes, matched in string values regardless of key.
_VALUE_PATTERNS = [
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),              # GitHub classic PAT
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),      # GitHub fine-grained PAT
    re.compile(r"\bgho_[A-Za-z0-9]{20,}\b"),              # GitHub OAuth token
    re.compile(r"\b(?:ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), # other GitHub tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),      # Slack
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),               # generic "sk-" API keys
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                  # AWS access key id
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{10,}"),   # bearer tokens
]


def _key_is_sensitive(key: str) -> bool:
    k = key.lower()
    if "author" in k:  # author, authored_by, author_email ... not secrets
        return False
    return any(part in k for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    """Mask raw secret shapes inside a string."""
    for pat in _VALUE_PATTERNS:
        value = pat.sub(REDACTED, value)
    return value


def redact(obj: Any, _depth: int = 0) -> Any:
    """Recursively redact a value (dict/list/str/scalar).

    Returns a new structure; the input is not mutated.
    """
    if _depth > 20:  # guard against pathological nesting
        return REDACTED
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and _key_is_sensitive(k):
                out[k] = REDACTED
            else:
                out[k] = redact(v, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth + 1) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj
