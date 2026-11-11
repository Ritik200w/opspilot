from app.collectors.redact import (
    REDACTED,
    REDACTED_EMAIL,
    REDACTED_KEY,
    redact_text,
    redact_value,
)

PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAK...\nabc\n-----END RSA PRIVATE KEY-----"


def test_redacts_key_value_secrets() -> None:
    out = redact_text("password=hunter2 user=alice retries=3")
    assert "hunter2" not in out
    assert REDACTED in out
    # Non-secret fields are untouched.
    assert "user=alice" in out
    assert "retries=3" in out


def test_redacts_various_secret_key_names() -> None:
    for raw, secret in [
        ("pwd=topsecret", "topsecret"),
        ("api_key=ABCdef123", "ABCdef123"),
        ("apikey: xyz987", "xyz987"),
        ('"token": "abc.def.ghi"', "abc.def.ghi"),
        ("access_key=AKREALVALUE", "AKREALVALUE"),
        ("secret='shh'", "shh"),
    ]:
        out = redact_text(raw)
        assert secret not in out, raw
        assert REDACTED in out, raw


def test_redacts_bearer_token_without_leaking_tail() -> None:
    out = redact_text("Authorization: Bearer eyJhbGciOi.payloadpart.signature done")
    assert "eyJhbGciOi.payloadpart.signature" not in out
    assert "done" in out  # text after the token survives


def test_redacts_standalone_jwt() -> None:
    out = redact_text("token is eyJabc.eyJdef.sigGHI here")
    assert "eyJabc.eyJdef.sigGHI" not in out
    assert "here" in out


def test_redacts_aws_access_key_id() -> None:
    assert "AKIAIOSFODNN7EXAMPLE" not in redact_text("key AKIAIOSFODNN7EXAMPLE used")


def test_redacts_connection_string_password_only() -> None:
    out = redact_text("dsn=postgresql://opsuser:s3cr3tpw@db:5432/opspilot")
    assert "s3cr3tpw" not in out
    assert "opsuser" in out  # username is kept
    assert "db:5432/opspilot" in out


def test_leaves_plain_urls_untouched() -> None:
    url = "http://prometheus:9090/api/v1/query_range"
    assert redact_text(url) == url


def test_redacts_email_addresses() -> None:
    out = redact_text("contact alice.ops@example.co.uk about it")
    assert "alice.ops@example.co.uk" not in out
    assert REDACTED_EMAIL in out


def test_redacts_private_key_block() -> None:
    out = redact_text(f"here is a key {PRIVATE_KEY} end")
    assert "MIIEowIBAAK" not in out
    assert REDACTED_KEY in out
    assert "end" in out


def test_redact_value_walks_structures() -> None:
    data = {
        "password": "hunter2",
        "message": "connect to admin@example.com failed",
        "nested": {"api_key": "zzz", "count": 5},
        "lines": ["token=abc", "ok"],
    }

    out = redact_value(data)

    assert out["password"] == REDACTED  # sensitive key -> value dropped wholesale
    assert "admin@example.com" not in out["message"]
    assert out["nested"]["api_key"] == REDACTED
    assert out["nested"]["count"] == 5  # non-strings preserved
    assert "abc" not in out["lines"][0]
    assert out["lines"][1] == "ok"


def test_redact_value_passes_through_non_strings() -> None:
    assert redact_value(42) == 42
    assert redact_value(None) is None
    assert redact_value([1, 2.5, True]) == [1, 2.5, True]
