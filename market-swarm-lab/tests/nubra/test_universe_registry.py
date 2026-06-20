"""Offline tests for the universe registry + runner whitelist resolution."""
from __future__ import annotations

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT))

from scripts.run_nubra_equity import _load_config, _resolve_whitelist
from services.nubra_client.universe_registry import (
    _UNIVERSE_REGISTRY,
    get_universe,
    load_universes_from_config,
    register_universe,
)


# ---------------------------------------------------------------------------
# register / get
# ---------------------------------------------------------------------------

class TestRegisterAndGet:
    def test_register_then_get(self):
        register_universe("_tmp_u", ["AAA", "BBB"])
        try:
            assert get_universe("_tmp_u") == ["AAA", "BBB"]
        finally:
            _UNIVERSE_REGISTRY.pop("_tmp_u", None)

    def test_register_copies_list(self):
        source = ["AAA", "BBB"]
        register_universe("_tmp_copy", source)
        try:
            source.append("CCC")
            assert get_universe("_tmp_copy") == ["AAA", "BBB"]
        finally:
            _UNIVERSE_REGISTRY.pop("_tmp_copy", None)

    def test_unknown_universe_raises_valueerror(self):
        with pytest.raises(ValueError, match="Unknown universe"):
            get_universe("not-registered")

    def test_unknown_universe_lists_known(self):
        register_universe("_known_one", ["X"])
        try:
            with pytest.raises(ValueError, match="_known_one"):
                get_universe("definitely-missing")
        finally:
            _UNIVERSE_REGISTRY.pop("_known_one", None)


# ---------------------------------------------------------------------------
# load_universes_from_config
# ---------------------------------------------------------------------------

class TestLoadFromConfig:
    def test_loads_all_named_universes(self):
        cfg = {"universes": {"_lu_a": ["A1"], "_lu_b": ["B1", "B2"]}}
        load_universes_from_config(cfg)
        try:
            assert get_universe("_lu_a") == ["A1"]
            assert get_universe("_lu_b") == ["B1", "B2"]
        finally:
            _UNIVERSE_REGISTRY.pop("_lu_a", None)
            _UNIVERSE_REGISTRY.pop("_lu_b", None)

    def test_missing_universes_key_is_noop(self):
        before = dict(_UNIVERSE_REGISTRY)
        load_universes_from_config({})
        assert dict(_UNIVERSE_REGISTRY) == before


# ---------------------------------------------------------------------------
# Real config integrity
# ---------------------------------------------------------------------------

class TestConfigUniverses:
    def test_config_has_nifty50_and_midcap150(self):
        cfg = _load_config()
        assert "nifty50" in cfg["universes"]
        assert "midcap150" in cfg["universes"]

    def test_nifty50_equals_whitelist(self):
        cfg = _load_config()
        assert cfg["universes"]["nifty50"] == cfg["whitelist"]
        assert len(cfg["universes"]["nifty50"]) == 48

    def test_midcap150_has_150_unique_symbols(self):
        cfg = _load_config()
        midcap = cfg["universes"]["midcap150"]
        assert len(midcap) == 150
        assert len(set(midcap)) == 150

    def test_midcap150_uses_upl_not_upll(self):
        cfg = _load_config()
        midcap = cfg["universes"]["midcap150"]
        assert "UPL" in midcap
        assert "UPLL" not in midcap

    def test_default_universe_and_provider(self):
        cfg = _load_config()
        assert cfg["universe"] == "nifty50"
        assert cfg["data_provider"] == "nubra"


# ---------------------------------------------------------------------------
# _resolve_whitelist precedence: flag > config universe > legacy whitelist
# ---------------------------------------------------------------------------

class TestResolveWhitelist:
    def setup_method(self):
        register_universe("nifty50", ["A", "B"])
        register_universe("midcap150", ["M1", "M2", "M3"])

    def teardown_method(self):
        # leave only test-injected entries cleaned; real config reloads repopulate.
        pass

    def test_flag_overrides_config_universe(self):
        cfg = {"universe": "nifty50", "whitelist": ["LEGACY"]}
        resolved = _resolve_whitelist(cfg, "midcap150")
        assert resolved == ["M1", "M2", "M3"]
        assert cfg["whitelist"] == ["M1", "M2", "M3"]

    def test_config_universe_used_when_no_flag(self):
        cfg = {"universe": "nifty50", "whitelist": ["LEGACY"]}
        resolved = _resolve_whitelist(cfg, None)
        assert resolved == ["A", "B"]
        assert cfg["whitelist"] == ["A", "B"]

    def test_legacy_whitelist_when_no_universe(self):
        cfg = {"whitelist": ["LEGACY1", "LEGACY2"]}
        resolved = _resolve_whitelist(cfg, None)
        assert resolved == ["LEGACY1", "LEGACY2"]
        assert cfg["whitelist"] == ["LEGACY1", "LEGACY2"]

    def test_mutates_in_place(self):
        cfg = {"universe": "midcap150", "whitelist": ["OLD"]}
        _resolve_whitelist(cfg, None)
        # both consumers read config["whitelist"]; it must reflect the resolution.
        assert cfg["whitelist"] == ["M1", "M2", "M3"]

    def test_unknown_universe_flag_raises(self):
        cfg = {"whitelist": ["X"]}
        with pytest.raises(ValueError, match="Unknown universe"):
            _resolve_whitelist(cfg, "nonexistent-universe")
