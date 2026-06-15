from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from filelock import FileLock


class NubraSession:
    def __init__(self, env: str, base_dir: str = "~"):
        self.env = env.upper()
        base = Path(os.path.expanduser(base_dir))
        self.path = base / f".nubra_session_{self.env}.json"
        self.lock_path = str(self.path) + ".lock"

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        with open(self.path) as file_handle:
            return json.load(file_handle)

    def save(self, session_token: str, auth_token: str, expires_at: str) -> None:
        data = {"env": self.env, "session_token": session_token,
                "auth_token": auth_token, "expires_at": expires_at}
        # Write 0600: create with restrictive mode, then write.
        fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file_handle:
            json.dump(data, file_handle)
        os.chmod(self.path, 0o600)

    def is_valid(self, now: datetime | None = None) -> bool:
        data = self.load()
        if not data or not data.get("session_token"):
            return False
        try:
            exp = datetime.fromisoformat(data["expires_at"])
        except (KeyError, ValueError):
            return False
        now = now or datetime.now(timezone.utc)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp > now

    def refresh_with(self, callback) -> dict:
        """Take the lock, double-check validity, call callback only if still invalid.
        callback() must return {session_token, auth_token, expires_at}."""
        with FileLock(self.lock_path, timeout=60):
            if self.is_valid():
                return self.load()
            result = callback()
            if result:
                self.save(result["session_token"], result["auth_token"],
                          result["expires_at"])
            return self.load()
