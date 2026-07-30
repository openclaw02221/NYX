"""
keys.py — Key generation and public-key bundle helpers for Project NYX.

Provides:
  - X25519 keypair generation (for ECDH key exchange)
  - Ed25519 keypair generation (for identity / device ID derivation)
  - Passphrase-based private key encryption (AES-256-GCM + PBKDF2)
  - Public key bundle encode / decode
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PBKDF2_ITERATIONS = 600_000  # OWASP recommendation for PBKDF2-SHA256
PBKDF2_SALT_SIZE = 16
AES_NONCE_SIZE = 12


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class IdentityKeys:
    """Holds a complete NYX identity: Ed25519 identity + X25519 encryption keys."""

    device_id: str
    # Ed25519 (identity / signing)
    ed25519_private: bytes  # raw 32-byte seed
    ed25519_public: bytes   # raw 32-byte public key
    # X25519 (encryption / ECDH)
    x25519_private: bytes   # raw 32-byte private key
    x25519_public: bytes    # raw 32-byte public key


@dataclass
class EncryptedMessage:
    """Result of encrypting a plaintext message for a recipient."""

    ciphertext_b64: str   # base64(ephemeral_pub || ciphertext_with_tag)
    nonce_b64: str        # base64(nonce)
    message_id: str       # unique message identifier


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def generate_identity() -> IdentityKeys:
    """
    Generate a fresh NYX identity.

    Creates an Ed25519 keypair (for identity) and an X25519 keypair
    (for encryption). The device_id is derived from the Ed25519 public key
    as a truncated SHA-256 hex digest.
    """
    # Ed25519 identity key
    ed_priv = Ed25519PrivateKey.generate()
    ed_pub = ed_priv.public_key()
    ed_priv_bytes = ed_priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    ed_pub_bytes = ed_pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    # X25519 encryption key
    x_priv = X25519PrivateKey.generate()
    x_pub = x_priv.public_key()
    x_priv_bytes = x_priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    x_pub_bytes = x_pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    # Device ID: first 16 hex chars of SHA-256(ed25519_public)
    device_id = hashlib.sha256(ed_pub_bytes).hexdigest()[:16]

    return IdentityKeys(
        device_id=device_id,
        ed25519_private=ed_priv_bytes,
        ed25519_public=ed_pub_bytes,
        x25519_private=x_priv_bytes,
        x25519_public=x_pub_bytes,
    )


def public_key_bundle_b64(identity: IdentityKeys) -> str:
    """
    Encode the public key bundle as a base64 string for registration.

    Format: base64( ed25519_public (32) || x25519_public (32) )
    Total: 64 raw bytes → 88 base64 characters.
    """
    bundle = identity.ed25519_public + identity.x25519_public
    return base64.b64encode(bundle).decode("ascii")


def parse_public_key_bundle(bundle_b64: str) -> Tuple[bytes, bytes]:
    """
    Decode a public key bundle.

    Returns (ed25519_public, x25519_public) as raw bytes.
    """
    raw = base64.b64decode(bundle_b64)
    if len(raw) != 64:
        raise ValueError(f"Invalid public key bundle length: expected 64 bytes, got {len(raw)}")
    return raw[:32], raw[32:]


# ---------------------------------------------------------------------------
# Passphrase-based private key encryption (for local storage)
# ---------------------------------------------------------------------------

def encrypt_private_keys(
    identity: IdentityKeys,
    passphrase: str,
) -> Tuple[str, str, str]:
    """
    Encrypt the private keys with a user passphrase for local storage.

    Uses PBKDF2-HMAC-SHA256 to derive an AES-256 key, then AES-256-GCM
    to encrypt the concatenated private keys.

    Returns (encrypted_blob_b64, salt_b64, nonce_b64).
    """
    salt = os.urandom(PBKDF2_SALT_SIZE)
    nonce = os.urandom(AES_NONCE_SIZE)

    # Derive AES-256 key from passphrase
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    aes_key = kdf.derive(passphrase.encode("utf-8"))

    # Concatenate private keys: ed25519_priv (32) || x25519_priv (32)
    plaintext = identity.ed25519_private + identity.x25519_private

    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    return (
        base64.b64encode(ciphertext).decode("ascii"),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
    )


def decrypt_private_keys(
    encrypted_blob_b64: str,
    salt_b64: str,
    nonce_b64: str,
    passphrase: str,
    device_id: str,
    ed25519_public: bytes,
    x25519_public: bytes,
) -> IdentityKeys:
    """
    Decrypt private keys from local storage using the user passphrase.

    Returns a fully reconstructed IdentityKeys object.
    Raises cryptography.exceptions.InvalidTag on wrong passphrase.
    """
    salt = base64.b64decode(salt_b64)
    nonce = base64.b64decode(nonce_b64)
    ciphertext = base64.b64decode(encrypted_blob_b64)

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    aes_key = kdf.derive(passphrase.encode("utf-8"))

    aesgcm = AESGCM(aes_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)

    if len(plaintext) != 64:
        raise ValueError("Decrypted private key blob has unexpected length")

    return IdentityKeys(
        device_id=device_id,
        ed25519_private=plaintext[:32],
        ed25519_public=ed25519_public,
        x25519_private=plaintext[32:],
        x25519_public=x25519_public,
    )