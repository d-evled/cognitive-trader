"""Shared Streamlit chrome: theme CSS, DB access, and the evidence renderer.

Kept apart from the pages so every page opens with the same look and the
"what did the AI see" bundle renders identically wherever it appears.
"""
import sqlite3
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import load_config

# A characterful pairing — Fraunces (editorial serif) for headings, JetBrains
# Mono for numbers — over the dark amber theme. Deliberately not the default
# sans-on-white Streamlit look.
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=JetBrains+Mono:wght@400;600&display=swap');
h1, h2, h3 { font-family: 'Fraunces', Georgia, serif !important; letter-spacing: -0.01em; }
h1 { font-weight: 600; }
[data-testid="stMetricValue"], [data-testid="stMetricDelta"] { font-family: 'JetBrains Mono', monospace; }
[data-testid="stMetric"] {
    background: #1A1D25; border: 1px solid #262A33; border-radius: 10px;
    padding: 12px 16px;
}
.ct-badge {
    font-family: 'JetBrains Mono', monospace; font-size: 0.72rem;
    background: #2A2118; color: #E0A458; border: 1px solid #4A3A25;
    padding: 1px 7px; border-radius: 5px; margin-right: 6px;
}
.ct-verdict-approve { color: #7FB77E; font-weight: 600; }
.ct-verdict-reject  { color: #C97A6D; font-weight: 600; }
.ct-verdict-error, .ct-verdict-rules-only { color: #9AA0AA; font-weight: 600; }
.ct-rule { color: #E0A458; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; }
.ct-card-text { color: #C7C4BD; font-size: 0.86rem; line-height: 1.5; }
hr { border-color: #262A33; }
</style>
"""


def setup_page(title: str, icon: str = "📈") -> None:
    st.set_page_config(page_title=f"{title} · Cognitive Trader",
                       page_icon=icon, layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)


@st.cache_data
def get_cfg() -> dict:
    return load_config()


DEMO_DB_PATH = "demo/cognitive_trader.db"  # committed snapshot for cloud/read-only


def resolve_db_path(live_path: str, demo_path: str = DEMO_DB_PATH,
                    exists=None) -> tuple[str, bool]:
    """Decide which DB the UI should read, and whether it's the demo snapshot.

    Live DB present → use it. Missing but the committed demo exists (fresh
    clone / Streamlit Cloud, where data/ is gitignored) → serve the demo so the
    app isn't blank. Neither → hand back the live path so db.get_conn creates a
    fresh empty DB (normal first-run-before-backfill). Only the UI's read path
    uses this; backfill/run_daily write through db.get_conn directly."""
    if exists is None:
        import os
        exists = os.path.exists
    if exists(live_path):
        return live_path, False
    if exists(demo_path):
        return demo_path, True
    return live_path, False


def get_conn() -> sqlite3.Connection:
    """Fresh read connection per script run (SQLite connect is cheap; a
    cached connection would cross Streamlit's script threads). Routed through
    db.get_conn so the schema + migrations (e.g. decisions.bundle_json) are
    applied even on an older DB file."""
    from src.data.db import get_conn as _db_conn
    path, is_demo = resolve_db_path(get_cfg()["data"]["db_path"])
    if is_demo:
        st.session_state["_demo_mode"] = True
    return _db_conn(path)


def demo_banner() -> None:
    """Shown when the app is serving the committed snapshot instead of a live
    account — so a cloud visitor knows the numbers are illustrative."""
    if st.session_state.get("_demo_mode"):
        st.info("📦 **Demo mode** — showing a committed snapshot (the live "
                "`data/` directory isn't present). Run the pipeline locally for "
                "your own account. See the README.")


def disclaimer() -> None:
    st.caption("Decision support with retrieval-grounded reasoning — **not "
               "financial advice**. Paper trading. Most short-horizon retail "
               "traders lose money.")


def _verdict_html(verdict: str) -> str:
    cls = {"approve": "ct-verdict-approve", "reject": "ct-verdict-reject"}.get(
        verdict, "ct-verdict-error")
    return f"<span class='{cls}'>{verdict.upper()}</span>"


def render_bundle(bundle: dict) -> None:
    """Render a stored retrieval bundle — the exact evidence the model saw."""
    if not bundle:
        st.info("No evidence bundle stored (rules-only decision, or pre-Week-4).")
        return
    st.markdown(f"<span class='ct-card-text'><em>query:</em> {bundle.get('query','')}"
                "</span>", unsafe_allow_html=True)

    setups = bundle.get("setups", [])
    if setups:
        st.markdown("**Similar historic setups** (date-filtered — no lookahead)")
        for h in setups:
            md = h.get("metadata", {})
            st.markdown(
                f"<span class='ct-badge'>{h['id']}</span>"
                f"<span class='ct-card-text'>fwd_10d "
                f"{md.get('fwd_10d','?')}% · dist {h.get('distance','?')}</span><br>"
                f"<span class='ct-card-text'>{h['text']}</span>",
                unsafe_allow_html=True)
        stats = bundle.get("setup_stats", {})
        chips = []
        for hz in ("fwd_5d", "fwd_10d", "fwd_20d"):
            s = stats.get(hz) or {}
            if s.get("n"):
                chips.append(f"{hz}: median {s['median']}% · {s['pct_positive']}% "
                             f"positive (n={s['n']})")
        if chips:
            st.markdown("**Base rates** — " + "  ·  ".join(chips))

    journal = bundle.get("journal", [])
    st.markdown("**Similar journal entries**")
    if not journal:
        st.markdown("<span class='ct-card-text'>(none yet — the journal fills as "
                    "trades close)</span>", unsafe_allow_html=True)
    for h in journal:
        st.markdown(f"<span class='ct-badge'>{h['id']}</span>"
                    f"<span class='ct-card-text'>{h['text']}</span>",
                    unsafe_allow_html=True)

    news = bundle.get("news", [])
    if news:
        st.markdown("**Recent news**")
        for h in news:
            st.markdown(f"<span class='ct-badge'>{h['id']}</span>"
                        f"<span class='ct-card-text'>{h['text']}</span>",
                        unsafe_allow_html=True)
