"""Fernet-based encryption for API keys stored in DB."""
import os
import base64
from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    raw = os.getenv("ENCRYPTION_KEY", "")
    if raw:
        # Accept raw 32-byte base64 key OR pre-generated Fernet key
        try:
            return Fernet(raw.encode())
        except Exception:
            pass
    # Derive a stable key from JWT_SECRET if ENCRYPTION_KEY not set
    secret = os.getenv("JWT_SECRET", "dev-secret-change-in-production-please-use-long-random-string")
    padded = (secret * 4)[:32].encode()
    key = base64.urlsafe_b64encode(padded)
    return Fernet(key)


def encrypt_key(plaintext: str) -> str:
    """Encrypt an API key for secure DB storage."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    """Decrypt a stored API key."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
