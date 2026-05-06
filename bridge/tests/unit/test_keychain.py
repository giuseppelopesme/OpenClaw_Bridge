"""Keychain wrapper: serialisation, manifest, rotation grace, and platform guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bridge import keychain


def test_set_get_round_trips_scopes_and_token() -> None:
    keychain.set_credential("brain.agent", "tok-1", ["llm:call", "vault:read"])
    cred = keychain.get_credential("brain.agent")
    assert cred is not None
    assert cred.actor == "brain.agent"
    assert cred.token == "tok-1"
    assert cred.scopes == ("llm:call", "vault:read")
    assert cred.previous_token is None
    assert cred.previous_expires_at is None


def test_get_credential_returns_none_for_missing_actor() -> None:
    assert keychain.get_credential("nope") is None


def test_set_credential_with_rotation_round_trip() -> None:
    expires = datetime.now(UTC) + timedelta(hours=24)
    keychain.set_credential(
        "brain.agent",
        "tok-2",
        ["admin"],
        previous_token="tok-1",
        previous_expires_at=expires,
    )
    cred = keychain.get_credential("brain.agent")
    assert cred is not None
    assert cred.token == "tok-2"
    assert cred.previous_token == "tok-1"
    assert cred.previous_expires_at is not None
    assert abs((cred.previous_expires_at - expires).total_seconds()) < 1


def test_previous_is_active_window() -> None:
    now = datetime.now(UTC)
    fresh = keychain.Credential(
        actor="brain.agent",
        token="t",
        scopes=("admin",),
        previous_token="old",
        previous_expires_at=now + timedelta(minutes=1),
    )
    expired = keychain.Credential(
        actor="brain.agent",
        token="t",
        scopes=("admin",),
        previous_token="old",
        previous_expires_at=now - timedelta(minutes=1),
    )
    no_prev = keychain.Credential(actor="brain.agent", token="t", scopes=("admin",))
    assert fresh.previous_is_active(now) is True
    assert expired.previous_is_active(now) is False
    assert no_prev.previous_is_active(now) is False


def test_list_actors_reflects_set_and_delete() -> None:
    keychain.set_credential("a", "t1", ["admin"])
    keychain.set_credential("b", "t2", ["admin"])
    assert keychain.list_actors() == ["a", "b"]

    keychain.delete_credential("a")
    assert keychain.list_actors() == ["b"]


def test_delete_credential_is_idempotent() -> None:
    keychain.delete_credential("never-existed")  # must not raise
    assert keychain.list_actors() == []


def test_list_credentials_skips_corrupted_entries() -> None:
    keychain.set_credential("good", "t", ["admin"])
    # Corrupt a stored value directly via the test backend.
    keychain._backend.set_password(keychain.SERVICE_NAME, "garbage", "{not json")
    # Manifest is read by list_actors; manually add garbage to manifest.
    actors = keychain._read_manifest()
    actors.append("garbage")
    keychain._write_manifest(actors)

    creds = keychain.list_credentials()
    assert len(creds) == 1
    assert creds[0].actor == "good"


def test_manifest_account_name_is_reserved() -> None:
    with pytest.raises(ValueError, match="reserved"):
        keychain.set_credential("_actors_", "t", ["admin"])
    with pytest.raises(ValueError, match="reserved"):
        keychain.delete_credential("_actors_")


@pytest.mark.macos_keychain
def test_real_macos_keychain_round_trip() -> None:
    """Opt-in: exercises the live macOS Keychain. Requires GUI access on first run."""
    import keyring

    # Bypass the fake — use the real backend.
    keychain._set_backend(keyring)
    test_actor = "openclaw.test._do_not_keep_"
    try:
        keychain.set_credential(test_actor, "real-test-token", ["admin"])
        cred = keychain.get_credential(test_actor)
        assert cred is not None
        assert cred.token == "real-test-token"
    finally:
        keychain.delete_credential(test_actor)
