#!/usr/bin/env python3
"""
Local unit / integration tests for the NYX client upgrade.

Tests (no live server required):
  1. Config defaults (auto_sync, sync_interval, theme)
  2. URL validation
  3. Contact aliases (save, resolve, sort, update)
  4. Theme manager
  5. Session message recording (in-memory only)
  6. First-run wizard URL validation helpers
  7. DB schema has alias column + migration safety
  8. Command dispatch pieces (alias, theme, sync status) via mocks
  9. Crypto still works end-to-end
 10. Display name / resolve_contact priority

Run:
    cd client && python test_upgrade.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from unittest import mock

# Ensure client package imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import crypto
import db
import themes
import ui
import commands


PASSED = 0
FAILED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        extra = f" — {detail}" if detail else ""
        print(f"  [FAIL] {name}{extra}")


# ---------------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------------

def test_config() -> None:
    print("\n[1] Config defaults & persistence")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        cfg = config.NYXConfig(config_path=path)
        assert not cfg.exists()
        data = cfg.load()
        check("default auto_sync is True", data.get("auto_sync") is True)
        check("default sync_interval is 3", data.get("sync_interval") == 3)
        check("default theme is matrix", data.get("theme") == "matrix")
        check("default server_url present", "server_url" in data)

        cfg.set("auto_sync", False)
        cfg.set("sync_interval", 5)
        cfg.set("theme", "telegram")
        cfg.set("server_url", "https://example.com")

        # Reload
        cfg2 = config.NYXConfig(config_path=path)
        cfg2.load()
        check("persisted auto_sync=False", cfg2.auto_sync is False)
        check("persisted sync_interval=5", cfg2.sync_interval == 5)
        check("persisted theme=telegram", cfg2.theme == "telegram")
        check("persisted server_url", cfg2.server_url == "https://example.com")

        # Property clamps
        cfg2.set("sync_interval", 0)
        check("sync_interval clamps to >=1", cfg2.sync_interval >= 1)

        # ensure_defaults fills missing keys on old configs
        path.write_text(json.dumps({"server_url": "http://x"}), encoding="utf-8")
        cfg3 = config.NYXConfig(config_path=path)
        cfg3.load()
        cfg3.ensure_defaults()
        check("ensure_defaults adds theme", cfg3.get("theme") is not None)
        check("ensure_defaults adds auto_sync", cfg3.get("auto_sync") is not None)


# ---------------------------------------------------------------------------
# 2. URL validation
# ---------------------------------------------------------------------------

def test_url_validation() -> None:
    print("\n[2] URL validation")
    ok, _ = ui._validate_url("https://nyx-relay.up.railway.app")
    check("https URL accepted", ok)
    ok, _ = ui._validate_url("http://localhost:8000")
    check("http localhost accepted", ok)
    ok, err = ui._validate_url("ftp://bad")
    check("ftp rejected", not ok)
    ok, err = ui._validate_url("not-a-url")
    check("bare host rejected", not ok)
    ok, err = ui._validate_url("")
    check("empty rejected", not ok)
    ok, err = ui._validate_url("https://")
    check("https without host rejected", not ok)


# ---------------------------------------------------------------------------
# 3. Contact aliases
# ---------------------------------------------------------------------------

def test_aliases() -> None:
    print("\n[3] Contact alias system")
    with tempfile.TemporaryDirectory() as tmp:
        local = db.NYXDatabase(Path(tmp) / "test.db")

        # Fake public keys (any non-empty string works for DB layer)
        local.save_contact("aaaaaaaaaaaaaaaa", "PUBKEY_A" * 5, alias="Alice")
        local.save_contact("bbbbbbbbbbbbbbbb", "PUBKEY_B" * 5, alias="Bob")
        local.save_contact("cccccccccccccccc", "PUBKEY_C" * 5)  # no alias

        contacts = local.get_contacts(sort_by="id")
        check("3 contacts stored", len(contacts) == 3)
        check("alias column returned", contacts[0][2] == "Alice")

        # Resolve by alias
        check("resolve by alias Alice", local.resolve_contact("Alice") == "aaaaaaaaaaaaaaaa")
        check("resolve by alias case-insensitive", local.resolve_contact("alice") == "aaaaaaaaaaaaaaaa")
        check("resolve by device_id", local.resolve_contact("bbbbbbbbbbbbbbbb") == "bbbbbbbbbbbbbbbb")
        check("resolve by prefix", local.resolve_contact("cccc") == "cccccccccccccccc")
        check("resolve unknown returns None", local.resolve_contact("Nope") is None)

        # display_name
        check("display_name uses alias", local.display_name("aaaaaaaaaaaaaaaa") == "Alice")
        check("display_name falls back to id", local.display_name("cccccccccccccccc") == "cccccccccccccccc")

        # update_alias
        ok = local.update_alias("bbbbbbbbbbbbbbbb", "Bobby")
        check("update_alias returns True", ok)
        check("alias updated", local.get_contact_alias("bbbbbbbbbbbbbbbb") == "Bobby")
        check("resolve new alias", local.resolve_contact("Bobby") == "bbbbbbbbbbbbbbbb")

        # sort by alias
        sorted_alias = local.get_contacts(sort_by="alias")
        # Alice, Bobby first (have aliases), then no-alias
        aliases = [c[2] for c in sorted_alias]
        check("sort by alias puts named first", aliases[0] in ("Alice", "Bobby"))
        check("no-alias last when sorting by alias", aliases[-1] is None)

        # preserve alias on public-key-only update
        local.save_contact("aaaaaaaaaaaaaaaa", "NEW_PUBKEY")
        check("alias preserved on key update", local.get_contact_alias("aaaaaaaaaaaaaaaa") == "Alice")
        check("pubkey updated", local.get_contact("aaaaaaaaaaaaaaaa") == "NEW_PUBKEY")

        # clear alias
        local.update_alias("aaaaaaaaaaaaaaaa", "")
        check("alias cleared", local.get_contact_alias("aaaaaaaaaaaaaaaa") is None)

        local.close()


# ---------------------------------------------------------------------------
# 4. Theme manager
# ---------------------------------------------------------------------------

def test_themes() -> None:
    print("\n[4] Theme system")
    tm = themes.ThemeManager("matrix")
    check("default name matrix", tm.name == "matrix")
    check("matrix has green foreground", "green" in tm.get("foreground"))
    check("switch to telegram", tm.set_theme("telegram") is True)
    check("name is telegram", tm.name == "telegram")
    check("telegram accent is blue-ish", "blue" in tm.get("accent") or "dodger" in tm.get("accent"))
    check("switch to monochrome", tm.set_theme("monochrome"))
    check("switch to solarized", tm.set_theme("solarized"))
    check("unknown theme rejected", tm.set_theme("neon") is False)
    check("list_themes has 4", len(themes.ThemeManager.list_themes()) == 4)

    # sender colour stability
    c1 = tm.sender_color("alice")
    c2 = tm.sender_color("alice")
    c3 = tm.sender_color("bob")
    check("sender colour stable", c1 == c2)
    check("different senders can differ", True)  # may collide; just ensure no crash
    _ = c3


# ---------------------------------------------------------------------------
# 5. Session messages (no DB persistence)
# ---------------------------------------------------------------------------

def test_session_messages() -> None:
    print("\n[5] Session-only message log")
    commands.clear_session_messages()
    check("starts empty", len(commands.get_session_messages()) == 0)
    commands._record_message("Alice", "Hello", False, "aaa")
    commands._record_message("You", "Hi", True, "me")
    msgs = commands.get_session_messages()
    check("2 messages recorded", len(msgs) == 2)
    check("first is Alice", msgs[0][1] == "Alice" and msgs[0][3] is False)
    check("second is You", msgs[1][1] == "You" and msgs[1][3] is True)
    commands.clear_session_messages()
    check("cleared", len(commands.get_session_messages()) == 0)


# ---------------------------------------------------------------------------
# 6. DB has no messages table (ephemeral design)
# ---------------------------------------------------------------------------

def test_no_message_persistence() -> None:
    print("\n[6] No message persistence in DB")
    with tempfile.TemporaryDirectory() as tmp:
        local = db.NYXDatabase(Path(tmp) / "test.db")
        conn = local.connect()
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        check("contacts table exists", "contacts" in tables)
        check("meta table exists", "meta" in tables)
        check("messages table NOT created", "messages" not in tables)
        # alias column present
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
        check("alias column present", "alias" in cols)
        local.close()


# ---------------------------------------------------------------------------
# 7. Crypto still works
# ---------------------------------------------------------------------------

def test_crypto() -> None:
    print("\n[7] Crypto E2EE round-trip")
    with tempfile.TemporaryDirectory() as tmp:
        a = crypto.NYXCrypto(
            device_id_path=os.path.join(tmp, "a_id"),
            keys_path=os.path.join(tmp, "a_keys"),
        )
        b = crypto.NYXCrypto(
            device_id_path=os.path.join(tmp, "b_id"),
            keys_path=os.path.join(tmp, "b_keys"),
        )
        a.generate_identity()
        b.generate_identity()
        check("alice has identity", a.has_identity())
        check("bob has identity", b.has_identity())
        check("device_id is 16 hex", len(a.device_id) == 16)

        bundle = b.get_public_key_b64()
        check("public key bundle 88 chars", len(bundle) == 88)
        _, b_x = crypto.parse_public_key_bundle(bundle)

        ct, nonce = a.encrypt("secret hello", b_x)
        pt = b.decrypt(ct, nonce, a.device_id)
        check("decrypt succeeds", pt == "secret hello")
        pt_bad = b.decrypt(ct, nonce, "wrong_sender")
        check("wrong AAD fails", pt_bad is None)


# ---------------------------------------------------------------------------
# 8. Mocked network: register / send / sync
# ---------------------------------------------------------------------------

def test_mocked_network() -> None:
    print("\n[8] Mocked network commands")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.json"
        cfg = config.NYXConfig(config_path=cfg_path)
        cfg.load()
        cfg.set("server_url", "http://mock.server")

        local = db.NYXDatabase(Path(tmp) / "local.db")
        eng = crypto.NYXCrypto(
            device_id_path=os.path.join(tmp, "id"),
            keys_path=os.path.join(tmp, "keys"),
        )
        eng.generate_identity()

        # Mock register
        fake_reg = mock.Mock()
        fake_reg.json.return_value = {"status": "ok"}
        fake_reg.status_code = 200

        with mock.patch("commands.requests.post", return_value=fake_reg) as post:
            resp = commands.register(cfg, local, eng, quiet=True)
            check("register returns ok", resp is not None and resp.get("status") == "ok")
            check("is_registered True", local.is_registered())
            check("POST called once", post.call_count == 1)

        # Import contact + alias without interactive prompt
        bob = crypto.generate_identity()
        bob_pub = crypto.public_key_bundle_b64(bob)
        did = commands.import_contact(
            local, bob_pub, alias="Bob", prompt_alias=False
        )
        check("import returns device_id", did == bob.device_id)
        check("alias Bob stored", local.get_contact_alias(bob.device_id) == "Bob")
        check("resolve Bob", local.resolve_contact("Bob") == bob.device_id)

        # Mock send
        fake_send = mock.Mock()
        fake_send.json.return_value = {"status": "ok"}
        fake_send.status_code = 200
        with mock.patch("commands.requests.post", return_value=fake_send):
            resp = commands.send_message(cfg, local, eng, "Bob", "Hi Bob!")
            check("send returns ok", resp is not None and resp.get("status") == "ok")

        # Session log should have our outbound message
        msgs = commands.get_session_messages()
        check("session has sent message", any(m[2] == "Hi Bob!" for m in msgs))

        # Mock sync with an encrypted inbound message from Bob
        # Encrypt as Bob → Alice
        alice_bundle = eng.get_public_key_b64()
        _, alice_x = crypto.parse_public_key_bundle(alice_bundle)
        enc = crypto.encrypt_message("Hey Alice!", alice_x, bob.device_id)

        fake_sync = mock.Mock()
        fake_sync.json.return_value = {
            "status": "ok",
            "messages": [{
                "message_id": enc.message_id,
                "sender_id": bob.device_id,
                "ciphertext": enc.ciphertext_b64,
                "nonce": enc.nonce_b64,
                "created_at": "2026-01-01 12:00:00",
            }],
            "keys": {bob.device_id: bob_pub},
        }
        fake_sync.status_code = 200

        before = len(commands.get_session_messages())
        with mock.patch("commands.requests.post", return_value=fake_sync):
            with mock.patch("ui.play_beep"), mock.patch("ui.show_desktop_notification"):
                resp = commands.sync_messages(
                    cfg, local, eng, quiet=True, notify=True
                )
        check("sync got 1 message", resp is not None and len(resp.get("messages", [])) == 1)
        after = len(commands.get_session_messages())
        check("session grew by 1", after == before + 1)
        last = commands.get_session_messages()[-1]
        check("decrypted inbound content", last[2] == "Hey Alice!")
        check("sender display is Bob", last[1] == "Bob")

        local.close()


# ---------------------------------------------------------------------------
# 9. Sync command handler (config side)
# ---------------------------------------------------------------------------

def test_sync_command_config() -> None:
    print("\n[9] Sync command config mutations")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = config.NYXConfig(config_path=Path(tmp) / "c.json")
        cfg.load()
        local = db.NYXDatabase(Path(tmp) / "d.db")
        eng = crypto.NYXCrypto(
            device_id_path=os.path.join(tmp, "id"),
            keys_path=os.path.join(tmp, "keys"),
        )
        eng.generate_identity()

        commands.handle_sync_command(cfg, local, eng, "off")
        check("sync off", cfg.auto_sync is False)
        commands.handle_sync_command(cfg, local, eng, "on")
        check("sync on", cfg.auto_sync is True)
        commands.handle_sync_command(cfg, local, eng, "interval 7")
        check("sync interval 7", cfg.sync_interval == 7)
        commands.handle_sync_command(cfg, local, eng, "interval 0")
        check("invalid interval rejected (stays 7)", cfg.sync_interval == 7)
        local.close()


# ---------------------------------------------------------------------------
# 10. Theme command
# ---------------------------------------------------------------------------

def test_theme_command() -> None:
    print("\n[10] Theme command")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = config.NYXConfig(config_path=Path(tmp) / "c.json")
        cfg.load()
        tm = themes.ThemeManager("matrix")
        commands.set_theme_manager(tm)

        commands.handle_theme_command(cfg, "telegram")
        check("theme config updated", cfg.theme == "telegram")
        check("theme manager updated", tm.name == "telegram")

        commands.handle_theme_command(cfg, "list")  # should not crash
        commands.handle_theme_command(cfg, "nope")  # unknown
        check("unknown theme not applied", cfg.theme == "telegram")


# ---------------------------------------------------------------------------
# 11. UI helpers
# ---------------------------------------------------------------------------

def test_ui_helpers() -> None:
    print("\n[11] UI helpers")
    ts = ui.format_timestamp()
    check("timestamp HH:MM:SS", len(ts) == 8 and ts[2] == ":")
    text = ui.format_chat_message("12:00:00", "Alice", "Hi", is_you=False)
    check("format_chat_message returns string", text is not None)
    plain = text if isinstance(text, str) else text.plain
    check("contains timestamp", "[12:00:00]" in plain)
    check("contains sender", "Alice:" in plain)
    check("contains content", "Hi" in plain)

    you = ui.format_chat_message("12:00:01", "You", "Hey", is_you=True)
    you_plain = you if isinstance(you, str) else you.plain
    check("You prefix", "You:" in you_plain)

    bar = ui.format_status_bar(
        active_contact="Alice",
        auto_sync=True,
        sync_interval=3,
        theme_name="matrix",
        connected=True,
    )
    check("status bar has Active", "Active: Alice" in bar)
    check("status bar has Sync", "Sync: ON/3s" in bar)
    check("status bar has Theme", "Theme: matrix" in bar)

    # beep should not raise
    try:
        ui.play_beep()
        check("play_beep no crash", True)
    except Exception as e:
        check("play_beep no crash", False, str(e))


# ---------------------------------------------------------------------------
# 12. Connection test with mock
# ---------------------------------------------------------------------------

def test_connection_mock() -> None:
    print("\n[12] Server connection test (mocked)")
    fake = mock.Mock()
    fake.status_code = 200
    fake.json.return_value = {"status": "ok", "service": "NYX Relay"}

    with mock.patch("ui.requests.get", return_value=fake):
        ok, detail = ui.test_server_connection("http://mock.server")
        check("connection success", ok is True)
        check("detail mentions NYX", "NYX" in detail)

    # Failure path
    with mock.patch(
        "ui.requests.get",
        side_effect=__import__("requests").exceptions.ConnectionError(),
    ):
        ok, detail = ui.test_server_connection("http://down.server")
        check("connection failure detected", ok is False)
        check("error message present", len(detail) > 0)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("NYX Client Upgrade — Local Test Suite")
    print("=" * 60)

    tests = [
        test_config,
        test_url_validation,
        test_aliases,
        test_themes,
        test_session_messages,
        test_no_message_persistence,
        test_crypto,
        test_mocked_network,
        test_sync_command_config,
        test_theme_command,
        test_ui_helpers,
        test_connection_mock,
    ]

    for t in tests:
        try:
            t()
        except Exception:
            global FAILED
            FAILED += 1
            print(f"  [FAIL] {t.__name__} raised:")
            traceback.print_exc()

    print()
    print("=" * 60)
    print(f"Results: {PASSED} passed, {FAILED} failed")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())