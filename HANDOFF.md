# Cognitive Trader — Handoff / Continuation Notes

Paste this into Claude Code to pick up where the design + Week 1 build left off.

## What this project is
A retrieval-augmented (RAG) **swing-trading assistant** for US stocks on daily bars (holds of days to weeks). Deterministic quantitative **rules propose** candidate trades; an **LLM vets** each one using retrieved evidence (your trade journal, similar historic setups, news) and returns approve/reject + position size + written reasoning with citations. Trades run on an **Alpaca paper account**. A Streamlit app gives a dashboard + chat over the knowledge base.

Dual purpose: job-search portfolio piece **and** a real decision-support tool. Framing everywhere is "decision support with retrieval-grounded reasoning," NOT "profitable bot." Not financial advice.

## Locked-in decisions
- US stocks, **daily bars**, long-only v1. Swing style.
- **Rules propose, AI disposes.** LLM value-add is a single ablatable stage.
- **Risk lives in code, not prompts** — gates enforce caps/stops before the LLM; LLM can only size *below* the cap.
- **SQLite = source of truth; Chroma = derived index** (rebuildable).
- Setup "cards" (templated text) make price patterns embeddable + human-readable + citable.
- Citations validated in code (hallucinated cites → auto-reject). Prompts versioned.
- Stack (all free except LLM): Python, yfinance, SQLite, Chroma, local sentence-transformers embeddings, **Claude API** for vetting (~$5–15/mo during dev only), Streamlit, Streamlit Community Cloud for the hosted demo.
- Timeline: 6-week sprint. Beginner-ish coder — keep scaffolding + explanatory comments.

Full design in `ARCHITECTURE.md`; week-by-week in `BUILD_PLAN.md`.

## What's built and working (Week 1 ✅, Week 2 code ✅)
Verified on real data: backfilled ~751 rows/ticker (~3y), `run_daily.py --dry-run` fired a real trend_pullback on AAPL and passed gates. All 39 tests pass. Git repo initialized; Week 2 built on branch `week-2-paper-trading`.

```
config.yaml                 # universe (31 tickers w/ sectors), indicator params, rules, risk caps
src/config.py               # loads config; CT_DB_OVERRIDE env for dev DBs
src/data/db.py              # SQLite schema (6 tables) + trade lifecycle helpers (record/open/close trade, trading-day calendar via SPY)
src/data/ingest.py          # yfinance backfill + idempotent daily_update
src/signals/indicators.py   # hand-rolled SMA/RSI/ATR/rolling_high + enrich()
src/signals/rules.py        # Candidate dataclass; 3 rules; scan()
src/risk/gates.py           # PortfolioState, apply_gates(): rejects + computes max size
src/broker/alpaca_client.py # AlpacaBroker (paper-only): GTC bracket orders, positions, exit fills; pure helpers shares_for/exit_reason
src/broker/reconcile.py     # syncs DB with broker: records exits + P&L + exit journal, syncs fill prices, enforces 20-day time stop
src/journal/journaler.py    # entry/exit journal templates (embed-ready prose) + writes (embedded=0 for Week 3 sync)
scripts/backfill.py         # one-time history pull
scripts/run_daily.py        # ingest→reconcile→rules→gates→execute; dry-run default, --execute places paper orders
scripts/dev_seed.py         # DEV ONLY synthetic data (use --db /tmp/x.db)
tests/                      # 39 tests incl. broker logic, trade lifecycle, journal, reconcile (FakeBroker, offline)
```

Run it:
```
pip install -r requirements.txt
python scripts/backfill.py
python scripts/run_daily.py            # dry run (works without Alpaca keys)
python scripts/run_daily.py --execute  # real paper orders (needs .env)
pytest -q
```

## Next: finish Week 2 live check, then Week 3
**One manual step remains for Week 2's done-when:** create a free Alpaca **paper** account, copy `.env.example` → `.env`, fill in `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`. Then run `python scripts/run_daily.py --execute` one evening: a passed candidate should appear as a bracket order in the Alpaca dashboard, and (after it closes) reconcile writes the exit journal entry. From then on, run the loop nightly — the system is live on paper, accumulating journal entries for the RAG layer.

Week 2 design notes:
- Bracket orders are **GTC** (DAY legs would expire end of entry day, leaving swing holds unprotected).
- Rules-only mode records a stand-in `decisions` row (`model='rules-only'`, sized at the gate cap) so `signals→decisions→trades` stays traceable; Week 4 swaps in real LLM verdicts.
- `entry_price` is the signal close at submit; reconcile adopts the broker's actual `avg_entry_price` once the position appears.
- Time stop: reconcile market-closes positions ≥20 trading days old (SPY's stored dates are the calendar); the exit is recorded the *next* run, when the position is gone.
- Reconcile never guesses: position gone + no visible exit fill → warn and leave open.

Then Week 3 = RAG core (Chroma + setup cards + retriever), Week 4 = LLM vetting + backtester, Week 5 = Streamlit + news, Week 6 = polish/deploy/video.

## Watch-outs
- yfinance columns come capitalized / sometimes MultiIndex — `ingest._normalize()` handles it.
- No lookahead in future backtests: retrieval must date-filter to data available at that date.
- Keep risk caps in `gates.py`, never in prompts.
