import json
from typing import Any


from data.database import get_connection, initialize_and_migrate


# =========================================================
# INITIALIZE STORAGE
# =========================================================

def ensure_storage_files() -> None:
    """Initialize the PostgreSQL schema used by authentication storage."""

    initialize_and_migrate()


# =========================================================
# EXTRA DATA HELPER
# =========================================================

def _decode_extra(
    value: str | None
) -> dict[str, Any]:
    """
    Safely decode preserved JSON fields from PostgreSQL.
    """

    if not value:

        return {}

    try:

        data = json.loads(
            value
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):

        return {}

    return (
        data
        if isinstance(
            data,
            dict
        )
        else {}
    )


# =========================================================
# USERS
# =========================================================

def read_users() -> list[dict[str, Any]]:
    """
    Read all registered users from PostgreSQL.

    The returned dictionary structure intentionally matches
    the existing JSON-based authentication API.
    """

    ensure_storage_files()

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                id,
                full_name,
                email,
                hashed_password,
                role,
                is_verified,
                is_active,
                created_at,
                extra_json
            FROM users
            ORDER BY created_at ASC, email ASC
            """
        ).fetchall()

    finally:

        connection.close()


    users: list[dict[str, Any]] = []

    for row in rows:

        user = {
            "id":
                row["id"],

            "full_name":
                row["full_name"],

            "email":
                row["email"],

            "hashed_password":
                row["hashed_password"],

            "role":
                row["role"],

            "is_verified":
                bool(
                    row["is_verified"]
                ),

            "is_active":
                bool(
                    row["is_active"]
                ),

            "created_at":
                row["created_at"],
        }

        user.update(
            _decode_extra(
                row["extra_json"]
            )
        )

        users.append(
            user
        )

    return users


def write_users(
    users: list[dict[str, Any]]
) -> None:
    """
    Synchronize PostgreSQL user records with the supplied collection
    without deleting and recreating users that still exist.

    This preserves the original write_users() API so the
    existing auth routes do not need to change yet.
    """

    ensure_storage_files()

    if not isinstance(
        users,
        list
    ):

        raise ValueError(
            "Users must be provided as a list."
        )

    connection = get_connection()

    try:

        connection.execute(
            "BEGIN"
        )

        user_ids = []
        for user in users:

            if not isinstance(
                user,
                dict
            ):

                continue

            user_id = str(
                user.get(
                    "id",
                    ""
                )
            ).strip()

            email = str(
                user.get(
                    "email",
                    ""
                )
            ).strip().lower()

            full_name = str(
                user.get(
                    "full_name",
                    ""
                )
            ).strip()

            hashed_password = str(
                user.get(
                    "hashed_password",
                    ""
                )
            )

            if not user_id or not email:

                raise ValueError(
                    "Every user must contain a valid id and email."
                )

            user_ids.append(user_id)

            known_keys = {
                "id",
                "full_name",
                "email",
                "hashed_password",
                "role",
                "is_verified",
                "is_active",
                "created_at",
            }

            extra = {
                key: value
                for key, value in user.items()
                if key not in known_keys
            }

            connection.execute(
                """
                INSERT INTO users (
                    id,
                    full_name,
                    email,
                    hashed_password,
                    role,
                    is_verified,
                    is_active,
                    created_at,
                    extra_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    full_name = excluded.full_name,
                    email = excluded.email,
                    hashed_password = excluded.hashed_password,
                    role = excluded.role,
                    is_verified = excluded.is_verified,
                    is_active = excluded.is_active,
                    created_at = excluded.created_at,
                    extra_json = excluded.extra_json
                """,
                (
                    user_id,
                    full_name,
                    email,
                    hashed_password,
                    str(
                        user.get(
                            "role",
                            "user"
                        )
                    ),
                    1
                    if user.get(
                        "is_verified",
                        False
                    )
                    else 0,
                    1
                    if user.get(
                        "is_active",
                        False
                    )
                    else 0,
                    user.get(
                        "created_at"
                    ),
                    json.dumps(
                        extra,
                        ensure_ascii=False
                    ),
                )
            )

        if user_ids:
            placeholders = ", ".join("?" for _ in user_ids)
            connection.execute(
                f"DELETE FROM users WHERE id NOT IN ({placeholders})",
                user_ids,
            )
        else:
            connection.execute(
                "DELETE FROM users"
            )

        connection.commit()

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()


# =========================================================
# OTP
# =========================================================

def read_otps() -> dict[str, Any]:
    """
    Read all OTP records from PostgreSQL.

    Return shape remains:
    {
        "email@example.com": {
            "otp": "...",
            "expires_at": "...",
            "purpose": "..."
        }
    }
    """

    ensure_storage_files()

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                email,
                otp,
                expires_at,
                purpose
            FROM otp_records
            """
        ).fetchall()

    finally:

        connection.close()


    otps: dict[str, Any] = {}

    for row in rows:

        otps[
            row["email"]
        ] = {

            "otp":
                row["otp"],

            "expires_at":
                row["expires_at"],

            "purpose":
                row["purpose"],
        }

    return otps


def write_otps(
    otps: dict[str, Any]
) -> None:
    """
    Replace OTP records in PostgreSQL.

    The public API is kept identical to the original
    JSON-backed implementation.
    """

    ensure_storage_files()

    if not isinstance(
        otps,
        dict
    ):

        raise ValueError(
            "OTPs must be provided as a dictionary."
        )

    connection = get_connection()

    try:

        connection.execute(
            "BEGIN"
        )

        connection.execute(
            "DELETE FROM otp_records"
        )

        for email, record in otps.items():

            if not isinstance(
                record,
                dict
            ):

                continue

            normalized_email = str(
                email
            ).strip().lower()

            otp = str(
                record.get(
                    "otp",
                    ""
                )
            )

            expires_at = str(
                record.get(
                    "expires_at",
                    ""
                )
            )

            purpose = str(
                record.get(
                    "purpose",
                    ""
                )
            )

            if not normalized_email or not otp:

                continue

            connection.execute(
                """
                INSERT INTO otp_records (
                    email,
                    otp,
                    expires_at,
                    purpose
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    normalized_email,
                    otp,
                    expires_at,
                    purpose,
                )
            )

        connection.commit()

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()


__all__ = [
    "ensure_storage_files",
    "read_users",
    "write_users",
    "read_otps",
    "write_otps",
]
