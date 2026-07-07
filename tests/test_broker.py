"""Tests for the pure logic in the Alpaca broker wrapper.

We deliberately do NOT test alpaca-py itself or hit the network. What we
test is OUR translation layer: sizing math, bracket-order construction,
and mapping a filled exit order back to an exit reason.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce

from src.broker.alpaca_client import build_bracket_request, exit_reason, shares_for


class TestSharesFor:
    def test_floors_to_whole_shares(self):
        # 6.5% of $100k = $6,500; at $213.55/share that's 30.43 -> 30
        assert shares_for(equity=100_000, size_pct=6.5, entry_price=213.55) == 30

    def test_zero_when_cap_buys_less_than_one_share(self):
        assert shares_for(equity=1_000, size_pct=2.0, entry_price=500.0) == 0

    def test_zero_for_nonpositive_price(self):
        assert shares_for(equity=100_000, size_pct=5.0, entry_price=0.0) == 0


class TestBuildBracketRequest:
    def test_builds_gtc_bracket_buy(self):
        req = build_bracket_request("AAPL", qty=30, stop_price=205.10, target_price=225.30)
        assert req.symbol == "AAPL"
        assert req.qty == 30
        assert req.side == OrderSide.BUY
        assert req.order_class == OrderClass.BRACKET
        # GTC matters: with DAY, the unfilled stop/target legs would expire
        # at the end of entry day, leaving a multi-day hold unprotected.
        assert req.time_in_force == TimeInForce.GTC
        assert float(req.take_profit.limit_price) == 225.30
        assert float(req.stop_loss.stop_price) == 205.10


class TestExitReason:
    def test_stop_leg_fill_means_stopped_out(self):
        assert exit_reason("stop", hold_days=4, time_stop_days=20) == "stop"

    def test_limit_leg_fill_means_target_hit(self):
        assert exit_reason("limit", hold_days=4, time_stop_days=20) == "target"

    def test_market_sell_after_time_limit_is_time_stop(self):
        assert exit_reason("market", hold_days=21, time_stop_days=20) == "time"

    def test_market_sell_before_time_limit_is_manual(self):
        assert exit_reason("market", hold_days=3, time_stop_days=20) == "manual"
