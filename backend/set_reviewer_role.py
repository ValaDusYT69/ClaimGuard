from data.database import get_connection, initialize_and_migrate


def main() -> None:
    """
    Promote one existing ClaimGuard account to the reviewer role.

    This does not change the user's password, verification status,
    active status, name, email, or invoice data.
    """

    initialize_and_migrate()

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                id,
                full_name,
                email,
                role,
                is_verified,
                is_active
            FROM users
            ORDER BY email ASC
            """
        ).fetchall()

        if not rows:

            print("No users were found in the ClaimGuard database.")
            return

        print()
        print("Available ClaimGuard users:")
        print()

        for index, row in enumerate(
            rows,
            start=1
        ):

            print(
                f"{index}. "
                f"{row['full_name']} | "
                f"{row['email']} | "
                f"role={row['role']} | "
                f"verified={bool(row['is_verified'])} | "
                f"active={bool(row['is_active'])}"
            )

        print()

        email = input(
            "Enter the email to promote to reviewer: "
        ).strip().lower()

        if not email:

            print("No email entered. Nothing was changed.")
            return

        user = connection.execute(
            """
            SELECT
                id,
                full_name,
                email,
                role
            FROM users
            WHERE LOWER(email) = ?
            """,
            (
                email,
            )
        ).fetchone()

        if not user:

            print(
                "No user was found with that email."
            )

            return

        connection.execute(
            """
            UPDATE users
            SET role = ?
            WHERE id = ?
            """,
            (
                "reviewer",
                user["id"],
            )
        )

        connection.commit()

        print()
        print(
            "Reviewer role updated successfully:"
        )
        print(
            f"Name : {user['full_name']}"
        )
        print(
            f"Email: {user['email']}"
        )
        print(
            "Role : reviewer"
        )
        print()
        print(
            "Log out and log back in once so the frontend"
        )
        print(
            "localStorage user profile receives the new role."
        )

    finally:

        connection.close()


if __name__ == "__main__":
    main()