"""
scripts/create_user.py
========================
Creates a user account directly in the database.

Why this exists: public registration (`POST /api/v1/auth/register`) must stay disabled in staging and
production (the application refuses to start otherwise), and the platform has no user administration
endpoints. This command is therefore the supported way to create the first administrator and any
later account. It runs the same `AuthService.register` code path as the API, so the password is
hashed identically and a `user.register` audit entry is written.

The password is NEVER taken from the command line (it would end up in shell history and process
listings). Provide it through the CREATE_USER_PASSWORD environment variable for automation, or
leave it unset to be prompted twice without echo.

Usage (inside the API container or an environment with the same configuration):
    python scripts/create_user.py --email cfo@example.com --full-name "Chief Financial Officer" --role finance_director
    CREATE_USER_PASSWORD='...' python scripts/create_user.py --email ap@example.com --full-name "AP Clerk" --role ap_clerk

Roles: super_admin, finance_director, finance_manager, accountant, ap_clerk, ar_clerk, auditor,
approver, viewer. Grant the smallest role that does the job; super_admin and finance_director can
approve and execute payments.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MIN_PASSWORD_LENGTH = 12


def _read_password() -> str:
    from_env = os.environ.get("CREATE_USER_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise SystemExit("Passwords do not match.")
    return first


async def _create(email: str, full_name: str, role: str, password: str) -> None:
    from app.core.constants import UserRole
    from app.db.session import engine, session_scope
    from app.schemas.user import UserCreate
    from app.services.auth_service import AuthService

    try:
        async with session_scope() as session:
            user = await AuthService(session).register(
                UserCreate(email=email, password=password, full_name=full_name, role=UserRole(role))
            )
            print(f"Created user {user.email} with role {user.role} (id {user.id}).")
    finally:
        await engine.dispose()


def main() -> int:
    from app.core.constants import UserRole

    parser = argparse.ArgumentParser(description="Create a finance platform user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--role", required=True, choices=[role.value for role in UserRole])
    args = parser.parse_args()

    password = _read_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        return 2

    asyncio.run(_create(args.email, args.full_name, args.role, password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
