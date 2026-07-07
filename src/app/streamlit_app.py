"""Cognitive Trader — Dashboard (the app's front door).

Equity curve, open positions with unrealized P&L, and the decisions feed —
where each decision expands to show exactly what the AI saw and why. That
expansion is the demo: signal → evidence → reasoning, in one click.

Run:  streamlit run src/app/streamlit_app.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

import altair as alt
import pandas as pd
import streamlit as st

from src.app.queries import (
    closed_trades, equity_curve, open_positions, recent_decisions,
)
from src.app.ui import (
    _verdict_html, disclaimer, get_cfg, get_conn, render_bundle, setup_page,
)
from src.backtest.engine import summary_stats

setup_page("Dashboard")
cfg = get_cfg()
conn = get_conn()
start_equity = cfg["risk"]["starting_equity"]

st.title("Cognitive Trader")
disclaimer()

positions = open_positions(conn)
closed = closed_trades(conn)
curve = equity_curve(conn, start_equity)
stats = summary_stats(closed, start_equity)

realized = stats["final_equity"] - start_equity
unrealized = sum(p["unrealized_pnl"] or 0 for p in positions)
equity_now = stats["final_equity"] + unrealized

# --- headline metrics -----------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Equity", f"${equity_now:,.0f}", f"{100*(equity_now/start_equity-1):+.2f}%")
c2.metric("Open", len(positions), f"${unrealized:+,.0f}")
c3.metric("Closed", stats["n"],
          f"{stats['win_rate']}% win" if stats["n"] else "—")
c4.metric("Max DD", f"{stats['max_drawdown_pct']}%" if stats["n"] else "—")

# --- equity curve ---------------------------------------------------------
st.subheader("Equity curve")
if curve:
    df = pd.DataFrame([{"date": start_equity and c["date"], "equity": c["equity"]}
                       for c in curve])
    df = pd.concat([pd.DataFrame([{"date": df["date"].iloc[0], "equity": start_equity}]),
                    df], ignore_index=True)
    chart = (alt.Chart(df).mark_line(color="#E0A458", point=True)
             .encode(x=alt.X("date:O", title=None),
                     y=alt.Y("equity:Q", title="equity ($)",
                             scale=alt.Scale(zero=False)))
             .properties(height=260))
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("No closed trades yet — the curve appears once positions close. "
            "Run the daily loop for a while (it's paper trading live).")

# --- open positions -------------------------------------------------------
st.subheader("Open positions")
if positions:
    st.dataframe(pd.DataFrame([{
        "ticker": p["ticker"], "rule": p["rule_name"], "qty": p["qty"],
        "entry": p["entry_price"], "last": p["last_price"],
        "stop": p["stop_price"], "target": p["target_price"],
        "unreal $": p["unrealized_pnl"], "unreal %": p["unrealized_pct"],
    } for p in positions]), use_container_width=True, hide_index=True)
else:
    st.info("Flat — no open positions.")

# --- decisions feed (the money shot) --------------------------------------
st.subheader("Recent decisions")
st.caption("Every decision — approved or rejected — with the evidence behind it.")
decisions = recent_decisions(conn, limit=30)
if not decisions:
    st.info("No decisions logged yet. Run `scripts/run_daily.py` (add `--vet` "
            "for LLM vetting once your Anthropic key is set).")
for d in decisions:
    size = f" · {d['size_pct']}%" if d["verdict"] == "approve" else ""
    conf = f" · conf {d['confidence']}" if d["confidence"] is not None else ""
    header = f"{d['ticker']}  ·  {d['rule_name']}  ·  {d['verdict'].upper()}{size}{conf}"
    with st.expander(header):
        st.markdown(f"{_verdict_html(d['verdict'])} &nbsp; "
                    f"<span class='ct-rule'>{d['model']}"
                    f"{' · ' + d['prompt_version'] if d['prompt_version'] else ''}</span>",
                    unsafe_allow_html=True)
        st.markdown(f"**Reasoning.** {d['reasoning']}")
        if d["citations"]:
            st.markdown("**Cited:** " + ", ".join(
                f"`{c}`" for c in d["citations"]))
        if d["context"]:
            st.caption("signal context: " + ", ".join(
                f"{k}={v}" for k, v in d["context"].items()))
        st.markdown("---")
        render_bundle(d["bundle"])
