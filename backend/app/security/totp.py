"""TOTP (authenticator app) 2FA helpers."""
from __future__ import annotations

import pyotp

ISSUER = "AI LifeOS"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    """otpauth:// URI for QR codes in authenticator apps."""
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    # valid_window=1 tolerates one 30s step of clock drift either side.
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
