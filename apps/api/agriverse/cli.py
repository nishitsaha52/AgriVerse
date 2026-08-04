import argparse
import asyncio

from sqlalchemy import select

from agriverse.db import SessionFactory
from agriverse.dependencies import set_tenant_context
from agriverse.models import Membership, Organization, User
from agriverse.security import hash_pin, normalize_phone


async def bootstrap(name: str, phone: str, pin: str, email: str | None) -> None:
    normalized = normalize_phone(phone)
    async with SessionFactory() as db:
        if await db.scalar(select(Organization.id).limit(1)) is not None:
            raise RuntimeError("Bootstrap refused: an organization already exists")
        organization = Organization(name=name, licence_tier="standard")
        user = User(
            provider="phone",
            phone_e164=normalized,
            email=email.strip().lower() if email else None,
            pin_hash=hash_pin(pin),
        )
        db.add_all([organization, user])
        await db.flush()
        await set_tenant_context(db, organization.id)
        db.add(
            Membership(
                user_id=user.id,
                organization_id=organization.id,
                role="org_admin",
            )
        )
        await db.commit()
        print(f"Created organization {organization.id} and organization admin {user.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AgriVerse administration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("bootstrap")
    command.add_argument("--name", required=True)
    command.add_argument("--phone", required=True)
    command.add_argument("--pin", required=True)
    command.add_argument("--email")
    args = parser.parse_args()
    if args.command == "bootstrap":
        asyncio.run(bootstrap(args.name, args.phone, args.pin, args.email))


if __name__ == "__main__":
    main()
