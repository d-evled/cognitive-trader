"""Technical indicators, written from scratch on purpose.

Hand-rolling these (instead of importing ta-lib) is a Week 1 learning goal:
each one is a few lines of pandas, and knowing exactly what they measure
matters when you later read the AI's reasoning about them.

All functions take pandas Series/DataFrames and return Series aligned to
the same index. Early values are NaN until the window fills — callers must
handle that (the rules engine simply requires enough history).
"""
import pandas as pd


def sma(close: pd.Series, window: int) -> pd.Series:
    """Simple moving average: the mean of the last `window` closes.
    Price above a rising SMA is the classic definition of an uptrend."""
    return close.rolling(window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder), 0-100.

    Compares average up-moves to average down-moves over the window.
    ~70+ is considered overbought, ~30- oversold. Uses Wilder's
    exponential smoothing (alpha = 1/window), the standard formulation.
    """
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.ewm(alpha=1 / window, min_periods=window).mean()
    avg_loss = losses.ewm(alpha=1 / window, min_periods=window).mean()
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    # If there were no down-moves at all, avg_loss is 0 and RS is inf -> RSI 100.
    # (NaN rows from the warm-up window stay NaN: NaN == 0 is False.)
    out[(avg_loss == 0) & avg_gain.notna()] = 100.0
    return out


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range (Wilder): a volatility measure in price units.

    True range = the largest of (today's high-low), (high vs yesterday's
    close), (low vs yesterday's close) — i.e. how far price really traveled
    including overnight gaps. We use ATR to place stops: a stop 2 ATRs away
    scales naturally with how much the stock normally moves.
    """
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, min_periods=window).mean()


def rolling_high(series: pd.Series, window: int) -> pd.Series:
    """Highest value over the trailing `window` rows (inclusive of today)."""
    return series.rolling(window).max()


def enrich(df: pd.DataFrame, ind_cfg: dict) -> pd.DataFrame:
    """Attach every indicator column the rules need to a price DataFrame.

    One place to compute everything means rules stay declarative — they
    only read columns, never compute.
    """
    out = df.copy()
    out["sma_fast"] = sma(out["close"], ind_cfg["sma_fast"])
    out["sma_slow"] = sma(out["close"], ind_cfg["sma_slow"])
    out["rsi"] = rsi(out["close"], ind_cfg["rsi_window"])
    out["atr"] = atr(out, ind_cfg["atr_window"])
    # Prior N-day high/avg volume EXCLUDING today (shift by 1): a breakout
    # compares today against what came before, not against itself.
    out["prior_high"] = rolling_high(out["close"], ind_cfg["breakout_window"]).shift(1)
    out["vol_avg"] = sma(out["volume"], ind_cfg["volume_window"]).shift(1)
    return out
