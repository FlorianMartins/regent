import pytest

from regent.core.redaction import redact


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("key AKIAIOSFODNN7EXAMPLE here", "aws_access_key"),
        ("token ghp_" + "a" * 36, "github_token"),
        ("sk-ant-api03-" + "x" * 30, "anthropic_key"),
        ("xoxb-123456789012-abcdefgh", "slack_token"),
        ("AIza" + "b" * 35, "google_api_key"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop", "jwt"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----", "private_key"),
        ("password = 'hunter2hunter2'", "assignment"),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "bearer"),
        ("https://user:s3cretpass@host/x", "url_credentials"),
    ],
)
def test_patterns(text: str, kind: str):
    out = redact(text)
    assert kind in out.findings
    assert f"[REDACTED:{kind}]" in out.text


def test_clean_text_untouched():
    out = redact("nothing to see: user = alice, port = 8080")
    assert not out.changed and out.text.startswith("nothing")


def test_assignment_keeps_key_name():
    out = redact("api_key: abcdefgh12345678")
    assert out.text == "api_key: [REDACTED:assignment]"
