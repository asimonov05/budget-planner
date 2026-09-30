"""Password and session-token hashing used by authentication adapters."""

from __future__ import annotations

import hashlib

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


password_hasher = PasswordHasher(
    time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16
)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False
