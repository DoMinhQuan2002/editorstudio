"""Create the first separate administrator account once.

Run from server/account_api with:
    python -m app.admin_bootstrap

The generated password is printed once and must be changed at first sign-in.
"""
import argparse
import secrets

from sqlalchemy import select

from .db import SessionLocal
from .models import AdminAccount
from .routers.admin import ensure_admin_schema
from .security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the initial Media Studio administrator.")
    parser.add_argument("--email", default="admin@mediastudio.local", help="Admin sign-in email")
    parser.add_argument("--name", default="Media Studio Admin", help="Display name")
    args = parser.parse_args()

    ensure_admin_schema()
    email = args.email.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(AdminAccount.id).limit(1)) is not None:
            raise SystemExit("An administrator account already exists. No changes made.")
        password = secrets.token_urlsafe(24)
        admin = AdminAccount(
            email=email,
            display_name=args.name.strip() or "Media Studio Admin",
            password_hash=hash_password(password),
            role="super_admin",
            status="active",
            must_change_password=True,
        )
        db.add(admin)
        db.commit()
        print("Initial administrator created.")
        print(f"Email: {email}")
        print(f"Temporary password: {password}")
        print("The web admin will require a new password on first sign-in.")


if __name__ == "__main__":
    main()
