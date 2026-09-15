import json
from typing import Any, Dict, List, Optional
from cryptography.fernet import Fernet, MultiFernet

from app.config import settings


def get_cipher_suite(keys: Optional[List[str]] = None) -> MultiFernet:
    """Instantiate a MultiFernet suite supporting primary key encryption and multi-key decryption."""
    raw_keys = keys or settings.all_encryption_keys
    fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in raw_keys if k]
    if not fernets:
        raise ValueError("No encryption keys configured. Set ENCRYPTION_KEY in .env")
    return MultiFernet(fernets)


def encrypt_secret(data: Dict[str, Any], keys: Optional[List[str]] = None) -> str:
    """Encrypts a dictionary payload (e.g. auth credentials) into a Fernet ciphertext token."""
    suite = get_cipher_suite(keys)
    payload = json.dumps(data).encode("utf-8")
    return suite.encrypt(payload).decode("utf-8")


def decrypt_secret(ciphertext: str, keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """Decrypts a Fernet ciphertext token back into a dictionary payload."""
    suite = get_cipher_suite(keys)
    decrypted_bytes = suite.decrypt(ciphertext.encode("utf-8"))
    return json.loads(decrypted_bytes.decode("utf-8"))


def rotate_secret(ciphertext: str, new_keys: List[str]) -> str:
    """Re-encrypts a token using the newest key in a new MultiFernet rotation suite."""
    suite = get_cipher_suite(new_keys)
    rotated_bytes = suite.rotate(ciphertext.encode("utf-8"))
    return rotated_bytes.decode("utf-8")
