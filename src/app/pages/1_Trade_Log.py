"""Trade log — every trade joined to its decision, filterable, with per-rule
performance stats underneath."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root on path

import pandas as pd
import streamlit as st

from src.app.queries import closed_trades, trade_log
from src.app.ui import disclaimer, get_cfg, get_conn, setup_page
from src.backtest.engine import summary_stats

setup_page("Trade Log", icon="📒")
cfg = get_cfg()
conn = get_conn()

st.title("Trade log")
disclaimer()

rows = trade_log(conn)
if not rows:
    st.info("No trades yet. The log fills as the daily loop places orders.")
    st.stop()

df = pd.DataFrame(rows)

# --- filters --------------------------------------------------------------
f1, f2, f3 = st.columns(3)
rules = f1.multiselect("Rule", sorted(df["rule_name"].unique()))
statuses = f2.multiselect("Status", sorted(df["status"].unique()))
models = f3.multiselect("Model", sorted(df["model"].dropna().unique()))
view = df
if rules:
    view = view[view["rule_name"].isin(rules)]
if statuses:
    view = view[view["status"].isin(statuses)]
if models:
    view = view[view["model"].isin(models)]

cols = ["ticker", "rule_name", "status", "entry_date", "entry_price", "qty",
        "stop_price", "target_price", "exit_date", "exit_price", "exit_reason",
        "pnl", "pnl_pct", "verdict", "size_pct", "model"]
st.dataframe(view[[c for c in cols if c in view.columns]],
             use_container_width=True, hide_index=True)
st.caption(f"{len(view)} of {len(df)} trades")

# --- per-rule performance (closed trades only) ----------------------------
st.subheader("Per-rule performance")
closed = closed_trades(conn)
stats = summary_stats(closed, cfg["risk"]["starting_equity"])
if stats["n"] == 0:
    st.info("No closed trades yet — per-rule stats appear once positions close.")
else:
    st.dataframe(pd.DataFrame([
        {"rule": r, "trades": v["n"], "win %": v["win_rate"]}
        for r, v in sorted(stats["per_rule"].items())
    ]), use_container_width=True, hide_index=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Trades", stats["n"])
    m2.metric("Win rate", f"{stats['win_rate']}%")
    m3.metric("Avg win", f"{stats['avg_win_pct']}%" if stats["avg_win_pct"] else "—")
    m4.metric("Avg loss", f"{stats['avg_loss_pct']}%" if stats["avg_loss_pct"] else "—")
