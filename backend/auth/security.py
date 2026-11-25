from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash


# ---------------------------------------------------------
# Password hashing
# ---------------------------------------------------------

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """
    Convert a plain-text password into a secure hash.
    """

    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """
    Check whether the supplied password matches the stored hash.
    """

    return password_hash.verify(password, hashed_password)


# ---------------------------------------------------------
# JWT configuration
# ---------------------------------------------------------

ALGORITHM = "HS256"


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    secret_key: str,
    expires_minutes: int = 60,
) -> str:
    """
    Create a JWT access token for an authenticated user.
    """

    expire_time = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes
    )

    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expire_time,
    }

    token = jwt.encode(
        payload,
        secret_key,
        algorithm=ALGORITHM,
    )

    return token