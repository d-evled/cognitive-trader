"""Alpaca paper-trading wrapper.

Two layers on purpose:
  * Pure functions (shares_for, build_bracket_request, exit_reason) hold
    all the logic worth testing — no network, no mocks.
  * AlpacaBroker is thin glue over alpaca-py's TradingClient. Everything
    else in the codebase talks to this wrapper (or a fake with the same
    methods), never to alpaca-py directly.

Keys come from .env (gitignored):
    ALPACA_API_KEY=...
    ALPACA_SECRET_KEY=...
Paper trading only — the wrapper hard-codes paper=True; going live later
is a deliberate, separate decision.
"""
import math
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from src.config import REPO_ROOT


@dataclass
class BrokerPosition:
    """The slice of an Alpaca position the rest of the system needs."""
    ticker: str
    qty: float
    avg_entry_price: float
    market_value: float
    unrealized_pl: float


@dataclass
class ExitFill:
    """A filled sell order that closed a position."""
    price: float
    date: str        # YYYY-MM-DD of the fill
    order_type: str  # 'stop' | 'limit' | 'market' — how the exit happened


# --------------------------------------------------------------------------
# Pure logic (unit-tested, no network)
# --------------------------------------------------------------------------

def shares_for(equity: float, size_pct: float, entry_price: float) -> int:
    """Whole shares purchasable with size_pct of equity. Bracket orders
    require whole shares, so we floor — never round up past the cap."""
    if entry_price <= 0:
        return 0
    return math.floor(equity * size_pct / 100 / entry_price)


def build_bracket_request(ticker: str, qty: int, stop_price: float,
                          target_price: float) -> MarketOrderRequest:
    """Market entry + stop-loss + take-profit as one atomic bracket.

    GTC, not DAY: the legs inherit the time-in-force, and a DAY stop
    would expire at the end of entry day — leaving a multi-day swing
    position unprotected overnight. GTC keeps the bracket armed for the
    whole hold.
    """
    return MarketOrderRequest(
        symbol=ticker,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.GTC,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=target_price),
        stop_loss=StopLossRequest(stop_price=stop_price),
    )


def exit_reason(order_type: str, hold_days: int, time_stop_days: int) -> str:
    """Map the order type that closed a position to a trade exit reason.

    The bracket's stop leg is a 'stop' order, its target leg a 'limit'
    order. A 'market' sell is one we (time stop) or the human placed.
    """
    if order_type == "stop":
        return "stop"
    if order_type == "limit":
        return "target"
    return "time" if hold_days >= time_stop_days else "manual"


# --------------------------------------------------------------------------
# The live wrapper (thin glue; exercised against the real paper API)
# --------------------------------------------------------------------------

class AlpacaBroker:
    def __init__(self) -> None:
        load_dotenv(REPO_ROOT / ".env")
        key = os.environ.get("ALPACA_API_KEY")
        secret = os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError(
                "Missing Alpaca keys. Create a paper account at alpaca.markets, "
                "then put ALPACA_API_KEY and ALPACA_SECRET_KEY in .env "
                "(see .env.example)."
            )
        self.client = TradingClient(key, secret, paper=True)

    def equity(self) -> float:
        return float(self.client.get_account().equity)

    def open_positions(self) -> list[BrokerPosition]:
        return [
            BrokerPosition(
                ticker=p.symbol,
                qty=float(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                market_value=float(p.market_value),
                unrealized_pl=float(p.unrealized_pl),
            )
            for p in self.client.get_all_positions()
        ]

    def open_order_tickers(self) -> set[str]:
        """Tickers with pending orders — guards against submitting the same
        candidate twice if the loop runs twice in one evening."""
        orders = self.client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN))
        return {o.symbol for o in orders}

    def submit_bracket(self, ticker: str, qty: int, stop_price: float,
                       target_price: float) -> str:
        """Submit the bracket; returns the Alpaca order id. Submitted after
        close, the market entry queues for the next open."""
        order = self.client.submit_order(
            build_bracket_request(ticker, qty, stop_price, target_price))
        return str(order.id)

    def latest_exit_fill(self, ticker: str) -> ExitFill | None:
        """Most recent filled SELL for a ticker — how reconciliation learns
        the exit price and whether the stop or the target leg fired."""
        orders = self.client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED, symbols=[ticker]))
        fills = [o for o in orders
                 if o.side == OrderSide.SELL
                 and o.filled_avg_price is not None and o.filled_at is not None]
        if not fills:
            return None
        latest = max(fills, key=lambda o: o.filled_at)
        return ExitFill(
            price=float(latest.filled_avg_price),
            date=latest.filled_at.strftime("%Y-%m-%d"),
            order_type=str(latest.order_type.value),
        )

    def close_position_market(self, ticker: str) -> None:
        """Time-stop exit. The bracket legs hold the shares, so cancel the
        ticker's open orders first, then market-close the position."""
        for o in self.client.get_orders(GetOrdersRequest(
                status=QueryOrderStatus.OPEN, symbols=[ticker])):
            self.client.cancel_order_by_id(o.id)
        self.client.close_position(ticker)
