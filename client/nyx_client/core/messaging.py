"""
messaging.py — Message send/receive logic for the NYX Messenger client.

Handles encrypted message transmission, decryption of incoming messages,
and the in-memory session-only message log (not persisted to the database).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from nyx_client import config
from nyx_client import crypto
from nyx_client import ui
from nyx_client.storage import NYXDatabase
from nyx_client.themes import ThemeManager

# ---------------------------------------------------------------------------
# Optional ThemeManager reference set by the application at startup
# ---------------------------------------------------------------------------

_tm: Optional[ThemeManager] = None


def set_theme_manager(tm: ThemeManager) -> None:
    """Inject the shared ThemeManager used for styled output."""
    global _tm
    _tm = tm


def _tm_or_default() -> ThemeManager:
    return _tm if _tm is not None else ThemeManager()


# ---------------------------------------------------------------------------
# Output helpers (delegate to ui)
# ---------------------------------------------------------------------------

def _error(msg: str) -> None:
    ui.print_error(msg, _tm_or_default())


def _info(msg: str) -> None:
    ui.print_info(msg, _tm_or_default())


def _success(msg: str) -> None:
    ui.print_success(msg, _tm_or_default())


def _warning(msg: str) -> None:
    ui.print_warning(msg, _tm_or_default())


# ---------------------------------------------------------------------------
# Network helper
# ---------------------------------------------------------------------------

def post(
    cfg: config.NYXConfig,
    endpoint: str,
    payload: dict,
    timeout: int = 10,
) -> Optional[dict]:
    """
    POST JSON to the relay server. Returns the parsed response on
    success, or None on failure.
    """
    url = f"{cfg.server_url.rstrip('/')}/{endpoint.lstrip('/')}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        try:
            return resp.json()
        except Exception:
            _error(f"Invalid JSON response from {url} (HTTP {resp.status_code})")
            return None
    except requests.exceptions.ConnectionError:
        _error(f"Cannot reach server at {url}")
        return None
    except requests.exceptions.Timeout:
        _error(f"Request timed out after {timeout}s")
        return None
    except Exception as e:
        _error(f"Network error: {e}")
        return None


# ---------------------------------------------------------------------------
# In-memory session message log (NOT persisted)
# ---------------------------------------------------------------------------

# Each entry: (timestamp_str, sender_display, content, is_you, device_id)
SessionMessage = Tuple[str, str, str, bool, str]
_session_messages: List[SessionMessage] = []


def get_session_messages() -> List[SessionMessage]:
    """Return the in-memory message log for this session."""
    return list(_session_messages)


def clear_session_messages() -> None:
    """Clear the in-memory message log."""
    _session_messages.clear()


def record_message(
    sender_display: str,
    content: str,
    is_you: bool,
    device_id: str = "",
    timestamp: Optional[str] = None,
) -> str:
    """Append a message to the session log and return the timestamp used."""
    ts = timestamp or ui.format_timestamp()
    _session_messages.append((ts, sender_display, content, is_you, device_id))
    return ts


def session_message_count() -> int:
    """Return the number of messages in the session log."""
    return len(_session_messages)


# ---------------------------------------------------------------------------
# Send / receive
# ---------------------------------------------------------------------------

def sync_messages(
    cfg: config.NYXConfig,
    local_db: NYXDatabase,
    crypto_engine: crypto.NYXCrypto,
    since: Optional[str] = None,
    quiet: bool = False,
    notify: bool = True,
    push_fn: Optional[Callable[[str, str, str, bool], None]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Pull pending messages from the relay server.
    Decrypts and displays or queues them.
    Does NOT store plaintext in the database.
    """
    device_id = crypto_engine.device_id
    tm = _tm_or_default()

    payload: Dict[str, Any] = {"user_id": device_id}
    if since:
        payload["since"] = since

    resp = post(cfg, "sync.php", payload)

    if resp is None:
        if not quiet:
            _error("Sync failed — server unreachable.")
        return None

    # ── Process received messages ──────────────────────────────────
    messages = resp.get("messages", [])
    if messages:
        if not quiet:
            _info(f"Received {len(messages)} new message(s).")
        for msg in messages:
            sender_id = msg.get("sender_id", "???")
            ciphertext_b64 = msg.get("ciphertext", "")
            nonce_b64 = msg.get("nonce", "")
            created = msg.get("created_at", "")

            # Prefer HH:MM:SS from created_at if available
            ts = ui.format_timestamp()
            if created:
                try:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                        try:
                            dt = datetime.strptime(created[:19], fmt)
                            ts = dt.strftime("%H:%M:%S")
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass

            plaintext = crypto_engine.decrypt(
                ciphertext_b64, nonce_b64, sender_id
            )

            sender_display = local_db.display_name(sender_id)

            if plaintext:
                record_message(sender_display, plaintext, False, sender_id, ts)
                if push_fn is not None:
                    push_fn(ts, sender_display, plaintext, False)
                else:
                    ui.print_chat_message(
                        ts, sender_display, plaintext, is_you=False, tm=tm
                    )
                if notify:
                    ui.notify_new_message(sender_display, plaintext, tm)
            else:
                raw_err = "[encrypted, cannot decrypt]"
                record_message(sender_display, raw_err, False, sender_id, ts)
                if push_fn is not None:
                    push_fn(ts, sender_display, raw_err, False)
                else:
                    ui.print_chat_message(
                        ts, sender_display, raw_err, is_you=False, tm=tm
                    )
    else:
        if not quiet:
            _info("No new messages.")

    # ── Store discovered public keys (contacts only, no messages) ──
    keys = resp.get("keys", {})
    count = 0
    for kid, kpub in keys.items():
        if kid != device_id:
            if local_db.get_contact(kid) is None:
                local_db.save_contact(kid, kpub)
                count += 1
            else:
                local_db.save_contact(kid, kpub)
    if count and not quiet:
        _info(f"Discovered {count} new contact(s).")

    return resp


def send_message(
    cfg: config.NYXConfig,
    local_db: NYXDatabase,
    crypto_engine: crypto.NYXCrypto,
    contact_name: str,
    plaintext: str,
) -> Optional[Dict[str, Any]]:
    """
    Send an encrypted message to a contact.
    contact_name can be a full device_id, prefix, or alias.
    """
    tm = _tm_or_default()

    # ── Resolve contact ────────────────────────────────────────────
    recipient_id = local_db.resolve_contact(contact_name)

    if not recipient_id:
        _error(f"Unknown contact: {contact_name}")
        _info("Use '/contacts' to list known contacts, or '/import' to add one.")
        return None

    # ── Fetch recipient's public key bundle from local DB ─────────
    recipient_pubkey_bundle = local_db.get_contact(recipient_id)
    if not recipient_pubkey_bundle:
        _error(f"No public key found for {recipient_id}")
        _info("Use '/sync' to discover contacts, or '/import' to add manually.")
        return None

    # ── Parse the bundle to extract X25519 public key ─────────────
    try:
        _, recipient_x25519_pub = crypto.parse_public_key_bundle(
            recipient_pubkey_bundle
        )
    except ValueError as e:
        _error(f"Invalid public key format: {e}")
        return None

    # ── Encrypt with recipient's X25519 public key ────────────────
    ciphertext_b64, nonce_b64 = crypto_engine.encrypt(
        plaintext, recipient_x25519_pub
    )

    message_id = str(uuid.uuid4())
    sender_id = crypto_engine.device_id
    display = local_db.display_name(recipient_id)

    _info(f"Encrypting and sending to {display}...")

    resp = post(cfg, "send.php", {
        "message_id": message_id,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "ciphertext": ciphertext_b64,
        "nonce": nonce_b64,
    })

    if resp is None:
        _error("Send failed — server unreachable.")
        return None

    if resp.get("status") == "ok":
        _success(f"Message sent to {display}.")
        # Display locally as "You:" and record in session memory only
        ts = ui.format_timestamp()
        ui.print_chat_message(ts, "You", plaintext, is_you=True, tm=tm)
        record_message("You", plaintext, True, sender_id, ts)
    else:
        _error(f"Send rejected: {resp.get('error', 'unknown error')}")

    return resp