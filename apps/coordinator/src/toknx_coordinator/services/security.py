import hmac
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def derive_stable_token(prefix: str, *, subject: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), subject.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{prefix}_{digest}"


def issue_node_jwt(*, node_id: str, account_id: str, secret: str, ttl_seconds: int = 86_400) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": node_id,
        "account_id": account_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_node_jwt(token: str, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])
