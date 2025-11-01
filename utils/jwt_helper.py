import jwt
from datetime import datetime, timedelta


# To change the key use python -c "import secrets; print(secrets.token_hex(32))" from terminal
SECRET_KEY = "efb91ddb118b36b986f0017acdc5805a7594bb3ff530a1a233cfa6dde931a3d2"
ALGORITHM = "HS256"

def generate_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "iat": datetime.utcnow(),  # issued at
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token

def validate_token(token: str):
    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded.get("user_id")
    except jwt.InvalidTokenError:
        return None
