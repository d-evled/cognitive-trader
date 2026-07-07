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

## What's built and working (Week 1 ✅)
Verified on real data: backfilled ~751 rows/ticker (~3y), `run_daily.py --dry-run` fired a real trend_pullback on AAPL and passed gates. All 19 tests pass.

```
config.yaml                 # universe (31 tickers w/ sectors), indicator params, rules, risk caps
src/config.py               # loads config; CT_DB_OVERRIDE env for dev DBs
src/data/db.py              # SQLite schema (6 tables), upsert/load helpers
src/data/ingest.py          # yfinance backfill + idempotent daily_update
src/signals/indicators.py   # hand-rolled SMA/RSI/ATR/rolling_high + enrich()
src/signals/rules.py        # Candidate dataclass; 3 rules (trend_pullback, breakout, oversold_reversion); scan()
src/risk/gates.py           # PortfolioState, apply_gates(): rejects + computes max size (2%-risk rule + 10% cap)
scripts/backfill.py         # one-time history pull
scripts/run_daily.py        # daily loop: ingest→rules→gates→print+log signals (dry-run only so far)
scripts/dev_seed.py         # DEV ONLY synthetic data (use --db /tmp/x.db)
tests/                      # conftest fixtures + test_indicators/test_rules/test_gates
```
DB tables already defined for later weeks: `signals`, `decisions`, `trades`, `journal_entries`, `news_items`.

Run it:
```
pip install -r requirements.txt
python scripts/backfill.py
python scripts/run_daily.py --dry-run
pytest -q
```

## Next: Week 2 — paper trading loop + journal (NOT yet started)
Goal: end-to-end loop trading on Alpaca paper, still no AI.
1. Create free Alpaca **paper** account; put keys in `.env` (add `.env` is already gitignored).
2. `src/broker/alpaca_client.py`: submit **bracket orders** (entry/stop/target), poll fills, reconcile positions.
3. Wire `run_daily.py`: ingest → rules → gates → **execute** (rules-only mode). Replace the hard-coded flat `PortfolioState` with real positions from Alpaca.
4. `src/journal/journaler.py`: auto-write entry/exit rows into `journal_entries`; template the exit post-mortem (ticker, rule, hold days, outcome, lesson).
5. Enforce the **20-day time stop**; ensure every position always has a stop (bracket order).
Done when: a passed candidate becomes a real paper order visible in Alpaca, and a closed position writes an exit journal entry.

Then Week 3 = RAG core (Chroma + setup cards + retriever), Week 4 = LLM vetting + backtester, Week 5 = Streamlit + news, Week 6 = polish/deploy/video.

## Watch-outs
- yfinance columns come capitalized / sometimes MultiIndex — `ingest._normalize()` handles it.
- No lookahead in future backtests: retrieval must date-filter to data available at that date.
- Keep risk caps in `gates.py`, never in prompts.
