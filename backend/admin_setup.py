from datetime import datetime, timezone
import uuid

from auth.security import hash_password
from auth.storage import read_users, write_users


def main() -> None:

    print()
    print("ClaimGuard Admin Account Setup")
    print("--------------------------------")
    print()

    name = input(
        "Admin full name: "
    ).strip()

    email = input(
        "Admin email: "
    ).strip().lower()

    password = input(
        "Admin password (minimum 8 characters): "
    )

    if len(name) < 2:
        print("Name must contain at least 2 characters.")
        return

    if "@" not in email:
        print("Please enter a valid email address.")
        return

    if len(password) < 8:
        print("Password must contain at least 8 characters.")
        return

    users = read_users()

    existing = next(
        (
            user
            for user in users
            if user.get(
                "email",
                ""
            ).lower() == email
        ),
        None
    )

    if existing:

        print()
        print(
            "An account with this email already exists."
        )

        print(
            f"Current role: {existing.get('role', 'unknown')}"
        )

        confirm = input(
            "Promote this existing account to Admin? (yes/no): "
        ).strip().lower()

        if confirm != "yes":

            print(
                "Nothing was changed."
            )

            return

        existing["role"] = "admin"
        existing["is_verified"] = True
        existing["is_active"] = True

        write_users(
            users
        )

        print()
        print(
            "Existing account promoted to Admin."
        )
        print(
            f"Email: {email}"
        )
        print(
            "Role : admin"
        )
        print()
        print(
            "Log out and log in again."
        )

        return

    admin = {

        "id":
            str(uuid.uuid4()),

        "full_name":
            name,

        "email":
            email,

        "hashed_password":
            hash_password(
                password
            ),

        "role":
            "admin",

        "is_verified":
            True,

        "is_active":
            True,

        "created_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "created_by_system_setup":
            True,

    }

    users.append(
        admin
    )

    write_users(
        users
    )

    print()
    print(
        "Admin account created successfully."
    )
    print(
        f"Email: {email}"
    )
    print(
        "Role : admin"
    )
    print()
    print(
        "Log out any existing session, then log in with this Admin account."
    )


if __name__ == "__main__":
    main()
