"""Strip credentials from anything that leaves the platform.

Two lessons drive this module:

* CloudGuard-IaC showed that credentials have recognisable *shapes* (``AKIA…``,
  ``ghp_…``, PEM blocks). Matching shapes is cheap and catches the common cases
  before a diff or a log reaches an LLM provider.
* The LLM Security Lab showed that once a secret is in the model's context it
  can be exfiltrated by prompt injection (OWASP LLM02/LLM07). The only reliable
  mitigation is to never put it there.

Redaction is applied to every prompt and every tool result by the runtime; it
is not optional and agents cannot bypass it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----.*?"
            r"-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----",
            re.DOTALL,
        ),
    ),
    (
        "assignment",
        re.compile(
            r"(?i)\b(password|passwd|secret|api[_-]?key|token|authorization)\b"
            r"(\s*[:=]\s*['\"]?)([^\s'\"]{8,})"
        ),
    ),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{16,}")),
    ("url_credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@")),
)


@dataclass(frozen=True)
class Redaction:
    """Result of :func:`redact`: the cleaned text and what was found."""

    text: str
    findings: tuple[str, ...]

    @property
    def changed(self) -> bool:
        """True when at least one secret was replaced."""
        return bool(self.findings)


def redact(text: str) -> Redaction:
    """Replace recognisable credentials with ``[REDACTED:<kind>]``."""
    found: list[str] = []
    out = text
    for kind, pattern in _PATTERNS:
        if kind == "assignment":

            def _assign(m: re.Match[str], kind: str = kind) -> str:
                found.append(kind)
                return f"{m.group(1)}{m.group(2)}[REDACTED:{kind}]"

            out = pattern.sub(_assign, out)
        elif kind == "url_credentials":

            def _url(m: re.Match[str], kind: str = kind) -> str:
                found.append(kind)
                return f"{m.group(1)}[REDACTED:{kind}]@"

            out = pattern.sub(_url, out)
        else:

            def _plain(m: re.Match[str], kind: str = kind) -> str:  # noqa: ARG001
                found.append(kind)
                return f"[REDACTED:{kind}]"

            out = pattern.sub(_plain, out)
    return Redaction(text=out, findings=tuple(found))
