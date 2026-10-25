"""
scripts/generate_dev_token.py
================================
DEV/DEMO SHORTCUT. Mints a JWT access token directly, bypassing
registration and login entirely.

A real authentication flow now exists — `POST /api/v1/auth/register`
and `POST /api/v1/auth/login` (see `app.api.v1.auth`) — and is what any
real demo or deployment should use. This script remains useful only for
quick local testing when you don't want to spin up a user first (e.g.
testing a single endpoint in isolation). It mints a token with no
password check and no persisted user behind it, so anything it produces
will NOT show up as a real `User` row — audit log entries referencing
this actor id won't resolve to an actual account. Don't use it for
anything beyond throwaway local testing, and don't expose an endpoint
that does this in any deployed environment.

Usage:
    python scripts/generate_dev_token.py --role finance_director --user-id demo-user-1
    python scripts/generate_dev_token.py --role ap_clerk
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.constants import UserRole  # noqa: E402
from app.core.security import create_access_token  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role",
        required=True,
        choices=[role.value for role in UserRole],
        help="Role to embed in the token's claims.",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Actor id to embed as the token subject. Defaults to a random UUID.",
    )
    args = parser.parse_args()

    user_id = args.user_id or str(uuid.uuid4())
    role = UserRole(args.role)
    token = create_access_token(user_id=user_id, role=role, dev_token=True)

    print(f"user_id: {user_id}")
    print(f"role:    {role.value}")
    print(f"token:   {token}")
    print()
    print("Use it as:")
    print(f'  Authorization: Bearer {token}')


if __name__ == "__main__":
    main()
