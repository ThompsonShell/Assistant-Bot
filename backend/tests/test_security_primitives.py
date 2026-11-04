import pyotp

from app.security.passwords import hash_password, verify_password
from app.security.totp import generate_secret, provisioning_uri, verify_totp


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password(h, "correct horse battery staple") is True
    assert verify_password(h, "wrong") is False


def test_verify_password_rejects_garbage_hash():
    assert verify_password("not-a-hash", "whatever") is False


def test_totp_verify():
    secret = generate_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code) is True
    assert verify_totp(secret, "000000") is False
    assert verify_totp(secret, "") is False


def test_provisioning_uri_contains_issuer():
    uri = provisioning_uri(generate_secret(), "admin")
    assert uri.startswith("otpauth://totp/")
    assert "AI%20LifeOS" in uri or "AI LifeOS" in uri
