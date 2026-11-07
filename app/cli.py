"""Operator setup: python -m app.cli create-admin email@example.edu."""

import argparse
import getpass

from app.core.security import hash_password
from app.database import SessionLocal, init_db
from app.models import Role, User


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus medical response setup")
    parser.add_argument("command", choices=["create-admin"])
    parser.add_argument("email")
    parser.add_argument("--name", default="Campus Admin")
    args = parser.parse_args()
    init_db()
    password = getpass.getpass("New admin password: ")
    if len(password) < 12:
        raise SystemExit("Use a password of at least 12 characters")
    with SessionLocal() as db:
        if db.query(User).filter_by(email=args.email.lower()).first():
            raise SystemExit("Email already registered")
        db.add(User(name=args.name, email=args.email.lower(),
                    password_hash=hash_password(password), role=Role.admin))
        db.commit()
    print("Admin account created")


if __name__ == "__main__":
    main()
