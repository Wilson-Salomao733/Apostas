"""Ledger SQLite auditável para scans, ordens, pernas e liquidações."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BET_LEDGER_PATH", ROOT / "data" / "bet_ledger.db"))
logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with _connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                strategy TEXT NOT NULL,
                event_id TEXT,
                event_name TEXT,
                league TEXT,
                kickoff TEXT,
                market_id TEXT NOT NULL,
                market_type TEXT,
                selection_id INTEGER,
                selection_name TEXT,
                back_price REAL,
                back_size REAL,
                lay_price REAL,
                lay_size REAL,
                spread_pct REAL,
                total_matched REAL,
                total_available REAL,
                market_status TEXT,
                decision TEXT,
                reason TEXT,
                leg_key TEXT,
                favorite_odds REAL,
                outcome TEXT,
                settled_at TEXT,
                simulated_profit REAL,
                payload_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_snapshot_market_time
                ON market_snapshots(market_id, captured_at);
            CREATE INDEX IF NOT EXISTS idx_snapshot_decision
                ON market_snapshots(strategy, decision, captured_at);

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opp_id TEXT NOT NULL,
                strategy TEXT NOT NULL,
                event_id TEXT,
                event_name TEXT,
                league TEXT,
                total_stake REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                placed_at TEXT NOT NULL,
                settled_at TEXT,
                profit REAL
            );
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, placed_at);

            CREATE TABLE IF NOT EXISTS order_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                leg_index INTEGER NOT NULL,
                bet_id TEXT NOT NULL,
                market_id TEXT NOT NULL,
                selection_id INTEGER NOT NULL,
                requested_price REAL NOT NULL,
                stake REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                matched_price REAL,
                size_settled REAL,
                profit REAL,
                settled_at TEXT,
                UNIQUE(order_id, leg_index),
                UNIQUE(bet_id)
            );
            CREATE INDEX IF NOT EXISTS idx_legs_bet_id ON order_legs(bet_id);
            """
        )
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(market_snapshots)")
        }
        for name, sql_type in (
            ("outcome", "TEXT"),
            ("settled_at", "TEXT"),
            ("simulated_profit", "REAL"),
            ("leg_key", "TEXT"),
            ("favorite_odds", "REAL"),
        ):
            if name not in columns:
                db.execute(
                    f"ALTER TABLE market_snapshots ADD COLUMN {name} {sql_type}"
                )


def record_snapshot(
    strategy: str,
    market: dict,
    book: dict | None,
    selection_id: int | None,
    selection_name: str = "",
    decision: str = "SEEN",
    reason: str = "",
    favorite_odds: float | None = None,
    leg_key: str = "",
) -> int:
    """Persiste o book observado e a decisão, sem dados de autenticação."""
    init_db()
    book = book or {}
    runner = next(
        (
            item for item in book.get("runners", [])
            if selection_id is not None and item.get("selectionId") == selection_id
        ),
        {},
    )
    exchange = runner.get("ex", {})
    backs = exchange.get("availableToBack", [])
    lays = exchange.get("availableToLay", [])
    back = backs[0] if backs else {}
    lay = lays[0] if lays else {}
    back_price = float(back.get("price", 0) or 0)
    lay_price = float(lay.get("price", 0) or 0)
    spread = (
        ((lay_price - back_price) / back_price) * 100
        if back_price > 0 and lay_price >= back_price
        else None
    )
    event = market.get("event", {})
    competition = market.get("competition", {})
    description = market.get("description", {})
    safe_payload = {"market": market, "book": book}
    try:
        with _connect() as db:
            cursor = db.execute(
            """
            INSERT INTO market_snapshots (
                captured_at, strategy, event_id, event_name, league, kickoff,
                market_id, market_type, selection_id, selection_name,
                back_price, back_size, lay_price, lay_size, spread_pct,
                total_matched, total_available, market_status, decision, reason,
                leg_key, favorite_odds, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(), strategy, str(event.get("id", "")), event.get("name", ""),
                competition.get("name", ""), market.get("marketStartTime", ""),
                str(market.get("marketId", "")),
                description.get("marketType", market.get("marketType", "")),
                selection_id, selection_name, back_price or None,
                float(back.get("size", 0) or 0), lay_price or None,
                float(lay.get("size", 0) or 0), spread,
                float(book.get("totalMatched", 0) or 0),
                float(book.get("totalAvailable", 0) or 0),
                book.get("status", ""), decision, reason,
                leg_key, favorite_odds,
                json.dumps(safe_payload, ensure_ascii=False, default=str),
            ),
            )
            return int(cursor.lastrowid)
    except sqlite3.Error:
        logger.exception("Falha ao registrar snapshot do mercado %s", market.get("marketId"))
        return 0


def record_order(
    opp: Any,
    bet_ids: Iterable[str],
    leg_stakes: Iterable[float],
) -> int:
    init_db()

    def field(name: str, default: Any = None) -> Any:
        if isinstance(opp, dict):
            return opp.get(name, default)
        return getattr(opp, name, default)

    legs = list(field("legs", []) or [])
    ids = [str(value) for value in bet_ids]
    stakes = [float(value) for value in leg_stakes]
    if not legs:
        legs = [{
            "market_id": field("market_id"),
            "selection_id": field("selection_id"),
            "odds": field("odds"),
        }]
    with _connect() as db:
        cursor = db.execute(
            """
            INSERT INTO orders (
                opp_id, strategy, event_id, event_name, league,
                total_stake, status, placed_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (
                str(field("opp_id", "")), str(field("bet_key", "")),
                str(field("event_id", "")), f"{field('home', '')} x {field('away', '')}",
                str(field("league", "")), sum(stakes), _now(),
            ),
        )
        order_id = int(cursor.lastrowid)
        for index, (leg, bet_id, stake) in enumerate(zip(legs, ids, stakes), start=1):
            db.execute(
                """
                INSERT INTO order_legs (
                    order_id, leg_index, bet_id, market_id, selection_id,
                    requested_price, stake
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id, index, bet_id, str(leg.get("market_id", "")),
                    int(leg.get("selection_id", 0)), float(leg.get("odds", 0)),
                    stake,
                ),
            )
        return order_id


def settle_order_from_cleared(bet_ids: Iterable[str], cleared_orders: Iterable[dict]) -> float | None:
    """Atualiza pernas; fecha o grupo apenas quando todas estiverem liquidadas."""
    init_db()
    ids = [str(value) for value in bet_ids]
    cleared = {str(item.get("betId")): item for item in cleared_orders}
    with _connect() as db:
        rows = db.execute(
            f"SELECT * FROM order_legs WHERE bet_id IN ({','.join('?' for _ in ids)})",
            ids,
        ).fetchall()
        if not rows:
            return None
        order_id = int(rows[0]["order_id"])
        for row in rows:
            item = cleared.get(str(row["bet_id"]))
            if not item:
                continue
            db.execute(
                """
                UPDATE order_legs
                SET status='SETTLED', matched_price=?, size_settled=?,
                    profit=?, settled_at=?
                WHERE bet_id=?
                """,
                (
                    float(item.get("priceMatched", 0) or 0),
                    float(item.get("sizeSettled", 0) or 0),
                    float(item.get("profit", 0) or 0),
                    item.get("settledDate") or _now(),
                    str(row["bet_id"]),
                ),
            )
        remaining = db.execute(
            "SELECT COUNT(*) FROM order_legs WHERE order_id=? AND status!='SETTLED'",
            (order_id,),
        ).fetchone()[0]
        if remaining:
            return None
        profit = float(
            db.execute(
                "SELECT COALESCE(SUM(profit), 0) FROM order_legs WHERE order_id=?",
                (order_id,),
            ).fetchone()[0]
        )
        db.execute(
            "UPDATE orders SET status='SETTLED', settled_at=?, profit=? WHERE id=?",
            (_now(), profit, order_id),
        )
        return profit


def daily_exposure_and_profit(day: str | None = None) -> tuple[float, float]:
    init_db()
    day = day or date.today().isoformat()
    with _connect() as db:
        exposure = float(
            db.execute(
                """
                SELECT COALESCE(SUM(total_stake), 0) FROM orders
                WHERE status='OPEN'
                """
            ).fetchone()[0]
        )
        profit = float(
            db.execute(
                """
                SELECT COALESCE(SUM(profit), 0) FROM orders
                WHERE status='SETTLED' AND substr(settled_at, 1, 10)=?
                """,
                (day,),
            ).fetchone()[0]
        )
    return exposure, profit


def reconcile_snapshots(betfair_api: Any, limit: int = 20) -> int:
    """Marca o resultado dos snapshots, inclusive dos candidatos não apostados."""
    init_db()
    now = _now()
    with _connect() as db:
        rows = db.execute(
            """
            SELECT market_id, selection_id
            FROM market_snapshots
            WHERE outcome IS NULL
              AND selection_id IS NOT NULL
              AND kickoff != ''
              AND kickoff < ?
            GROUP BY market_id, selection_id
            ORDER BY MIN(kickoff)
            LIMIT ?
            """,
            (now, max(1, int(limit))),
        ).fetchall()
    settled = 0
    for row in rows:
        try:
            result = betfair_api.get_market_result(row["market_id"])
        except Exception:
            continue
        if not result or result.get("market_status") != "CLOSED":
            continue
        selected = next(
            (
                runner for runner in result.get("runners", [])
                if int(runner.get("selection_id", 0)) == int(row["selection_id"])
            ),
            {},
        )
        outcome = selected.get("result")
        if outcome not in ("WIN", "LOSE"):
            continue
        with _connect() as db:
            snapshots = db.execute(
                """
                SELECT id, back_price FROM market_snapshots
                WHERE market_id=? AND selection_id=? AND outcome IS NULL
                """,
                (row["market_id"], row["selection_id"]),
            ).fetchall()
            for snapshot in snapshots:
                price = float(snapshot["back_price"] or 0)
                simulated = price - 1 if outcome == "WIN" else -1.0
                db.execute(
                    """
                    UPDATE market_snapshots
                    SET outcome=?, settled_at=?, simulated_profit=?
                    WHERE id=?
                    """,
                    (outcome, now, simulated, snapshot["id"]),
                )
        settled += 1
    return settled
