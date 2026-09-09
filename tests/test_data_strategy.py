from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import bet_ledger
import config_loader
import risk_manager
from backtest.settled_csv import analyze
from bet_placement import _parlay_leg_stakes, build_instructions, projected_profit
from betfair_api import BetfairAPI
from combo_definitions import u45_league_allowed
from opportunity_scanner import Opportunity, OpportunityScanner, _league_allowed
from strategy_model import (
    assess_value,
    break_even_probability,
    execution_quality,
    expected_value_pct,
    poisson_under_probability,
)


def sample_book(back=1.60, back_size=100.0, lay=1.68):
    return {
        "status": "OPEN",
        "complete": True,
        "totalMatched": 0.0,
        "totalAvailable": 500.0,
        "runners": [{
            "selectionId": 10,
            "status": "ACTIVE",
            "ex": {
                "availableToBack": [{"price": back, "size": back_size}],
                "availableToLay": [{"price": lay, "size": 100.0}],
            },
        }],
    }


class StrategyTests(unittest.TestCase):
    def test_zero_matched_can_still_be_executable(self):
        quality = execution_quality(sample_book(), 10, 2.0, 10.0, 10.0)
        self.assertTrue(quality.allowed)
        self.assertAlmostEqual(quality.spread_pct, 5.0)

    def test_wide_spread_is_rejected(self):
        quality = execution_quality(sample_book(lay=2.0), 10, 2.0, 10.0, 10.0)
        self.assertFalse(quality.allowed)
        self.assertEqual(quality.reason, "spread_too_wide")

    def test_ev_accounts_for_commission(self):
        probability = break_even_probability(1.50, 0.065)
        self.assertAlmostEqual(expected_value_pct(1.50, probability, 0.065), 0.0)

    def test_poisson_under_probability_is_bounded(self):
        probability = poisson_under_probability(9.0, 10)
        self.assertGreater(probability, 0)
        self.assertLess(probability, 1)

    def test_portfolio_profit_is_sum_not_odds_product(self):
        stakes = _parlay_leg_stakes(4.0, 1.30, 1.60, leg2_ratio=0.5)
        actual = projected_profit(1.30, stakes[0]) + projected_profit(1.60, stakes[1])
        fake_parlay = projected_profit(1.30 * 1.60, 4.0)
        self.assertLess(actual, fake_parlay)

    def test_explicit_leg_stakes_are_not_redivided(self):
        opp = {
            "stake": 20,
            "leg_stakes": [15, 5],
            "legs": [
                {"selection_id": 1, "odds": 1.6},
                {"selection_id": 2, "odds": 1.3},
            ],
        }
        _, exposure, stakes = build_instructions(opp)
        self.assertEqual(stakes, [15.0, 5.0])
        self.assertEqual(exposure, 20.0)

    def test_target_league_aliases_are_accent_insensitive(self):
        allowed = ("brasileirao serie b", "segunda division")
        self.assertTrue(_league_allowed("Brasileirão Série B", allowed))
        self.assertTrue(_league_allowed("Spanish Segunda División", allowed))
        self.assertFalse(_league_allowed("UEFA Champions League", allowed))

    def test_u45_allowlist_uses_betfair_names(self):
        self.assertTrue(u45_league_allowed("Brazilian Serie B"))
        self.assertTrue(u45_league_allowed("Egyptian Premier"))
        self.assertTrue(u45_league_allowed("Argentinian Primera Nacional"))
        self.assertTrue(u45_league_allowed("Greek Super League"))
        self.assertTrue(u45_league_allowed("Spanish Segunda"))
        self.assertFalse(u45_league_allowed("UEFA Champions League"))
        self.assertFalse(u45_league_allowed("Egyptian 2nd Division"))
        self.assertFalse(u45_league_allowed("Colombian Cup"))
        self.assertTrue(u45_league_allowed("Finnish Veikkausliiga"))
        self.assertFalse(u45_league_allowed("US MLS"))

    def test_independent_profiles_are_split(self):
        profiles = config_loader.build_scan_profiles("combo_u105_u45", filter_mode="auto")
        self.assertEqual([item["key"] for item in profiles], ["corners_105", "under45"])
        self.assertTrue(profiles[0]["authorize_on_price_band"])
        self.assertTrue(profiles[1]["use_u45_allowlist"])
        self.assertEqual(profiles[0]["min_odds"], 1.40)
        self.assertEqual(profiles[0]["max_odds"], 1.73)

    def test_corners_price_band_authorizes_without_poisson(self):
        analysis = assess_value(
            {
                "key": "corners_105",
                "market_type": "OVER_UNDER_105_CORNR",
                "authorize_on_price_band": True,
            },
            1.61,
            sample_book(back=1.61, lay=1.70),
            10,
            {},
            {},
            {},
        )
        self.assertTrue(analysis["recommend"])
        self.assertIn("faixa", analysis["reasoning"])

    def test_favorite_threshold_allows_exactly_140(self):
        self.assertTrue(
            OpportunityScanner._favorite_allows_u45((1, "Time A", 1.40), 1.40)
        )
        self.assertFalse(
            OpportunityScanner._favorite_allows_u45((1, "Time A", 1.39), 1.40)
        )
        self.assertFalse(OpportunityScanner._favorite_allows_u45(None, 1.40))

    def test_pick_favorite_ignores_draw(self):
        scanner = object.__new__(OpportunityScanner)
        favorite = scanner._pick_favorite(
            [
                {"selectionId": 1, "runnerName": "The Draw"},
                {"selectionId": 2, "runnerName": "Home"},
                {"selectionId": 3, "runnerName": "Away"},
            ],
            {
                "runners": [
                    {"selectionId": 1, "ex": {"availableToBack": [{"price": 1.20}]}},
                    {"selectionId": 2, "ex": {"availableToBack": [{"price": 1.80}]}},
                    {"selectionId": 3, "ex": {"availableToBack": [{"price": 2.10}]}},
                ]
            },
        )
        self.assertEqual(favorite, (2, "Home", 1.80))

    def test_assess_value_uses_model_key_when_strategy_is_combo(self):
        analysis = assess_value(
            {
                "key": "combo_u105_u45",
                "model_key": "corners_under_105",
                "market_type": "OVER_UNDER_105_CORNR",
                "min_ev_pct": 2.0,
                "min_probability_edge_pct": 2.0,
            },
            1.60,
            sample_book(back=1.60, lay=1.68),
            10,
            {},
            {},
            {"home": {"avg_total": 8.0}, "away": {"avg_total": 8.0}},
        )
        self.assertTrue(analysis["recommend"])
        self.assertIn("poisson_corners", analysis["source"])


class StakeSettingsTests(unittest.TestCase):
    def test_runtime_stakes_are_persisted_and_bounded(self):
        original = config_loader.STAKE_FILE
        try:
            with tempfile.TemporaryDirectory() as temp:
                config_loader.STAKE_FILE = Path(temp) / "stakes.json"
                config_loader.save_stake("corners", 15)
                config_loader.save_stake("goals", 5)
                self.assertEqual(
                    config_loader.get_stake_settings(),
                    {"corners": 15.0, "goals": 5.0},
                )
                with self.assertRaises(ValueError):
                    config_loader.save_stake("goals", 36)
        finally:
            config_loader.STAKE_FILE = original

    def test_telegram_confirmation_and_decimal_parsing(self):
        self.assertFalse(config_loader.needs_stake_confirmation(10))
        self.assertTrue(config_loader.needs_stake_confirmation(15))
        self.assertEqual(config_loader.parse_stake_value("12,5"), 12.5)
        with self.assertRaises(ValueError):
            config_loader.parse_stake_value("1")


class RiskExposureTests(unittest.TestCase):
    def test_daily_limit_70_allows_full_wallet_and_blocks_more(self):
        original_active = risk_manager.ACTIVE_BETS_FILE
        original_daily = risk_manager.DAILY_PL_FILE
        try:
            with tempfile.TemporaryDirectory() as temp:
                risk_manager.ACTIVE_BETS_FILE = Path(temp) / "active.json"
                risk_manager.DAILY_PL_FILE = Path(temp) / "daily.json"
                opp = {
                    "opp_id": "wallet",
                    "bet_key": "combo_u105_u45",
                    "market_id": "corner",
                    "selection_id": 1,
                    "event_id": "event-1",
                    "home": "A",
                    "away": "B",
                    "model_probability": 0.8,
                    "ev_pct": 3.0,
                    "stake": 70,
                    "leg_stakes": [35, 35],
                    "legs": [
                        {"market_id": "corner", "selection_id": 1, "odds": 1.6},
                        {"market_id": "goal", "selection_id": 2, "odds": 1.35},
                    ],
                }
                ok, reason = risk_manager.can_bet(opp)
                self.assertTrue(ok, reason)
                risk_manager.record_bet(opp, "b1,b2", leg_stakes=[35, 35])
                extra = {
                    **opp,
                    "opp_id": "extra",
                    "event_id": "event-2",
                    "market_id": "other",
                    "legs": [{"market_id": "other", "selection_id": 3, "odds": 1.5}],
                    "leg_stakes": [2],
                    "stake": 2,
                }
                blocked, blocked_reason = risk_manager.can_bet(extra)
                self.assertFalse(blocked)
                self.assertTrue(
                    "Exposição" in blocked_reason or "perda diária" in blocked_reason,
                    blocked_reason,
                )
        finally:
            risk_manager.ACTIVE_BETS_FILE = original_active
            risk_manager.DAILY_PL_FILE = original_daily

    def test_old_payload_still_uses_ratio(self):
        _, exposure, stakes = build_instructions({
            "stake": 4,
            "leg2_stake_ratio": 0.5,
            "legs": [
                {"selection_id": 1, "odds": 1.3},
                {"selection_id": 2, "odds": 1.6},
            ],
        })
        self.assertEqual(stakes, [2.0, 2.0])
        self.assertEqual(exposure, 4.0)


class PrimaryCornersTests(unittest.TestCase):
    def test_same_event_adds_conditional_goal_leg(self):
        corner_market = {
            "marketId": "corner",
            "marketStartTime": "2026-09-09T12:00:00Z",
            "competition": {"name": "Brasileirão Série B"},
            "event": {"id": "event-1", "name": "A v B"},
            "description": {"marketType": "OVER_UNDER_105_CORNR"},
        }
        goal_market = {
            "marketId": "goal",
            "marketStartTime": "2026-09-09T12:00:00Z",
            "competition": {"name": "Brasileirão Série B"},
            "event": {"id": "event-1", "name": "A v B"},
            "description": {"marketType": "OVER_UNDER_45"},
        }
        match_market = {
            "marketId": "match",
            "marketStartTime": "2026-09-09T12:00:00Z",
            "competition": {"name": "Brasileirão Série B"},
            "event": {"id": "event-1", "name": "A v B"},
            "description": {"marketType": "MATCH_ODDS"},
        }
        scanner = object.__new__(OpportunityScanner)
        scanner.max_per_profile = 10
        scanner._prioritize_markets = lambda markets, _sport: markets
        scanner._fetch_markets = (
            lambda market_type, _event_type, hours=None:
            [corner_market] if "CORNR" in market_type else [goal_market]
        )
        scanner._match_odds_favorite = (
            lambda _event_id: (match_market, sample_book(back=1.40), (10, "A", 1.40))
        )

        def evaluate(market, profile):
            odds = 1.60 if market["marketId"] == "corner" else 1.35
            return Opportunity(
                opp_id=market["marketId"],
                bet_type=profile["label"],
                bet_key=profile["key"],
                risk="médio",
                home="A",
                away="B",
                league="Brasileirão Série B",
                market_id=market["marketId"],
                selection_id=10,
                selection_label="Under",
                odds=odds,
                stake=float(profile["stake"]),
                confidence=70,
                reasoning="modelo aprovado",
                potential_profit=1.0,
                event_id="event-1",
                model_probability=0.8,
                market_probability=0.7,
                ev_pct=3.0,
            ), None

        scanner._evaluate_market = evaluate
        profile = {
            "key": "combo_u105_u45",
            "label": "Teste",
            "leg1_short": "U10.5 esc",
            "leg2_short": "U4.5 gols",
            "leg1_profile": {
                "market_type": "OVER_UNDER_105_CORNR",
                "selection_hint": "under",
                "min_odds": 1.2,
                "max_odds": 2.5,
            },
            "leg2_profile": {
                "market_type": "OVER_UNDER_45",
                "selection_hint": "under",
                "min_odds": 1.3,
                "max_odds": 1.4,
            },
            "u45_leagues": ("brasileirao serie b",),
            "favorite_min_odds": 1.4,
            "corner_stake": 15,
            "goal_stake": 5,
        }
        original = bet_ledger.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as temp:
                bet_ledger.DB_PATH = Path(temp) / "ledger.db"
                opportunities, stats = scanner._scan_primary_optional(profile)
                self.assertEqual(len(opportunities), 1)
                self.assertEqual(len(opportunities[0].legs), 2)
                self.assertEqual(opportunities[0].leg_stakes, [15, 5])
                self.assertEqual(stats["u45_added"], 1)
        finally:
            bet_ledger.DB_PATH = original

    def _scanner_for(self, league: str, favorite):
        corner_market = {
            "marketId": "corner",
            "marketStartTime": "2026-09-09T12:00:00Z",
            "competition": {"name": league},
            "event": {"id": "event-1", "name": "A v B"},
            "description": {"marketType": "OVER_UNDER_105_CORNR"},
        }
        goal_market = {
            "marketId": "goal",
            "marketStartTime": "2026-09-09T12:00:00Z",
            "competition": {"name": league},
            "event": {"id": "event-1", "name": "A v B"},
            "description": {"marketType": "OVER_UNDER_45"},
        }
        scanner = object.__new__(OpportunityScanner)
        scanner.max_per_profile = 10
        scanner._prioritize_markets = lambda markets, _sport: markets
        scanner._fetch_markets = (
            lambda market_type, _event_type, hours=None:
            [corner_market] if "CORNR" in market_type else [goal_market]
        )
        scanner._match_odds_favorite = lambda _event_id: (None, None, favorite)

        def evaluate(market, profile):
            odds = 1.60 if market["marketId"] == "corner" else 1.35
            return Opportunity(
                opp_id=market["marketId"],
                bet_type=profile["label"],
                bet_key=profile["key"],
                risk="médio",
                home="A",
                away="B",
                league=league,
                market_id=market["marketId"],
                selection_id=10,
                selection_label="Under",
                odds=odds,
                stake=float(profile["stake"]),
                confidence=70,
                reasoning="modelo aprovado",
                potential_profit=1.0,
                event_id="event-1",
                model_probability=0.8,
                market_probability=0.7,
                ev_pct=3.0,
            ), None

        scanner._evaluate_market = evaluate
        return scanner, {
            "key": "combo_u105_u45",
            "label": "Teste",
            "leg1_short": "U10.5 esc",
            "leg2_short": "U4.5 gols",
            "leg1_profile": {
                "market_type": "OVER_UNDER_105_CORNR",
                "selection_hint": "under",
                "min_odds": 1.2,
                "max_odds": 2.5,
            },
            "leg2_profile": {
                "market_type": "OVER_UNDER_45",
                "selection_hint": "under",
                "min_odds": 1.3,
                "max_odds": 1.4,
            },
            "u45_leagues": ("brasileirao serie b",),
            "favorite_min_odds": 1.4,
            "corner_stake": 15,
            "goal_stake": 5,
        }

    def test_disallowed_league_keeps_only_corners(self):
        original = bet_ledger.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as temp:
                bet_ledger.DB_PATH = Path(temp) / "ledger.db"
                scanner, profile = self._scanner_for(
                    "UEFA Champions League", (10, "A", 1.80),
                )
                opportunities, stats = scanner._scan_primary_optional(profile)
                self.assertEqual(len(opportunities), 1)
                self.assertEqual(opportunities[0].legs, [])
                self.assertEqual(opportunities[0].leg_stakes, [15])
                self.assertEqual(stats["u45_league_rejected"], 1)
        finally:
            bet_ledger.DB_PATH = original

    def test_favorite_below_threshold_keeps_only_corners(self):
        original = bet_ledger.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as temp:
                bet_ledger.DB_PATH = Path(temp) / "ledger.db"
                scanner, profile = self._scanner_for(
                    "Brasileirão Série B", (10, "A", 1.39),
                )
                opportunities, stats = scanner._scan_primary_optional(profile)
                self.assertEqual(len(opportunities), 1)
                self.assertEqual(opportunities[0].legs, [])
                self.assertEqual(stats["u45_favorite_rejected"], 1)
        finally:
            bet_ledger.DB_PATH = original

    def test_snapshot_stores_favorite_odds_and_leg(self):
        original = bet_ledger.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as temp:
                bet_ledger.DB_PATH = Path(temp) / "ledger.db"
                snapshot_id = bet_ledger.record_snapshot(
                    "combo_u105_u45",
                    {
                        "marketId": "goal",
                        "marketStartTime": "2026-09-09T12:00:00Z",
                        "competition": {"name": "Brasileirão Série B"},
                        "event": {"id": "event-1", "name": "A v B"},
                        "description": {"marketType": "OVER_UNDER_45"},
                    },
                    None,
                    10,
                    "Under 4.5",
                    "REJECTED",
                    "favorite_below_1.40",
                    favorite_odds=1.39,
                    leg_key="goals",
                )
                self.assertGreater(snapshot_id, 0)
                with bet_ledger._connect() as db:
                    row = db.execute(
                        "SELECT league, favorite_odds, leg_key, decision FROM market_snapshots WHERE id=?",
                        (snapshot_id,),
                    ).fetchone()
                self.assertEqual(row["league"], "Brasileirão Série B")
                self.assertAlmostEqual(row["favorite_odds"], 1.39)
                self.assertEqual(row["leg_key"], "goals")
                self.assertEqual(row["decision"], "REJECTED")
        finally:
            bet_ledger.DB_PATH = original


class ApiPaginationTests(unittest.TestCase):
    def test_current_orders_pagination(self):
        api = object.__new__(BetfairAPI)
        calls = []

        def page(**kwargs):
            calls.append(kwargs["from_record"])
            if kwargs["from_record"] == 0:
                return {"currentOrders": [{"betId": "1"}], "moreAvailable": True}
            return {"currentOrders": [{"betId": "2"}], "moreAvailable": False}

        api.list_current_orders = page
        result = api.list_current_orders_all()
        self.assertEqual(calls, [0, 1])
        self.assertEqual(len(result["currentOrders"]), 2)


class LedgerTests(unittest.TestCase):
    def test_two_legs_close_only_when_both_settle(self):
        with tempfile.TemporaryDirectory() as temp:
            bet_ledger.DB_PATH = Path(temp) / "ledger.db"
            opp = {
                "opp_id": "abc",
                "bet_key": "combo",
                "home": "A",
                "away": "B",
                "league": "Test",
                "legs": [
                    {"market_id": "m1", "selection_id": 1, "odds": 1.3},
                    {"market_id": "m2", "selection_id": 2, "odds": 1.6},
                ],
            }
            bet_ledger.record_order(opp, ["b1", "b2"], [2, 2])
            first = bet_ledger.settle_order_from_cleared(
                ["b1", "b2"], [{"betId": "b1", "profit": 0.6}]
            )
            self.assertIsNone(first)
            second = bet_ledger.settle_order_from_cleared(
                ["b1", "b2"],
                [
                    {"betId": "b1", "profit": 0.6},
                    {"betId": "b2", "profit": -2.0},
                ],
            )
            self.assertAlmostEqual(second, -1.4)


class BacktestTests(unittest.TestCase):
    def test_csv_ids_are_deduplicated(self):
        headers = [
            "Realizada", "Resolvida", "Descrição", "Tipo", "Cotações",
            "Valor Apostado (R$)", "Risco (R$)", "Lucro/Perda", "Status",
        ]
        row = [
            "08-set-26 02:08:41", "08-set-26 17:35:49",
            "A x B Menos de 4,5 gols-Mais/Menos de 4,5 Gols | "
            "ID Aposta Betfair 1:123 | Evento 08-set-26 15:45",
            "A favor", "1.30", "2.00", "--", "0.60", "Ganhas",
        ]
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for name in ("a.csv", "b.csv"):
                path = Path(temp) / name
                with path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(headers)
                    writer.writerow(row)
                paths.append(path)
            report = analyze(paths)
            self.assertEqual(report["source_rows"], 2)
            self.assertEqual(report["unique_bets"], 1)
            self.assertEqual(report["duplicates_removed"], 1)


if __name__ == "__main__":
    unittest.main()
