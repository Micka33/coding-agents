"""Small stdlib-only helpers for redacting secrets from CLI diagnostics."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

_REDACTED = "<redacted>"
_URL_CREDENTIALS_RE = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)"
    r"(?P<username>[^\s/?#@:\\]+):"
    r"(?P<password>[^\s/?#@\\]+)@"
)
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_AUTHORIZATION_HEADER_RE = re.compile(
    r"(?P<key>\bAuthorization)"
    r"(?P<sep>\s*:\s*)"
    r"(?P<scheme>Bearer|Basic)"
    r"\s+"
    r"(?P<value>[^'\"\s,;&}\]]+)",
    re.IGNORECASE,
)
_SENSITIVE_KEY_PATTERN = (
    r"[A-Za-z0-9_-]*"
    r"(?:password|token|api[_-]?key|apikey|secret|private[_-]?key|access[_-]?key|credentials?)"
    r"[A-Za-z0-9_-]*"
)
_KEY_VALUE_QUOTED_RE = re.compile(
    r"(?P<key_quote>['\"]?)"
    rf"(?P<key>\b{_SENSITIVE_KEY_PATTERN})"
    r"(?P=key_quote)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>['\"])"
    r"(?P<value>[^\n]*?)"
    r"(?P=quote)",
    re.IGNORECASE,
)
_KEY_VALUE_UNQUOTED_RE = re.compile(
    r"(?P<key_quote>['\"]?)"
    rf"(?P<key>\b{_SENSITIVE_KEY_PATTERN})"
    r"(?P=key_quote)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>[^'\"\s,;&}\]]+)",
    re.IGNORECASE,
)
_SENSITIVE_ENV_NAME_PARTS = (
    "PASSWORD",
    "TOKEN",
    "API_KEY",
    "APIKEY",
    "SECRET",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "CREDENTIAL",
    "AUTHORIZATION",
    "AUTH_TOKEN",
    "DATABASE_URL",
    "POSTGRES_URL",
)


def redact_secrets(value: Any, *, env: Mapping[str, str] | None = None) -> str:
    """Return ``value`` as text with common secret shapes redacted.

    The helper intentionally uses only the standard library so it can run while
    startup is failing. It covers URL credentials, common key-value forms, and
    values of environment variables whose names commonly hold credentials.
    """

    text = str(value)
    text = _PRIVATE_KEY_BLOCK_RE.sub(_REDACTED, text)
    text = _URL_CREDENTIALS_RE.sub(r"\g<scheme>***:***@", text)
    text = _AUTHORIZATION_HEADER_RE.sub(_replace_authorization_header, text)
    text = _redact_sensitive_env_values(text, os.environ if env is None else env)
    text = _KEY_VALUE_QUOTED_RE.sub(_replace_quoted_key_value, text)
    text = _KEY_VALUE_UNQUOTED_RE.sub(_replace_unquoted_key_value, text)
    return text


def _replace_authorization_header(match: re.Match[str]) -> str:
    return f"{match.group('key')}{match.group('sep')}{match.group('scheme')} {_REDACTED}"


def _replace_quoted_key_value(match: re.Match[str]) -> str:
    return f"{_matched_key(match)}{match.group('sep')}{match.group('quote')}{_REDACTED}{match.group('quote')}"


def _replace_unquoted_key_value(match: re.Match[str]) -> str:
    return f"{_matched_key(match)}{match.group('sep')}{_REDACTED}"


def _matched_key(match: re.Match[str]) -> str:
    key_quote = match.group("key_quote") or ""
    return f"{key_quote}{match.group('key')}{key_quote}"


def _redact_sensitive_env_values(text: str, env: Mapping[str, str]) -> str:
    redacted = text
    for name, value in env.items():
        if not value or len(value) < 4:
            continue
        if not _looks_sensitive_env_name(name):
            continue
        redacted = redacted.replace(value, _REDACTED)
    return redacted


def _looks_sensitive_env_name(name: str) -> bool:
    folded = name.upper()
    return any(part in folded for part in _SENSITIVE_ENV_NAME_PARTS)
