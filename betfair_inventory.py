#!/usr/bin/env python3
"""Gera inventário sanitizado dos payloads Betfair usados pelo bot."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from betfair_api import BetfairAPI

OUTPUT = Path("data/betfair_payload_inventory.json")
MARKET_TYPES = (
    "MATCH_ODDS",
    "OVER_UNDER_45",
    "OVER_UNDER_105_CORNR",
    "OVER_UNDER_85_CORNR",
    "CORNER_ODDS",
)


def collect_inventory(api: BetfairAPI) -> dict:
    now = datetime.now(timezone.utc)
    time_range = {
        "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": (now + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    base_filter = {"eventTypeIds": ["1"], "marketStartTime": time_range}
    available_types = api.list_market_types(base_filter) or []
    report = {
        "captured_at": now.isoformat(),
        "event_type": "1",
        "window_hours": 72,
        "available_market_types": sorted(
            [
                {
                    "marketType": item.get("marketType"),
                    "marketCount": item.get("marketCount", 0),
                }
                for item in available_types
            ],
            key=lambda item: (-item["marketCount"], item["marketType"] or ""),
        ),
        "payload_fields": {},
        "configured_market_counts": {},
    }
    all_catalogue = []
    for market_type in MARKET_TYPES:
        market_filter = {**base_filter, "marketTypeCodes": [market_type]}
        markets = api.list_market_catalogue_complete(
            market_filter,
            market_projection=[
                "COMPETITION", "EVENT", "RUNNER_DESCRIPTION",
                "MARKET_START_TIME", "MARKET_DESCRIPTION",
            ],
            max_results=200,
            slice_hours=12,
        )
        report["configured_market_counts"][market_type] = len(markets)
        all_catalogue.extend(markets)

    report["payload_fields"]["marketCatalogue"] = api.payload_inventory(all_catalogue)
    market_ids = [item.get("marketId") for item in all_catalogue[:40]]
    books = api.list_market_books_batched(
        market_ids,
        price_projection={
            "priceData": ["EX_BEST_OFFERS", "EX_TRADED"],
            "exBestOffersOverrides": {"bestPricesDepth": 3},
        },
        batch_size=5,
    )
    report["payload_fields"]["marketBook"] = api.payload_inventory(books)
    report["book_status_counts"] = dict(Counter(
        item.get("status", "UNKNOWN") for item in books
    ))

    current = api.list_current_orders_all()
    report["payload_fields"]["currentOrders"] = api.payload_inventory(
        current.get("currentOrders", [])
    )
    since = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cleared = api.list_cleared_orders_all(
        bet_status="SETTLED",
        event_type_ids=["1"],
        settled_date_range={"from": since, "to": time_range["from"]},
    )
    report["payload_fields"]["clearedOrders"] = api.payload_inventory(
        cleared.get("clearedOrders", [])
    )
    report["settled_orders_30d"] = len(cleared.get("clearedOrders", []))
    return report


def main() -> int:
    api = BetfairAPI()
    if not api.login():
        raise SystemExit("Falha no login Betfair")
    report = collect_inventory(api)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Inventário sanitizado salvo em {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
