"""
aead.py — ChaCha20-Poly1305 AEAD encrypt / decrypt for Project NYX.

Message-level sealed-box encryption with ephemeral X25519 keys.
All encryption/decryption happens on the client. The relay server never
sees plaintext or private keys.
"""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from nyx_client.crypto.keys import EncryptedMessage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHACHA_NONCE_SIZE = 12
HKDF_INFO = b"nyx-message-v1"


# ---------------------------------------------------------------------------
# Message encryption / decryption (sealed box with ephemeral X25519)
# ---------------------------------------------------------------------------

def encrypt_message(
    plaintext: str,
    recipient_x25519_public: bytes,
    sender_device_id: str,
) -> EncryptedMessage:
    """
    Encrypt a plaintext message for a recipient using sealed-box style encryption.

    Protocol:
      1. Generate an ephemeral X25519 keypair.
      2. Perform ECDH: shared_secret = ECDH(ephemeral_priv, recipient_pub).
      3. Derive a ChaCha20-Poly1305 key via HKDF-SHA256.
      4. Encrypt plaintext with a random nonce.
      5. Ciphertext blob = ephemeral_pub (32) || chacha_ciphertext_with_tag.

    The recipient uses their X25519 private key + the embedded ephemeral
    public key to recover the shared secret and decrypt.
    """
    # Generate ephemeral X25519 keypair
    eph_priv = X25519PrivateKey.generate()
    eph_pub = eph_priv.public_key()
    eph_pub_bytes = eph_pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    # ECDH with recipient's static public key
    recipient_pub = X25519PublicKey.from_public_bytes(recipient_x25519_public)
    shared_secret = eph_priv.exchange(recipient_pub)

    # Derive AEAD key via HKDF
    aead_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=HKDF_INFO,
    ).derive(shared_secret)

    # Encrypt with ChaCha20-Poly1305
    nonce = os.urandom(CHACHA_NONCE_SIZE)
    chacha = ChaCha20Poly1305(aead_key)
    # Associated data binds the sender identity to the ciphertext
    aad = sender_device_id.encode("utf-8")
    ct = chacha.encrypt(nonce, plaintext.encode("utf-8"), aad)

    # Final ciphertext: ephemeral_pub || encrypted_payload
    full_ciphertext = eph_pub_bytes + ct

    # Generate a unique message ID
    message_id = secrets.token_hex(16)

    return EncryptedMessage(
        ciphertext_b64=base64.b64encode(full_ciphertext).decode("ascii"),
        nonce_b64=base64.b64encode(nonce).decode("ascii"),
        message_id=message_id,
    )


def decrypt_message(
    ciphertext_b64: str,
    nonce_b64: str,
    recipient_x25519_private: bytes,
    sender_device_id: str,
) -> str:
    """
    Decrypt a sealed-box message.

    Protocol (inverse of encrypt_message):
      1. Split ciphertext into ephemeral_pub (32) || chacha_ct.
      2. ECDH(recipient_priv, ephemeral_pub) → shared_secret.
      3. HKDF → AEAD key.
      4. ChaCha20-Poly1305 decrypt with AAD = sender_device_id.

    Returns the plaintext string.
    Raises cryptography.exceptions.InvalidTag on tampering / wrong key.
    """
    full_ct = base64.b64decode(ciphertext_b64)
    nonce = base64.b64decode(nonce_b64)

    if len(full_ct) < 33:
        raise ValueError("Ciphertext too short to contain ephemeral key + payload")

    eph_pub_bytes = full_ct[:32]
    chacha_ct = full_ct[32:]

    # Reconstruct keys
    eph_pub = X25519PublicKey.from_public_bytes(eph_pub_bytes)
    recip_priv = X25519PrivateKey.from_private_bytes(recipient_x25519_private)

    # ECDH
    shared_secret = recip_priv.exchange(eph_pub)

    # Derive AEAD key
    aead_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=HKDF_INFO,
    ).derive(shared_secret)

    # Decrypt
    chacha = ChaCha20Poly1305(aead_key)
    aad = sender_device_id.encode("utf-8")
    plaintext_bytes = chacha.decrypt(nonce, chacha_ct, aad)

    return plaintext_bytes.decode("utf-8")