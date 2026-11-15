import argparse
import asyncio
import re
import uuid
from urllib.parse import urlencode

from sqlalchemy import select

from agriverse.config import get_settings
from agriverse.db import SessionFactory
from agriverse.dependencies import set_tenant_context
from agriverse.models import Membership, Organization, User
from agriverse.security import hash_pin, normalize_phone


async def bootstrap(name: str, phone: str, pin: str, email: str | None) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Bootstrap organization name must not be empty")
    if not re.fullmatch(r"\d{6,12}", pin):
        raise ValueError("Bootstrap PIN must contain 6 to 12 digits")
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
        origin = get_settings().web_origin.rstrip("/")
        query = urlencode({"organization_id": str(organization.id), "staff_pin": "1"})
        print(f"Sign in: {origin}/login?{query}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AgriVerse administration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("bootstrap")
    command.add_argument("--name", help="Organization name (default: BOOTSTRAP_NAME)")
    command.add_argument("--phone", help="Admin phone/login ID (default: BOOTSTRAP_PHONE)")
    command.add_argument("--pin", help="Admin PIN (default: BOOTSTRAP_PIN)")
    command.add_argument("--email", help="Admin OIDC email (default: BOOTSTRAP_EMAIL)")
    reindex = subparsers.add_parser(
        "reindex-embeddings", help="Rebuild provider-specific retrieval vectors"
    )
    reindex.add_argument("--batch-size", type=int, default=32)
    reindex.add_argument(
        "--organization-id", type=uuid.UUID, help="Limit scan reindexing to one organization"
    )
    args = parser.parse_args()
    if args.command == "reindex-embeddings":
        from agriverse.services.reindex import reindex_embeddings

        try:
            asyncio.run(reindex_embeddings(args.batch_size, args.organization_id))
        except (ValueError, RuntimeError) as exc:
            reindex.error(str(exc))
        return
    if args.command == "bootstrap":
        settings = get_settings()
        name = args.name if args.name is not None else settings.bootstrap_name
        phone = args.phone if args.phone is not None else settings.bootstrap_phone
        pin = args.pin if args.pin is not None else settings.bootstrap_pin.get_secret_value()
        email = args.email if args.email is not None else settings.bootstrap_email
        missing = [
            f"--{key} (or BOOTSTRAP_{key.upper()})"
            for key, value in (("name", name), ("phone", phone), ("pin", pin))
            if not value or not value.strip()
        ]
        if missing:
            command.error(f"Missing bootstrap configuration: {', '.join(missing)}")
        assert name is not None and phone is not None
        try:
            asyncio.run(bootstrap(name, phone, pin, email))
        except (ValueError, RuntimeError) as exc:
            command.error(str(exc))


if __name__ == "__main__":
    main()
