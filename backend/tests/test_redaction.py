from app.redaction import REDACTED, redact, redact_text


def test_redacts_sensitive_keys():
    out = redact(
        {
            "username": "alice",
            "password": "hunter2",
            "api_key": "abc123",
            "nested": {"access_token": "xyz", "note": "fine"},
        }
    )
    assert out["username"] == "alice"
    assert out["password"] == REDACTED
    assert out["api_key"] == REDACTED
    assert out["nested"]["access_token"] == REDACTED
    assert out["nested"]["note"] == "fine"


def test_author_is_not_treated_as_secret():
    out = redact({"author": "octocat", "author_email": "o@example.com"})
    assert out["author"] == "octocat"
    assert out["author_email"] == "o@example.com"


def test_redacts_token_shapes_in_values():
    assert redact_text("token is ghp_" + "A" * 36) == "token is " + REDACTED
    pem = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"
    assert REDACTED in redact_text(pem)
    assert "Bearer" not in redact_text("Authorization: Bearer abcdef0123456789")


def test_redact_handles_lists_and_scalars():
    out = redact({"items": [{"secret": "s"}, {"ok": 1}], "count": 3})
    assert out["items"][0]["secret"] == REDACTED
    assert out["items"][1]["ok"] == 1
    assert out["count"] == 3
