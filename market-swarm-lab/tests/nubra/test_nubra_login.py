"""Offline tests for nubra_login.py helper functions.

Tests cover the parts that do NOT require the live SDK or a real session:
  - _project_root() path resolution
  - _validate_session() session-token checking
  - _check_interactive() non-interactive guard

Live auth, OTP flow, and network calls are intentionally not tested here —
those are validated manually by the user running the script in a terminal.
"""
from __future__ import annotations

import pathlib
import sys
import types
from unittest.mock import patch

import pytest

# Import the helper functions directly from the scripts module.
sys.path.insert(0, str(pathlib.Path(__file__).parents[2] / "scripts"))
from nubra_login import _PROJECT_ROOT, _check_interactive, _validate_session


# ---------------------------------------------------------------------------
# _PROJECT_ROOT: must resolve to market-swarm-lab/
# ---------------------------------------------------------------------------

class TestProjectRoot:
    def test_project_root_resolves_to_market_swarm_lab(self):
        assert _PROJECT_ROOT.name == "market-swarm-lab"
        assert _PROJECT_ROOT.is_absolute()

    def test_env_example_lives_under_project_root(self):
        assert (_PROJECT_ROOT / ".env.example").exists()

    def test_config_lives_under_project_root(self):
        assert (_PROJECT_ROOT / "config" / "nubra_config.json").exists()


# ---------------------------------------------------------------------------
# _validate_session: checks token_data + HEADERS without a network call
# ---------------------------------------------------------------------------

def _fake_nubra(session_token=None, auth_header=None):
    """Build a minimal fake SDK object with the fields _validate_session inspects."""
    nubra = types.SimpleNamespace()
    nubra.token_data = {}
    nubra.HEADERS = {}
    if session_token is not None:
        nubra.token_data["session_token"] = session_token
    if auth_header is not None:
        nubra.HEADERS["Authorization"] = auth_header
    return nubra


class TestValidateSession:
    def test_empty_token_data_returns_false(self):
        assert _validate_session(_fake_nubra()) is False

    def test_missing_session_token_returns_false(self):
        nubra = _fake_nubra(auth_header="Bearer abc123")
        assert _validate_session(nubra) is False

    def test_missing_auth_header_returns_false(self):
        nubra = _fake_nubra(session_token="tok123")
        assert _validate_session(nubra) is False

    def test_empty_string_session_token_returns_false(self):
        nubra = _fake_nubra(session_token="", auth_header="Bearer abc")
        assert _validate_session(nubra) is False

    def test_empty_string_auth_header_returns_false(self):
        nubra = _fake_nubra(session_token="tok123", auth_header="")
        assert _validate_session(nubra) is False

    def test_valid_tokens_returns_true(self):
        nubra = _fake_nubra(session_token="tok123", auth_header="Bearer tok123")
        assert _validate_session(nubra) is True


# ---------------------------------------------------------------------------
# _check_interactive: exits with code 1 when stdin is not a tty
# ---------------------------------------------------------------------------

class TestCheckInteractive:
    def test_non_tty_stdin_exits_with_code_1(self):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            with pytest.raises(SystemExit) as exc_info:
                _check_interactive()
        assert exc_info.value.code == 1

    def test_non_tty_message_mentions_interactive_terminal(self, capsys):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            with pytest.raises(SystemExit):
                _check_interactive()
        stderr = capsys.readouterr().err
        assert "interactive terminal" in stderr
        assert "OTP" in stderr

    def test_tty_stdin_does_not_exit(self):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            _check_interactive()  # must not raise
