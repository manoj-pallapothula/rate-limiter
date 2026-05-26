from jose import jwt, JWTError
from datetime import datetime, timedelta
from app.config import settings


# Secret key for signing tokens
# In production this would be an env var
JWT_SECRET = "rate-limiter-secret-key-change-in-production"
JWT_ALGORITHM = "HS256"


def create_token(user_id: str, expires_minutes: int = 60) -> str:
    """Create a JWT token for a user."""
    payload = {
        "sub": user_id,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """
    Decode a JWT token and return the payload.
    Returns None if token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def get_user_id_from_token(token: str) -> str | None:
    """Extract user_id from JWT token subject claim."""
    payload = decode_token(token)
    if payload:
        return payload.get("sub")
    return None