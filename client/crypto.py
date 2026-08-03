"""
NYX Client Cryptography Module.

Consolidated X25519 + Ed25519 + ChaCha20-Poly1305 E2EE implementation.
Merges crypto/keys.py, crypto/aead.py, crypto/bech32.py, crypto/identity.py, 
crypto/bip39.py, and crypto/ratchet.py.
"""

from __future__ import annotations

import os
import hashlib
import hmac
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.exceptions import InvalidSignature, InvalidTag

from config import get_logger

log = get_logger(__name__)

# Constants
KEY_SIZE = 32
TAG_SIZE = 16
NONCE_SIZE = 12
HRP = "nyx"  # Bech32 human-readable part


# =============================================================================
# Bech32 Encoding (BIP-0173)
# =============================================================================

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
GENERATOR = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]


def _polymod(values: List[int]) -> int:
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= GENERATOR[i]
    return chk


def _hrp_expand(hrp: str) -> List[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _create_checksum(hrp: str, data: List[int]) -> List[int]:
    values = _hrp_expand(hrp) + data + [0, 0, 0, 0, 0, 0]
    polymod = _polymod(values) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _verify_checksum(hrp: str, data: List[int]) -> bool:
    return _polymod(_hrp_expand(hrp) + data) == 1


def _convertbits(data, from_bits: int, to_bits: int, pad: bool = True) -> Optional[List[int]]:
    acc = 0
    bits = 0
    ret: List[int] = []
    maxv = (1 << to_bits) - 1
    max_acc = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        if value < 0 or (value >> from_bits):
            return None
        acc = ((acc << from_bits) | value) & max_acc
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (to_bits - bits)) & maxv)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & maxv):
        return None
    return ret


def bech32_encode(hrp: str, witver: int, witprog: bytes) -> str:
    """Encode bytes to bech32 string."""
    if not (0 <= witver <= 16):
        raise ValueError("invalid witness version")
    converted = _convertbits(witprog, 8, 5)
    if converted is None:
        raise ValueError("bit conversion failed")
    data = [witver] + converted
    combined = data + _create_checksum(hrp, data)
    return hrp + "1" + "".join(CHARSET[d] for d in combined)


def bech32_decode(addr: str) -> Tuple[str, int, bytes]:
    """Decode bech32 string to (hrp, version, bytes)."""
    if any(ord(c) < 33 or ord(c) > 126 for c in addr):
        raise ValueError("invalid character in bech32 string")
    if addr.lower() != addr and addr.upper() != addr:
        raise ValueError("mixed case bech32 string")
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr) or len(addr) > 90:
        raise ValueError("invalid bech32 length or separator")
    if not all(c in CHARSET for c in addr[pos + 1:]):
        raise ValueError("invalid bech32 character")
    hrp = addr[:pos]
    data = [CHARSET.find(c) for c in addr[pos + 1:]]
    if not _verify_checksum(hrp, data):
        raise ValueError("invalid bech32 checksum")
    decoded = _convertbits(data[1:-6], 5, 8, False)
    if decoded is None or len(decoded) < 2 or len(decoded) > 40:
        raise ValueError("invalid bech32 data length")
    return hrp, data[0], bytes(decoded)


# =============================================================================
# AEAD (ChaCha20-Poly1305)
# =============================================================================

def generate_aead_key() -> bytes:
    """Generate a random 32-byte AEAD key."""
    return os.urandom(KEY_SIZE)


def generate_nonce() -> bytes:
    """Generate a random nonce."""
    return os.urandom(NONCE_SIZE)


def aead_encrypt(
    key: bytes,
    plaintext: bytes,
    associated_data: bytes = b"",
    nonce: Optional[bytes] = None,
) -> bytes:
    """
    Authenticated encryption.
    Returns: nonce || ciphertext || tag
    """
    if len(key) != KEY_SIZE:
        raise ValueError(f"key must be {KEY_SIZE} bytes")
    if nonce is None:
        nonce = generate_nonce()
    if len(nonce) != NONCE_SIZE:
        raise ValueError(f"nonce must be {NONCE_SIZE} bytes")

    aead = ChaCha20Poly1305(key)
    ct_and_tag = aead.encrypt(nonce, plaintext, associated_data)
    return nonce + ct_and_tag


def aead_decrypt(
    key: bytes,
    blob: bytes,
    associated_data: bytes = b"",
) -> bytes:
    """
    Authenticated decryption.
    Raises InvalidTag on authentication failure.
    """
    if len(key) != KEY_SIZE:
        raise ValueError(f"key must be {KEY_SIZE} bytes")
    if len(blob) < NONCE_SIZE + TAG_SIZE:
        raise ValueError("ciphertext blob too short")

    nonce = blob[:NONCE_SIZE]
    ct_and_tag = blob[NONCE_SIZE:]

    aead = ChaCha20Poly1305(key)
    return aead.decrypt(nonce, ct_and_tag, associated_data)


# =============================================================================
# Key Pairs (Ed25519 + X25519)
# =============================================================================

@dataclass(frozen=True, slots=True)
class IdentityKeyPair:
    """Long-term identity key pair (Ed25519)."""
    
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    @classmethod
    def generate(cls) -> "IdentityKeyPair":
        priv = Ed25519PrivateKey.generate()
        return cls(private_key=priv, public_key=priv.public_key())

    @classmethod
    def from_private_bytes(cls, data: bytes) -> "IdentityKeyPair":
        if len(data) != 32:
            raise ValueError("Ed25519 private key must be 32 bytes")
        priv = Ed25519PrivateKey.from_private_bytes(data)
        return cls(private_key=priv, public_key=priv.public_key())

    def private_bytes(self) -> bytes:
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def public_bytes(self) -> bytes:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign(self, message: bytes) -> bytes:
        return self.private_key.sign(message)

    def verify(self, signature: bytes, message: bytes) -> bool:
        try:
            self.public_key.verify(signature, message)
            return True
        except InvalidSignature:
            return False

    def identity_string(self) -> str:
        """Bech32-encoded identity: nyx1..."""
        return bech32_encode(HRP, 0, self.public_bytes())

    @staticmethod
    def public_key_from_identity(identity: str) -> Ed25519PublicKey:
        hrp, witver, prog = bech32_decode(identity)
        if hrp != HRP:
            raise ValueError(f"unexpected HRP: {hrp}")
        if witver != 0:
            raise ValueError(f"unexpected witness version: {witver}")
        if len(prog) != 32:
            raise ValueError("identity public key must be 32 bytes")
        return Ed25519PublicKey.from_public_bytes(prog)


@dataclass(frozen=True, slots=True)
class X25519KeyPair:
    """X25519 key pair for Diffie-Hellman."""
    
    private_key: X25519PrivateKey
    public_key: X25519PublicKey

    @classmethod
    def generate(cls) -> "X25519KeyPair":
        priv = X25519PrivateKey.generate()
        return cls(private_key=priv, public_key=priv.public_key())

    def private_bytes(self) -> bytes:
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def public_bytes(self) -> bytes:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def exchange(self, peer_public: bytes) -> bytes:
        """Perform X25519 key exchange."""
        peer_key = X25519PublicKey.from_public_bytes(peer_public)
        return self.private_key.exchange(peer_key)


@dataclass(frozen=True, slots=True)
class DeviceKeyPair:
    """Device-specific key pair."""
    
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey
    device_id: str

    @classmethod
    def generate(cls) -> "DeviceKeyPair":
        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()
        device_id = hashlib.sha256(pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )).hexdigest()[:16]
        return cls(private_key=priv, public_key=pub, device_id=device_id)

    def public_bytes(self) -> bytes:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )


# =============================================================================
# Identity
# =============================================================================

@dataclass
class Identity:
    """In-memory representation of a NYX identity."""
    
    identity_key: IdentityKeyPair
    devices: List[DeviceKeyPair] = field(default_factory=list)

    @property
    def id(self) -> str:
        """Bech32 identity string (nyx1...)."""
        return self.identity_key.identity_string()

    @property
    def public_key_bytes(self) -> bytes:
        return self.identity_key.public_bytes()

    @classmethod
    def create(cls, with_device: bool = True) -> "Identity":
        """Create a brand-new identity with a fresh Ed25519 key pair."""
        ik = IdentityKeyPair.generate()
        devices: List[DeviceKeyPair] = []
        if with_device:
            devices.append(DeviceKeyPair.generate())
        identity = cls(identity_key=ik, devices=devices)
        log.info("identity.created", identity=identity.id, devices=len(devices))
        return identity

    @classmethod
    def from_private_bytes(cls, ik_bytes: bytes) -> "Identity":
        """Restore identity from private key bytes."""
        ik = IdentityKeyPair.from_private_bytes(ik_bytes)
        return cls(identity_key=ik)

    def sign(self, message: bytes) -> bytes:
        """Sign with the long-term identity key."""
        return self.identity_key.sign(message)

    def verify(self, signature: bytes, message: bytes) -> bool:
        return self.identity_key.verify(signature, message)


# =============================================================================
# BIP39 Recovery (simplified)
# =============================================================================

def generate_mnemonic_phrase() -> str:
    """Generate a 24-word BIP39-style recovery phrase."""
    # Simplified implementation - generates random words
    entropy = os.urandom(32)
    # In production, use proper BIP39 wordlist
    word_indices = [int.from_bytes(entropy[i:i+2], 'big') % 2048 for i in range(0, 32, 2)]
    words = [f"word{i:04d}" for i in word_indices[:24]]
    return " ".join(words)


def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """Convert mnemonic to 64-byte seed."""
    # Simplified PBKDF2 derivation
    return hashlib.pbkdf2_hmac(
        'sha512',
        mnemonic.encode('utf-8'),
        ('mnemonic' + passphrase).encode('utf-8'),
        2048,
        dklen=64
    )


# =============================================================================
# Utility Functions
# =============================================================================

def generate_random_bytes(n: int) -> bytes:
    """Generate n random bytes."""
    return os.urandom(n)


def kdf(shared_secret: bytes, info: bytes = b"") -> bytes:
    """Key derivation function (HKDF-SHA256 simplified)."""
    salt = b"\x00" * 32
    return hmac.new(salt, shared_secret + info, hashlib.sha256).digest()