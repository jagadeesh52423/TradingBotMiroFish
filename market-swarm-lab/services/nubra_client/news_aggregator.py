"""Aggregates multiple Indian-equity news sources into one nse_result-shaped dict.

Unions the items from each enabled source (NSE filings, Google News, ...) and
runs ONE sentiment analysis over the union — so downstream signal/risk code
that reads a single `nse_result` needs no changes. Drop-in for the runner's
`nse_collector` (exposes the same `.collect(symbol)`).

# add a source: give it a `.fetch(symbol) -> (items, provider_mode)` and register it in from_config
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


class AggregatingNewsCollector:
    def __init__(self, sources: list[tuple[str, Any]], analyzer: Any) -> None:
        # sources: [(audit_key, collector_with_fetch), ...]; first source is primary.
        self._sources = sources
        self._analyzer = analyzer

    @classmethod
    def from_config(cls, config: dict) -> "AggregatingNewsCollector":
        from services.nse_announcements.nse_announcements_collector import NseAnnouncementsCollector
        from services.nse_announcements.sentiment_analyzer import get_analyzer

        engine = config.get("nse", {}).get("sentiment_engine", "keyword")
        sources: list[tuple[str, Any]] = [
            ("nse_announcements", NseAnnouncementsCollector.from_config(config)),
        ]
        if config.get("news", {}).get("google", {}).get("enabled"):
            from services.google_news.google_news_collector import GoogleNewsCollector
            sources.append(("google_news", GoogleNewsCollector.from_config(config)))
        return cls(sources, get_analyzer(engine, config))

    def collect(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper()
        all_items: list[dict] = []
        audit: dict[str, dict] = {}
        modes: list[str] = []
        for key, source in self._sources:
            try:
                items, mode = source.fetch(symbol)
            except Exception as exc:  # a broken source must not sink the others
                _log.warning("%s fetch failed for %s: %s", key, symbol, exc)
                items, mode = [], "fixture_fallback"
            all_items.extend(items)
            modes.append(mode)
            audit[key] = {"status": _live_status(mode), "count": len(items)}

        result = self._analyzer.analyze(all_items)
        # News is "live" for risk purposes if ANY source came back live.
        provider_mode = "nse_live" if any(m.endswith("_live") for m in modes) else "fixture_fallback"
        for a in audit.values():
            a.update(engine=result.engine, degraded=result.degraded)

        return {
            "symbol": symbol,
            "provider_mode": provider_mode,
            "items": all_items,
            "documents": [
                {"source": "news", "content": item.get("attchmntText", "")}
                for item in all_items
                if item.get("attchmntText")
            ],
            "sentiment_score": round(result.sentiment_score, 4),
            "sentiment_label": result.sentiment_label,
            "sentiment_confidence": round(result.confidence, 4),
            "sentiment_reasoning": result.reasoning,
            "sentiment_engine": result.engine,
            "source_audit": audit,
        }


def _live_status(mode: str) -> str:
    return "live" if mode.endswith("_live") else "fallback"
