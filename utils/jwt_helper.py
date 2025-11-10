from __future__ import annotations

import jwt
import os
from datetime import datetime, timedelta

SECRET_KEY = os.getenv("JWT_SECRET", "efb91ddb118b36b986f0017acdc5805a7594bb3ff530a1a233cfa6dde931a3d2")
ALGORITHM = "HS256"
EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))


def generate_token(user_id: str) -> str:
    now = datetime.utcnow()
    payload = {
        "user_id": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=EXPIRE_MIN),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def validate_token(token: str) -> str | None:
    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded.get("user_id")
    except jwt.InvalidTokenError:
        return None
