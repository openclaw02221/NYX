"""
identity.py — High-level identity management for the NYX client.

Manages identity generation, persistence (to files), and
encrypt/decrypt operations for the REPL layer.
"""

from __future__ import annotations

import base64
from typing import Optional, Tuple

from nyx_client.crypto.aead import decrypt_message, encrypt_message
from nyx_client.crypto.keys import (
    IdentityKeys,
    generate_identity,
    public_key_bundle_b64,
)


class NYXCrypto:
    """
    High-level cryptographic interface for the NYX client.

    Manages identity generation, persistence (to files), and
    encrypt/decrypt operations for the REPL layer.
    """

    def __init__(self, device_id_path: str, keys_path: str):
        self._device_id_path = device_id_path
        self._keys_path = keys_path
        self._identity: Optional[IdentityKeys] = None
        self._load()

    # -- persistence ----------------------------------------------------------

    def _load(self) -> None:
        """Try to load an existing identity from disk."""
        try:
            with open(self._device_id_path, "r") as f:
                device_id = f.read().strip()
        except FileNotFoundError:
            return

        try:
            import json
            with open(self._keys_path, "r") as f:
                keys = json.load(f)
        except (FileNotFoundError, Exception):
            return

        try:
            self._identity = IdentityKeys(
                device_id=device_id,
                ed25519_private=base64.b64decode(keys["ed25519_private"]),
                ed25519_public=base64.b64decode(keys["ed25519_public"]),
                x25519_private=base64.b64decode(keys["x25519_private"]),
                x25519_public=base64.b64decode(keys["x25519_public"]),
            )
        except Exception:
            pass

    def _save(self) -> None:
        """Persist the identity to disk."""
        if self._identity is None:
            return

        import json
        from pathlib import Path

        Path(self._device_id_path).parent.mkdir(parents=True, exist_ok=True)

        with open(self._device_id_path, "w") as f:
            f.write(self._identity.device_id)

        with open(self._keys_path, "w") as f:
            json.dump({
                "ed25519_private": base64.b64encode(self._identity.ed25519_private).decode(),
                "ed25519_public":  base64.b64encode(self._identity.ed25519_public).decode(),
                "x25519_private":  base64.b64encode(self._identity.x25519_private).decode(),
                "x25519_public":   base64.b64encode(self._identity.x25519_public).decode(),
            }, f, indent=2)

    # -- public API -----------------------------------------------------------

    def has_identity(self) -> bool:
        """Return True if an identity is loaded."""
        return self._identity is not None

    @property
    def device_id(self) -> str:
        """Return the device_id, or empty string if no identity."""
        return self._identity.device_id if self._identity else ""

    def generate_identity(self) -> IdentityKeys:
        """Generate a new identity and save it to disk."""
        self._identity = generate_identity()
        self._save()
        return self._identity

    def get_public_key_b64(self) -> str:
        """Return the base64 public key bundle."""
        if self._identity is None:
            return ""
        return public_key_bundle_b64(self._identity)

    def encrypt(self, plaintext: str, recipient_x25519_public: bytes) -> Tuple[str, str]:
        """
        Encrypt a message for a recipient.

        MUST accept recipient's X25519 public key (raw 32 bytes) as parameter.
        MUST call encrypt_message(plaintext, recipient_x25519_public, self._identity.device_id).

        Returns (ciphertext_b64, nonce_b64).
        """
        if self._identity is None:
            raise RuntimeError("No identity loaded")

        enc = encrypt_message(plaintext, recipient_x25519_public, self._identity.device_id)
        return enc.ciphertext_b64, enc.nonce_b64

    def decrypt(self, ciphertext_b64: str, nonce_b64: str, sender_device_id: str) -> Optional[str]:
        """
        Decrypt a message.

        MUST accept sender_device_id as parameter for AAD verification.
        MUST call decrypt_message(ciphertext_b64, nonce_b64, self._identity.x25519_private, sender_device_id).

        Returns the plaintext string, or None on failure.
        """
        if self._identity is None:
            return None

        try:
            plaintext = decrypt_message(
                ciphertext_b64,
                nonce_b64,
                self._identity.x25519_private,
                sender_device_id,
            )
            return plaintext
        except Exception:
            return None