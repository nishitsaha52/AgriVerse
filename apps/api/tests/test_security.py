import uuid

import pytest
from fastapi import HTTPException

from agriverse.security import (
    create_access_token,
    decode_token,
    generate_invite_code,
    hash_pin,
    hash_token,
    normalize_phone,
    verify_pin,
)


def test_phone_numbers_are_normalized_to_e164() -> None:
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("09876543210") == "+919876543210"
    assert normalize_phone("+91 98765 43210") == "+919876543210"


def test_invalid_phone_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_phone("123")


def test_pin_hash_round_trip() -> None:
    encoded = hash_pin("123456")
    assert encoded != "123456"
    assert verify_pin("123456", encoded)
    assert not verify_pin("654321", encoded)


def test_access_token_round_trip_and_type_enforcement() -> None:
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    token, _ = create_access_token(user_id, organization_id, "farmer")
    claims = decode_token(token, "access")
    assert claims["sub"] == str(user_id)
    assert claims["org"] == str(organization_id)
    with pytest.raises(HTTPException):
        decode_token(token, "refresh")


def test_invite_codes_are_random_and_only_hashes_need_storage() -> None:
    first = generate_invite_code()
    second = generate_invite_code()
    assert first != second
    assert len(first) >= 32
    assert len(hash_token(first)) == 64
