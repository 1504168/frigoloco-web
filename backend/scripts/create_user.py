"""Create or update a FrigoLoco login user against the configured DB_URL.

Usage (run against whichever environment's DB you target via APP_ENV):
    APP_ENV=production python scripts/create_user.py --email me@x.com --password 'secret'
    APP_ENV=test       python scripts/create_user.py --email me@x.com   # prompts for password

Passwords are bcrypt-hashed before storage. Re-running for an existing email
updates that user's password and re-activates it (idempotent).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.master import User  # noqa: E402
from app.security import hash_password  # noqa: E402


def _mask_dsn(dsn: str) -> str:
    if "://" not in dsn or "@" not in dsn:
        return "***"
    scheme, rest = dsn.split("://", 1)
    return f"{scheme}://***:***@{rest.split('@', 1)[1]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/update a FrigoLoco login user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default=None, help="If omitted, prompts securely.")
    parser.add_argument("--full-name", dest="full_name", default=None, help="Defaults to the email local-part.")
    parser.add_argument(
        "--role",
        default=UserRole.admin.value,
        choices=[role.value for role in UserRole],
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    password = args.password or getpass.getpass("Password: ")
    if not password:
        print("ERROR: empty password", file=sys.stderr)
        return 1
    full_name = args.full_name or email.split("@", 1)[0]

    print(f"Target database : {_mask_dsn(get_settings().db_url)}")
    session = SessionLocal()
    try:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            session.add(
                User(
                    email=email,
                    full_name=full_name,
                    password_hash=hash_password(password),
                    role=UserRole(args.role),
                    is_active=True,
                )
            )
            action = "created"
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
            action = "updated"
        session.commit()
    finally:
        session.close()
    print(f"user {action}: {email} (role={args.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
