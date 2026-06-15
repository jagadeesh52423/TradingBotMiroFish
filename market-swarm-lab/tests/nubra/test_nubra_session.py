import os
from datetime import datetime, timedelta, timezone
from services.nubra_client.nubra_session import NubraSession


def test_save_then_load_roundtrip(tmp_path):
    session = NubraSession(env="UAT", base_dir=str(tmp_path))
    exp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    session.save(session_token="tok", auth_token="auth", expires_at=exp)
    loaded = NubraSession(env="UAT", base_dir=str(tmp_path)).load()
    assert loaded["session_token"] == "tok"


def test_file_mode_is_0600(tmp_path):
    session = NubraSession(env="UAT", base_dir=str(tmp_path))
    exp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    session.save(session_token="tok", auth_token="a", expires_at=exp)
    mode = oct(os.stat(session.path).st_mode & 0o777)
    assert mode == "0o600"


def test_env_isolation(tmp_path):
    NubraSession("UAT", str(tmp_path)).save("uat-tok", "a",
        (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    NubraSession("PROD", str(tmp_path)).save("prod-tok", "a",
        (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    assert NubraSession("UAT", str(tmp_path)).load()["session_token"] == "uat-tok"
    assert NubraSession("PROD", str(tmp_path)).load()["session_token"] == "prod-tok"


def test_is_valid_false_when_expired(tmp_path):
    session = NubraSession("UAT", str(tmp_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    session.save("tok", "a", past)
    assert session.is_valid() is False


def test_refresh_with_calls_callback_when_invalid(tmp_path):
    session = NubraSession("UAT", str(tmp_path))
    calls = []

    def cb():
        calls.append(1)
        return {"session_token": "new", "auth_token": "a",
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}

    session.refresh_with(cb)
    assert calls == [1]
    assert session.load()["session_token"] == "new"


def test_refresh_with_skips_callback_when_already_valid(tmp_path):
    session = NubraSession("UAT", str(tmp_path))
    session.save("tok", "a", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    calls = []
    session.refresh_with(lambda: calls.append(1))
    assert calls == []  # double-checked locking: still valid, no re-auth
