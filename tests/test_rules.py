from src.signals.indicators import enrich
from src.signals.rules import breakout, oversold_reversion, scan, trend_pullback


def _enriched(df, cfg):
    return enrich(df, cfg["indicators"])


def test_trend_pullback_fires(uptrend_pullback_df, cfg):
    c = trend_pullback("TEST", _enriched(uptrend_pullback_df, cfg), cfg)
    assert c is not None
    assert c.rule_name == "trend_pullback"
    assert c.stop_price < c.entry_price < c.target_price


def test_breakout_fires(breakout_df, cfg):
    c = breakout("TEST", _enriched(breakout_df, cfg), cfg)
    assert c is not None
    assert c.context["volume_ratio"] >= cfg["rules"]["breakout"]["volume_mult"]


def test_breakout_needs_volume(breakout_df, cfg):
    quiet = breakout_df.copy()
    quiet.iloc[-1, quiet.columns.get_loc("volume")] = 1_000_000.0  # no conviction
    assert breakout("TEST", _enriched(quiet, cfg), cfg) is None


def test_oversold_reversion_fires(washout_df, cfg):
    c = oversold_reversion("TEST", _enriched(washout_df, cfg), cfg)
    assert c is not None
    assert c.context["rsi"] < cfg["rules"]["oversold_reversion"]["rsi_below"]
    assert c.context["pct_above_sma_slow"] > 0  # the falling-knife filter held


def test_quiet_market_fires_nothing(boring_df, cfg):
    assert scan("TEST", _enriched(boring_df, cfg), cfg) == []


def test_rules_need_warmup(uptrend_pullback_df, cfg):
    short = uptrend_pullback_df.iloc[-30:]  # not enough history for 200d MA
    assert scan("TEST", _enriched(short, cfg), cfg) == []


def test_candidate_bracket_geometry(uptrend_pullback_df, cfg):
    c = trend_pullback("TEST", _enriched(uptrend_pullback_df, cfg), cfg)
    risk = c.entry_price - c.stop_price
    reward = c.target_price - c.entry_price
    # 2 ATR stop / 3 ATR target -> reward:risk must be ~1.5
    assert 1.4 < reward / risk < 1.6
