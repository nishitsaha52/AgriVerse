import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agriverse import cli
from agriverse.config import Settings
from agriverse.models import Membership, Organization, User
from agriverse.security import verify_pin
from tests.fakes import FakeSession


def test_bootstrap_reads_dotenv_without_cli_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        'BOOTSTRAP_NAME="Example cooperative"\n'
        'BOOTSTRAP_PHONE="+919876543210"\n'
        'BOOTSTRAP_PIN="012345"\n'
        'BOOTSTRAP_EMAIL="admin@example.com"\n',
        encoding="utf-8",
    )
    settings = Settings(_env_file=env)
    assert "012345" not in repr(settings)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    run = AsyncMock()
    monkeypatch.setattr(cli, "bootstrap", run)
    monkeypatch.setattr(sys, "argv", ["agriverse.cli", "bootstrap"])
    cli.main()
    run.assert_awaited_once_with(
        "Example cooperative",
        "+919876543210",
        "012345",
        "admin@example.com",
    )


def test_cli_arguments_override_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        bootstrap_name="Env org",
        bootstrap_phone="+919876543210",
        bootstrap_pin="012345",
        bootstrap_email="env@example.com",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    run = AsyncMock()
    monkeypatch.setattr(cli, "bootstrap", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agriverse.cli",
            "bootstrap",
            "--name",
            "CLI org",
            "--phone",
            "+919876543211",
            "--pin",
            "654321",
            "--email",
            "cli@example.com",
        ],
    )
    cli.main()
    run.assert_awaited_once_with("CLI org", "+919876543211", "654321", "cli@example.com")


def test_missing_credentials_fail_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    run = AsyncMock()
    monkeypatch.setattr(cli, "bootstrap", run)
    monkeypatch.setattr(sys, "argv", ["agriverse.cli", "bootstrap"])
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 2
    assert "BOOTSTRAP_NAME" in capsys.readouterr().err
    run.assert_not_called()


@pytest.mark.parametrize("pin", ["short", "12345", "1234567890123", "abcdef", "123 456"])
async def test_bootstrap_rejects_pin_that_cannot_be_used_to_log_in(pin: str) -> None:
    with pytest.raises(ValueError, match="6 to 12 digits") as error:
        await cli.bootstrap("Org", "+919876543210", pin, None)
    assert pin not in str(error.value)


async def test_bootstrap_persists_hashed_admin_and_prints_login_link(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = FakeSession()

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(cli, "SessionFactory", session)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    await cli.bootstrap(" Demo ", "9876543210", "012345", " Admin@Example.com ")
    org, user, membership = db.added
    assert isinstance(org, Organization) and org.name == "Demo"
    assert isinstance(user, User) and user.phone_e164 == "+919876543210"
    assert user.email == "admin@example.com"
    assert user.pin_hash and verify_pin("012345", user.pin_hash)
    assert isinstance(membership, Membership) and membership.role == "org_admin"
    assert membership.organization_id == org.id
    assert db.commits == 1
    output = capsys.readouterr().out
    assert "012345" not in output
    assert f"http://localhost:3001/login?organization_id={org.id}&staff_pin=1" in output


async def test_bootstrap_refuses_existing_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession(scalar_values=[uuid.uuid4()])

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(cli, "SessionFactory", session)
    with pytest.raises(RuntimeError, match="already exists"):
        await cli.bootstrap("Org", "+919876543210", "012345", None)
    assert db.added == [] and db.commits == 0
