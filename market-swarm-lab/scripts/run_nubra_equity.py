"""Nubra equity runner — processes Nifty50 whitelist through the full signal pipeline.

Usage:
    python scripts/run_nubra_equity.py --once
    python scripts/run_nubra_equity.py --interval 3600
    python scripts/run_nubra_equity.py --once --dry-run
    python scripts/run_nubra_equity.py --once --dry-run --strategy news_only

The 3-phase pipeline per symbol:
  1. Fetch  — OHLCV via NubraClient.historical() + NSE announcements
  2. Signal — TimesFM forecast → MiroFish simulation → EquitySignalBuilder (blended)
              OR NSE announcements only → NewsOnlySignalStrategy (news_only)
  3. Trade  — RiskEngine → ExpectedUpsideGate → ExecutionEngine (or skip in dry-run)

Strategy selection:
  --strategy blended    (default) — full blended pipeline, OHLCV required
  --strategy news_only  — news-only pipeline; thin-history skip does NOT apply

Config toggles (set in .env or environment):
  MIROFISH_BASE_URL   — if set, MiroFish runs as a remote service
  ENABLE_TIMESFM      — if "false", uses linear fallback instead of neural model

All `provider_mode` values are logged per symbol so Caveats D/E are always visible.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(_ROOT))

from services.nubra_client.equity_runner import (  # noqa: E402
    NubraEquityRunner,
    _build_risk_audit,
    _chunk,
    build_runner,
    load_config as _load_config,
)
from services.nubra_client.signal_strategies import _REGISTRY  # noqa: E402
from services.nubra_client.universe_registry import (  # noqa: E402
    _UNIVERSE_REGISTRY,
    get_universe,
    load_universes_from_config,
)

_log = logging.getLogger(__name__)
_CONFIG_PATH = _ROOT / "config" / "nubra_config.json"


def _load_config(path: pathlib.Path = _CONFIG_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_whitelist(config: dict, universe_override: str | None) -> list[str]:
    """Resolve the active symbol list and mutate config["whitelist"] in place.

    Precedence: --universe flag > config["universe"] > legacy config["whitelist"].
    Mutating in place keeps both consumers (build_equity_stack + NubraEquityRunner,
    which each read config["whitelist"]) in sync from a single source of truth.
    """
    name = universe_override or config.get("universe")
    resolved = get_universe(name) if name else config["whitelist"]
    config["whitelist"] = resolved
    return resolved


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _preparse_config_path(argv=None) -> pathlib.Path:
    """Extract --config before the main parse so universes load before argparse.

    The --universe choices come from the registry, which is populated from the
    config's "universes" map — so the config path must be known first.
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=str(_CONFIG_PATH))
    known, _ = pre.parse_known_args(argv)
    return pathlib.Path(known.config)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Nubra equity signal runner")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run one pass then exit")
    mode.add_argument(
        "--interval", type=int, metavar="SECONDS", help="Loop with this sleep between runs"
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip order placement")
    parser.add_argument("--config", default=str(_CONFIG_PATH), help="Path to nubra_config.json")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    parser.add_argument(
        "--strategy",
        choices=sorted(_REGISTRY),
        default=None,
        help="Signal strategy override (default: read from config signal.strategy)",
    )
    parser.add_argument(
        "--universe",
        choices=sorted(_UNIVERSE_REGISTRY),
        default=None,
        help="Universe override (default: read from config universe / whitelist)",
    )
    return parser.parse_args(argv)


def main(argv=None) -> None:
    # Load config + universes BEFORE argparse so --universe choices are populated.
    config = _load_config(_preparse_config_path(argv))
    load_universes_from_config(config)
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    _resolve_whitelist(config, args.universe)
    runner = build_runner(config, strategy=args.strategy)

    if args.once:
        summary = runner.run_once(dry_run=args.dry_run)
        print(json.dumps(summary, indent=2, default=str))
    else:
        while True:
            summary = runner.run_once(dry_run=args.dry_run)
            print(json.dumps(summary, indent=2, default=str))
            runner._trade_count = 0  # reset daily cap between intervals
            _log.info("Sleeping %ds before next run", args.interval)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
