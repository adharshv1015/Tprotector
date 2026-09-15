from cryptography.fernet import Fernet
from app.services.encryption import decrypt_secret, encrypt_secret, rotate_secret


def test_encryption_and_decryption():
    key = Fernet.generate_key().decode()
    payload = {"client_id": "abc", "client_secret": "super_secret_key"}

    ciphertext = encrypt_secret(payload, keys=[key])
    assert ciphertext != payload

    decrypted = decrypt_secret(ciphertext, keys=[key])
    assert decrypted == payload


def test_multifernet_key_rotation():
    """Verifies that secrets encrypted with old_key can still be decrypted and rotated to new_key."""
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    payload = {"api_key": "live_prod_key_999"}

    # Encrypted with old_key
    token_with_old_key = encrypt_secret(payload, keys=[old_key])

    # MultiFernet suite containing [new_key, old_key] can decrypt tokens from old_key
    rotation_keys = [new_key, old_key]
    decrypted = decrypt_secret(token_with_old_key, keys=rotation_keys)
    assert decrypted == payload

    # Rotate re-encrypts token under new_key
    rotated_token = rotate_secret(token_with_old_key, new_keys=rotation_keys)
    
    # Token can now be decrypted using only new_key
    decrypted_new = decrypt_secret(rotated_token, keys=[new_key])
    assert decrypted_new == payload
