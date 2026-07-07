from src.risk.gates import PortfolioState, apply_gates
from src.signals.rules import Candidate


def _cand(ticker="AAPL", entry=100.0, stop=96.0):
    return Candidate(
        ticker=ticker, date="2026-07-06", rule_name="trend_pullback",
        direction="long", entry_price=entry, stop_price=stop,
        target_price=entry + 1.5 * (entry - stop), context={},
    )


def _sectors(mapping):
    return lambda t: mapping.get(t, "unknown")


def test_size_cap_respects_both_limits(cfg):
    state = PortfolioState(equity=100_000)
    # 4% stop distance -> risk rule allows 2/0.04 = 50%, so the 10% cap binds.
    [r] = apply_gates([_cand(stop=96.0)], state, cfg, _sectors({"AAPL": "tech"}))
    assert r.passed and r.max_size_pct == cfg["risk"]["max_position_pct"]

    # 25% stop distance -> risk rule allows only 8%, tighter than the cap.
    [r] = apply_gates([_cand(stop=75.0)], state, cfg, _sectors({"AAPL": "tech"}))
    assert r.passed and r.max_size_pct == 8.0


def test_max_open_positions(cfg):
    full = PortfolioState(
        equity=100_000,
        open_tickers=["A", "B", "C", "D", "E"],
        open_sectors=["s1", "s2", "s3", "s4", "s5"],
    )
    [r] = apply_gates([_cand()], full, cfg, _sectors({}))
    assert not r.passed and "max_open_positions" in r.reject_reason


def test_no_doubling_up_on_ticker(cfg):
    state = PortfolioState(equity=100_000, open_tickers=["AAPL"], open_sectors=["tech"])
    [r] = apply_gates([_cand("AAPL")], state, cfg, _sectors({"AAPL": "tech"}))
    assert not r.passed and "AAPL" in r.reject_reason


def test_sector_limit_counts_within_batch(cfg):
    # Two tech positions already open -> a third tech candidate is rejected.
    state = PortfolioState(equity=100_000,
                           open_tickers=["MSFT", "NVDA"],
                           open_sectors=["tech", "tech"])
    [r] = apply_gates([_cand("AAPL")], state, cfg, _sectors({"AAPL": "tech"}))
    assert not r.passed and "sector" in r.reject_reason

    # And the batch itself claims slots: 2 tech candidates on a flat book
    # pass, the 3rd is rejected even though nothing is 'open' yet.
    flat = PortfolioState(equity=100_000)
    cands = [_cand("AAPL"), _cand("MSFT"), _cand("NVDA")]
    rs = apply_gates(cands, flat, cfg,
                     _sectors({"AAPL": "tech", "MSFT": "tech", "NVDA": "tech"}))
    assert [r.passed for r in rs] == [True, True, False]


def test_malformed_bracket_rejected(cfg):
    state = PortfolioState(equity=100_000)
    bad = _cand(stop=105.0)  # stop above entry: nonsense for a long
    [r] = apply_gates([bad], state, cfg, _sectors({"AAPL": "tech"}))
    assert not r.passed and "unsizeable" in r.reject_reason
